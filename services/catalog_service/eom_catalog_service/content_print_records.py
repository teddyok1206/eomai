"""Catalog transaction owner for user-recorded printing and append-only corrections."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.content_print_commands import (
    ContentPrintCommand,
    ContentPrintMutationResult,
    ContentRecordPrintCommand,
    RecordContentPrintWithOutput,
    VoidContentPrint,
    parse_content_print_command,
)
from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
from eom_catalog_contracts.content_print_views import (
    ContentPrintEntry,
    ContentPrintList,
    ReadContentPrints,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, Text, cast, func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_layout import ContentPlanningConflict, select_print_scope
from eom_catalog_service.content_planning_models import ContentPlanningCommandReceiptRecord
from eom_catalog_service.content_planning_storage import (
    load_content_edition,
    new_content_id,
    read_edition_revision,
)
from eom_catalog_service.content_print_models import (
    ContentPrintEventRecord,
    ContentPrintRecord,
    ContentPrintScopeRecord,
)
from eom_catalog_service.content_print_output import resolve_content_print_output
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import read_curated_slot_revisions


def _authorize_print(
    session: Session, actor: ActorContext, command: ContentPrintCommand
) -> ActorContext:
    authorized = authorize_content_planning(session, actor, PermissionKey.USAGE_FULFILL_PLAN)
    if isinstance(command, RecordContentPrintWithOutput) and (
        PermissionKey.HWPX_READ not in authorized.permissions
    ):
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    return authorized


def read_print_record(session: Session, print_id: str, edition_id: str) -> ContentPrintRecordV1:
    row = session.get(ContentPrintRecord, print_id)
    if row is None or row.edition_id != edition_id:
        raise ContentPlanningError("CONTENT_PRINT_NOT_FOUND")
    return parse_stored_print_record(row)


def parse_stored_print_record(row: ContentPrintRecord) -> ContentPrintRecordV1:
    try:
        record = ContentPrintRecordV1.model_validate(row.canonical_record)
    except ValueError as exc:
        raise ContentPlanningError("CONTENT_PRINT_POINTER_INVALID") from exc
    if (
        record.print_record_id != row.print_record_id
        or record.scope.edition_id != row.edition_id
        or record.deliverable_revision_id != row.deliverable_revision_id
        or record.scope.scope_sha256 != row.scope_sha256
        or record.record_sha256 != row.record_sha256
        or record.intent != row.intent
        or record.predecessor_print_record_id != row.predecessor_print_record_id
        or record.recorded_at != row.recorded_at
        or record.recorded_by != row.recorded_by
    ):
        raise ContentPlanningError("CONTENT_PRINT_POINTER_INVALID")
    return record


def read_content_prints(session: Session, query: ReadContentPrints) -> ContentPrintList:
    """Caller already authorized; batched record/event reads, no per-record DB lookup."""
    edition = load_content_edition(session, query.edition_id, include_archived=True)
    if edition.current_revision_id is None:
        raise ContentPlanningError("CONTENT_REVISION_NOT_FOUND")
    current = read_edition_revision(session, edition, edition.current_revision_id)
    model = ContentPrintRecord
    statement = select(
        model.print_record_id, func.octet_length(cast(model.canonical_record, Text))
    ).where(model.edition_id == query.edition_id)
    if query.before_id is not None:
        before = read_print_record(session, query.before_id, query.edition_id)
        statement = statement.where(
            tuple_(model.recorded_at, model.print_record_id)
            < (before.recorded_at, before.print_record_id)
        )
    candidates = session.execute(
        statement.order_by(model.recorded_at.desc(), model.print_record_id.desc()).limit(
            query.limit + 1
        )
    ).all()
    # Bound materialized JSON before loading whole scopes. Limit is an upper bound,
    # and the cursor continues from the last included record when bytes fill first.
    selected, byte_count = [], 1024
    for identity, size in candidates[: query.limit]:
        if byte_count + size + 8192 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
            break
        selected.append(identity)
        byte_count += size + 8192
    if candidates and not selected:
        raise ContentPlanningError("CONTENT_RESULT_TOO_LARGE")
    page = (
        session.scalars(
            select(model)
            .where(model.print_record_id.in_(selected))
            .order_by(model.recorded_at.desc(), model.print_record_id.desc())
        ).all()
        if selected
        else []
    )
    events = (
        {
            event.print_record_id: event
            for event in session.scalars(
                select(ContentPrintEventRecord).where(
                    ContentPrintEventRecord.print_record_id.in_(
                        [row.print_record_id for row in page]
                    )
                )
            )
        }
        if page
        else {}
    )
    entries = []
    for row in page:
        record = parse_stored_print_record(row)
        event = events.get(row.print_record_id)
        try:
            current_scope = select_print_scope(
                current, tuple(form.section_id for form in record.scope.forms)
            )
            matches = current_scope.scope_sha256 == record.scope.scope_sha256
        except ContentPlanningConflict as exc:
            if exc.code not in {"CONTENT_SECTION_NOT_FOUND", "CONTENT_PRINT_EMPTY_SECTION"}:
                raise
            matches = False
        entries.append(
            ContentPrintEntry(
                record=record,
                state="ACTIVE"
                if event is None
                else ("VOIDED" if event.event_kind == "VOID_RECORD" else "CORRECTED"),
                replacement_print_record_id=None
                if event is None
                else event.replacement_print_record_id,
                reason=None if event is None else event.reason,
                matches_current_scope=matches,
            )
        )
    return ContentPrintList(
        edition_id=query.edition_id,
        current_revision_id=current.deliverable_revision_id,
        rows=tuple(entries),
        next_id=page[-1].print_record_id if len(candidates) > len(page) else None,
    )


class ContentPrintService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def record_in_transaction(
        self, session: Session, command: ContentRecordPrintCommand, actor: ActorContext
    ) -> ContentPrintMutationResult:
        """Reuse print rules when another application use case owns atomic commit/replay."""
        parsed = parse_content_print_command(command.model_dump(mode="json"))
        if isinstance(parsed, VoidContentPrint):
            raise ContentPlanningError("CONTENT_PRINT_REQUEST_INVALID")
        authorized = _authorize_print(session, actor, parsed)
        load_content_edition(session, parsed.edition_id, for_update=True)
        return self._record(session, parsed, authorized)

    def execute(
        self, command: ContentPrintCommand, *, actor: ActorContext, idempotency_key: str
    ) -> ContentPrintMutationResult:
        command = parse_content_print_command(command.model_dump(mode="json"))
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_KEY_INVALID")
        digest = content_sha256(command.model_dump(mode="json"))
        try:
            with transaction(self.sessions) as session:
                authorized = _authorize_print(session, actor, command)
                # One Edition lock orders save/print/void/correct. No renderer or file I/O in TX.
                load_content_edition(session, command.edition_id, for_update=True)
                replay = self._replay(session, command, actor.actor_id, idempotency_key, digest)
                if replay is not None:
                    return replay
                result = (
                    self._record(session, command, authorized)
                    if not isinstance(command, VoidContentPrint)
                    else self._void(session, command, authorized)
                )
                if (
                    len(canonical_json_bytes(result.model_dump(mode="json"))) + 16384
                    > CATALOG_APPLICATION_MAX_MESSAGE_BYTES
                ):
                    raise ContentPlanningError("CONTENT_RESULT_TOO_LARGE")
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=actor.actor_id,
                        command_kind=command.command_kind,
                        idempotency_key=idempotency_key,
                        request_sha256=digest,
                        result_pointer={
                            "edition_id": command.edition_id,
                            "print_record_id": result.record.print_record_id,
                            "record_sha256": result.record.record_sha256,
                            "disposition": result.disposition,
                        },
                    )
                )
                session.flush()
                validate_contract("content-print-result-v1", result.model_dump(mode="json"))
                return result
        except IntegrityError as exc:
            with self.sessions() as session:
                _authorize_print(session, actor, command)
                replay = self._replay(session, command, actor.actor_id, idempotency_key, digest)
                if replay is not None:
                    return replay
            raise ContentPlanningError("CONTENT_PRINT_PERSISTENCE_CONFLICT") from exc

    @staticmethod
    def _replay(
        session: Session, command: ContentPrintCommand, actor_id: str, key: str, digest: str
    ) -> ContentPrintMutationResult | None:
        receipt = session.get(
            ContentPlanningCommandReceiptRecord, (actor_id, command.command_kind, key)
        )
        if receipt is None:
            return None
        if receipt.request_sha256 != digest:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_CONFLICT")
        pointer = receipt.result_pointer
        if pointer.get("edition_id") != command.edition_id:
            raise ContentPlanningError("CONTENT_PRINT_POINTER_INVALID")
        record = read_print_record(session, pointer["print_record_id"], command.edition_id)
        if record.record_sha256 != pointer["record_sha256"]:
            raise ContentPlanningError("CONTENT_PRINT_POINTER_INVALID")
        return ContentPrintMutationResult(
            disposition=pointer["disposition"], replayed=True, record=record
        )

    @staticmethod
    def _record(
        session: Session, command: ContentRecordPrintCommand, actor: ActorContext
    ) -> ContentPrintMutationResult:
        edition = load_content_edition(session, command.edition_id)
        composition = read_edition_revision(session, edition, command.revision_id)
        if composition.composition_sha256 != command.composition_sha256:
            raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
        scope = select_print_scope(composition, command.section_ids)
        output = (
            resolve_content_print_output(session, command, scope, actor)
            if isinstance(command, RecordContentPrintWithOutput)
            else None
        )
        manifests = read_curated_slot_revisions(session, tuple(form.form for form in scope.forms))
        slots = tuple(
            slot
            for form in scope.forms
            for slot in manifests[form.form.assembly_revision_id].placements
        )
        if any(slot.target.placement_kind == "EMPTY" for slot in slots):
            raise ContentPlanningError("CONTENT_PRINT_UNFILLED_PLACEMENTS")
        if (
            resolve_curated_slots(session, tuple(slot.selection() for slot in slots), actor)
            != slots
        ):
            raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
        if command.intent == "INITIAL":
            previous = session.scalar(
                select(ContentPrintRecord).where(
                    ContentPrintRecord.edition_id == command.edition_id,
                    ContentPrintRecord.scope_sha256 == scope.scope_sha256,
                    ContentPrintRecord.intent == "INITIAL",
                )
            )
            if previous is not None:
                if session.get(ContentPrintEventRecord, (previous.print_record_id, 1)) is not None:
                    raise ContentPlanningError("CONTENT_PRINT_EXPLICIT_REPRINT_REQUIRED")
                return ContentPrintMutationResult(
                    disposition="ALREADY_RECORDED",
                    replayed=False,
                    record=read_print_record(session, previous.print_record_id, command.edition_id),
                )
        else:
            assert command.predecessor_print_record_id is not None
            read_print_record(session, command.predecessor_print_record_id, command.edition_id)
            terminal = session.get(
                ContentPrintEventRecord, (command.predecessor_print_record_id, 1)
            )
            if terminal is not None and (
                command.intent == "CORRECTION" or terminal.event_kind == "CORRECT_RECORD"
            ):
                raise ContentPlanningError("CONTENT_PRINT_ALREADY_CLOSED")
            if terminal is not None and not command.note.strip():
                raise ContentPlanningError("CONTENT_PRINT_REPRINT_REASON_REQUIRED")
        now = datetime.now(UTC)
        value = dict(
            schema_version="content-print-record/1.0",
            print_record_id=new_content_id("print"),
            deliverable_revision_id=composition.deliverable_revision_id,
            composition_sha256=composition.composition_sha256,
            scope=scope.model_dump(mode="json"),
            origin="USER_RECORDED",
            intent=command.intent,
            predecessor_print_record_id=command.predecessor_print_record_id,
            printed_on=None if command.printed_on is None else command.printed_on.isoformat(),
            recorded_at=now.isoformat().replace("+00:00", "Z"),
            recorded_by=actor.actor_id,
            note=command.note,
            output=None if output is None else output.model_dump(mode="json"),
        )
        record = ContentPrintRecordV1.model_validate(
            {**value, "record_sha256": content_sha256(value)}
        )
        validate_contract("content-print-record-v1", record.model_dump(mode="json"))
        session.add(
            ContentPrintRecord(
                print_record_id=record.print_record_id,
                edition_id=command.edition_id,
                deliverable_revision_id=record.deliverable_revision_id,
                scope_sha256=scope.scope_sha256,
                intent=record.intent,
                predecessor_print_record_id=record.predecessor_print_record_id,
                canonical_record=record.model_dump(mode="json"),
                record_sha256=record.record_sha256,
                recorded_by=actor.actor_id,
                recorded_at=now,
            )
        )
        session.flush()
        session.add_all(
            ContentPrintScopeRecord(
                print_record_id=record.print_record_id,
                assessment_form_revision_id=form.form.form_revision_id,
                edition_id=command.edition_id,
                section_id=form.section_id,
                scope_order=index,
            )
            for index, form in enumerate(scope.forms, 1)
        )
        if command.intent == "CORRECTION":
            session.add(
                ContentPrintEventRecord(
                    print_record_id=command.predecessor_print_record_id,
                    sequence=1,
                    event_kind="CORRECT_RECORD",
                    replacement_print_record_id=record.print_record_id,
                    reason=command.note,
                    actor_id=actor.actor_id,
                    created_at=now,
                )
            )
        return ContentPrintMutationResult(disposition="RECORDED", replayed=False, record=record)

    @staticmethod
    def _void(
        session: Session, command: VoidContentPrint, actor: ActorContext
    ) -> ContentPrintMutationResult:
        record = read_print_record(session, command.print_record_id, command.edition_id)
        if record.record_sha256 != command.record_sha256:
            raise ContentPlanningError("CONTENT_PRINT_POINTER_INVALID")
        if session.get(ContentPrintEventRecord, (command.print_record_id, 1)) is not None:
            raise ContentPlanningError("CONTENT_PRINT_ALREADY_CLOSED")
        session.add(
            ContentPrintEventRecord(
                print_record_id=command.print_record_id,
                sequence=1,
                event_kind="VOID_RECORD",
                replacement_print_record_id=None,
                reason=command.reason,
                actor_id=actor.actor_id,
                created_at=datetime.now(UTC),
            )
        )
        return ContentPrintMutationResult(disposition="VOIDED", replayed=False, record=record)

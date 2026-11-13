"""Prepare immutable workbook evidence; atomically import through existing content owners."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.content_print_commands import RecordContentPrint
from eom_catalog_contracts.content_workbook_import import (
    CONTENT_WORKBOOK_PROPOSAL_SCHEMA,
    ContentWorkbookImportResult,
    ContentWorkbookPreview,
    ContentWorkbookPreviewRow,
    ContentWorkbookProposal,
    PrepareContentWorkbookRequest,
)
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_editions import create_planned_content
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentEditionRevisionRecord,
    ContentPlanningCommandReceiptRecord,
)
from eom_catalog_service.content_planning_storage import load_content_edition, read_edition_revision
from eom_catalog_service.content_print_models import ContentPrintRecord
from eom_catalog_service.content_print_records import ContentPrintService
from eom_catalog_service.content_workbook_layout import require_workbook_layout, workbook_layout
from eom_catalog_service.content_workbook_reader import read_content_workbook
from eom_catalog_service.content_workbook_resolution import resolve_workbook_rows
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import read_curated_slot_revisions
from eom_catalog_service.models import DeliverableRecord
from eom_catalog_service.settings import CatalogSettings

_MEMBER = "import/proposal.json"
_PREPARE = "PREPARE_CONTENT_WORKBOOK"
_COMMIT = "COMMIT_CONTENT_WORKBOOK"
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ContentWorkbookImportService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.prints = ContentPrintService(engine)

    @staticmethod
    def authorize(session: Session, actor: ActorContext, *, write: bool) -> ActorContext:
        authorized = authorize_content_planning(
            session,
            actor,
            PermissionKey.DELIVERABLE_CREATE if write else PermissionKey.DELIVERABLE_READ,
        )
        if PermissionKey.CONTENT_INTAKE_READ not in authorized.permissions:
            raise ContentPlanningError("CURATED_SOURCE_PERMISSION_DENIED")
        return authorized

    def authorize_upload(self, actor: ActorContext) -> None:
        with self.sessions() as session:
            self.authorize(session, actor, write=True)

    def prepare(
        self, path: Path, request: PrepareContentWorkbookRequest, actor: ActorContext
    ) -> ContentWorkbookPreview:
        if not request.original_filename.lower().endswith(".xlsx"):
            raise ContentPlanningError("CONTENT_WORKBOOK_REQUEST_INVALID")
        identity = dict(
            uploaded_by=actor.actor_id,
            original_filename=request.original_filename,
            workbook_sha256=request.sha256,
            workbook_bytes=request.content_length,
        )
        digest = content_sha256(identity)
        with self.sessions() as session:
            self.authorize(session, actor, write=True)
            receipt = self._receipt(session, actor, _PREPARE, request.idempotency_key, digest)
            if receipt is not None:
                pointer = OriginArtifactMemberPointer.model_validate(receipt.result_pointer)
                return self.read(pointer, actor=actor, limit=100)
        if path.stat().st_size != request.content_length or (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != request.sha256
        ):
            raise ContentPlanningError("CONTENT_WORKBOOK_UPLOAD_HASH_MISMATCH")
        document = read_content_workbook(path)
        require_workbook_layout(document)
        with self.sessions() as session:
            self.authorize(session, actor, write=True)
            resolutions = resolve_workbook_rows(session, document)
        proposal = ContentWorkbookProposal(
            document=document,
            resolutions=resolutions,
            uploaded_by=actor.actor_id,
            original_filename=request.original_filename,
            workbook_sha256=request.sha256,
            workbook_bytes=request.content_length,
        )
        validate_contract("content-workbook-proposal-v1", proposal.model_dump(mode="json"))
        encoded = canonical_json_bytes(proposal.model_dump(mode="json"))
        with tempfile.TemporaryDirectory(
            prefix="content-workbook.", dir=self.settings.staging_root
        ) as directory:
            proposal_path = Path(directory) / "proposal.json"
            proposal_path.write_bytes(encoded)
            artifact = self.artifacts.commit_file_set(
                files={_MEMBER: proposal_path, "source/original.xlsx": path},
                primary_file=_MEMBER,
                artifact_type="content-workbook-proposal",
                idempotency_key="workbook:" + digest[7:],
                request=identity,
                result=identity,
                file_metadata={
                    _MEMBER: {
                        "schema_ref": CONTENT_WORKBOOK_PROPOSAL_SCHEMA,
                        "media_type": "application/json",
                    },
                    "source/original.xlsx": {
                        "schema_ref": "eom://schemas/content-planning/workbook-source/1.0",
                        "media_type": _XLSX_MEDIA,
                    },
                },
                expected_file_sha256={
                    _MEMBER: "sha256:" + hashlib.sha256(encoded).hexdigest(),
                    "source/original.xlsx": request.sha256,
                },
            )
        # On replay the committed proposal, not a newly resolved candidate, owns the hash.
        member = next(
            entry for entry in artifact.manifest["files"] if entry["file_name"] == _MEMBER
        )
        pointer = OriginArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=_MEMBER,
            schema_ref=CONTENT_WORKBOOK_PROPOSAL_SCHEMA,
            media_type="application/json",
            sha256=member["sha256"],
        )
        with transaction(self.sessions) as session:
            self.authorize(session, actor, write=True)
            self._lock(
                session, "workbook-prepare:" + actor.actor_id + ":" + request.idempotency_key
            )
            receipt = self._receipt(session, actor, _PREPARE, request.idempotency_key, digest)
            if receipt is None:
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=actor.actor_id,
                        command_kind=_PREPARE,
                        idempotency_key=request.idempotency_key,
                        request_sha256=digest,
                        result_pointer=pointer.model_dump(mode="json"),
                    )
                )
            elif receipt.result_pointer != pointer.model_dump(mode="json"):
                raise ContentPlanningError("CONTENT_WORKBOOK_REPLAY_CONFLICT")
        return self.read(pointer, actor=actor, limit=100)

    def _proposal(
        self, pointer: OriginArtifactMemberPointer, actor: ActorContext
    ) -> ContentWorkbookProposal:
        if (
            pointer.member_path != _MEMBER
            or pointer.schema_ref != CONTENT_WORKBOOK_PROPOSAL_SCHEMA
            or pointer.media_type != "application/json"
        ):
            raise ContentPlanningError("CONTENT_WORKBOOK_PROPOSAL_INVALID")
        try:
            encoded = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                schema_ref=pointer.schema_ref,
                media_type=pointer.media_type,
                max_bytes=40 * 1024 * 1024,
            )
            proposal = ContentWorkbookProposal.model_validate_json(encoded)
            validate_contract("content-workbook-proposal-v1", proposal.model_dump(mode="json"))
        except (ValueError, OSError, SchemaError) as exc:
            raise ContentPlanningError("CONTENT_WORKBOOK_PROPOSAL_INVALID") from exc
        if proposal.uploaded_by != actor.actor_id:
            raise ContentPlanningError("CONTENT_WORKBOOK_PROPOSAL_OWNER_MISMATCH")
        return proposal

    def read(
        self,
        pointer: OriginArtifactMemberPointer,
        *,
        actor: ActorContext,
        offset: int = 0,
        limit: int = 50,
    ) -> ContentWorkbookPreview:
        with self.sessions() as session:
            self.authorize(session, actor, write=False)
        proposal = self._proposal(pointer, actor)
        require_workbook_layout(proposal.document)
        total = len(proposal.document.rows)
        if not 0 <= offset <= total or not 1 <= limit <= 100:
            raise ContentPlanningError("CONTENT_WORKBOOK_REQUEST_INVALID")
        matched = sum(row.status == "MATCHED" for row in proposal.resolutions)
        end = min(total, offset + limit)
        return ContentWorkbookPreview(
            proposal=pointer,
            original_filename=proposal.original_filename,
            workbook_sha256=proposal.workbook_sha256,
            metadata=proposal.document.metadata,
            total_rows=total,
            matched_rows=matched,
            unresolved_rows=total - matched,
            duplicate_uses=total - len({row.external_number for row in proposal.document.rows}),
            can_commit=matched == total,
            offset=offset,
            next_offset=end if end < total else None,
            rows=tuple(
                ContentWorkbookPreviewRow(row=row, resolution=resolution)
                for row, resolution in zip(
                    proposal.document.rows[offset:end],
                    proposal.resolutions[offset:end],
                    strict=True,
                )
            ),
        )

    def commit(
        self, pointer: OriginArtifactMemberPointer, *, actor: ActorContext, idempotency_key: str
    ) -> ContentWorkbookImportResult:
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_KEY_INVALID")
        with self.sessions() as session:
            self.authorize(session, actor, write=True)
        proposal = self._proposal(pointer, actor)
        command, slots = workbook_layout(proposal)
        digest = content_sha256(pointer.model_dump(mode="json"))
        key = "excel-import-v1:" + proposal.workbook_sha256[7:]
        try:
            with transaction(self.sessions) as session:
                authorized = self.authorize(session, actor, write=True)
                self._lock(session, key)
                receipt = self._receipt(session, actor, _COMMIT, idempotency_key, digest)
                if receipt is not None:
                    return self._result(session, receipt.result_pointer, authorized, replayed=True)
                product = session.scalar(
                    select(DeliverableRecord).where(DeliverableRecord.deliverable_key == key)
                )
                if product is None:
                    edition, composition = create_planned_content(
                        session,
                        command,
                        authorized,
                        content_key=key,
                        initial_slots=slots,
                    )
                    print_id = None
                    if proposal.document.metadata.print_status == "PRINTED":
                        printed = self.prints.record_in_transaction(
                            session,
                            RecordContentPrint(
                                command_kind="RECORD_PRINT",
                                edition_id=edition.edition_id,
                                revision_id=composition.deliverable_revision_id,
                                composition_sha256=composition.composition_sha256,
                                section_ids=tuple(
                                    section.section_id
                                    for section in composition.sections
                                    if section.kind == "FORM"
                                ),
                                intent="INITIAL",
                                predecessor_print_record_id=None,
                                printed_on=proposal.document.metadata.printed_on,
                                note="표준 엑셀에서 가져온 사용자 확인 인쇄 기록",
                            ),
                            authorized,
                        )
                        print_id = printed.record.print_record_id
                    output: dict[str, Any] = dict(
                        edition_id=edition.edition_id,
                        revision_id=composition.deliverable_revision_id,
                        composition_sha256=composition.composition_sha256,
                        print_record_id=print_id,
                    )
                    replayed = False
                else:
                    first = session.scalar(
                        select(ContentEditionRevisionRecord)
                        .join(
                            ContentEditionRecord,
                            ContentEditionRecord.edition_id
                            == ContentEditionRevisionRecord.edition_id,
                        )
                        .where(
                            ContentEditionRevisionRecord.deliverable_id == product.deliverable_id,
                            ContentEditionRevisionRecord.revision_number == 1,
                        )
                        .order_by(ContentEditionRecord.created_at, ContentEditionRecord.edition_id)
                        .limit(1)
                    )
                    if first is None:
                        raise ContentPlanningError("CONTENT_WORKBOOK_PROPOSAL_INVALID")
                    print_id = (
                        session.scalar(
                            select(ContentPrintRecord.print_record_id)
                            .where(
                                ContentPrintRecord.deliverable_revision_id
                                == first.deliverable_revision_id,
                                ContentPrintRecord.intent == "INITIAL",
                            )
                            .order_by(
                                ContentPrintRecord.recorded_at, ContentPrintRecord.print_record_id
                            )
                            .limit(1)
                        )
                        if proposal.document.metadata.print_status == "PRINTED"
                        else None
                    )
                    output = dict(
                        edition_id=first.edition_id,
                        revision_id=first.deliverable_revision_id,
                        composition_sha256=first.composition_sha256,
                        print_record_id=print_id,
                    )
                    replayed = True
                output["proposal"] = pointer.model_dump(mode="json")
                result = self._result(session, output, authorized, replayed=replayed)
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=actor.actor_id,
                        command_kind=_COMMIT,
                        idempotency_key=idempotency_key,
                        request_sha256=digest,
                        result_pointer=output,
                    )
                )
                session.flush()
                return result
        except IntegrityError as exc:
            # Same key / different file may race on two content locks. Never keep the loser product.
            with self.sessions() as session:
                authorized = self.authorize(session, actor, write=True)
                receipt = self._receipt(session, actor, _COMMIT, idempotency_key, digest)
                if receipt is not None:
                    return self._result(session, receipt.result_pointer, authorized, replayed=True)
            raise ContentPlanningError("CONTENT_PLANNING_PERSISTENCE_CONFLICT") from exc

    @staticmethod
    def _receipt(
        session: Session, actor: ActorContext, operation: str, key: str, digest: str
    ) -> ContentPlanningCommandReceiptRecord | None:
        row = session.get(ContentPlanningCommandReceiptRecord, (actor.actor_id, operation, key))
        if row is not None and row.request_sha256 != digest:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_CONFLICT")
        return row

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    @staticmethod
    def _result(
        session: Session, pointer: dict[str, Any], actor: ActorContext, *, replayed: bool
    ) -> ContentWorkbookImportResult:
        edition = load_content_edition(session, pointer["edition_id"], include_archived=True)
        composition = read_edition_revision(session, edition, pointer["revision_id"])
        if (
            composition.composition_sha256 != pointer["composition_sha256"]
            or edition.current_revision_id is None
        ):
            raise ContentPlanningError("CONTENT_RECEIPT_POINTER_INVALID")
        manifests = read_curated_slot_revisions(
            session,
            tuple(section.form for section in composition.sections if section.form is not None),
        )
        slots = tuple(slot for manifest in manifests.values() for slot in manifest.placements)
        if (
            resolve_curated_slots(session, tuple(slot.selection() for slot in slots), actor)
            != slots
        ):
            raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
        result = ContentWorkbookImportResult(
            disposition="ALREADY_IMPORTED" if replayed else "IMPORTED",
            replayed=replayed,
            composition=composition,
            current_revision_id=edition.current_revision_id,
            print_record_id=pointer["print_record_id"],
        )
        validate_contract("content-workbook-import-result-v1", result.model_dump(mode="json"))
        if (
            len(canonical_json_bytes(result.model_dump(mode="json"))) + 1024
            > CATALOG_APPLICATION_MAX_MESSAGE_BYTES
        ):
            raise ContentPlanningError("CONTENT_RESULT_TOO_LARGE")
        return result

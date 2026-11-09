"""Shared content editing application: actual actor, one transaction, exact replay."""

from __future__ import annotations

import re
from typing import Literal

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.content_planning import (
    ContentEditionCompositionV1,
    ContentSectionStructure,
)
from eom_catalog_contracts.content_planning_commands import (
    ContentPlanningCommand,
    ContentPlanningWriteResult,
    CopyContentEdition,
    CreateContentEdition,
    CreatePlannedContent,
    EditContentEdition,
    parse_content_planning_command,
)
from eom_catalog_contracts.content_planning_queries import (
    ContentPlanningQuery,
    ContentPlanningQueryResult,
    parse_content_planning_query,
)
from eom_catalog_contracts.content_usage import ReadContentUsage, ReadContentUsageSummary
from eom_catalog_contracts.curated_document_slots import CuratedDocumentAssemblyManifestV2
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_service import ContentDeliveryService
from eom_catalog_service.content_lifecycle_service import ContentLifecycleService
from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_editions import (
    create_edition_snapshot,
    save_edition_snapshot,
)
from eom_catalog_service.content_planning_layout import copy_assembly_slots
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentPlanningCommandReceiptRecord,
)
from eom_catalog_service.content_planning_read import query_content_planning
from eom_catalog_service.content_planning_storage import (
    load_content_edition,
    new_content_id,
    read_edition_revision,
)
from eom_catalog_service.content_print_records import ContentPrintService
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import read_curated_slot_revisions
from eom_catalog_service.models import DeliverableRecord


class ContentPlanningService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.prints = ContentPrintService(engine)
        self.deliveries = ContentDeliveryService(engine)
        self.lifecycle = ContentLifecycleService(engine)

    def query(
        self, query: ContentPlanningQuery, *, actor: ActorContext
    ) -> ContentPlanningQueryResult:
        query = parse_content_planning_query(query.model_dump(mode="json"))
        with self.sessions() as session:
            if isinstance(query, (ReadContentUsage, ReadContentUsageSummary)):
                # The count/page/representative joins must observe one committed head set.
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return query_content_planning(session, query, actor)

    def execute(
        self, command: ContentPlanningCommand, *, actor: ActorContext, idempotency_key: str
    ) -> ContentPlanningWriteResult:
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_KEY_INVALID")
        command = parse_content_planning_command(command.model_dump(mode="json"))
        digest = content_sha256(command.model_dump(mode="json"))
        permission = (
            PermissionKey.DELIVERABLE_UPDATE
            if isinstance(command, EditContentEdition)
            else PermissionKey.DELIVERABLE_CREATE
        )
        try:
            with transaction(self.sessions) as session:
                authorized = authorize_content_planning(session, actor, permission)
                replay = self._replay(
                    session, authorized, command.command_kind, idempotency_key, digest
                )
                if replay is not None:
                    return replay
                if isinstance(command, EditContentEdition):
                    edition = load_content_edition(session, command.edition_id, for_update=True)
                    # The same command may have committed while this caller waited for the head.
                    replay = self._replay(
                        session, authorized, command.command_kind, idempotency_key, digest
                    )
                    if replay is not None:
                        return replay
                    current = self._current(session, edition)
                    product = self._product(session, edition.deliverable_id)
                    composition = save_edition_snapshot(
                        session,
                        edition=edition,
                        product=product,
                        current=current,
                        edit=command.edit,
                        actor=authorized,
                    )
                    disposition: Literal["SAVED", "NO_CHANGE"] = (
                        "NO_CHANGE" if composition == current else "SAVED"
                    )
                else:
                    edition, composition = self._create(session, command, authorized)
                    disposition = "SAVED"
                result = ContentPlanningWriteResult(
                    disposition=disposition,
                    replayed=False,
                    composition=composition,
                    current_revision_id=composition.deliverable_revision_id,
                )
                if (
                    len(canonical_json_bytes(result.model_dump(mode="json"))) + 1024
                    > CATALOG_APPLICATION_MAX_MESSAGE_BYTES
                ):
                    # Do not commit a result the supported private transport cannot return.
                    raise ContentPlanningError("CONTENT_RESULT_TOO_LARGE")
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=authorized.actor_id,
                        command_kind=command.command_kind,
                        idempotency_key=idempotency_key,
                        request_sha256=digest,
                        result_pointer={
                            "edition_id": edition.edition_id,
                            "deliverable_revision_id": composition.deliverable_revision_id,
                            "composition_sha256": composition.composition_sha256,
                            "disposition": disposition,
                        },
                    )
                )
                session.flush()
                validate_contract(
                    "content-planning-write-result-v1", result.model_dump(mode="json")
                )
                return result
        except IntegrityError as exc:
            # Losing a concurrent receipt insert rolls back the *entire* edit,
            # then returns only the exact winner, not an unrelated latest head.
            with self.sessions() as session:
                authorized = authorize_content_planning(session, actor, permission)
                replay = self._replay(
                    session, authorized, command.command_kind, idempotency_key, digest
                )
                if replay is not None:
                    return replay
            raise ContentPlanningError("CONTENT_PLANNING_PERSISTENCE_CONFLICT") from exc

    def read(
        self, edition_id: str, *, actor: ActorContext, revision_id: str | None = None
    ) -> ContentEditionCompositionV1:
        with self.sessions() as session:
            authorize_content_planning(session, actor, PermissionKey.DELIVERABLE_READ)
            edition = load_content_edition(
                session, edition_id, include_archived=revision_id is not None
            )
            selected = revision_id or edition.current_revision_id
            if selected is None:
                raise ContentPlanningError("CONTENT_REVISION_NOT_FOUND")
            return read_edition_revision(session, edition, selected)

    def read_section(
        self,
        edition_id: str,
        section_id: str,
        *,
        revision_id: str,
        composition_sha256: str,
        actor: ActorContext,
    ) -> CuratedDocumentAssemblyManifestV2:
        with self.sessions() as session:
            authorized = authorize_content_planning(session, actor, PermissionKey.DELIVERABLE_READ)
            edition = load_content_edition(session, edition_id, include_archived=True)
            composition = read_edition_revision(session, edition, revision_id)
            if composition.composition_sha256 != composition_sha256:
                raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
            section = next(
                (section for section in composition.sections if section.section_id == section_id),
                None,
            )
            if section is None or section.form is None:
                raise ContentPlanningError("CONTENT_SECTION_NOT_FOUND")
            manifest = read_curated_slot_revisions(session, (section.form,))[
                section.form.assembly_revision_id
            ]
            resolved = resolve_curated_slots(
                session, tuple(slot.selection() for slot in manifest.placements), authorized
            )
            if resolved != manifest.placements:
                raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
            return manifest

    @staticmethod
    def _product(session: Session, product_id: str) -> DeliverableRecord:
        product = session.scalar(
            select(DeliverableRecord)
            .where(DeliverableRecord.deliverable_id == product_id)
            .with_for_update(read=True)
        )
        if product is None or product.lifecycle_state in {"ARCHIVED", "CANCELLED"}:
            raise ContentPlanningError("CONTENT_NOT_AVAILABLE")
        return product

    @staticmethod
    def _current(session: Session, edition: ContentEditionRecord) -> ContentEditionCompositionV1:
        if edition.current_revision_id is None:
            raise ContentPlanningError("CONTENT_REVISION_NOT_FOUND")
        return read_edition_revision(session, edition, edition.current_revision_id)

    def _create(
        self,
        session: Session,
        command: CreatePlannedContent | CreateContentEdition | CopyContentEdition,
        actor: ActorContext,
    ) -> tuple[ContentEditionRecord, ContentEditionCompositionV1]:
        if isinstance(command, CopyContentEdition):
            source_edition = load_content_edition(session, command.source_edition_id)
            source = read_edition_revision(session, source_edition, command.source_revision_id)
            if source.composition_sha256 != command.source_sha256:
                raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
            product = self._product(session, source.deliverable_id)
            manifests = read_curated_slot_revisions(
                session,
                tuple(section.form for section in source.sections if section.form is not None),
            )
            # A new edition gets new section/Form/occurrence identities but keeps
            # exact Item/source/Graph revisions and a copy-origin pointer.
            ids = {section.section_id: new_content_id("section") for section in source.sections}
            structures = tuple(
                ContentSectionStructure.model_validate(
                    {
                        **section.model_dump(exclude={"form"}),
                        "section_id": ids[section.section_id],
                        "parent_id": None if section.parent_id is None else ids[section.parent_id],
                    }
                )
                for section in source.sections
            )
            copied = {}
            for section in source.sections:
                if section.form is not None:
                    manifest = manifests[section.form.assembly_revision_id]
                    copied[ids[section.section_id]] = copy_assembly_slots(
                        manifest, tuple(new_content_id("placement") for _ in manifest.placements)
                    )
            return create_edition_snapshot(
                session,
                product=product,
                edition_label=command.edition_label,
                academic_year=command.academic_year,
                structures=structures,
                actor=actor,
                command_kind=command.command_kind,
                copied_slots=copied,
                copied_from_revision_id=source.deliverable_revision_id,
            )
        if isinstance(command, CreatePlannedContent):
            product_id = new_content_id("deliverable")
            product = DeliverableRecord(
                deliverable_id=product_id,
                deliverable_key="content-planning:" + product_id,
                deliverable_type=command.content_type,
                title=command.content_title,
                edition="CONTENT_PLANNING",
                lifecycle_state="IN_PRODUCTION",
                created_by=actor.actor_id,
            )
            session.add(product)
            session.flush()
        else:
            product = self._product(session, command.deliverable_id)
            if (
                session.scalar(
                    select(ContentEditionRecord.edition_id)
                    .where(ContentEditionRecord.deliverable_id == product.deliverable_id)
                    .limit(1)
                )
                is None
            ):
                raise ContentPlanningError("CONTENT_PROFILE_UNSUPPORTED")
        return create_edition_snapshot(
            session,
            product=product,
            edition_label=command.edition_label,
            academic_year=command.academic_year,
            structures=command.sections,
            actor=actor,
            command_kind=command.command_kind,
        )

    def _replay(
        self, session: Session, actor: ActorContext, command_kind: str, key: str, digest: str
    ) -> ContentPlanningWriteResult | None:
        receipt = session.get(
            ContentPlanningCommandReceiptRecord, (actor.actor_id, command_kind, key)
        )
        if receipt is None:
            return None
        if receipt.request_sha256 != digest:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_CONFLICT")
        pointer = receipt.result_pointer
        edition = load_content_edition(session, pointer["edition_id"], include_archived=True)
        composition = read_edition_revision(session, edition, pointer["deliverable_revision_id"])
        if (
            composition.composition_sha256 != pointer["composition_sha256"]
            or edition.current_revision_id is None
        ):
            raise ContentPlanningError("CONTENT_RECEIPT_POINTER_INVALID")
        result = ContentPlanningWriteResult(
            disposition=pointer["disposition"],
            replayed=True,
            composition=composition,
            current_revision_id=edition.current_revision_id,
        )
        validate_contract("content-planning-write-result-v1", result.model_dump(mode="json"))
        return result

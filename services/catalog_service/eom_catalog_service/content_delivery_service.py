"""Pin a selected content scope; reuse the existing HWPX application for execution."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from eom_catalog_contracts.content_delivery import ContentDeliveryPrepared, PrepareContentDelivery
from eom_catalog_contracts.content_planning import ContentPrintScopeV1
from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    ResolvedCuratedSlot,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_models import ContentDeliveryScopeRecord
from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_layout import select_print_scope
from eom_catalog_service.content_planning_models import ContentPlanningCommandReceiptRecord
from eom_catalog_service.content_planning_storage import (
    load_content_edition,
    new_content_id,
    read_edition_revision,
)
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import (
    CuratedSlotRevisionWrite,
    append_curated_slot_revisions,
    read_curated_slot_revisions,
)


def _scope_slots(
    session: Session,
    scope: ContentPrintScopeV1,
    actor: ActorContext,
) -> tuple[ResolvedCuratedSlot, ...]:
    manifests = read_curated_slot_revisions(session, tuple(row.form for row in scope.forms))
    slots = tuple(
        slot
        for form in scope.forms
        for slot in manifests[form.form.assembly_revision_id].placements
    )
    if not slots or any(slot.target.placement_kind == "EMPTY" for slot in slots):
        raise ContentPlanningError("CONTENT_DELIVERY_UNFILLED_PLACEMENTS")
    if len(slots) > 100000:
        raise ContentPlanningError("CONTENT_DELIVERY_SCOPE_TOO_LARGE")
    if resolve_curated_slots(session, tuple(slot.selection() for slot in slots), actor) != slots:
        raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
    return tuple(
        slot.model_copy(update={"position": number}) for number, slot in enumerate(slots, 1)
    )


def read_content_delivery(
    session: Session,
    assembly_id: str,
    assembly_revision_id: str,
    manifest_sha256: str,
    *,
    actor: ActorContext,
    permission: PermissionKey,
) -> tuple[ContentDeliveryPrepared, CuratedDocumentAssemblyManifestV2]:
    """Metadata-only reauthorization of a saved scope, including old pinned Forms."""
    authorized = authorize_content_planning(session, actor, permission)
    row = session.get(ContentDeliveryScopeRecord, assembly_revision_id)
    if row is None or row.assembly_id != assembly_id:
        raise ContentPlanningError("CONTENT_DELIVERY_NOT_FOUND")
    scope = ContentPrintScopeV1.model_validate(row.canonical_scope)
    edition = load_content_edition(
        session, row.edition_id, include_archived=permission is PermissionKey.HWPX_READ
    )
    composition = read_edition_revision(session, edition, row.deliverable_revision_id)
    if (
        scope != select_print_scope(composition, tuple(form.section_id for form in scope.forms))
        or scope.scope_sha256 != row.scope_sha256
    ):
        raise ContentPlanningError("CONTENT_DELIVERY_SCOPE_INVALID")
    result = ContentDeliveryPrepared(
        edition_id=row.edition_id,
        revision_id=row.deliverable_revision_id,
        composition_sha256=composition.composition_sha256,
        scope_sha256=row.scope_sha256,
        assembly_id=row.assembly_id,
        assembly_revision_id=row.assembly_revision_id,
        manifest_sha256=manifest_sha256,
        placement_count=sum(form.form.placement_count for form in scope.forms),
        created_at=row.created_at,
        replayed=False,
    )
    manifest = read_curated_slot_revisions(session, (result,))[assembly_revision_id]
    if manifest.created_at != row.created_at or manifest.placements != _scope_slots(
        session, scope, authorized
    ):
        raise ContentPlanningError("CONTENT_DELIVERY_SCOPE_INVALID")
    return result, manifest


class ContentDeliveryService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def prepare(
        self, command: PrepareContentDelivery, *, actor: ActorContext, idempotency_key: str
    ) -> ContentDeliveryPrepared:
        validate_contract("content-delivery-command-v1", command.model_dump(mode="json"))
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_KEY_INVALID")
        digest = content_sha256(command.model_dump(mode="json"))
        try:
            with transaction(self.sessions) as session:
                authorized = authorize_content_planning(
                    session, actor, PermissionKey.HWPX_BUILD_CREATE
                )
                edition = load_content_edition(session, command.edition_id, for_update=True)
                replay = self._replay(session, command, authorized, idempotency_key, digest)
                if replay is not None:
                    return replay
                composition = read_edition_revision(session, edition, command.revision_id)
                if composition.composition_sha256 != command.composition_sha256:
                    raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
                scope = select_print_scope(composition, command.section_ids)
                existing = session.scalar(
                    select(ContentDeliveryScopeRecord).where(
                        ContentDeliveryScopeRecord.deliverable_revision_id == command.revision_id,
                        ContentDeliveryScopeRecord.scope_sha256 == scope.scope_sha256,
                    )
                )
                if existing is None:
                    slots = _scope_slots(session, scope, authorized)
                    if (
                        len(canonical_json_bytes(scope.model_dump(mode="json")))
                        > 4 * 1024**2 - 4096
                    ):
                        raise ContentPlanningError("CONTENT_DELIVERY_SCOPE_TOO_LARGE")
                    now = datetime.now(UTC)
                    assembly_id, revision_id = (
                        new_content_id("assembly"),
                        new_content_id("assemblyrev"),
                    )
                    manifest = append_curated_slot_revisions(
                        session,
                        (
                            CuratedSlotRevisionWrite(
                                assembly_id=assembly_id,
                                revision_id=revision_id,
                                previous=None,
                                title=composition.content_title,
                                placements=slots,
                            ),
                        ),
                        actor_id=authorized.actor_id,
                        created_at=now,
                    )[assembly_id]
                    existing = ContentDeliveryScopeRecord(
                        assembly_id=assembly_id,
                        assembly_revision_id=revision_id,
                        edition_id=command.edition_id,
                        deliverable_revision_id=command.revision_id,
                        scope_sha256=scope.scope_sha256,
                        canonical_scope=scope.model_dump(mode="json"),
                        created_at=now,
                    )
                    session.add(existing)
                    session.flush()
                    result = ContentDeliveryPrepared(
                        edition_id=command.edition_id,
                        revision_id=command.revision_id,
                        composition_sha256=command.composition_sha256,
                        scope_sha256=scope.scope_sha256,
                        assembly_id=assembly_id,
                        assembly_revision_id=revision_id,
                        manifest_sha256=manifest.manifest_sha256,
                        placement_count=len(slots),
                        created_at=now,
                        replayed=False,
                    )
                else:
                    result = self._read(session, existing.assembly_revision_id, authorized)
                session.add(
                    ContentPlanningCommandReceiptRecord(
                        actor_id=authorized.actor_id,
                        command_kind=command.command_kind,
                        idempotency_key=idempotency_key,
                        request_sha256=digest,
                        result_pointer={"assembly_revision_id": result.assembly_revision_id},
                    )
                )
                session.flush()
                validate_contract("content-delivery-prepared-v1", result.model_dump(mode="json"))
                return result
        except IntegrityError as exc:
            with self.sessions() as session:
                authorized = authorize_content_planning(
                    session, actor, PermissionKey.HWPX_BUILD_CREATE
                )
                replay = self._replay(session, command, authorized, idempotency_key, digest)
                if replay is not None:
                    return replay
            raise ContentPlanningError("CONTENT_DELIVERY_PERSISTENCE_CONFLICT") from exc

    @staticmethod
    def _read(session: Session, revision_id: str, actor: ActorContext) -> ContentDeliveryPrepared:
        revision = session.get(CuratedDocumentAssemblyRevisionRecord, revision_id)
        if revision is None:
            raise ContentPlanningError("CONTENT_DELIVERY_NOT_FOUND")
        return read_content_delivery(
            session,
            revision.assembly_id,
            revision_id,
            revision.manifest_sha256,
            actor=actor,
            permission=PermissionKey.HWPX_BUILD_CREATE,
        )[0]

    def _replay(
        self,
        session: Session,
        command: PrepareContentDelivery,
        actor: ActorContext,
        key: str,
        digest: str,
    ) -> ContentDeliveryPrepared | None:
        row = session.get(
            ContentPlanningCommandReceiptRecord, (actor.actor_id, command.command_kind, key)
        )
        if row is None:
            return None
        if row.request_sha256 != digest:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_CONFLICT")
        result = self._read(session, row.result_pointer["assembly_revision_id"], actor)
        if result.edition_id != command.edition_id or result.revision_id != command.revision_id:
            raise ContentPlanningError("CONTENT_DELIVERY_SCOPE_INVALID")
        return result.model_copy(update={"replayed": True})

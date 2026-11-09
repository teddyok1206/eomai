"""Catalog application use case for one immutable mixed-source selection."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_catalog_contracts import (
    CuratedDocumentAssemblyListEntryV1,
    CuratedDocumentAssemblyManifestV1,
    CuratedExternalDocumentPlacement,
    CuratedPastExamItemPlacement,
    validate_contract,
)
from eom_catalog_contracts.curated_document_assembly_draft import (
    CuratedDocumentAssemblyDraftV1,
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts.curated_document_assembly_library import (
    CuratedDocumentAssemblyDraftV2,
    CuratedDocumentAssemblyListEntryV2,
    CuratedDocumentAssemblyRemovalInput,
    CuratedDocumentAssemblyRemovalReceipt,
)
from eom_catalog_contracts.curated_document_slots import CuratedDeliveryManifest
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.curated_occurrences import CuratedBuildInput
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_models import ContentDeliveryScopeRecord
from eom_catalog_service.content_delivery_service import read_content_delivery
from eom_catalog_service.content_planning_models import ContentFormMembershipRecord
from eom_catalog_service.curated_delivery_inputs import CuratedDeliveryInputs
from eom_catalog_service.curated_document_assembly_item import (
    reauthorize_curated_registered_items,
)
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyPlacementRecord,
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_assembly_resolution import (
    resolve_curated_document_assembly_manifest,
)
from eom_catalog_service.curated_document_assembly_source import (
    reauthorize_curated_external_documents,
)
from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService


class CuratedDocumentAssemblyError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _stable_id(prefix: str, identity: dict[str, str]) -> str:
    return prefix + content_sha256(identity).removeprefix("sha256:")[:32]


class CuratedDocumentAssemblyService:
    """Persist only pinned inputs; HWPX delivery has its own later admission."""

    def __init__(self, engine: Engine, media: ExternalItemDocumentMediaService) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.media = media

    def create(
        self,
        draft: CuratedDocumentAssemblyDraftV1 | CuratedDocumentAssemblyDraftV2,
        *,
        actor: ActorContext,
        idempotency_key: str,
    ) -> CuratedDocumentAssemblyManifestV1:
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_INVALID")
        draft = type(draft).model_validate(draft.model_dump(mode="json"))
        title = draft.title if isinstance(draft, CuratedDocumentAssemblyDraftV2) else ""
        selection = (
            draft.selection() if isinstance(draft, CuratedDocumentAssemblyDraftV2) else draft
        )
        selection_sha256 = content_sha256(selection.model_dump(mode="json"))
        request_value = {
            "actor_id": actor.actor_id,
            "idempotency_key": idempotency_key,
            "selection_sha256": selection_sha256,
        }
        if isinstance(draft, CuratedDocumentAssemblyDraftV2):
            request_value.update(draft_schema_version=draft.schema_version, title=title)
        request_sha256 = content_sha256(request_value)
        try:
            with transaction(self.sessions) as session:
                actor = self._authorized_actor(session, actor)
                existing = session.scalar(
                    select(CuratedDocumentAssemblyRevisionRecord).where(
                        CuratedDocumentAssemblyRevisionRecord.created_by == actor.actor_id,
                        CuratedDocumentAssemblyRevisionRecord.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return self._replay(
                        session, existing, selection, actor, request_sha256, expected_title=title
                    )

                identity = {"actor_id": actor.actor_id, "idempotency_key": idempotency_key}
                assembly_id = _stable_id("assembly_", identity)
                assembly_revision_id = _stable_id("assemblyrev_", {**identity, "revision": "1"})
                created_at = datetime.now(UTC)
                manifest = resolve_curated_document_assembly_manifest(
                    session,
                    self.media,
                    draft=selection,
                    actor=actor,
                    assembly_id=assembly_id,
                    assembly_revision_id=assembly_revision_id,
                    created_at=created_at,
                )
                session.add(
                    CuratedDocumentAssemblyRecord(
                        assembly_id=assembly_id,
                        current_revision_id=None,
                        created_by=actor.actor_id,
                        created_at=created_at,
                        title=title,
                    )
                )
                session.flush()
                session.add(
                    CuratedDocumentAssemblyRevisionRecord(
                        assembly_revision_id=assembly_revision_id,
                        assembly_id=assembly_id,
                        revision_number=1,
                        previous_revision_id=None,
                        revision_state="INPUT_PINNED",
                        selection_sha256=manifest.selection_sha256,
                        request_sha256=request_sha256,
                        manifest_sha256=manifest.manifest_sha256,
                        canonical_document=manifest.model_dump(mode="json"),
                        idempotency_key=idempotency_key,
                        created_by=actor.actor_id,
                        created_at=created_at,
                    )
                )
                session.flush()
                session.add_all(self._placement_rows(manifest))
                aggregate = session.get(CuratedDocumentAssemblyRecord, assembly_id)
                if aggregate is None:
                    raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDENTITY_MISSING")
                aggregate.current_revision_id = assembly_revision_id
                return manifest
        except IntegrityError as exc:
            # A concurrent submit can win the unique actor/key race. Reopen a
            # fresh transaction and replay only its exact committed result.
            with self.sessions() as session:
                actor = self._authorized_actor(session, actor)
                existing = session.scalar(
                    select(CuratedDocumentAssemblyRevisionRecord).where(
                        CuratedDocumentAssemblyRevisionRecord.created_by == actor.actor_id,
                        CuratedDocumentAssemblyRevisionRecord.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return self._replay(
                        session, existing, selection, actor, request_sha256, expected_title=title
                    )
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERSISTENCE_CONFLICT") from exc

    def read(self, assembly_id: str, *, actor: ActorContext) -> CuratedDocumentAssemblyManifestV1:
        """Return one owned pinned selection, never an implicit latest Item/source."""

        with self.sessions() as session:
            authorized = self._authorized_actor(session, actor)
            if PermissionKey.ITEM_READ not in authorized.permissions:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
            aggregate = session.get(CuratedDocumentAssemblyRecord, assembly_id)
            if aggregate is None or aggregate.created_by != authorized.actor_id:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_NOT_FOUND")
            revision_id = aggregate.current_revision_id
            if revision_id is None:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
            revision = session.get(CuratedDocumentAssemblyRevisionRecord, revision_id)
            if (
                revision is None
                or revision.assembly_id != assembly_id
                or revision.created_by != authorized.actor_id
                or revision.revision_state != "INPUT_PINNED"
            ):
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
            try:
                value = revision.canonical_document
                validate_contract("curated-document-assembly-manifest-v1", value)
                manifest = CuratedDocumentAssemblyManifestV1.model_validate(value)
            except (ValueError, TypeError, JsonSchemaValidationError) as exc:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID") from exc
            if (
                manifest.assembly_id != assembly_id
                or manifest.assembly_revision_id != revision_id
                or manifest.created_by != authorized.actor_id
                or manifest.created_at != revision.created_at
                or manifest.manifest_sha256 != revision.manifest_sha256
                or manifest.selection_sha256 != revision.selection_sha256
                or not self._placements_match(session, manifest)
            ):
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
            if (
                any(
                    isinstance(row, CuratedExternalDocumentPlacement) for row in manifest.placements
                )
                and PermissionKey.CONTENT_INTAKE_READ not in authorized.permissions
            ):
                raise CuratedDocumentAssemblyError("CURATED_SOURCE_PERMISSION_DENIED")
            return manifest

    def pin_delivery_inputs(
        self,
        manifest: CuratedDeliveryManifest,
        *,
        actor: ActorContext,
        handoff: ContentTeamHandoffSnapshot,
        converter: CuratedHwpConverterSnapshot,
    ) -> CuratedBuildInput:
        return CuratedDeliveryInputs(
            self.engine, assemblies=self, handoff=handoff, converter=converter
        ).pin_inputs(manifest, actor=actor)

    def read_for_delivery(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDeliveryManifest:
        """Read/status/download permission, distinct from permission to build."""
        return self._authorize_delivery(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
            permission=PermissionKey.HWPX_READ,
        )

    def authorize_delivery_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDeliveryManifest:
        """Admit or execute a durable build with the initiator's current authority."""
        return self._authorize_delivery(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
            permission=PermissionKey.HWPX_BUILD_CREATE,
        )

    def _authorize_delivery(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
        permission: PermissionKey,
    ) -> CuratedDeliveryManifest:
        """Authorize one exact saved input with bounded metadata reads.

        No file materialization or render is performed by a status/replay read.
        The original published Graph remains pinned when the corpus head advances.
        Source revocation, changed source pointers and operator permissions are
        still checked; none of them is repaired by resolving an implicit latest.
        """
        with self.sessions() as session:
            schema = session.scalar(
                select(CuratedDocumentAssemblyRevisionRecord.manifest_schema_version).where(
                    CuratedDocumentAssemblyRevisionRecord.assembly_id == assembly_id,
                    CuratedDocumentAssemblyRevisionRecord.assembly_revision_id
                    == assembly_revision_id,
                )
            )
            if schema == "curated-document-assembly-manifest/2.0":
                return read_content_delivery(
                    session,
                    assembly_id,
                    assembly_revision_id,
                    manifest_sha256,
                    actor=actor,
                    permission=permission,
                )[1]
        manifest = self.read(assembly_id, actor=actor)
        if (
            manifest.assembly_revision_id != assembly_revision_id
            or manifest.manifest_sha256 != manifest_sha256
        ):
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
        with self.sessions() as session:
            authorized = self._authorized_actor(session, actor)
            required = {PermissionKey.ITEM_READ, permission}
            if not required <= authorized.permissions:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
            external = tuple(
                row
                for row in manifest.placements
                if isinstance(row, CuratedExternalDocumentPlacement)
            )
            if external and PermissionKey.CONTENT_INTAKE_READ not in authorized.permissions:
                raise CuratedDocumentAssemblyError("CURATED_SOURCE_PERMISSION_DENIED")
            reauthorize_curated_external_documents(session, external)
            selections: list[RegisteredItemPlacement | PastExamItemPlacement] = []
            for row in manifest.placements:
                if isinstance(row, CuratedExternalDocumentPlacement):
                    continue
                model = (
                    PastExamItemPlacement
                    if isinstance(row, CuratedPastExamItemPlacement)
                    else RegisteredItemPlacement
                )
                selections.append(
                    model.model_validate({name: getattr(row, name) for name in model.model_fields})
                )
            resolved = reauthorize_curated_registered_items(session, tuple(selections))
            if resolved != tuple(
                row
                for row in manifest.placements
                if not isinstance(row, CuratedExternalDocumentPlacement)
            ):
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
        return manifest

    def list_recent(
        self, *, actor: ActorContext, limit: int = 20, cursor: str | None = None
    ) -> tuple[tuple[CuratedDocumentAssemblyListEntryV1, ...], str | None]:
        values, next_cursor = self.list_recent_titled(actor=actor, limit=limit, cursor=cursor)
        return (
            tuple(
                CuratedDocumentAssemblyListEntryV1.model_validate(
                    row.model_dump(mode="json", exclude={"title"})
                )
                for row in values
            ),
            next_cursor,
        )

    def list_recent_titled(
        self, *, actor: ActorContext, limit: int = 20, cursor: str | None = None
    ) -> tuple[tuple[CuratedDocumentAssemblyListEntryV2, ...], str | None]:
        """Keyset page over the operator's own pinned assemblies, without copying manifests."""

        if not 1 <= limit <= 50:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_LIST_INVALID")
        boundary: tuple[datetime, str] | None = None
        if cursor is not None:
            try:
                micros, assembly_id = cursor.split("|", 1)
                if (
                    re.fullmatch(r"[0-9]{13,20}", micros) is None
                    or re.fullmatch(r"assembly_[0-9a-f]{32}", assembly_id) is None
                ):
                    raise ValueError("invalid cursor")
                boundary = (
                    datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(micros)),
                    assembly_id,
                )
            except (ValueError, OverflowError) as exc:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_LIST_INVALID") from exc
        with self.sessions() as session:
            authorized = self._authorized_actor(session, actor)
            if PermissionKey.ITEM_READ not in authorized.permissions:
                raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
            aggregate = CuratedDocumentAssemblyRecord
            revision = CuratedDocumentAssemblyRevisionRecord
            statement = (
                select(
                    aggregate.assembly_id,
                    aggregate.current_revision_id,
                    aggregate.created_at,
                    aggregate.title,
                    revision.manifest_sha256,
                    revision.revision_state,
                    revision.created_by,
                    func.jsonb_array_length(revision.canonical_document["placements"]),
                )
                .outerjoin(revision, aggregate.current_revision_id == revision.assembly_revision_id)
                .where(
                    aggregate.created_by == authorized.actor_id,
                    aggregate.removed_at.is_(None),
                    ~select(ContentFormMembershipRecord.assessment_form_id)
                    .where(ContentFormMembershipRecord.assembly_id == aggregate.assembly_id)
                    .exists(),
                    ~select(ContentDeliveryScopeRecord.assembly_id)
                    .where(ContentDeliveryScopeRecord.assembly_id == aggregate.assembly_id)
                    .exists(),
                )
                .order_by(aggregate.created_at.desc(), aggregate.assembly_id.desc())
                .limit(limit + 1)
            )
            if boundary is not None:
                statement = statement.where(
                    tuple_(aggregate.created_at, aggregate.assembly_id) < boundary
                )
            rows = session.execute(statement).all()
            values: list[CuratedDocumentAssemblyListEntryV2] = []
            for assembly_id, revision_id, created_at, title, digest, state, owner, count in rows[
                :limit
            ]:
                if (
                    revision_id is None
                    or digest is None
                    or state != "INPUT_PINNED"
                    or owner != authorized.actor_id
                ):
                    raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
                try:
                    values.append(
                        CuratedDocumentAssemblyListEntryV2(
                            assembly_id=assembly_id,
                            assembly_revision_id=revision_id,
                            created_at=created_at,
                            title=title,
                            placement_count=count,
                            manifest_sha256=digest,
                        )
                    )
                except ValueError as exc:
                    raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID") from exc
            next_cursor = None
            if len(rows) > limit and values:
                last = values[-1]
                cursor_micros = (last.created_at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(
                    microseconds=1
                )
                next_cursor = f"{cursor_micros}|{last.assembly_id}"
            return tuple(values), next_cursor

    def remove_from_list(
        self,
        assembly_id: str,
        selection: CuratedDocumentAssemblyRemovalInput,
        *,
        actor: ActorContext,
        idempotency_key: str,
    ) -> CuratedDocumentAssemblyRemovalReceipt:
        """Archive one owned list entry; never delete input revisions or HWPX history."""
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_INVALID")
        selection = CuratedDocumentAssemblyRemovalInput.model_validate(selection)
        digest = content_sha256(
            dict(
                purpose="REMOVE_CURATED_DOCUMENT_ASSEMBLY/1.0",
                actor_id=actor.actor_id,
                assembly_id=assembly_id,
                selection=selection.model_dump(mode="json"),
                idempotency_key=idempotency_key,
            )
        )
        try:
            with transaction(self.sessions) as session:
                authorized = self._authorized_actor(session, actor)
                if (
                    not {PermissionKey.ITEM_READ, PermissionKey.DELIVERABLE_CREATE}
                    <= authorized.permissions
                ):
                    raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
                aggregate = session.scalar(
                    select(CuratedDocumentAssemblyRecord)
                    .where(
                        CuratedDocumentAssemblyRecord.assembly_id == assembly_id,
                        CuratedDocumentAssemblyRecord.created_by == authorized.actor_id,
                    )
                    .with_for_update()
                )
                if aggregate is None:
                    raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_NOT_FOUND")
                if aggregate.removed_at is not None:
                    if (
                        aggregate.removal_idempotency_key != idempotency_key
                        or aggregate.removal_request_sha256 != digest
                    ):
                        raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_CONFLICT")
                else:
                    revision = session.get(
                        CuratedDocumentAssemblyRevisionRecord, selection.assembly_revision_id
                    )
                    if (
                        aggregate.current_revision_id != selection.assembly_revision_id
                        or revision is None
                        or revision.assembly_id != assembly_id
                        or revision.created_by != authorized.actor_id
                        or revision.revision_state != "INPUT_PINNED"
                        or revision.manifest_sha256 != selection.manifest_sha256
                    ):
                        raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_POINTER_INVALID")
                    aggregate.removed_at = datetime.now(UTC)
                    aggregate.removal_idempotency_key = idempotency_key
                    aggregate.removal_request_sha256 = digest
                return CuratedDocumentAssemblyRemovalReceipt(
                    assembly_id=assembly_id,
                    assembly_revision_id=selection.assembly_revision_id,
                    manifest_sha256=selection.manifest_sha256,
                    removed_at=aggregate.removed_at,
                )
        except IntegrityError as exc:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_CONFLICT") from exc

    @staticmethod
    def _authorized_actor(session: Session, actor: ActorContext) -> ActorContext:
        """Use the authenticated API identity, but never trust its stale role snapshot."""
        if (
            actor.actor_type is not ActorType.OPERATOR
            or actor.source is not ActorSource.APPLICATION_API
            or actor.operator_id is None
        ):
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
        operator = session.get(OperatorRecord, actor.operator_id)
        if (
            operator is None
            or operator.status != "ACTIVE"
            or operator.deleted_at is not None
            or operator.must_change_password
        ):
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
        return actor.model_copy(
            update={"permissions": effective_permissions(session, actor.operator_id)}
        )

    @staticmethod
    def _placement_rows(
        manifest: CuratedDocumentAssemblyManifestV1,
    ) -> tuple[CuratedDocumentAssemblyPlacementRecord, ...]:
        rows: list[CuratedDocumentAssemblyPlacementRecord] = []
        for placement in manifest.placements:
            common: dict[str, Any] = {
                "assembly_revision_id": manifest.assembly_revision_id,
                "position": placement.position,
                "placement_kind": placement.placement_kind,
            }
            if isinstance(placement, CuratedExternalDocumentPlacement):
                common.update(
                    source_id=placement.source_id,
                    source_revision_id=placement.source_revision_id,
                    source_file_id=placement.source_file_id,
                    item_id=None,
                    item_revision_id=None,
                    graph_snapshot_revision_id=None,
                )
            else:
                common.update(
                    source_id=None,
                    source_revision_id=None,
                    source_file_id=None,
                    item_id=placement.item_id,
                    item_revision_id=placement.item_revision_id,
                    graph_snapshot_revision_id=placement.graph_snapshot_revision_id,
                )
            rows.append(CuratedDocumentAssemblyPlacementRecord(**common))
        return tuple(rows)

    @staticmethod
    def _replay(
        session: Session,
        existing: CuratedDocumentAssemblyRevisionRecord,
        draft: CuratedDocumentAssemblyDraftV1,
        actor: ActorContext,
        request_sha256: str,
        *,
        expected_title: str = "",
    ) -> CuratedDocumentAssemblyManifestV1:
        if existing.request_sha256 != request_sha256 or existing.selection_sha256 != content_sha256(
            draft.model_dump(mode="json")
        ):
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_CONFLICT")
        if not {PermissionKey.ITEM_READ, PermissionKey.DELIVERABLE_CREATE} <= actor.permissions:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERMISSION_DENIED")
        if (
            any(row.placement_kind == "EXTERNAL_SOURCE_DOCUMENT" for row in draft.placements)
            and PermissionKey.CONTENT_INTAKE_READ not in actor.permissions
        ):
            raise CuratedDocumentAssemblyError("CURATED_SOURCE_PERMISSION_DENIED")
        value = existing.canonical_document
        validate_contract("curated-document-assembly-manifest-v1", value)
        manifest = CuratedDocumentAssemblyManifestV1.model_validate(value)
        aggregate = session.get(CuratedDocumentAssemblyRecord, existing.assembly_id)
        identity = {"actor_id": actor.actor_id, "idempotency_key": existing.idempotency_key}
        if (
            manifest.manifest_sha256 != existing.manifest_sha256
            or manifest.selection_sha256 != existing.selection_sha256
            or not CuratedDocumentAssemblyService._selection_matches(draft, manifest)
            or existing.created_by != actor.actor_id
            or existing.revision_number != 1
            or existing.previous_revision_id is not None
            or existing.assembly_id != _stable_id("assembly_", identity)
            or existing.assembly_revision_id
            != _stable_id("assemblyrev_", {**identity, "revision": "1"})
            or manifest.assembly_id != existing.assembly_id
            or manifest.assembly_revision_id != existing.assembly_revision_id
            or manifest.created_by != actor.actor_id
            or manifest.created_at != existing.created_at
            or existing.revision_state != "INPUT_PINNED"
            or aggregate is None
            or aggregate.created_by != actor.actor_id
            or aggregate.title != expected_title
            or not CuratedDocumentAssemblyService._placements_match(session, manifest)
        ):
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_REPLAY_POINTER_INVALID")
        return manifest

    @staticmethod
    def _selection_matches(
        draft: CuratedDocumentAssemblyDraftV1,
        manifest: CuratedDocumentAssemblyManifestV1,
    ) -> bool:
        if len(draft.placements) != len(manifest.placements):
            return False
        return all(
            all(
                getattr(requested, name) == getattr(resolved, name)
                for name in type(requested).model_fields
            )
            for requested, resolved in zip(draft.placements, manifest.placements, strict=True)
        )

    @staticmethod
    def _placements_match(session: Session, manifest: CuratedDocumentAssemblyManifestV1) -> bool:
        rows = tuple(
            session.scalars(
                select(CuratedDocumentAssemblyPlacementRecord)
                .where(
                    CuratedDocumentAssemblyPlacementRecord.assembly_revision_id
                    == manifest.assembly_revision_id
                )
                .order_by(CuratedDocumentAssemblyPlacementRecord.position)
            )
        )
        if len(rows) != len(manifest.placements):
            return False
        for row, placement in zip(rows, manifest.placements, strict=True):
            if row.position != placement.position or row.placement_kind != placement.placement_kind:
                return False
            if isinstance(placement, CuratedExternalDocumentPlacement):
                if (
                    row.source_id != placement.source_id
                    or row.source_revision_id != placement.source_revision_id
                    or row.source_file_id != placement.source_file_id
                    or row.item_id is not None
                    or row.item_revision_id is not None
                    or row.graph_snapshot_revision_id is not None
                ):
                    return False
            elif (
                row.item_id != placement.item_id
                or row.item_revision_id != placement.item_revision_id
                or row.graph_snapshot_revision_id != placement.graph_snapshot_revision_id
                or row.source_id is not None
                or row.source_revision_id is not None
                or row.source_file_id is not None
            ):
                return False
        return True

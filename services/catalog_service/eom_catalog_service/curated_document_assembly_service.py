"""Catalog application use case for one immutable mixed-source selection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from eom_catalog_contracts import (
    CuratedDocumentAssemblyManifestV1,
    CuratedExternalDocumentPlacement,
    validate_contract,
)
from eom_catalog_contracts.curated_document_assembly_draft import CuratedDocumentAssemblyDraftV1
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyPlacementRecord,
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_assembly_resolution import (
    resolve_curated_document_assembly_manifest,
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
        self.sessions = build_session_factory(engine)
        self.media = media

    def create(
        self,
        draft: CuratedDocumentAssemblyDraftV1,
        *,
        actor: ActorContext,
        idempotency_key: str,
    ) -> CuratedDocumentAssemblyManifestV1:
        if re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_IDEMPOTENCY_INVALID")
        selection_sha256 = content_sha256(draft.model_dump(mode="json"))
        request_sha256 = content_sha256(
            {
                "actor_id": actor.actor_id,
                "idempotency_key": idempotency_key,
                "selection_sha256": selection_sha256,
            }
        )
        try:
            with transaction(self.sessions) as session:
                actor = self._authorized_actor(session, actor)
                existing = session.scalar(
                    select(CuratedDocumentAssemblyRevisionRecord)
                    .where(
                        CuratedDocumentAssemblyRevisionRecord.created_by == actor.actor_id,
                        CuratedDocumentAssemblyRevisionRecord.idempotency_key == idempotency_key,
                    )
                    .with_for_update(read=True)
                )
                if existing is not None:
                    return self._replay(session, existing, draft, actor, request_sha256)

                identity = {"actor_id": actor.actor_id, "idempotency_key": idempotency_key}
                assembly_id = _stable_id("assembly_", identity)
                assembly_revision_id = _stable_id("assemblyrev_", {**identity, "revision": "1"})
                created_at = datetime.now(UTC)
                manifest = resolve_curated_document_assembly_manifest(
                    session,
                    self.media,
                    draft=draft,
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
                    return self._replay(session, existing, draft, actor, request_sha256)
            raise CuratedDocumentAssemblyError("CURATED_ASSEMBLY_PERSISTENCE_CONFLICT") from exc

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

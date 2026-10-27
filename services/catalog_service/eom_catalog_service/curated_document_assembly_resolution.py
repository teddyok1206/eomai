"""Resolve a browser draft into exact, uncommitted mixed-source assembly inputs."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from eom_api_contracts.curated_document_assembly import (
    CuratedDocumentAssemblyDraftV1,
    ExternalSourcePlacement,
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1, validate_contract
from eom_catalog_contracts.curated_document_assembly import CuratedResolvedPlacement
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy.orm import Session

from eom_catalog_service.curated_document_assembly_item import resolve_curated_registered_items
from eom_catalog_service.curated_document_assembly_source import resolve_curated_external_document
from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService


class CuratedDocumentAssemblyResolutionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_curated_document_assembly_manifest(
    session: Session,
    media: ExternalItemDocumentMediaService,
    *,
    draft: CuratedDocumentAssemblyDraftV1,
    actor: ActorContext,
    assembly_id: str,
    assembly_revision_id: str,
    created_at: datetime,
) -> CuratedDocumentAssemblyManifestV1:
    """Validate one pinned selection; the caller must commit it as an Artifact.

    This resolves current authority under the caller's transaction but does not
    register an Assembly, publish an Item, or build HWPX. Callers must authorize
    the real operator and preserve the transaction through the eventual commit.
    """

    if (
        re.fullmatch(r"assembly_[0-9a-f]{32}", assembly_id) is None
        or re.fullmatch(r"assemblyrev_[0-9a-f]{32}", assembly_revision_id) is None
        or created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
    ):
        raise CuratedDocumentAssemblyResolutionError("CURATED_ASSEMBLY_IDENTITY_INVALID")
    if not {PermissionKey.ITEM_READ, PermissionKey.DELIVERABLE_CREATE} <= actor.permissions:
        raise CuratedDocumentAssemblyResolutionError("CURATED_ASSEMBLY_PERMISSION_DENIED")
    external = tuple(
        placement
        for placement in draft.placements
        if isinstance(placement, ExternalSourcePlacement)
    )
    if external and PermissionKey.CONTENT_INTAKE_READ not in actor.permissions:
        raise CuratedDocumentAssemblyResolutionError("CURATED_SOURCE_PERMISSION_DENIED")
    registered: tuple[RegisteredItemPlacement | PastExamItemPlacement, ...] = tuple(
        placement
        for placement in draft.placements
        if isinstance(placement, (RegisteredItemPlacement, PastExamItemPlacement))
    )
    resolved_items = resolve_curated_registered_items(session, registered)
    by_item_revision = {row.item_revision_id: row for row in resolved_items}
    # One lock order for concurrent drafts with opposite display order.
    by_external_source = {
        placement.source_id: resolve_curated_external_document(session, media, placement)
        for placement in sorted(external, key=lambda row: row.source_id)
    }
    ordered: tuple[CuratedResolvedPlacement, ...] = tuple(
        by_external_source[placement.source_id]
        if isinstance(placement, ExternalSourcePlacement)
        else by_item_revision[placement.item_revision_id]
        for placement in draft.placements
    )
    manifest_value: dict[str, object] = {
        "schema_version": "curated-document-assembly-manifest/1.0",
        "assembly_id": assembly_id,
        "assembly_revision_id": assembly_revision_id,
        "selection_sha256": content_sha256(draft.model_dump(mode="json")),
        "placements": [row.model_dump(mode="json") for row in ordered],
        "created_by": actor.actor_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    validate_contract("curated-document-assembly-manifest-v1", manifest_value)
    return CuratedDocumentAssemblyManifestV1.model_validate(manifest_value)

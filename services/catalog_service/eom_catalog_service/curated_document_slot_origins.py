"""Validate declared copy lineage against exact shared-content occurrences."""

from __future__ import annotations

from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    CuratedSlot,
)
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_models import ContentFormMembershipRecord
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord


def validate_slot_origins(
    session: Session, slots: tuple[CuratedSlot, ...], actor: ActorContext
) -> None:
    copies = tuple(slot for slot in slots if slot.copied_from is not None)
    if not copies:
        return
    if PermissionKey.DELIVERABLE_READ not in actor.permissions:
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    keys = {
        (slot.copied_from.assembly_revision_id, slot.copied_from.placement_id)
        for slot in copies
        if slot.copied_from
    }
    index = CuratedDocumentAssemblySlotRecord
    revision = CuratedDocumentAssemblyRevisionRecord
    # Do not extend shared read permission to old private assemblies.
    rows = session.execute(
        select(index, revision)
        .join(revision, revision.assembly_revision_id == index.assembly_revision_id)
        .join(
            ContentFormMembershipRecord,
            ContentFormMembershipRecord.assembly_id == revision.assembly_id,
        )
        .where(tuple_(index.assembly_revision_id, index.placement_id).in_(tuple(keys)))
    ).all()
    by_key = {(row.assembly_revision_id, row.placement_id): (row, parent) for row, parent in rows}
    if by_key.keys() != keys:
        raise ContentPlanningError("CONTENT_COPY_ORIGIN_NOT_FOUND")
    manifests: dict[str, CuratedDocumentAssemblyManifestV2] = {}
    for slot in copies:
        origin = slot.copied_from
        assert origin is not None
        if origin.placement_id == slot.placement_id:
            raise ContentPlanningError("CONTENT_COPY_PLACEMENT_ID_INVALID")
        row, parent = by_key[(origin.assembly_revision_id, origin.placement_id)]
        if (
            origin.assembly_id != parent.assembly_id
            or origin.manifest_sha256 != parent.manifest_sha256
            or parent.manifest_schema_version != "curated-document-assembly-manifest/2.0"
        ):
            raise ContentPlanningError("CONTENT_COPY_ORIGIN_INVALID")
        manifest = manifests.get(parent.assembly_revision_id)
        if manifest is None:
            try:
                manifest = CuratedDocumentAssemblyManifestV2.model_validate(
                    parent.canonical_document
                )
            except ValueError as exc:
                raise ContentPlanningError("CONTENT_COPY_ORIGIN_INVALID") from exc
            if (
                manifest.manifest_sha256 != parent.manifest_sha256
                or manifest.assembly_id != parent.assembly_id
                or manifest.assembly_revision_id != parent.assembly_revision_id
            ):
                raise ContentPlanningError("CONTENT_COPY_ORIGIN_INVALID")
            manifests[parent.assembly_revision_id] = manifest
        if not 1 <= row.position <= len(manifest.placements):
            raise ContentPlanningError("CONTENT_COPY_ORIGIN_INVALID")
        source = manifest.placements[row.position - 1]
        if (
            source.placement_id != origin.placement_id
            or source.model_dump(mode="json") != row.canonical_slot
            or source.selection().target != slot.target
        ):
            raise ContentPlanningError("CONTENT_COPY_ORIGIN_INVALID")

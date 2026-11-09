"""V2 revision/index persistence in the curated Assembly owner's caller transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    ResolvedCuratedSlot,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord


def curated_slots_sha256(slots: tuple[ResolvedCuratedSlot, ...]) -> str:
    return content_sha256(
        {"placements": [slot.selection().model_dump(mode="json") for slot in slots]}
    )


@dataclass(frozen=True)
class CuratedSlotRevisionWrite:
    assembly_id: str
    revision_id: str
    previous: CuratedDocumentAssemblyManifestV2 | None
    title: str
    placements: tuple[ResolvedCuratedSlot, ...]


def _manifest(
    write: CuratedSlotRevisionWrite, actor_id: str, created_at: datetime
) -> CuratedDocumentAssemblyManifestV2:
    previous = write.previous
    value = {
        "schema_version": "curated-document-assembly-manifest/2.0",
        "assembly_id": write.assembly_id,
        "assembly_revision_id": write.revision_id,
        "revision_number": 1 if previous is None else previous.revision_number + 1,
        "previous_revision_id": None if previous is None else previous.assembly_revision_id,
        "selection_sha256": curated_slots_sha256(write.placements),
        "placements": [slot.model_dump(mode="json") for slot in write.placements],
        "created_by": actor_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    value["manifest_sha256"] = content_sha256(value)
    validate_contract("curated-document-assembly-manifest-v2", value)
    return CuratedDocumentAssemblyManifestV2.model_validate(value)


def append_curated_slot_revisions(
    session: Session,
    writes: tuple[CuratedSlotRevisionWrite, ...],
    *,
    actor_id: str,
    created_at: datetime,
) -> dict[str, CuratedDocumentAssemblyManifestV2]:
    """Batch append in the caller TX, without per-Form lookup/flush or file I/O."""
    if not writes:
        return {}
    keys = {write.assembly_id for write in writes}
    if len(keys) != len(writes):
        raise ContentPlanningError("CONTENT_ASSEMBLY_IDENTITY_CONFLICT")
    aggregates = {
        row.assembly_id: row
        for row in session.scalars(
            select(CuratedDocumentAssemblyRecord).where(
                CuratedDocumentAssemblyRecord.assembly_id.in_(tuple(keys))
            )
        )
    }
    manifests = {}
    for write in writes:
        aggregate = aggregates.get(write.assembly_id)
        if write.previous is None:
            if aggregate is not None:
                raise ContentPlanningError("CONTENT_ASSEMBLY_IDENTITY_CONFLICT")
            aggregate = CuratedDocumentAssemblyRecord(
                assembly_id=write.assembly_id,
                current_revision_id=None,
                created_by=actor_id,
                title=write.title,
                created_at=created_at,
            )
            aggregates[write.assembly_id] = aggregate
            session.add(aggregate)
        elif (
            aggregate is None
            or write.previous.assembly_id != write.assembly_id
            or aggregate.current_revision_id != write.previous.assembly_revision_id
        ):
            raise ContentPlanningError("CONTENT_ASSEMBLY_REVISION_STALE")
        manifests[write.assembly_id] = _manifest(write, actor_id, created_at)
    session.flush()
    for manifest in manifests.values():
        session.add(
            CuratedDocumentAssemblyRevisionRecord(
                assembly_revision_id=manifest.assembly_revision_id,
                assembly_id=manifest.assembly_id,
                revision_number=manifest.revision_number,
                previous_revision_id=manifest.previous_revision_id,
                revision_state="INPUT_PINNED",
                manifest_schema_version=manifest.schema_version,
                selection_sha256=manifest.selection_sha256,
                request_sha256=manifest.selection_sha256,
                manifest_sha256=manifest.manifest_sha256,
                canonical_document=manifest.model_dump(mode="json"),
                idempotency_key="content:" + manifest.assembly_revision_id,
                created_by=actor_id,
                created_at=created_at,
            )
        )
    session.flush()
    rows = []
    for manifest in manifests.values():
        for slot in manifest.placements:
            target = slot.target
            rows.append(
                {
                    "assembly_revision_id": manifest.assembly_revision_id,
                    "placement_id": slot.placement_id,
                    "position": slot.position,
                    "placement_kind": target.placement_kind,
                    "source_id": getattr(target, "source_id", None),
                    "source_revision_id": getattr(target, "source_revision_id", None),
                    "item_id": getattr(target, "item_id", None),
                    "item_revision_id": getattr(target, "item_revision_id", None),
                    "graph_snapshot_revision_id": getattr(
                        target, "graph_snapshot_revision_id", None
                    ),
                    "canonical_slot": slot.model_dump(mode="json"),
                }
            )
            if len(rows) == 1000:
                session.execute(insert(CuratedDocumentAssemblySlotRecord), rows)
                rows.clear()
        aggregates[manifest.assembly_id].current_revision_id = manifest.assembly_revision_id
    if rows:
        session.execute(insert(CuratedDocumentAssemblySlotRecord), rows)
    session.flush()
    return manifests


class CuratedSlotRevisionPointer(Protocol):
    @property
    def assembly_id(self) -> str: ...
    @property
    def assembly_revision_id(self) -> str: ...
    @property
    def manifest_sha256(self) -> str: ...
    @property
    def placement_count(self) -> int: ...


def read_curated_slot_revisions(
    session: Session, pointers: tuple[CuratedSlotRevisionPointer, ...]
) -> dict[str, CuratedDocumentAssemblyManifestV2]:
    """Two batched indexed reads; exact historical revisions, never aggregate latest."""
    if not pointers:
        return {}
    by_id = {pointer.assembly_revision_id: pointer for pointer in pointers}
    if len(by_id) != len(pointers):
        raise ContentPlanningError("CONTENT_ASSEMBLY_POINTER_INVALID")
    result: dict[str, CuratedDocumentAssemblyManifestV2] = {}
    for row in session.scalars(
        select(CuratedDocumentAssemblyRevisionRecord).where(
            CuratedDocumentAssemblyRevisionRecord.assembly_revision_id.in_(tuple(by_id))
        )
    ):
        pointer = by_id[row.assembly_revision_id]
        if (
            row.assembly_id != pointer.assembly_id
            or row.manifest_sha256 != pointer.manifest_sha256
            or row.manifest_schema_version != "curated-document-assembly-manifest/2.0"
            or row.revision_state != "INPUT_PINNED"
        ):
            raise ContentPlanningError("CONTENT_ASSEMBLY_POINTER_INVALID")
        try:
            manifest = CuratedDocumentAssemblyManifestV2.model_validate(row.canonical_document)
        except ValueError as exc:
            raise ContentPlanningError("CONTENT_ASSEMBLY_POINTER_INVALID") from exc
        if (
            manifest.assembly_id != row.assembly_id
            or manifest.assembly_revision_id != row.assembly_revision_id
            or manifest.manifest_sha256 != row.manifest_sha256
            or manifest.selection_sha256 != row.selection_sha256
            or manifest.selection_sha256 != curated_slots_sha256(manifest.placements)
            or manifest.revision_number != row.revision_number
            or manifest.previous_revision_id != row.previous_revision_id
            or manifest.created_by != row.created_by
            or manifest.created_at != row.created_at
            or len(manifest.placements) != pointer.placement_count
        ):
            raise ContentPlanningError("CONTENT_ASSEMBLY_POINTER_INVALID")
        result[row.assembly_revision_id] = manifest
    if result.keys() != by_id.keys():
        raise ContentPlanningError("CONTENT_ASSEMBLY_NOT_FOUND")
    counts = dict.fromkeys(by_id, 0)
    for index in session.scalars(
        select(CuratedDocumentAssemblySlotRecord)
        .where(CuratedDocumentAssemblySlotRecord.assembly_revision_id.in_(tuple(by_id)))
        .order_by(
            CuratedDocumentAssemblySlotRecord.assembly_revision_id,
            CuratedDocumentAssemblySlotRecord.position,
        )
    ):
        manifest = result[index.assembly_revision_id]
        offset = counts[index.assembly_revision_id]
        if offset >= len(manifest.placements):
            raise ContentPlanningError("CONTENT_SLOT_INDEX_INVALID")
        slot = manifest.placements[offset]
        if (
            index.position != slot.position
            or index.placement_id != slot.placement_id
            or index.canonical_slot != slot.model_dump(mode="json")
        ):
            raise ContentPlanningError("CONTENT_SLOT_INDEX_INVALID")
        counts[index.assembly_revision_id] += 1
    if any(counts[key] != len(value.placements) for key, value in result.items()):
        raise ContentPlanningError("CONTENT_SLOT_INDEX_INVALID")
    return result

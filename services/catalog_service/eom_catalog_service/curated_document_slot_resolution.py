"""V2 occurrences reuse the existing Catalog target-resolution owners in batches."""

from __future__ import annotations

from collections import defaultdict

from eom_catalog_contracts.curated_document_assembly_draft import (
    ExternalSourcePlacement,
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts.curated_document_slots import (
    CuratedSlot,
    ExternalSlotTarget,
    RegisteredSlotTarget,
    ResolvedCuratedSlot,
    ResolvedExternalSlotTarget,
    ResolvedSlotTarget,
    SlotTarget,
)
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.curated_document_assembly_item import reauthorize_curated_registered_items
from eom_catalog_service.curated_document_assembly_source import (
    resolve_pinned_curated_external_documents,
)


def resolve_curated_slots(
    session: Session, slots: tuple[CuratedSlot, ...], actor: ActorContext
) -> tuple[ResolvedCuratedSlot, ...]:
    """Deduplicate targets, not occurrences; O(n) maps plus bounded indexed reads.

    Graph pins from different saved editions may coexist. The original resolver
    still owns Graph membership, approved revision/hash and lifecycle checks.
    Source metadata only is resolved here; no network/file I/O inside the edit TX.
    """
    if PermissionKey.ITEM_READ not in actor.permissions:
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    targets: dict[SlotTarget, ResolvedSlotTarget] = {}
    seen: set[SlotTarget] = set()
    groups: dict[str, list[RegisteredSlotTarget]] = defaultdict(list)
    external: list[ExternalSlotTarget] = []
    for slot in slots:
        target = slot.target
        if target in seen:
            continue
        seen.add(target)
        if not isinstance(target, ExternalSlotTarget):
            targets[target] = target
        if isinstance(target, RegisteredSlotTarget):
            groups[target.graph_snapshot_revision_id].append(target)
        elif isinstance(target, ExternalSlotTarget):
            external.append(target)
    if external and PermissionKey.CONTENT_INTAKE_READ not in actor.permissions:
        raise ContentPlanningError("CURATED_SOURCE_PERMISSION_DENIED")
    for snapshot_id in sorted(groups):
        group = sorted(groups[snapshot_id], key=lambda target: target.item_revision_id)
        for start in range(0, len(group), 200):
            chunk = group[start : start + 200]
            selections = tuple(
                (
                    PastExamItemPlacement
                    if target.placement_kind == "PAST_EXAM_ITEM_REVISION"
                    else RegisteredItemPlacement
                ).model_validate({"position": i, **target.model_dump(mode="json")})
                for i, target in enumerate(chunk, 1)
            )
            reauthorize_curated_registered_items(session, selections)
    external.sort(key=lambda target: (target.source_id, target.source_revision_id, target.edition))
    for start in range(0, len(external), 200):
        source_chunk = external[start : start + 200]
        resolved = resolve_pinned_curated_external_documents(
            session,
            tuple(
                ExternalSourcePlacement(position=i, **target.model_dump(mode="json"))
                for i, target in enumerate(source_chunk, 1)
            ),
        )
        for target, value in zip(source_chunk, resolved, strict=True):
            targets[target] = ResolvedExternalSlotTarget.model_validate(
                value.model_dump(mode="json", exclude={"position"})
            )
    return tuple(
        ResolvedCuratedSlot(**slot.model_dump(exclude={"target"}), target=targets[slot.target])
        for slot in slots
    )

"""Confirmed Catalog registration lineage for usage, never number/name similarity."""

from collections import defaultdict

from eom_catalog_contracts.curated_document_slots import SlotTarget, logical_slot_target_key
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import or_
from sqlalchemy.orm import Session

from eom_catalog_service.creative_source_registration import creative_registration_pairs
from eom_catalog_service.external_item_models import (
    ExternalItemSourceRecord,
)
from eom_catalog_service.models import ItemRevisionRecord


def content_usage_identity_matches(
    session: Session, targets: tuple[SlotTarget, ...], actor: ActorContext
) -> dict[tuple[str, str], set[int]]:
    matches: dict[tuple[str, str], set[int]] = defaultdict(set)
    for i, target in enumerate(targets):
        key = logical_slot_target_key(target)
        if key is not None:
            matches[key].add(i)
    if PermissionKey.CONTENT_INTAKE_READ not in actor.permissions:
        return dict(matches)
    source_ids = [key for kind, key in matches if kind == "SOURCE"]
    item_ids = [key for kind, key in matches if kind == "ITEM"]
    source, item = ExternalItemSourceRecord, ItemRevisionRecord
    pairs = session.execute(
        creative_registration_pairs().where(
            or_(source.source_id.in_(source_ids), item.item_id.in_(item_ids)),
        )
    ).all()
    # A single registration key is the owner's authoritative relation. Different
    # source revisions stay pinned in locations even when their logical key agrees.
    by_source: dict[str, set[str]] = defaultdict(set)
    for source_id, item_id in pairs:
        by_source[source_id].add(item_id)
    for source_id, related_items in by_source.items():
        related = set(matches[("SOURCE", source_id)])
        for item_id in related_items:
            related.update(matches[("ITEM", item_id)])
        matches[("SOURCE", source_id)].update(related)
        for item_id in related_items:
            matches[("ITEM", item_id)].update(related)
    return dict(matches)

"""Append-only Item audit persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.models import ItemEventRecord, ItemRecord


def append_item_event(
    session: Session,
    item: ItemRecord,
    *,
    item_revision_id: str | None,
    event_type: str,
    prior_state: str | None,
    new_state: str,
    actor_id: str,
    source: str,
    idempotency_key: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ItemEventRecord:
    sequence = (
        session.scalar(
            select(func.max(ItemEventRecord.sequence)).where(
                ItemEventRecord.item_id == item.item_id
            )
        )
        or 0
    ) + 1
    event = ItemEventRecord(
        item_id=item.item_id,
        item_revision_id=item_revision_id,
        sequence=sequence,
        event_type=event_type,
        prior_state=prior_state,
        new_state=new_state,
        actor_id=actor_id,
        source=source,
        command_id=None,
        idempotency_key=idempotency_key,
        payload=payload or {},
    )
    session.add(event)
    return event

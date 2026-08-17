"""Transactional persistence for content intake aggregates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_content_intake import IntakeState, require_transition
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeEventRecord,
)


def append_intake_event(
    session: Session,
    batch: ContentIntakeBatchRecord,
    *,
    event_type: str,
    prior_state: str | None,
    new_state: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
) -> ContentIntakeEventRecord:
    last = session.scalar(
        select(func.max(ContentIntakeEventRecord.sequence)).where(
            ContentIntakeEventRecord.intake_batch_id == batch.intake_batch_id
        )
    )
    event = ContentIntakeEventRecord(
        intake_batch_id=batch.intake_batch_id,
        sequence=(last or 0) + 1,
        event_type=event_type,
        prior_state=prior_state,
        new_state=new_state,
        actor_id=actor_id,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def transition_intake(
    session: Session,
    batch: ContentIntakeBatchRecord,
    target: IntakeState,
    *,
    event_type: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
) -> ContentIntakeBatchRecord:
    current = IntakeState(batch.state)
    require_transition(current, target)
    batch.state = target.value
    batch.lock_version += 1
    batch.updated_at = datetime.now(UTC)
    if target == IntakeState.ACCEPTED:
        batch.accepted_at = datetime.now(UTC)
    elif target == IntakeState.REJECTED:
        batch.rejected_at = datetime.now(UTC)
    elif target == IntakeState.SUPERSEDED:
        batch.superseded_at = datetime.now(UTC)
    append_intake_event(
        session,
        batch,
        event_type=event_type,
        prior_state=current.value,
        new_state=target.value,
        actor_id=actor_id,
        payload=payload,
    )
    session.flush()
    return batch


def list_intake_events(session: Session, intake_batch_id: str) -> list[ContentIntakeEventRecord]:
    return list(
        session.scalars(
            select(ContentIntakeEventRecord)
            .where(ContentIntakeEventRecord.intake_batch_id == intake_batch_id)
            .order_by(ContentIntakeEventRecord.sequence)
        )
    )

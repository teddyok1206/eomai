"""Transactional Content Pack lifecycle persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_content_pack import ContentPackState, require_transition
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.models import ContentPackEventRecord, ContentPackReleaseRecord


def append_pack_event(
    session: Session,
    release: ContentPackReleaseRecord,
    *,
    event_type: str,
    prior_state: str | None,
    new_state: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
) -> ContentPackEventRecord:
    sequence = (
        session.scalar(
            select(func.max(ContentPackEventRecord.sequence)).where(
                ContentPackEventRecord.content_pack_release_id == release.content_pack_release_id
            )
        )
        or 0
    ) + 1
    event = ContentPackEventRecord(
        content_pack_release_id=release.content_pack_release_id,
        sequence=sequence,
        event_type=event_type,
        prior_state=prior_state,
        new_state=new_state,
        actor_id=actor_id,
        payload=payload or {},
    )
    session.add(event)
    return event


def transition_pack(
    session: Session,
    release: ContentPackReleaseRecord,
    target: ContentPackState,
    *,
    event_type: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    current = ContentPackState(release.state)
    require_transition(current, target)
    release.state = target.value
    release.lock_version += 1
    now = datetime.now(UTC)
    if target == ContentPackState.VALIDATED:
        release.validated_at = now
    elif target == ContentPackState.RELEASED:
        release.released_at = now
        release.released_by = actor_id
    elif target == ContentPackState.DEPRECATED:
        release.deprecated_at = now
    elif target == ContentPackState.RETIRED:
        release.retired_at = now
    append_pack_event(
        session,
        release,
        event_type=event_type,
        prior_state=current.value,
        new_state=target.value,
        actor_id=actor_id,
        payload=payload,
    )

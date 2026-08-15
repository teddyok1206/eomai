"""Deterministic job state transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from eom_protocol import ErrorCode
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord


class JobState(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    VALIDATING_RESULT = "VALIDATING_RESULT"
    COMMITTING = "COMMITTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED: frozenset({JobState.VALIDATED, JobState.FAILED, JobState.CANCELLED}),
    JobState.VALIDATED: frozenset({JobState.QUEUED, JobState.FAILED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset({JobState.CLAIMED, JobState.FAILED, JobState.CANCELLED}),
    JobState.CLAIMED: frozenset({JobState.RUNNING, JobState.FAILED, JobState.CANCELLED}),
    JobState.RUNNING: frozenset({JobState.VALIDATING_RESULT, JobState.FAILED, JobState.CANCELLED}),
    JobState.VALIDATING_RESULT: frozenset({JobState.COMMITTING, JobState.FAILED}),
    JobState.COMMITTING: frozenset({JobState.SUCCEEDED, JobState.FAILED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


class InvalidStateTransition(RuntimeError):
    error_code = ErrorCode.INVALID_STATE_TRANSITION

    def __init__(self, current: JobState, target: JobState) -> None:
        super().__init__(f"invalid job state transition: {current} -> {target}")
        self.current = current
        self.target = target


def require_transition(current: JobState, target: JobState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(current, target)


def record_initial_event(session: Session, job: JobRecord) -> None:
    session.add(
        JobEventRecord(
            job_id=job.job_id,
            sequence=1,
            from_state=None,
            to_state=JobState.CREATED.value,
            event="JOB_CREATED",
            data={},
        )
    )


def transition_job(
    session: Session,
    job_id: str,
    target: JobState,
    event: str,
    *,
    data: dict[str, Any] | None = None,
) -> JobRecord:
    job = session.execute(
        select(JobRecord).where(JobRecord.job_id == job_id).with_for_update()
    ).scalar_one()
    current = JobState(job.status)
    require_transition(current, target)
    next_sequence = session.scalar(
        select(func.coalesce(func.max(JobEventRecord.sequence), 0) + 1).where(
            JobEventRecord.job_id == job_id
        )
    )
    if next_sequence is None:
        raise RuntimeError("failed to allocate job event sequence")
    job.status = target.value
    job.updated_at = datetime.now(UTC)
    if target in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
        job.completed_at = datetime.now(UTC)
    session.add(
        JobEventRecord(
            job_id=job_id,
            sequence=next_sequence,
            from_state=current.value,
            to_state=target.value,
            event=event,
            data=data or {},
        )
    )
    return job

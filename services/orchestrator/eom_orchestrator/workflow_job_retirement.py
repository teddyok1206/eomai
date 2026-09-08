"""Orchestrator-owned platform-job fencing for Workflow occurrence retirement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from eom_identifiers import content_sha256
from eom_workflow import RoleWorkerInput
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState, transition_job

_HELD_LEASE_STATES = ("ACTIVE", "RECONCILING")
_CANCELLABLE_JOB_STATES = frozenset(
    {
        JobState.CREATED,
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
    }
)
_UNSAFE_JOB_STATES = _CANCELLABLE_JOB_STATES | frozenset(
    {JobState.VALIDATING_RESULT, JobState.COMMITTING}
)


@dataclass(frozen=True)
class WorkflowJobRetirementBinding:
    """Exact Workflow step identity allowed to affect one orchestrator Job."""

    job_id: str
    workflow_id: str
    step_run_id: str
    attempt: int
    role: str


class WorkflowJobRetirementError(RuntimeError):
    """Stable failure raised before an unsafe platform-job mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require_no_held_worker_leases(
    session: Session,
    workflow_ids: tuple[str, ...],
) -> None:
    """Require external worker quiescence evidence at the durable lease boundary."""

    held = session.scalar(
        select(WorkerLeaseRecord.lease_id)
        .where(
            WorkerLeaseRecord.workflow_id.in_(workflow_ids),
            WorkerLeaseRecord.state.in_(_HELD_LEASE_STATES),
        )
        .limit(1)
    )
    if held is not None:
        _fail(
            "PRODUCTION_RETIREMENT_WORKER_LEASE_HELD",
            "an active or reconciling worker lease blocks production retirement",
        )


def fence_workflow_platform_jobs(
    session: Session,
    *,
    bindings: tuple[WorkflowJobRetirementBinding, ...],
    reason_code: str,
) -> None:
    """Terminalize cancellable jobs without deleting job or event history."""

    if not bindings:
        return
    jobs = _load_and_validate_jobs(session, bindings=bindings, for_update=True)
    for job in jobs:
        state = JobState(job.status)
        if state in {JobState.VALIDATING_RESULT, JobState.COMMITTING}:
            _fail(
                "PRODUCTION_RETIREMENT_JOB_COMMIT_IN_PROGRESS",
                "a platform job has crossed the safe cancellation boundary",
            )
        if state in _CANCELLABLE_JOB_STATES:
            transition_job(
                session,
                job.job_id,
                JobState.CANCELLED,
                "PRODUCTION_OCCURRENCE_RETIRED",
                data={"reason_code": reason_code},
            )


def require_workflow_platform_jobs_fenced(
    session: Session,
    *,
    bindings: tuple[WorkflowJobRetirementBinding, ...],
) -> None:
    """Verify that no platform job from the occurrence remains executable."""

    if not bindings:
        return
    jobs = _load_and_validate_jobs(session, bindings=bindings, for_update=False)
    if any(JobState(job.status) in _UNSAFE_JOB_STATES for job in jobs):
        _fail(
            "PRODUCTION_RETIREMENT_JOB_FENCE_INCOMPLETE",
            "a platform job remains executable after production retirement",
        )


def _load_and_validate_jobs(
    session: Session,
    *,
    bindings: tuple[WorkflowJobRetirementBinding, ...],
    for_update: bool,
) -> tuple[JobRecord, ...]:
    job_ids = tuple(binding.job_id for binding in bindings)
    if len(job_ids) != len(set(job_ids)):
        _fail(
            "PRODUCTION_RETIREMENT_JOB_POINTER_CONFLICT",
            "one platform job is linked from more than one Workflow step",
        )
    query = select(JobRecord).where(JobRecord.job_id.in_(job_ids)).order_by(JobRecord.job_id)
    if for_update:
        query = query.with_for_update()
    jobs = tuple(session.scalars(query))
    by_id = {job.job_id: job for job in jobs}
    if set(by_id) != set(job_ids):
        _fail(
            "PRODUCTION_RETIREMENT_JOB_POINTER_MISSING",
            "a Workflow step points to a missing platform job",
        )
    for binding in bindings:
        _validate_job_provenance(by_id[binding.job_id], binding)
    return tuple(by_id[job_id] for job_id in sorted(job_ids))


def _validate_job_provenance(
    job: JobRecord,
    binding: WorkflowJobRetirementBinding,
) -> None:
    try:
        worker_input = RoleWorkerInput.model_validate(job.request)
    except PydanticValidationError as exc:
        raise WorkflowJobRetirementError(
            "PRODUCTION_RETIREMENT_JOB_PROVENANCE_INVALID",
            "a platform job does not contain a valid pinned Workflow role request",
        ) from exc
    if (
        worker_input.job_id != job.job_id
        or worker_input.workflow_id != binding.workflow_id
        or worker_input.step_run_id != binding.step_run_id
        or worker_input.attempt != binding.attempt
        or worker_input.role != binding.role
        or worker_input.protocol_version != job.protocol_version
        or worker_input.artifact.logical_artifact_id != job.logical_artifact_id
        or worker_input.artifact.revision_id != job.revision_id
        or job.task_type != f"workflow_{binding.role}"
        or job.request_hash
        != content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
    ):
        _fail(
            "PRODUCTION_RETIREMENT_JOB_PROVENANCE_MISMATCH",
            "a platform job does not belong to its exact pinned Workflow step",
        )


def _fail(code: str, message: str) -> Never:
    raise WorkflowJobRetirementError(code, message)

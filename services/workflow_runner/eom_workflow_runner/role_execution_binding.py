"""Fenced Runner step ↔ platform job binding and the existing result projection."""

from __future__ import annotations

from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowStepRunRecord
from eom_workflow_runner.role_execution_port import RoleExecutionResult
from eom_workflow_runner.state_machine import StepState


def bind_platform_role_job(
    session: Session,
    *,
    workflow_id: str,
    step_run_id: str,
    step_key: str,
    attempt: int,
    worker_role: str | None,
    job_id: str,
) -> None:
    """Bind only the exact running step; caller holds the command-lease fence."""

    current = session.execute(
        select(WorkflowStepRunRecord)
        .where(WorkflowStepRunRecord.step_run_id == step_run_id)
        .with_for_update()
    ).scalar_one()
    if (
        current.workflow_id != workflow_id
        or current.step_key != step_key
        or current.attempt != attempt
        or current.worker_role != worker_role
        or current.state != StepState.RUNNING.value
        or current.platform_job_id not in {None, job_id}
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
            "platform job does not match the running workflow step",
        )
    current.platform_job_id = job_id


def read_platform_role_result(session: Session, job: JobRecord) -> RoleExecutionResult:
    """Preserve the platform executor's exact outcome, without reading result bytes."""

    content_hash: str | None = None
    if job.status == "SUCCEEDED":
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        if revision is None:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                "platform job succeeded without artifact revision",
            )
        content_hash = revision.content_hash
    return RoleExecutionResult(
        job_id=job.job_id,
        status=job.status,
        worker_slot=job.worker_slot_id,
        logical_artifact_id=job.logical_artifact_id,
        revision_id=job.revision_id,
        content_hash=content_hash,
        error_code=job.error_code,
    )

"""Recover an original single-item renderer job without submitting new work."""

from __future__ import annotations

from eom_orchestrator.database import transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode


def recover_item_renderer_job(
    sessions: sessionmaker[Session],
    *,
    job_key: str,
    task_type: str,
    build_id: str,
    source_revision_id: str,
    source_sha256: str,
) -> str | None:
    """Called only after the owning fixed renderer has been proven inactive."""
    with transaction(sessions) as session:
        job = session.scalar(
            select(JobRecord).where(JobRecord.idempotency_key == job_key).with_for_update()
        )
        if job is None:
            return None
        source = job.request.get("source", job.request.get("item_content"))
        if (
            job.task_type != task_type
            or job.request.get("build_id", build_id) != build_id
            or not isinstance(source, dict)
            or source.get("artifact_revision_id") != source_revision_id
            or source.get("sha256", source.get("json_sha256")) != source_sha256
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                "interrupted renderer job does not match the pinned application source",
            )
        state = JobState(job.status)
        if state is JobState.SUCCEEDED:
            artifact = session.get(ArtifactRecord, job.logical_artifact_id)
            revision = session.get(ArtifactRevisionRecord, job.revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != artifact.logical_artifact_id
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_RESULT_INVALID,
                    "interrupted renderer output pointer is missing or no longer approved",
                )
            return job.job_id
        if state not in {JobState.FAILED, JobState.CANCELLED}:
            job.error_code = HwpxManagerErrorCode.HWPX_BUILD_INTERRUPTED.value
            job.error_message = "single-item HWPX manager was interrupted"
            transition_job(
                session,
                job.job_id,
                JobState.FAILED,
                "HWPX_ITEM_MANAGER_INTERRUPTED",
                data={"error_code": job.error_code},
            )
        return None

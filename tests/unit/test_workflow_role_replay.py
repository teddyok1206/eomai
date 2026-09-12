from __future__ import annotations

from collections.abc import Callable

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import _validated_workflow_role_replay
from eom_workflow.models import ArtifactPointer, ArtifactSpec, RoleWorkerInput, WorkerRequest

JOB_ID = "job_0123456789abcdef0123456789abcdef"
WORKFLOW_ID = "workflow_0123456789abcdef0123456789abcdef"
STEP_RUN_ID = "steprun_0123456789abcdef0123456789abcdef"
ARTIFACT_ID = "artifact_0123456789abcdef0123456789abcdef"
REVISION_ID = "rev_0123456789abcdef0123456789abcdef"


def _upstream() -> tuple[ArtifactPointer, ...]:
    return (
        ArtifactPointer(
            step_key="source",
            attempt=1,
            job_id="job_11111111111111111111111111111111",
            logical_artifact_id="artifact_11111111111111111111111111111111",
            revision_id="rev_11111111111111111111111111111111",
            content_hash="sha256:" + "1" * 64,
            result_schema="source-result@1.0",
        ),
    )


def _stored_job() -> JobRecord:
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.0.1",
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required"),
        upstream_artifacts=_upstream(),
        artifact=ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID),
    )
    document = worker_input.model_dump(mode="json")
    task_type = "workflow_authoring"
    return JobRecord(
        job_id=JOB_ID,
        protocol_version=worker_input.protocol_version,
        idempotency_key="workflow-role-replay-unit",
        request_hash=content_sha256(
            {
                "protocol_version": worker_input.protocol_version,
                "task_type": task_type,
                "request": document,
            }
        ),
        task_type=task_type,
        request=document,
        status="QUEUED",
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
    )


def _validate(
    job: JobRecord,
    *,
    request: WorkerRequest | None = None,
    upstream: tuple[ArtifactPointer, ...] | None = None,
    result_schema: str = "authoring-result@1.0",
) -> None:
    _validated_workflow_role_replay(
        job,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="authoring",
        request=request or WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required"),
        upstream_artifacts=_upstream() if upstream is None else upstream,
        result_schema=result_schema,
    )


def test_exact_workflow_role_replay_preserves_stored_identity() -> None:
    job = _stored_job()

    worker_input, document = _validated_workflow_role_replay(
        job,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required"),
        upstream_artifacts=_upstream(),
        result_schema="authoring-result@1.0",
    )

    assert worker_input.job_id == JOB_ID
    assert worker_input.artifact.logical_artifact_id == ARTIFACT_ID
    assert document == job.request


@pytest.mark.parametrize(
    "drift",
    [
        lambda job: setattr(job, "request_hash", "sha256:" + "f" * 64),
        lambda job: setattr(job, "task_type", "workflow_review"),
        lambda job: setattr(job, "logical_artifact_id", "artifact_" + "f" * 32),
        lambda job: setattr(job, "revision_id", "rev_" + "f" * 32),
    ],
)
def test_workflow_role_replay_rejects_stored_identity_drift(
    drift: Callable[[JobRecord], None],
) -> None:
    job = _stored_job()
    drift(job)

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _validate(job)


def test_workflow_role_replay_rejects_changed_request_or_upstream() -> None:
    job = _stored_job()

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _validate(
            job,
            request=WorkerRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip"),
        )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _validate(job, upstream=())


def test_workflow_role_replay_rejects_changed_result_protocol() -> None:
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _validate(_stored_job(), result_schema="authoring-result@2.0")

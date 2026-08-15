from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_protocol import (
    ArtifactManifest,
    ArtifactSpec,
    ErrorCode,
    ErrorResult,
    JobRequest,
    ResultContent,
    SchemaValidationError,
    SmokePayload,
    WorkerInput,
    WorkerResult,
    validate_message,
)
from pydantic import ValidationError

JOB_ID = "job_0123456789abcdef0123456789abcdef"
ARTIFACT_ID = "artifact_0123456789abcdef0123456789abcdef"
REVISION_ID = "rev_0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 8, 15, tzinfo=UTC)


def _artifact() -> ArtifactSpec:
    return ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID)


def test_all_external_messages_pass_json_schema() -> None:
    request = JobRequest(
        job_id=JOB_ID,
        idempotency_key="smoke-1",
        payload=SmokePayload(message="EOM_PLATFORM_SMOKE_TEST"),
        artifact=_artifact(),
        submitted_at=NOW,
    )
    worker_input = WorkerInput(
        job_id=JOB_ID,
        payload=request.payload,
        artifact=request.artifact,
        submitted_at=NOW,
    )
    result = WorkerResult(
        job_id=JOB_ID,
        message="EOM_PLATFORM_SMOKE_TEST_OK",
        artifact=request.artifact,
        content=ResultContent(message="EOM_PLATFORM_SMOKE_TEST_OK"),
        completed_at=NOW,
    )
    manifest = ArtifactManifest(
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        content_hash="sha256:" + "a" * 64,
        content_bytes=10,
        worker_slot="01",
        created_at=NOW,
    )
    error = ErrorResult(
        job_id=JOB_ID,
        error_code=ErrorCode.WORKER_TIMEOUT,
        message="worker timed out",
        occurred_at=NOW,
    )
    error = ErrorResult(
        job_id=JOB_ID,
        error_code=ErrorCode.WORKER_TIMEOUT,
        message="worker timed out",
        occurred_at=NOW,
    )

    for name, model in (
        ("job-request", request),
        ("worker-input", worker_input),
        ("worker-result", result),
        ("artifact-manifest", manifest),
        ("error-result", error),
        ("error-result", error),
    ):
        validate_message(name, model.model_dump(mode="json"))  # type: ignore[arg-type]


def test_schema_rejects_extra_fields() -> None:
    with pytest.raises(SchemaValidationError, match="unexpected"):
        validate_message(
            "worker-result",
            {
                "protocol_version": "1.0.1",
                "job_id": JOB_ID,
                "status": "ok",
                "message": "EOM_PLATFORM_SMOKE_TEST_OK",
                "artifact": _artifact().model_dump(mode="json"),
                "content": {"message": "EOM_PLATFORM_SMOKE_TEST_OK"},
                "completed_at": "2026-08-15T00:00:00Z",
                "unexpected": True,
            },
        )


def test_pydantic_rejects_non_utc_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        WorkerInput(
            job_id=JOB_ID,
            payload=SmokePayload(message="EOM_PLATFORM_SMOKE_TEST"),
            artifact=_artifact(),
            submitted_at="2026-08-15T09:00:00+09:00",  # type: ignore[arg-type]
        )

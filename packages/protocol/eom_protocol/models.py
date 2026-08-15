"""Pydantic counterparts for the versioned JSON messages."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

PROTOCOL_VERSION: Final[Literal["1.0.1"]] = "1.0.1"
JOB_ID_PATTERN = r"^job_[0-9a-f]{32}$"
ARTIFACT_ID_PATTERN = r"^artifact_[0-9a-f]{32}$"
REVISION_ID_PATTERN = r"^rev_[0-9a-f]{32}$"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
ArtifactId = Annotated[str, Field(pattern=ARTIFACT_ID_PATTERN)]
RevisionId = Annotated[str, Field(pattern=REVISION_ID_PATTERN)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class ErrorCode(StrEnum):
    PROTOCOL_VALIDATION_FAILED = "PROTOCOL_VALIDATION_FAILED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
    WORKER_TIMEOUT = "WORKER_TIMEOUT"
    WORKER_EXEC_FAILED = "WORKER_EXEC_FAILED"
    WORKER_RESULT_MISSING = "WORKER_RESULT_MISSING"
    WORKER_RESULT_INVALID = "WORKER_RESULT_INVALID"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    ARTIFACT_COMMIT_FAILED = "ARTIFACT_COMMIT_FAILED"
    DATABASE_ERROR = "DATABASE_ERROR"
    NAS_UNAVAILABLE = "NAS_UNAVAILABLE"


class SmokePayload(ProtocolModel):
    message: Annotated[str, Field(min_length=1, max_length=256)]


class ArtifactSpec(ProtocolModel):
    logical_artifact_id: ArtifactId
    revision_id: RevisionId
    file_name: Literal["result.json"] = "result.json"
    media_type: Literal["application/json"] = "application/json"


class JobRequest(ProtocolModel):
    protocol_version: Literal["1.0.1"] = PROTOCOL_VERSION
    job_id: JobId
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    task_type: Literal["authoring_smoke"] = "authoring_smoke"
    payload: SmokePayload
    artifact: ArtifactSpec
    submitted_at: UtcDatetime


class WorkerInput(ProtocolModel):
    protocol_version: Literal["1.0.1"] = PROTOCOL_VERSION
    job_id: JobId
    task_type: Literal["authoring_smoke"] = "authoring_smoke"
    payload: SmokePayload
    artifact: ArtifactSpec
    submitted_at: UtcDatetime


class ResultContent(ProtocolModel):
    message: Annotated[str, Field(min_length=1, max_length=256)]


class WorkerResult(ProtocolModel):
    protocol_version: Literal["1.0.1"] = PROTOCOL_VERSION
    job_id: JobId
    status: Literal["ok"] = "ok"
    message: Literal["EOM_PLATFORM_SMOKE_TEST_OK"]
    artifact: ArtifactSpec
    content: ResultContent
    completed_at: UtcDatetime


class ArtifactManifest(ProtocolModel):
    protocol_version: Literal["1.0.1"] = PROTOCOL_VERSION
    manifest_version: Literal["1.0.0"] = "1.0.0"
    job_id: JobId
    logical_artifact_id: ArtifactId
    revision_id: RevisionId
    content_hash: Sha256
    content_bytes: Annotated[int, Field(ge=1)]
    file_name: Literal["result.json"] = "result.json"
    media_type: Literal["application/json"] = "application/json"
    worker_slot: Annotated[str, Field(pattern=r"^[0-9]{2}$")]
    created_at: UtcDatetime


class ErrorResult(ProtocolModel):
    protocol_version: Literal["1.0.1"] = PROTOCOL_VERSION
    job_id: JobId | None = None
    status: Literal["error"] = "error"
    error_code: ErrorCode
    message: Annotated[str, Field(min_length=1, max_length=1024)]
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: UtcDatetime

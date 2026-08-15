"""Versioned EOM message protocol."""

from eom_protocol.models import (
    PROTOCOL_VERSION,
    ArtifactManifest,
    ArtifactSpec,
    ErrorCode,
    ErrorResult,
    JobRequest,
    ResultContent,
    SmokePayload,
    WorkerInput,
    WorkerResult,
)
from eom_protocol.validation import SchemaValidationError, validate_message

__all__ = [
    "PROTOCOL_VERSION",
    "ArtifactManifest",
    "ArtifactSpec",
    "ErrorCode",
    "ErrorResult",
    "JobRequest",
    "ResultContent",
    "SchemaValidationError",
    "SmokePayload",
    "WorkerInput",
    "WorkerResult",
    "validate_message",
]

"""Bounded producer retry metadata; no source authority, allocation or failed→success."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator

from eom_workflow.embedding_unpublished_recovery import (
    UNPUBLISHED_ENCODING_FAILURE_CODE,
    UNPUBLISHED_ENCODING_FAILURE_EVENT,
    RetiredUnpublishedEmbeddingResult,
    UnpublishedEmbeddingEncodingFailure,
    UnpublishedEmbeddingRecoveryCommand,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.models import JobId
from eom_workflow.schemas import NativeEmbeddingContract, local_embedding_admission_schema_registry

ENCODING_RECOVERY_PROTOCOL = "embedding-encoding-recovery/1.0"
ENCODING_RECOVERY_SCHEMA_REF = "eom://schemas/workflow/embedding-encoding-recovery/1.0"
ENCODING_RECOVERY_SCHEMA_SHA256 = (
    "sha256:ddb29cff67e8f494a3953f0193630e784960f38cf19acb47e10deebfad477244"
)
ENCODING_RECOVERY_MAX_BYTES = 64 * 1024
MAX_ENCODING_RETRIES = 3
KNOWN_ENCODING_FAILURE_EVENT = "EMBEDDING_ENCODING_KNOWN_FAILED"
ENCODING_RETRY_SUCCESSOR_EVENT = "EMBEDDING_ENCODING_RETRY_SUCCESSOR"
ENCODING_RETRY_PRODUCER_EVENT = "EMBEDDING_ENCODING_RETRY_PRODUCER"
KNOWN_ENCODING_FAILURE_CODE = "EMBEDDING_NATIVE_KNOWN_FAILED_RETIRED"


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_ENCODING_RECOVERY_INVALID")


@lru_cache(maxsize=1)
def _raw_schema() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-encoding-recovery-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(ENCODING_RECOVERY_MAX_BYTES + 1)
    _require(0 < len(raw) <= ENCODING_RECOVERY_MAX_BYTES)
    _require(sha256_bytes(raw) == ENCODING_RECOVERY_SCHEMA_SHA256)
    return raw


def embedding_encoding_recovery_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_raw_schema())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_encoding_recovery_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=local_embedding_admission_schema_registry(),
        format_checker=FormatChecker(),
    )


class RetiredEmbeddingRootFailure(NativeEmbeddingContract):
    """Small exact protected-record reference; actual root adapter must resolve it."""

    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    retirement_sha256: Sha256
    retired_at: UtcDatetime
    parent_plan_job_id: JobId
    parent_request_sha256: Sha256
    original_outcome: Literal["FAILED"]
    stored_descriptors: Literal[0]


class _RecoveryMessage(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-recovery/1.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            _require(len(canonical_json_bytes(document)) <= ENCODING_RECOVERY_MAX_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_ENCODING_RECOVERY_INVALID") from None


class _RecoveryEvent(_RecoveryMessage):
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        _require(
            self.event_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"event_sha256"}))
        )
        return self


class KnownFailedEmbeddingEncoding(_RecoveryEvent):
    record_type: Literal["FAILURE"]
    owned_job: LocalEmbeddingOwnedJob
    native_launch_job_id: JobId
    root: RetiredEmbeddingRootFailure


class EmbeddingEncodingRetryDeclaration(_RecoveryEvent):
    record_type: Literal["RETRY"]
    logical_job: EmbeddingEncodingJobReference
    predecessor: EmbeddingEncodingJobReference
    successor: EmbeddingEncodingJobReference
    encoding_sha256: Sha256
    attempt: int = Field(strict=True, ge=1, le=MAX_ENCODING_RETRIES)
    predecessor_failure_sha256: Sha256

    @model_validator(mode="after")
    def exact_relation(self) -> Self:
        root, old, new = self.logical_job, self.predecessor, self.successor
        _require(root.request_sha256 == old.request_sha256 == new.request_sha256)
        _require((self.attempt == 1) == (root == old))
        _require(new.job_id not in {root.job_id, old.job_id})
        _require(
            new.allocated_artifact_id not in {root.allocated_artifact_id, old.allocated_artifact_id}
        )
        _require(
            new.allocated_artifact_revision_id
            not in {root.allocated_artifact_revision_id, old.allocated_artifact_revision_id}
        )
        return self

    @property
    def storage_idempotency_key(self) -> str:
        """Explicit retry declaration, never a replacement computational encoding key."""
        return "embedding-encode-retry:" + content_sha256(
            {
                "logical_job": self.logical_job.model_dump(mode="json"),
                "predecessor": self.predecessor.model_dump(mode="json"),
                "attempt": self.attempt,
                "encoding_sha256": self.encoding_sha256,
            }
        ).removeprefix("sha256:")


class NativeEmbeddingFailureRecoveryCommand(_RecoveryMessage):
    record_type: Literal["RECOVER"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    lease_generation: int = Field(strict=True, ge=1, le=2**31 - 1)
    root: RetiredEmbeddingRootFailure
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command_hash(self) -> Self:
        _require(
            self.command_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        )
        return self


type SupportedEncodingFailure = KnownFailedEmbeddingEncoding | UnpublishedEmbeddingEncodingFailure
type SupportedFailureRecoveryCommand = (
    NativeEmbeddingFailureRecoveryCommand | UnpublishedEmbeddingRecoveryCommand
)
type SupportedRetiredEmbeddingFailure = (
    RetiredEmbeddingRootFailure | RetiredUnpublishedEmbeddingResult
)


@dataclass(frozen=True, slots=True)
class EncodingFailureDisposition:
    code: str
    encoding_event: str
    native_event: str
    message: str


_NUMERICAL_FAILED = EncodingFailureDisposition(
    KNOWN_ENCODING_FAILURE_CODE,
    KNOWN_ENCODING_FAILURE_EVENT,
    "EMBEDDING_NATIVE_KNOWN_FAILED",
    "Original numerical unit failed and its retirement was verified.",
)
_UNPUBLISHED = EncodingFailureDisposition(
    UNPUBLISHED_ENCODING_FAILURE_CODE,
    UNPUBLISHED_ENCODING_FAILURE_EVENT,
    "EMBEDDING_NATIVE_RESULT_UNPUBLISHED",
    "Numerical execution succeeded, but its failed controller never published completion.",
)
RECOVERABLE_ENCODING_FAILURE_CODES = frozenset((_NUMERICAL_FAILED.code, _UNPUBLISHED.code))
RECOVERABLE_ENCODING_FAILURE_EVENTS = (
    _NUMERICAL_FAILED.encoding_event,
    _UNPUBLISHED.encoding_event,
)


def encoding_failure_disposition(
    value: SupportedEncodingFailure | SupportedFailureRecoveryCommand,
) -> EncodingFailureDisposition:
    if isinstance(value, UnpublishedEmbeddingEncodingFailure | UnpublishedEmbeddingRecoveryCommand):
        return _UNPUBLISHED
    if isinstance(value, KnownFailedEmbeddingEncoding | NativeEmbeddingFailureRecoveryCommand):
        return _NUMERICAL_FAILED
    raise ValueError("EMBEDDING_ENCODING_RECOVERY_INVALID")


def parse_supported_encoding_failure(value: object) -> SupportedEncodingFailure:
    document = raw_similarity_contract_value(value)
    if document.get("schema_version") == "embedding-encoding-recovery/2.0":
        return UnpublishedEmbeddingEncodingFailure.model_validate(document)
    return KnownFailedEmbeddingEncoding.model_validate(document)


def parse_supported_failure_recovery(value: object) -> SupportedFailureRecoveryCommand:
    document = raw_similarity_contract_value(value)
    if document.get("schema_version") == "embedding-encoding-recovery/2.0":
        return UnpublishedEmbeddingRecoveryCommand.model_validate(document)
    return NativeEmbeddingFailureRecoveryCommand.model_validate(document)

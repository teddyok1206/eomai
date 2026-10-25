"""Explicit application failure after numerical success; never a fabricated failed unit."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator

from eom_workflow.local_embedding_encoding_job import LocalEmbeddingOwnedJob
from eom_workflow.models import JobId
from eom_workflow.schemas import NativeEmbeddingContract, local_embedding_admission_schema_registry

UNPUBLISHED_RECOVERY_PROTOCOL = "embedding-encoding-recovery/2.0"
UNPUBLISHED_RECOVERY_SCHEMA_SHA256 = (
    "sha256:996997c8b36626556cda4b2b7e63d1b8d004e8d9ca87aef0b465f06d9e4d5746"
)
UNPUBLISHED_ENCODING_FAILURE_CODE = "EMBEDDING_NATIVE_RESULT_UNPUBLISHED"
UNPUBLISHED_ENCODING_FAILURE_EVENT = "EMBEDDING_ENCODING_RESULT_UNPUBLISHED"
MAX_UNPUBLISHED_RECOVERY_BYTES = 64 * 1024


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_workflow")
        .joinpath("resources/embedding-encoding-recovery-v2.schema.json")
        .read_bytes()
    )
    if not 0 < len(raw) <= MAX_UNPUBLISHED_RECOVERY_BYTES or (
        sha256_bytes(raw) != UNPUBLISHED_RECOVERY_SCHEMA_SHA256
    ):
        raise ValueError("EMBEDDING_UNPUBLISHED_RECOVERY_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=local_embedding_admission_schema_registry(),
        format_checker=FormatChecker(),
    )


class RetiredUnpublishedEmbeddingResult(NativeEmbeddingContract):
    """Protected numerical-success retirement plus the separately failed controller."""

    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    retirement_sha256: Sha256
    retired_at: UtcDatetime
    parent_plan_job_id: JobId
    parent_request_sha256: Sha256
    original_outcome: Literal["SUCCEEDED"]
    stored_descriptors: Literal[0]
    controller_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    controller_outcome: Literal["FAILED"]

    @model_validator(mode="before")
    @classmethod
    def strict_root_metadata(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            validator = _validator()
            schema = validator.schema
            if (
                not isinstance(schema, dict)
                or len(canonical_json_bytes(document)) > MAX_UNPUBLISHED_RECOVERY_BYTES
            ):
                raise ValueError("invalid root recovery metadata")
            validator.evolve(schema=schema["$defs"]["root"]).validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_UNPUBLISHED_RECOVERY_INVALID") from None


class _UnpublishedRecoveryMessage(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-recovery/2.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_UNPUBLISHED_RECOVERY_BYTES:
                raise ValueError("oversized recovery metadata")
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_UNPUBLISHED_RECOVERY_INVALID") from None


class UnpublishedEmbeddingRecoveryCommand(_UnpublishedRecoveryMessage):
    record_type: Literal["RECOVER"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    lease_generation: int = Field(strict=True, ge=1)
    root: RetiredUnpublishedEmbeddingResult
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("EMBEDDING_UNPUBLISHED_RECOVERY_INVALID")
        return self


class UnpublishedEmbeddingEncodingFailure(_UnpublishedRecoveryMessage):
    record_type: Literal["FAILURE"]
    owned_job: LocalEmbeddingOwnedJob
    native_launch_job_id: JobId
    root: RetiredUnpublishedEmbeddingResult
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.event_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"event_sha256"})
        ):
            raise ValueError("EMBEDDING_UNPUBLISHED_RECOVERY_INVALID")
        return self

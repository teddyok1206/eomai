"""Explicit CPU preparation failure before numeric start; old numeric proof stays closed."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator

from eom_workflow.local_embedding_encoding_job import LocalEmbeddingOwnedJob
from eom_workflow.models import JobId
from eom_workflow.schemas import NativeEmbeddingContract, local_embedding_admission_schema_registry

CPU_PREPARATION_FAILURE_PROTOCOL = "embedding-encoding-recovery/4.0"
CPU_PREPARATION_FAILURE_SCHEMA_SHA256 = (
    "sha256:6e12dc3b52f69f5923d7fafc29b4fe51769ef0c3c639fe49b7227312176bcadc"
)
MAX_CPU_PREPARATION_FAILURE_BYTES = 64 * 1024


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_workflow")
        .joinpath("resources/embedding-encoding-recovery-v4.schema.json")
        .read_bytes()
    )
    if (
        not 0 < len(raw) <= MAX_CPU_PREPARATION_FAILURE_BYTES
        or sha256_bytes(raw) != CPU_PREPARATION_FAILURE_SCHEMA_SHA256
    ):
        raise ValueError("EMBEDDING_CPU_PREPARATION_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema, registry=local_embedding_admission_schema_registry(), format_checker=FormatChecker()
    )


def _schema_value(value: object, *, root: bool = False) -> Any:
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > MAX_CPU_PREPARATION_FAILURE_BYTES:
            raise ValueError("oversized preparation proof")
        validator = _validator()
        if root:
            schema = validator.schema
            if not isinstance(schema, dict):
                raise ValueError("invalid preparation recovery schema")
            validator.evolve(schema=schema["$defs"]["root"]).validate(document)
        else:
            validator.validate(document)
        return document
    except Exception:
        raise ValueError("EMBEDDING_CPU_PREPARATION_INVALID") from None


class RetiredNativeCpuPreparationFailure(NativeEmbeddingContract):
    kind: Literal["NATIVE_CPU_INDEX_PREPARATION_FAILED"]
    native_launch_job_id: JobId
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    prepare_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    prepare_template_sha256: Sha256
    numeric_template_sha256: Sha256
    prepare_started_monotonic_us: int = Field(strict=True, ge=1, le=2**63 - 1)
    prepare_exited_monotonic_us: int = Field(strict=True, ge=1, le=2**63 - 1)
    prepare_result: Literal["timeout", "exit-code", "signal", "core-dump", "oom-kill"]
    prepare_exec_main_code: int = Field(strict=True, ge=1, le=3)
    prepare_exec_main_status: int = Field(strict=True, ge=0, le=255)
    numeric_state: Literal["NOT_STARTED"]
    original_outcome: Literal["FAILED"]
    stored_descriptors: Literal[0]
    proof_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _schema_value(value, root=True)

    @model_validator(mode="after")
    def exact_original(self) -> Self:
        if (
            self.prepare_exited_monotonic_us < self.prepare_started_monotonic_us
            or self.proof_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"proof_sha256"}))
        ):
            raise ValueError("EMBEDDING_CPU_PREPARATION_INVALID")
        return self


class _PreparationFailureMessage(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-recovery/4.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _schema_value(value)


class CpuPreparationFailureRecoveryCommand(_PreparationFailureMessage):
    record_type: Literal["RECOVER"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    lease_generation: int = Field(strict=True, ge=1, le=2**31 - 1)
    native_intent_sha256: Sha256
    current_service: LocalIndexingServiceReference
    root: RetiredNativeCpuPreparationFailure
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("EMBEDDING_CPU_PREPARATION_INVALID")
        return self


class KnownFailedCpuPreparationEncoding(_PreparationFailureMessage):
    record_type: Literal["FAILURE"]
    owned_job: LocalEmbeddingOwnedJob
    native_launch_job_id: JobId
    root: RetiredNativeCpuPreparationFailure
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_encoding(self) -> Self:
        if (
            self.native_launch_job_id != self.root.native_launch_job_id
            or self.owned_job.request.space.runtime.device != "CPU"
            or self.event_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"event_sha256"}))
        ):
            raise ValueError("EMBEDDING_CPU_PREPARATION_INVALID")
        return self

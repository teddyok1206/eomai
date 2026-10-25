"""Exact terminated CPU failure metadata; not source, unit or mutation authority."""

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

CPU_FAILURE_RECOVERY_PROTOCOL = "embedding-encoding-recovery/3.0"
CPU_FAILURE_RECOVERY_SCHEMA_SHA256 = (
    "sha256:8cf9c426562f60892cc88035b88e33aca0db42e732de4534ba11b706468f02f7"
)
MAX_CPU_FAILURE_RECOVERY_BYTES = 64 * 1024


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_workflow")
        .joinpath("resources/embedding-encoding-recovery-v3.schema.json")
        .read_bytes()
    )
    if not 0 < len(raw) <= MAX_CPU_FAILURE_RECOVERY_BYTES or (
        sha256_bytes(raw) != CPU_FAILURE_RECOVERY_SCHEMA_SHA256
    ):
        raise ValueError("EMBEDDING_CPU_FAILURE_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=local_embedding_admission_schema_registry(),
        format_checker=FormatChecker(),
    )


def _schema_value(value: object, *, root: bool = False) -> Any:
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > MAX_CPU_FAILURE_RECOVERY_BYTES:
            raise ValueError("oversized CPU recovery value")
        validator = _validator()
        if root:
            schema = validator.schema
            if not isinstance(schema, dict):
                raise ValueError("invalid CPU recovery root schema")
            validator.evolve(schema=schema["$defs"]["root"]).validate(document)
        else:
            validator.validate(document)
        return document
    except Exception:
        raise ValueError("EMBEDDING_CPU_FAILURE_INVALID") from None


class RetiredNativeCpuIndexFailure(NativeEmbeddingContract):
    """Fixed original units on one boot; a root adapter independently proves termination."""

    kind: Literal["NATIVE_CPU_INDEX_FAILED"]
    native_launch_job_id: JobId
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    prepare_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    numeric_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    prepare_template_sha256: Sha256
    numeric_template_sha256: Sha256
    numeric_started_monotonic_us: int = Field(strict=True, ge=1, le=2**63 - 1)
    numeric_exited_monotonic_us: int = Field(strict=True, ge=1, le=2**63 - 1)
    numeric_result: Literal["timeout", "exit-code", "signal", "core-dump", "oom-kill"]
    numeric_exec_main_code: int = Field(strict=True, ge=1, le=3)
    numeric_exec_main_status: int = Field(strict=True, ge=0, le=255)
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
            self.numeric_exited_monotonic_us < self.numeric_started_monotonic_us
            or self.prepare_invocation_id == self.numeric_invocation_id
            or self.proof_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"proof_sha256"}))
        ):
            raise ValueError("EMBEDDING_CPU_FAILURE_INVALID")
        return self


class _CpuFailureMessage(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-recovery/3.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _schema_value(value)


class CpuEmbeddingFailureRecoveryCommand(_CpuFailureMessage):
    record_type: Literal["RECOVER"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    lease_generation: int = Field(strict=True, ge=1, le=2**31 - 1)
    native_intent_sha256: Sha256
    current_service: LocalIndexingServiceReference
    root: RetiredNativeCpuIndexFailure
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("EMBEDDING_CPU_FAILURE_INVALID")
        return self


class KnownFailedCpuEmbeddingEncoding(_CpuFailureMessage):
    record_type: Literal["FAILURE"]
    owned_job: LocalEmbeddingOwnedJob
    native_launch_job_id: JobId
    root: RetiredNativeCpuIndexFailure
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_encoding(self) -> Self:
        if (
            self.native_launch_job_id != self.root.native_launch_job_id
            or self.owned_job.request.space.runtime.device != "CPU"
            or self.event_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"event_sha256"}))
        ):
            raise ValueError("EMBEDDING_CPU_FAILURE_INVALID")
        return self

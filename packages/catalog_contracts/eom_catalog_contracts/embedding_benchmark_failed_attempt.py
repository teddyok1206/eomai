"""Known failed post-ACK reconciliation. Unknown model work is never a zero-work claim."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    EMPTY_SHA256,
    EmptyBenchmarkOutput,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkExecutionId,
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

FAILED_ATTEMPT_EVENT = "BENCHMARK_FAILED_ATTEMPT_RECONCILED"
MAX_FAILED_ATTEMPT_BYTES = 16384


class _FailedAttemptContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, "embedding-benchmark-failed-attempt", MAX_FAILED_ATTEMPT_BYTES
        )


class BenchmarkFailedAttemptObservation(_FailedAttemptContract):
    schema_version: Literal["embedding-benchmark-failed-attempt/1.0"]
    kind: Literal["ROOT_OBSERVATION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    device: Literal["CUDA"]
    launch_ordinal: Literal[2, 3, 6]
    invocation_raw_sha256: Sha256
    association_sha256: Sha256
    prepared_sha256: Sha256
    ready_raw_sha256: Sha256
    ack_result_raw_sha256: Sha256
    retirement_intent_raw_sha256: Sha256
    retirement_result_raw_sha256: Sha256
    native_service: str
    native_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    original_outcome: Literal["FAILED"]
    cleanup: Literal["CONFIRMED"]
    root_ack_sent: Literal[True]
    model_progress: Literal["NOT_RECORDED"]
    reuse_failed_outputs: Literal[False]
    stored_descriptors: Literal[0]
    cgroup_empty: Literal[True]
    gpu_client_count: Literal[0]
    outputs: tuple[EmptyBenchmarkOutput, ...] = Field(min_length=2, max_length=16)
    physical_fence_sha256: Sha256
    boot_id: str
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_failed_execution(self) -> BenchmarkFailedAttemptObservation:
        if (
            self.native_service
            != "eom-embedding-benchmark-cuda-budget1200@" + self.execution_id + ".service"
            or tuple(member.member_name for member in self.outputs)
            != benchmark_local_output_members(self.launch_ordinal)
            or self.ready_raw_sha256 == EMPTY_SHA256
            or self.ack_result_raw_sha256 == EMPTY_SHA256
            or self.physical_fence_sha256 == content_sha256(None)
        ):
            raise ValueError("BENCHMARK_FAILED_ATTEMPT_EXECUTION_INVALID")
        _require_hash(self, "observation_sha256")
        return self


class BenchmarkFailedAttemptDecision(_FailedAttemptContract):
    schema_version: Literal["embedding-benchmark-failed-attempt/1.0"]
    kind: Literal["RECOVERY_DECISION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    from_state: Literal["RUNNING"]
    to_state: Literal["RUNNING"]
    reason: Literal["FAILED_AFTER_ROOT_ACK"]
    observation: BenchmarkFailedAttemptObservation
    actor_id: ActorId
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_linkage(self) -> BenchmarkFailedAttemptDecision:
        if (
            any(
                getattr(self, key) != getattr(self.observation, key)
                for key in ("job_id", "execution_id", "request_sha256", "invocation_sha256")
            )
            or self.decided_at < self.observation.observed_at
        ):
            raise ValueError("BENCHMARK_FAILED_ATTEMPT_DECISION_INVALID")
        _require_hash(self, "decision_sha256")
        return self


def _require_hash(value: FrozenModel, key: str) -> None:
    if getattr(value, key) != content_sha256(value.model_dump(mode="json", exclude={key})):
        raise ValueError("BENCHMARK_FAILED_ATTEMPT_HASH_INVALID")


def require_benchmark_failed_attempt_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    observation: BenchmarkFailedAttemptObservation,
) -> BenchmarkFailedAttemptObservation:
    checked = BenchmarkFailedAttemptObservation.model_validate(observation)
    if (
        request.schema_version != "embedding-device-benchmark-request/1.2"
        or request.execution_policy.timeout_seconds != 1200
        or invocation.device != "CUDA"
        or checked.launch_ordinal != invocation.launch_ordinal
        or checked.job_id != invocation.job_id
        or checked.execution_id != invocation.execution_id
        or checked.request_sha256 != request.request_sha256
        or checked.invocation_sha256 != invocation.invocation_sha256
        or checked.invocation_raw_sha256
        != sha256_bytes(embedding_device_benchmark_bytes(invocation))
    ):
        raise ValueError("BENCHMARK_FAILED_ATTEMPT_OBSERVATION_CONFLICT")
    return checked


type BenchmarkFailedAttemptMessage = Annotated[
    BenchmarkFailedAttemptObservation | BenchmarkFailedAttemptDecision, Field(discriminator="kind")
]
_ADAPTER: TypeAdapter[BenchmarkFailedAttemptMessage] = TypeAdapter(BenchmarkFailedAttemptMessage)


def benchmark_failed_attempt_bytes(value: BenchmarkFailedAttemptMessage) -> bytes:
    return canonical_json_bytes(_ADAPTER.validate_python(value).model_dump(mode="json"))


def parse_benchmark_failed_attempt_bytes(raw: bytes) -> BenchmarkFailedAttemptMessage:
    value = _ADAPTER.validate_python(
        parse_rootlocal_evidence_document(raw, MAX_FAILED_ATTEMPT_BYTES)
    )
    if benchmark_failed_attempt_bytes(value) != raw:
        raise ValueError("BENCHMARK_FAILED_ATTEMPT_NONCANONICAL")
    return value

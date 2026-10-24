"""A retired, zero-compute CUDA attempt is history, never a successful measurement."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

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

PREACK_RECOVERY_EVENT = "BENCHMARK_CUDA_PREACK_RECOVERED"
MAX_PREACK_RECOVERY_BYTES = 16384
EMPTY_SHA256 = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class EmptyBenchmarkOutput(FrozenModel):
    member_name: str = Field(min_length=1, max_length=200)
    byte_count: Literal[0]
    sha256: Literal["sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"]


class _PreackContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, "embedding-benchmark-preack-recovery", MAX_PREACK_RECOVERY_BYTES
        )


class BenchmarkPreackObservation(_PreackContract):
    schema_version: Literal["embedding-benchmark-preack-recovery/1.0"]
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
    retirement_intent_raw_sha256: Sha256
    retirement_result_raw_sha256: Sha256
    native_service: str
    native_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    original_service_raw_sha256: Sha256
    original_outcome: Literal["FAILED"]
    cleanup: Literal["CONFIRMED"]
    root_ack_absent: Literal[True]
    constructor_calls: Literal[0]
    tokenizer_calls: Literal[0]
    cuda_init_calls: Literal[0]
    forward_calls: Literal[0]
    stored_descriptors: Literal[0]
    cgroup_empty: Literal[True]
    gpu_client_count: Literal[0]
    outputs: tuple[EmptyBenchmarkOutput, ...] = Field(min_length=2, max_length=16)
    physical_fence_sha256: Sha256
    boot_id: str
    observed_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_execution(self) -> BenchmarkPreackObservation:
        if (
            self.native_service
            != "eom-embedding-benchmark-cuda-budget1200@" + self.execution_id + ".service"
            or tuple(value.member_name for value in self.outputs)
            != benchmark_local_output_members(self.launch_ordinal)
        ):
            raise ValueError("BENCHMARK_PREACK_EXECUTION_INVALID")
        _require_hash(self, "observation_sha256")
        return self


class BenchmarkPreackRecoveryDecision(_PreackContract):
    schema_version: Literal["embedding-benchmark-preack-recovery/1.0"]
    kind: Literal["RECOVERY_DECISION"]
    job_id: JobId
    execution_id: BenchmarkExecutionId
    request_sha256: Sha256
    invocation_sha256: Sha256
    from_state: Literal["RUNNING"]
    to_state: Literal["RUNNING"]
    reason: Literal["CUDA_PREACK_FAILED_NO_COMPUTE"]
    observation: BenchmarkPreackObservation
    actor_id: ActorId
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_linkage(self) -> BenchmarkPreackRecoveryDecision:
        if (
            any(
                getattr(self, key) != getattr(self.observation, key)
                for key in ("job_id", "execution_id", "request_sha256", "invocation_sha256")
            )
            or self.decided_at < self.observation.observed_at
        ):
            raise ValueError("BENCHMARK_PREACK_DECISION_LINKAGE_INVALID")
        _require_hash(self, "decision_sha256")
        return self


def _require_hash(value: FrozenModel, key: str) -> None:
    if getattr(value, key) != content_sha256(value.model_dump(mode="json", exclude={key})):
        raise ValueError("BENCHMARK_PREACK_HASH_INVALID")


def require_benchmark_preack_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    observation: BenchmarkPreackObservation,
) -> BenchmarkPreackObservation:
    checked = BenchmarkPreackObservation.model_validate(observation)
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
        raise ValueError("BENCHMARK_PREACK_OBSERVATION_CONFLICT")
    return checked


type BenchmarkPreackMessage = Annotated[
    BenchmarkPreackObservation | BenchmarkPreackRecoveryDecision, Field(discriminator="kind")
]
_ADAPTER: TypeAdapter[BenchmarkPreackMessage] = TypeAdapter(BenchmarkPreackMessage)


def benchmark_preack_bytes(value: BenchmarkPreackMessage) -> bytes:
    return canonical_json_bytes(_ADAPTER.validate_python(value).model_dump(mode="json"))


def parse_benchmark_preack_bytes(raw: bytes) -> BenchmarkPreackMessage:
    document = parse_rootlocal_evidence_document(raw, MAX_PREACK_RECOVERY_BYTES)
    value = _ADAPTER.validate_python(document)
    if benchmark_preack_bytes(value) != raw:
        raise ValueError("BENCHMARK_PREACK_NONCANONICAL")
    return value

"""Untrusted pre-init retention request; parsing grants neither root ACK nor CUDA compute."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkExecutionId,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cuda_probe import NativeCudaProbeResourceDescriptors
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256

BENCHMARK_CUDA_READY_SCHEMA = "embedding-benchmark-cuda-ready"
MAX_BENCHMARK_CUDA_READY_BYTES = 8 * 1024


class BenchmarkCudaReady(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-benchmark-cuda-ready/1.0"]
    evidence_state: Literal["RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED"]
    execution_id: BenchmarkExecutionId
    job_id: JobId
    invocation_raw_sha256: Sha256
    configuration: RootLocalNativeConfigurationPin
    receipt_raw_sha256: Sha256
    fdstore_name: Literal["eom-gpu0-lease"]
    pid: int = Field(ge=1, le=2147483647, strict=True)
    start_time_ticks: int = Field(ge=1, le=18446744073709551615, strict=True)
    worker_uid: int = Field(ge=1, le=4294967294, strict=True)
    worker_gid: int = Field(ge=1, le=4294967294, strict=True)
    supplementary_gids: tuple[int, ...] = Field(min_length=1, max_length=1)
    resource_fds: NativeCudaProbeResourceDescriptors
    expected_device_capture: CudaRuntimeDeviceCapture
    cuda_initialization_calls: Literal[0]
    cuda_synchronize_calls: Literal[0]
    model_constructor_calls: Literal[0]
    tokenizer_constructor_calls: Literal[0]
    forward_calls: Literal[0]
    ready_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def exact_raw_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, BENCHMARK_CUDA_READY_SCHEMA, MAX_BENCHMARK_CUDA_READY_BYTES
        )

    @model_validator(mode="after")
    def closed_readiness(self) -> BenchmarkCudaReady:
        if self.worker_gid in self.supplementary_gids or self.ready_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"ready_sha256"})
        ):
            raise ValueError("BENCHMARK_CUDA_READINESS_INVALID")
        return self


def benchmark_cuda_ready_bytes(value: BenchmarkCudaReady) -> bytes:
    checked = BenchmarkCudaReady.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_benchmark_cuda_ready(raw: bytes) -> BenchmarkCudaReady:
    document = parse_rootlocal_evidence_document(raw, MAX_BENCHMARK_CUDA_READY_BYTES)
    value = BenchmarkCudaReady.model_validate(document)
    if benchmark_cuda_ready_bytes(value) != raw:
        raise ValueError("BENCHMARK_CUDA_READINESS_NONCANONICAL")
    return value


def validate_benchmark_cuda_ready(
    invocation: BenchmarkWorkerInvocation,
    readiness: BenchmarkCudaReady,
    *,
    configuration: RootLocalNativeConfigurationPin,
    receipt_raw_sha256: str,
    expected_device: CudaRuntimeDeviceCapture,
) -> None:
    """Pure linkage only; caller must independently inspect kernel/unit/store/host/source."""
    raw = embedding_device_benchmark_bytes(invocation)
    readiness = BenchmarkCudaReady.model_validate(readiness)
    if (
        invocation.device != "CUDA"
        or invocation.runtime.profile != "CUDA_INDEX_FP32"
        or readiness.execution_id != invocation.execution_id
        or readiness.job_id != invocation.job_id
        or readiness.invocation_raw_sha256 != sha256_bytes(raw)
        or readiness.configuration != configuration
        or readiness.receipt_raw_sha256 != receipt_raw_sha256
        or readiness.expected_device_capture != expected_device
        or expected_device.numeric_device != invocation.runtime.numerical_runtime.device
    ):
        raise ValueError("BENCHMARK_CUDA_READINESS_ASSOCIATION_INVALID")

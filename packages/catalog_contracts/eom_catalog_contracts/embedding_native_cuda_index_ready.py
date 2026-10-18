"""Pure INDEX pre-ML retention claims; not source admission, root ACK or GPU ownership."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cpu_probe import ExecutionId
from eom_catalog_contracts.embedding_native_cuda_probe import NativeCudaProbeResourceDescriptors
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

NATIVE_CUDA_INDEX_READY_SCHEMA = "embedding-native-cuda-index-ready"
MAX_NATIVE_CUDA_INDEX_READY_BYTES = 8 * 1024


class NativeCudaIndexReady(FrozenModel):
    """Untrusted descriptor numbers and identity claims, never an observed retained lease."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-native-cuda-index-ready/1.0"]
    purpose: Literal["INDEX"]
    evidence_state: Literal["RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED"]
    execution_id: ExecutionId
    job_id: JobId
    launch_association_sha256: Sha256
    input_raw_sha256: Sha256
    request_sha256: Sha256
    input_set_sha256: Sha256
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
            value, NATIVE_CUDA_INDEX_READY_SCHEMA, MAX_NATIVE_CUDA_INDEX_READY_BYTES
        )

    @model_validator(mode="after")
    def closed_readiness(self) -> NativeCudaIndexReady:
        if self.worker_gid in self.supplementary_gids or self.ready_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"ready_sha256"})
        ):
            raise ValueError("NATIVE_CUDA_INDEX_READINESS_INVALID")
        return self


def native_cuda_index_ready_bytes(value: NativeCudaIndexReady) -> bytes:
    checked = NativeCudaIndexReady.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_native_cuda_index_ready(raw: bytes) -> NativeCudaIndexReady:
    document = parse_rootlocal_evidence_document(raw, MAX_NATIVE_CUDA_INDEX_READY_BYTES)
    value = NativeCudaIndexReady.model_validate(document)
    if native_cuda_index_ready_bytes(value) != raw:
        raise ValueError("NATIVE_CUDA_INDEX_READINESS_NONCANONICAL")
    return value


def validate_native_cuda_index_ready(
    request: IncrementalEmbeddingInput,
    readiness: NativeCudaIndexReady,
    *,
    execution_id: str,
    native_launch_job_id: str,
    launch_association_sha256: str,
    input_raw_sha256: str,
    configuration: RootLocalNativeConfigurationPin,
    receipt_raw_sha256: str,
    expected_device: CudaRuntimeDeviceCapture,
) -> None:
    """Link only the original owner-selected values, without importing Workflow authority.

    The owner must first validate its actual LocalEmbeddingLaunchAssociation against
    this exact request and original input member. This comparison neither validates
    an opaque association hash nor observes any source, unit, FD, lease or root ACK.
    """
    request = parse_incremental_embedding_input(raw_similarity_contract_value(request))
    readiness = NativeCudaIndexReady.model_validate(readiness)
    configuration = RootLocalNativeConfigurationPin.model_validate(
        raw_similarity_contract_value(configuration)
    )
    expected_device = CudaRuntimeDeviceCapture.model_validate(
        raw_similarity_contract_value(expected_device)
    )
    execution_id = TypeAdapter(ExecutionId).validate_python(execution_id, strict=True)
    native_launch_job_id = TypeAdapter(JobId).validate_python(native_launch_job_id, strict=True)
    for selected_hash in (launch_association_sha256, input_raw_sha256, receipt_raw_sha256):
        TypeAdapter(Sha256).validate_python(selected_hash, strict=True)
    raw = canonical_json_bytes(request.model_dump(mode="json"))
    if (
        request.space.runtime.device != "CUDA"
        or request.batch_size != 4
        or request.threads != 4
        or readiness.execution_id != execution_id
        or request.job_id != native_launch_job_id
        or readiness.job_id != native_launch_job_id
        or readiness.launch_association_sha256 != launch_association_sha256
        or readiness.input_raw_sha256 != input_raw_sha256
        or readiness.input_raw_sha256 != sha256_bytes(raw)
        or readiness.request_sha256 != request.request_sha256
        or readiness.input_set_sha256 != request.input_set_sha256
        or readiness.configuration != configuration
        or readiness.receipt_raw_sha256 != receipt_raw_sha256
        or readiness.expected_device_capture != expected_device
    ):
        raise ValueError("NATIVE_CUDA_INDEX_READINESS_ASSOCIATION_INVALID")

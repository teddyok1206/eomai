"""CUDA probe wire observations only, never a root seal, live FD or compute grant."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    CudaRuntimeDeviceCapture,
    EmbeddingInstalledRuntimeProof,
    EmbeddingInstalledRuntimeProofPointer,
)
from eom_catalog_contracts.embedding_native_cpu_probe import (
    ExecutionId,
    NativeProbeFilesystemDenials,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfigV12,
    EmbeddingNativeRuntimeConfigV13,
    InstalledEmbeddingNativeRuntimeConfig,
    parse_installed_embedding_native_runtime_config,
    validate_installed_embedding_native_runtime_config_raw,
    validate_installed_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalRuntimeDescriptor,
    EmbeddingRuntimeBundle,
    LegacyEmbeddingPayloadPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

CUDA_PROBE_SCHEMA = "embedding-native-cuda-probe"
MAX_CUDA_PROBE_BYTES = 64 * 1024
CUDA_PROBE_READY_SCHEMA = "embedding-native-cuda-probe-lease-ready"
MAX_CUDA_PROBE_READY_BYTES = 16 * 1024
type _Gid = Annotated[int, Field(ge=1, le=4294967294, strict=True)]
type _Fd = Annotated[int, Field(ge=3, le=1048575, strict=True)]
type _Zero = Annotated[int, Field(ge=0, le=0, strict=True)]
type _One = Annotated[int, Field(ge=1, le=1, strict=True)]


class _CudaProbeEnvelope(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def exact_wire_values(cls, value: object) -> object:
        return similarity_contract_document(value, CUDA_PROBE_SCHEMA, MAX_CUDA_PROBE_BYTES)


class NativeCudaProbeInput(_CudaProbeEnvelope):
    schema_version: Literal["embedding-native-cuda-probe-input/1.0"]
    execution_id: ExecutionId
    profile: Literal["CUDA_INDEX_FP32"]
    configuration: RootLocalNativeConfigurationPin
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    payload: LegacyEmbeddingPayloadPointer
    shared_lease_gid: _Gid

    @model_validator(mode="after")
    def cuda_profile(self) -> NativeCudaProbeInput:
        if self.installed_proof.profile != "CUDA_INDEX_FP32":
            raise ValueError("native CUDA probe cannot accept another proof profile")
        return self


class NativeCudaProbeResourceDescriptors(FrozenModel):
    """Untrusted descriptor numbers for independent kernel readback, not held handles."""

    nvidia0_fd: _Fd
    nvidiactl_fd: _Fd
    nvidia_uvm_fd: _Fd
    nvidia_uvm_tools_fd: _Fd
    lease_fd: _Fd

    @model_validator(mode="after")
    def distinct_descriptors(self) -> NativeCudaProbeResourceDescriptors:
        if len(set(self.model_dump().values())) != 5:
            raise ValueError("native CUDA probe resource descriptors alias")
        return self


class NativeCudaProbeResult(_CudaProbeEnvelope):
    schema_version: Literal["embedding-native-cuda-probe-result/1.0"]
    evidence_state: Literal["OBSERVED_NOT_ADMITTED"]
    recipe: Literal["NATIVE_CUDA_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"]
    execution_id: ExecutionId
    input_raw_sha256: Sha256
    pid: int = Field(ge=1, le=2147483647, strict=True)
    start_time_ticks: int = Field(ge=1, le=18446744073709551615, strict=True)
    worker_uid: int = Field(ge=1, le=4294967294, strict=True)
    worker_gid: _Gid
    supplementary_gids: tuple[_Gid, ...] = Field(min_length=1, max_length=1)
    checked_model_members: int = Field(ge=2, le=32, strict=True)
    payload_file_set_sha256: Sha256
    denials: NativeProbeFilesystemDenials
    numerical_runtime: EmbeddingNumericalRuntimeDescriptor
    device_capture: CudaRuntimeDeviceCapture
    resource_fds: NativeCudaProbeResourceDescriptors
    cuda_initialization_calls: _One
    cuda_synchronize_calls: _One
    model_constructor_calls: _Zero
    tokenizer_constructor_calls: _Zero
    forward_calls: _Zero

    @model_validator(mode="after")
    def fixed_cuda_recipe(self) -> NativeCudaProbeResult:
        runtime = self.numerical_runtime
        if (
            runtime.device.kind != "CUDA"
            or runtime.torch_build_cuda_version != "12.8"
            or runtime.recipe.batch_size != 4
            or runtime.recipe.threads != 4
            or runtime.recipe.cublas_workspace != ":4096:8"
            or self.device_capture.numeric_device != runtime.device
            or self.worker_gid in self.supplementary_gids
        ):
            raise ValueError("native CUDA probe observed a different recipe/device/group")
        return self


class NativeCudaProbeLeaseReady(FrozenModel):
    """Pre-initialization request only; root must independently observe the store then ACK."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["embedding-native-cuda-probe-lease-ready/1.0"]
    evidence_state: Literal["RETENTION_REQUESTED_NOT_CUDA_ADMITTED"]
    execution_id: ExecutionId
    input_raw_sha256: Sha256
    configuration: RootLocalNativeConfigurationPin
    fdstore_name: Literal["eom-gpu0-lease"]
    pid: int = Field(ge=1, le=2147483647, strict=True)
    start_time_ticks: int = Field(ge=1, le=18446744073709551615, strict=True)
    worker_uid: int = Field(ge=1, le=4294967294, strict=True)
    worker_gid: _Gid
    supplementary_gids: tuple[_Gid, ...] = Field(min_length=1, max_length=1)
    payload_file_set_sha256: Sha256
    resource_fds: NativeCudaProbeResourceDescriptors
    expected_device_capture: CudaRuntimeDeviceCapture
    cuda_initialization_calls: _Zero
    cuda_synchronize_calls: _Zero
    model_constructor_calls: _Zero
    tokenizer_constructor_calls: _Zero
    forward_calls: _Zero

    @model_validator(mode="before")
    @classmethod
    def exact_wire_values(cls, value: object) -> object:
        return similarity_contract_document(
            value, CUDA_PROBE_READY_SCHEMA, MAX_CUDA_PROBE_READY_BYTES
        )

    @model_validator(mode="after")
    def distinct_primary_group(self) -> NativeCudaProbeLeaseReady:
        if self.worker_gid in self.supplementary_gids:
            raise ValueError("native CUDA readiness shared group equals primary group")
        return self


def _canonical_document(raw: bytes, maximum: int = MAX_CUDA_PROBE_BYTES) -> object:
    try:
        document = parse_rootlocal_evidence_document(raw, maximum)
        if canonical_json_bytes(document) != raw:
            raise ValueError("noncanonical CUDA probe metadata")
        return document
    except (ValueError, TypeError, RecursionError):
        raise ValueError("NATIVE_CUDA_PROBE_METADATA_INVALID") from None


def parse_native_cuda_probe_input(raw: bytes) -> NativeCudaProbeInput:
    return NativeCudaProbeInput.model_validate(_canonical_document(raw))


def parse_native_cuda_probe_result(raw: bytes) -> NativeCudaProbeResult:
    return NativeCudaProbeResult.model_validate(_canonical_document(raw))


def parse_native_cuda_probe_lease_ready(raw: bytes) -> NativeCudaProbeLeaseReady:
    return NativeCudaProbeLeaseReady.model_validate(
        _canonical_document(raw, MAX_CUDA_PROBE_READY_BYTES)
    )


def validate_native_cuda_probe_association(
    request: NativeCudaProbeInput, request_raw: bytes, result: NativeCudaProbeResult
) -> None:
    """Declared association only; independently observe PID/start, every FD and its lifetime."""
    request = NativeCudaProbeInput.model_validate(request)
    result = NativeCudaProbeResult.model_validate(result)
    if (
        parse_native_cuda_probe_input(request_raw) != request
        or result.execution_id != request.execution_id
        or result.input_raw_sha256 != sha256_bytes(request_raw)
        or result.payload_file_set_sha256 != request.payload.file_set_sha256
        or result.supplementary_gids != (request.shared_lease_gid,)
    ):
        raise ValueError("NATIVE_CUDA_PROBE_ASSOCIATION_INVALID")


def validate_native_cuda_probe_configuration(
    request: NativeCudaProbeInput,
    *,
    configuration: InstalledEmbeddingNativeRuntimeConfig,
    configuration_raw: bytes,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    """Common exact config/proof/bundle closure; never prefix/host/unit admission."""
    request = NativeCudaProbeInput.model_validate(request)
    config = parse_installed_embedding_native_runtime_config(configuration)
    if not isinstance(config, EmbeddingNativeRuntimeConfigV12 | EmbeddingNativeRuntimeConfigV13):
        raise ValueError("NATIVE_CUDA_PROBE_CONFIGURATION_INVALID")
    validate_installed_embedding_native_runtime_config_raw(
        config, configuration_raw, request.configuration.configuration_raw_sha256
    )
    validate_installed_embedding_native_runtime_config_references(
        config, bundle, bundle_raw, proof, proof_raw
    )
    pin = request.configuration
    if (
        config.profile != "CUDA_INDEX_FP32"
        or (pin.configuration_id, pin.configuration_revision_id, pin.configuration_sha256)
        != (config.configuration_id, config.configuration_revision_id, config.config_sha256)
        or config.installed_proof != request.installed_proof
        or request.payload != bundle.payload_pointer
    ):
        raise ValueError("NATIVE_CUDA_PROBE_REFERENCE_INVALID")


def validate_native_cuda_probe_references(
    request: NativeCudaProbeInput,
    request_raw: bytes,
    result: NativeCudaProbeResult,
    *,
    configuration: InstalledEmbeddingNativeRuntimeConfig,
    configuration_raw: bytes,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    """Pure exact metadata closure; actual unit/host/lease observation stays with root."""
    request = NativeCudaProbeInput.model_validate(request)
    result = NativeCudaProbeResult.model_validate(result)
    validate_native_cuda_probe_association(request, request_raw, result)
    validate_native_cuda_probe_configuration(
        request,
        configuration=configuration,
        configuration_raw=configuration_raw,
        bundle=bundle,
        bundle_raw=bundle_raw,
        proof=proof,
        proof_raw=proof_raw,
    )
    if (
        result.numerical_runtime != bundle.numerical_runtime
        or result.device_capture != proof.device_capture
        or result.checked_model_members != len(bundle.payload_model_spec.files) + 1
    ):
        raise ValueError("NATIVE_CUDA_PROBE_REFERENCE_INVALID")


def validate_native_cuda_probe_ready_association(
    request: NativeCudaProbeInput, request_raw: bytes, ready: NativeCudaProbeLeaseReady
) -> None:
    request = NativeCudaProbeInput.model_validate(request)
    ready = NativeCudaProbeLeaseReady.model_validate(ready)
    if (
        parse_native_cuda_probe_input(request_raw) != request
        or ready.execution_id != request.execution_id
        or ready.input_raw_sha256 != sha256_bytes(request_raw)
        or ready.configuration != request.configuration
        or ready.payload_file_set_sha256 != request.payload.file_set_sha256
        or ready.supplementary_gids != (request.shared_lease_gid,)
    ):
        raise ValueError("NATIVE_CUDA_PROBE_READY_ASSOCIATION_INVALID")


def validate_native_cuda_probe_progression(
    request: NativeCudaProbeInput,
    request_raw: bytes,
    ready: NativeCudaProbeLeaseReady,
    result: NativeCudaProbeResult,
) -> None:
    """No PID/descriptor/authority substitution between the two independently observed phases."""
    ready = NativeCudaProbeLeaseReady.model_validate(ready)
    result = NativeCudaProbeResult.model_validate(result)
    validate_native_cuda_probe_ready_association(request, request_raw, ready)
    validate_native_cuda_probe_association(request, request_raw, result)
    fields = (
        "execution_id",
        "input_raw_sha256",
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "supplementary_gids",
        "payload_file_set_sha256",
        "resource_fds",
    )
    if (
        any(getattr(ready, name) != getattr(result, name) for name in fields)
        or ready.expected_device_capture != result.device_capture
    ):
        raise ValueError("NATIVE_CUDA_PROBE_PHASE_SUBSTITUTION")


def validate_native_cuda_probe_ready_references(
    request: NativeCudaProbeInput,
    request_raw: bytes,
    ready: NativeCudaProbeLeaseReady,
    *,
    configuration: InstalledEmbeddingNativeRuntimeConfig,
    configuration_raw: bytes,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    """Expected device is a pinned pre-init claim, never a CUDA hardware observation."""
    ready = NativeCudaProbeLeaseReady.model_validate(ready)
    validate_native_cuda_probe_ready_association(request, request_raw, ready)
    validate_native_cuda_probe_configuration(
        request,
        configuration=configuration,
        configuration_raw=configuration_raw,
        bundle=bundle,
        bundle_raw=bundle_raw,
        proof=proof,
        proof_raw=proof_raw,
    )
    if ready.expected_device_capture != proof.device_capture:
        raise ValueError("NATIVE_CUDA_PROBE_READY_REFERENCE_INVALID")

"""Frozen native runtime/resource intent; none of these values admits a runtime."""

from __future__ import annotations

from typing import Literal, Self

from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    embedding_runtime_bundle_bytes,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from pydantic import Field, model_validator

from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_POLICY_SCHEMA_REF = "eom://schemas/workflow/local-embedding-execution-policy/1.0"
LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF = (
    "eom://schemas/workflow/local-embedding-execution-policy/1.1"
)
MAX_LOCAL_EMBEDDING_GPU_VRAM_BYTES = 8 * 1024**3


class LocalEmbeddingResourceProfile(NativeEmbeddingContract):
    """Integer-only limits; owner configuration/capacity must independently admit them."""

    device: Literal["CPU", "CUDA"]
    threads: int = Field(ge=1, le=16, strict=True)
    batch_size: int = Field(ge=1, le=16, strict=True)
    memory_max_bytes: int = Field(ge=256 * 1024**2, le=32 * 1024**3, strict=True)
    gpu_vram_max_bytes: int = Field(ge=0, le=MAX_LOCAL_EMBEDDING_GPU_VRAM_BYTES, strict=True)
    cpu_quota_percent: int = Field(ge=100, le=1600, strict=True)
    timeout_seconds: int = Field(ge=30, le=1800, strict=True)
    tasks_max: int = Field(ge=1, le=64, strict=True)
    output_max_bytes: int = Field(ge=1, le=64 * 1024**2, strict=True)
    maximum_active_launches: int = Field(ge=1, le=1, strict=True)
    physical_gpu_lease: Literal["NONE", "SHARED_GPU0"]
    network: Literal["DISABLED"] = "DISABLED"
    resource_profile_sha256: Sha256

    @model_validator(mode="after")
    def exact_resource_recipe(self) -> LocalEmbeddingResourceProfile:
        if self.device == "CPU":
            if self.physical_gpu_lease != "NONE" or self.gpu_vram_max_bytes != 0:
                raise ValueError("CPU resources cannot claim GPU capacity or lease")
        elif self.physical_gpu_lease != "SHARED_GPU0" or self.gpu_vram_max_bytes < 4:
            raise ValueError("CUDA resources require the shared lease and bounded VRAM")
        if self.resource_profile_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"resource_profile_sha256"})
        ):
            raise ValueError("native resource profile canonical hash differs")
        return self


class LocalEmbeddingRuntimeProfile(NativeEmbeddingContract):
    space: EmbeddingSpace
    runtime_bundle: EmbeddingRuntimeBundlePointer
    resource_profile: LocalEmbeddingResourceProfile

    @model_validator(mode="after")
    def exact_device(self) -> LocalEmbeddingRuntimeProfile:
        if (
            self.space.purpose != "DOCUMENT"
            or self.space.runtime.device != self.resource_profile.device
        ):
            raise ValueError("native resource profile and document space differ")
        return self


class _LocalEmbeddingExecutionPolicyBody(NativeEmbeddingContract):
    """One numerical/profile invariant, independent from the two actor admission modes."""

    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    workflow_definition_sha256: Sha256
    profiles: tuple[LocalEmbeddingRuntimeProfile, ...] = Field(min_length=1, max_length=2)
    default_device: Literal["CPU", "CUDA"]
    gpu_busy: Literal["WAIT"] = "WAIT"
    created_at: UtcDatetime
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_policy(self) -> Self:
        devices = tuple(profile.resource_profile.device for profile in self.profiles)
        if devices != tuple(sorted(set(devices))) or self.default_device not in devices:
            raise ValueError(
                "native policy runtime profiles must be sorted, unique and include default"
            )
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > 64 * 1024:
            raise ValueError("native policy exceeds its metadata bound")
        if self.policy_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"policy_sha256"})
        ):
            raise ValueError("native policy canonical hash differs")
        return self


class LocalEmbeddingExecutionPolicy(_LocalEmbeddingExecutionPolicyBody):
    """Original operator-seed-only candidate; not proof of released admission."""

    schema_version: Literal["local-embedding-execution-policy/1.0"] = (
        "local-embedding-execution-policy/1.0"
    )
    admission_mode: Literal["OPERATOR_SEED_ONLY"] = "OPERATOR_SEED_ONLY"


class LocalEmbeddingServiceExecutionPolicy(_LocalEmbeddingExecutionPolicyBody):
    """Service-only successor; no actual runtime, source grant or self-activation."""

    schema_version: Literal["local-embedding-execution-policy/1.1"] = (
        "local-embedding-execution-policy/1.1"
    )
    admission_mode: Literal["LOCAL_INDEXING_SERVICE_ONLY"] = "LOCAL_INDEXING_SERVICE_ONLY"
    service: LocalIndexingServiceReference


type LocalEmbeddingExecutablePolicy = (
    LocalEmbeddingExecutionPolicy | LocalEmbeddingServiceExecutionPolicy
)


def parse_local_embedding_execution_policy(value: object) -> LocalEmbeddingExecutionPolicy:
    validate_local_embedding_admission_message("execution-policy", value)
    try:
        return LocalEmbeddingExecutionPolicy.model_validate(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_service_execution_policy(
    value: object,
) -> LocalEmbeddingServiceExecutionPolicy:
    validate_local_embedding_admission_message("service-execution-policy", value)
    try:
        return LocalEmbeddingServiceExecutionPolicy.model_validate(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def parse_local_embedding_executable_policy(value: object) -> LocalEmbeddingExecutablePolicy:
    """Closed schema dispatch only; selecting a version is not owner release admission."""
    try:
        if isinstance(value, (LocalEmbeddingExecutionPolicy, LocalEmbeddingServiceExecutionPolicy)):
            value = type(value).model_validate(value).model_dump(mode="json")
        if isinstance(value, dict):
            if value.get("schema_version") == "local-embedding-execution-policy/1.0":
                return parse_local_embedding_execution_policy(value)
            if value.get("schema_version") == "local-embedding-execution-policy/1.1":
                return parse_local_embedding_service_execution_policy(value)
    except LocalEmbeddingAdmissionContractError:
        raise
    except (ValueError, TypeError):
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None
    raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def validate_local_embedding_runtime_profile(
    profile: LocalEmbeddingRuntimeProfile, bundle: EmbeddingRuntimeBundle
) -> None:
    """Pure exact bundle closure; installed files/device/isolation remain owner checks."""
    profile = LocalEmbeddingRuntimeProfile.model_validate(profile)
    bundle = EmbeddingRuntimeBundle.model_validate(bundle.model_dump(mode="json"))
    validate_embedding_runtime_bundle_pointer(
        bundle, profile.runtime_bundle, embedding_runtime_bundle_bytes(bundle)
    )
    runtime, resources = bundle.numerical_runtime, profile.resource_profile
    if (
        profile.space.model_spec != bundle.execution_model_spec
        or profile.space.runtime.execution_runtime_sha256 != runtime.runtime_sha256
        or resources.device != runtime.device.kind
        or resources.batch_size != runtime.recipe.batch_size
        or resources.threads != runtime.recipe.threads
    ):
        raise ValueError("native runtime profile differs from exact bundle numerical recipe")

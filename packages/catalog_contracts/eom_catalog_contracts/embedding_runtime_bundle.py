"""Metadata-only numerical runtime and canonical payload/execution bundle closure."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

RUNTIME_BUNDLE_SCHEMA = "embedding-runtime-bundle"
RUNTIME_BUNDLE_SCHEMA_REF: Final = "eom://schemas/knowledge/embedding-runtime-bundle/1.0"
NUMERICAL_RUNTIME_SCHEMA_REF = "eom://schemas/knowledge/embedding-numerical-runtime/1.0"
PAYLOAD_MODEL_SCHEMA_REF: Final = (
    "eom://schemas/knowledge/item-inference-transfer/1.0#/$defs/localEmbeddingModel"
)
MAX_RUNTIME_BUNDLE_BYTES = 64 * 1024
type RuntimeVersion = Annotated[str, Field(pattern=r"^[0-9][A-Za-z0-9.+_-]{0,95}$")]
type RuntimeRecipeVersion = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")]
type CapabilityPart = Annotated[int, Field(ge=0, le=99, strict=True)]
type EmbeddingBundleId = Annotated[str, Field(pattern=r"^embeddingbundle_[0-9a-f]{32}$")]
type EmbeddingBundleRevisionId = Annotated[str, Field(pattern=r"^embeddingbundlerev_[0-9a-f]{32}$")]


class _RuntimeContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")


def _exact_hash(value: FrozenModel, field: str) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > MAX_RUNTIME_BUNDLE_BYTES:
        raise ValueError("embedding runtime metadata exceeds its byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("embedding runtime canonical hash differs")


def embedding_payload_file_set_sha256(spec: LocalEmbeddingModelSpec) -> str:
    """Hash ordered metadata, not model bytes; actual file validation belongs to its owner."""
    checked = LocalEmbeddingModelSpec.model_validate(spec.model_dump(mode="json"))
    return content_sha256([member.model_dump(mode="json") for member in checked.files])


class LegacyEmbeddingPayloadPointer(_RuntimeContract):
    """Exact existing protected payload identity; no path, access role or runtime override."""

    model_id: str = Field(pattern=r"^embeddingmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^embeddingmodelrev_[0-9a-f]{32}$")
    schema_ref: Literal[
        "eom://schemas/knowledge/item-inference-transfer/1.0#/$defs/localEmbeddingModel"
    ] = PAYLOAD_MODEL_SCHEMA_REF
    manifest_sha256: Sha256
    manifest_raw_sha256: Sha256
    file_set_sha256: Sha256


class EmbeddingNumericImplementationPin(_RuntimeContract):
    component: Literal["FLOAT32_CODEC", "HOST_L2", "OFFLINE_ENCODER"]
    recipe_version: RuntimeRecipeVersion
    sha256: Sha256


class EmbeddingNumericLibraryPin(_RuntimeContract):
    """Immutable distribution identity; an asserted pin is not an installed RECORD check."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    version: RuntimeVersion
    distribution_sha256: Sha256


class EmbeddingNumericalDevice(_RuntimeContract):
    kind: Literal["CPU", "CUDA"]
    platform: Literal["LINUX_X86_64"] = "LINUX_X86_64"
    hardware_model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,127}$")
    compute_capability: tuple[CapabilityPart, CapabilityPart] | None
    driver_version: RuntimeVersion | None

    @model_validator(mode="after")
    def exact_device_fields(self) -> EmbeddingNumericalDevice:
        if self.kind == "CPU":
            if self.compute_capability is not None or self.driver_version is not None:
                raise ValueError("CPU numerical device cannot claim CUDA capability or driver")
        elif self.compute_capability is None or self.driver_version is None:
            raise ValueError("CUDA numerical device requires capability and driver pins")
        elif self.compute_capability[0] < 1:
            raise ValueError("CUDA compute capability requires a positive major version")
        return self


class EmbeddingNumericalRecipe(_RuntimeContract):
    """Small immutable numerical values; no plugin, executable, resource grant or model bytes."""

    precision: Literal["FLOAT32"] = "FLOAT32"
    execution_mode: Literal["EVAL_INFERENCE"] = "EVAL_INFERENCE"
    attention: Literal["EAGER"] = "EAGER"
    padding: Literal["LONGEST_WITHIN_BATCH"] = "LONGEST_WITHIN_BATCH"
    truncation: Literal["REJECT_OVERFLOW"] = "REJECT_OVERFLOW"
    pooling_transfer: Literal["HOST_AFTER_POOLING"] = "HOST_AFTER_POOLING"
    normalization: Literal["PINNED_HOST_L2"] = "PINNED_HOST_L2"
    matmul_precision: Literal["HIGHEST"] = "HIGHEST"
    matmul_tf32: Literal["DISABLED"] = "DISABLED"
    cudnn_tf32: Literal["DISABLED"] = "DISABLED"
    autocast: Literal["DISABLED"] = "DISABLED"
    compile: Literal["DISABLED"] = "DISABLED"
    deterministic_algorithms: Literal["REQUIRED"] = "REQUIRED"
    cudnn_benchmark: Literal["DISABLED"] = "DISABLED"
    cublas_workspace: Literal[":4096:8"] | None
    batch_size: int = Field(ge=1, le=16, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)


class EmbeddingNumericalRuntimeDescriptor(_RuntimeContract):
    """Relevant numerical fingerprint only; source/release audit is intentionally separate."""

    schema_version: Literal["embedding-numerical-runtime/1.0"] = "embedding-numerical-runtime/1.0"
    python_version: RuntimeVersion
    implementations: tuple[EmbeddingNumericImplementationPin, ...] = Field(
        min_length=3, max_length=3
    )
    libraries: tuple[EmbeddingNumericLibraryPin, ...] = Field(min_length=4, max_length=32)
    device: EmbeddingNumericalDevice
    recipe: EmbeddingNumericalRecipe
    torch_build_cuda_version: RuntimeVersion | None
    runtime_sha256: Sha256

    @model_validator(mode="after")
    def exact_numerical_descriptor(self) -> EmbeddingNumericalRuntimeDescriptor:
        device = EmbeddingNumericalDevice.model_validate(self.device.model_dump(mode="json"))
        recipe = EmbeddingNumericalRecipe.model_validate(self.recipe.model_dump(mode="json"))
        implementation_keys = tuple(pin.component for pin in self.implementations)
        if implementation_keys != ("FLOAT32_CODEC", "HOST_L2", "OFFLINE_ENCODER"):
            raise ValueError("numerical implementation pins must be complete, sorted and unique")
        library_keys = tuple(pin.name for pin in self.libraries)
        if library_keys != tuple(sorted(set(library_keys))) or not {
            "torch",
            "transformers",
            "safetensors",
            "tokenizers",
        }.issubset(library_keys):
            raise ValueError("numerical libraries must be required, sorted and unique")
        if device.kind == "CUDA":
            if self.torch_build_cuda_version is None or recipe.cublas_workspace != ":4096:8":
                raise ValueError("CUDA numerical runtime requires CUDA build and CUBLAS pins")
        elif recipe.cublas_workspace is not None:
            raise ValueError("CPU numerical recipe cannot claim a CUBLAS workspace")
        _exact_hash(self, "runtime_sha256")
        return self


class EmbeddingRuntimeBundle(_RuntimeContract):
    """Flat execution spec is usable only after trusted adapter resolves this exact bundle."""

    schema_version: Literal["embedding-runtime-bundle/1.0"] = "embedding-runtime-bundle/1.0"
    bundle_id: EmbeddingBundleId
    bundle_revision_id: EmbeddingBundleRevisionId
    payload_pointer: LegacyEmbeddingPayloadPointer
    payload_model_spec: LocalEmbeddingModelSpec
    execution_model_spec: LocalEmbeddingModelSpec
    numerical_runtime: EmbeddingNumericalRuntimeDescriptor
    bundle_sha256: Sha256

    @model_validator(mode="after")
    def exact_payload_execution_closure(self) -> EmbeddingRuntimeBundle:
        pointer = LegacyEmbeddingPayloadPointer.model_validate(
            self.payload_pointer.model_dump(mode="json")
        )
        payload = LocalEmbeddingModelSpec.model_validate(
            self.payload_model_spec.model_dump(mode="json")
        )
        execution = LocalEmbeddingModelSpec.model_validate(
            self.execution_model_spec.model_dump(mode="json")
        )
        runtime = EmbeddingNumericalRuntimeDescriptor.model_validate(
            self.numerical_runtime.model_dump(mode="json")
        )
        if (
            pointer.model_id != payload.model_id
            or pointer.model_revision_id != payload.model_revision_id
            or pointer.manifest_sha256 != payload.manifest_sha256
            or pointer.file_set_sha256 != embedding_payload_file_set_sha256(payload)
        ):
            raise ValueError("legacy payload pointer differs from its exact model spec")
        excluded = {"model_revision_id", "runtime_versions", "manifest_sha256"}
        if payload.model_dump(mode="json", exclude=excluded) != execution.model_dump(
            mode="json", exclude=excluded
        ):
            raise ValueError(
                "execution successor changes the canonical payload or numerical model recipe"
            )
        if payload.model_revision_id == execution.model_revision_id:
            raise ValueError("execution model successor requires a distinct immutable revision")
        libraries = {pin.name: pin.version for pin in runtime.libraries}
        if any(libraries[pin.name] != pin.version for pin in execution.runtime_versions):
            raise ValueError("execution model and numerical runtime library pins differ")
        _exact_hash(self, "bundle_sha256")
        return self


class EmbeddingRuntimeBundlePointer(_RuntimeContract):
    schema_version: Literal["embedding-runtime-bundle-pointer/1.0"] = (
        "embedding-runtime-bundle-pointer/1.0"
    )
    bundle_id: EmbeddingBundleId
    bundle_revision_id: EmbeddingBundleRevisionId
    schema_ref: Literal["eom://schemas/knowledge/embedding-runtime-bundle/1.0"] = (
        RUNTIME_BUNDLE_SCHEMA_REF
    )
    bundle_sha256: Sha256
    bundle_raw_sha256: Sha256
    manifest_member: ArtifactMemberPointer

    @model_validator(mode="after")
    def exact_member(self) -> EmbeddingRuntimeBundlePointer:
        member = ArtifactMemberPointer.model_validate(self.manifest_member.model_dump(mode="json"))
        if (
            member.member_path != "bundle.json"
            or member.schema_ref != RUNTIME_BUNDLE_SCHEMA_REF
            or member.media_type != "application/json"
            or member.sha256 != self.bundle_raw_sha256
        ):
            raise ValueError("runtime bundle member schema, media or raw hash differs")
        return self


def embedding_runtime_bundle_bytes(bundle: EmbeddingRuntimeBundle) -> bytes:
    """Serialize one small manifest; never materialize weights or validate storage/authority."""
    checked = EmbeddingRuntimeBundle.model_validate(bundle.model_dump(mode="json"))
    return canonical_json_bytes(checked.model_dump(mode="json"))


def validate_embedding_payload_manifest(
    bundle: EmbeddingRuntimeBundle, raw_manifest: bytes
) -> None:
    checked = EmbeddingRuntimeBundle.model_validate(bundle.model_dump(mode="json"))
    canonical = canonical_json_bytes(checked.payload_model_spec.model_dump(mode="json"))
    if (
        raw_manifest not in (canonical, canonical + b"\n")
        or sha256_bytes(raw_manifest) != checked.payload_pointer.manifest_raw_sha256
    ):
        raise ValueError("legacy payload manifest bytes or exact raw hash differ")


def validate_embedding_runtime_bundle_pointer(
    bundle: EmbeddingRuntimeBundle,
    pointer: EmbeddingRuntimeBundlePointer,
    raw_manifest: bytes,
) -> None:
    checked = EmbeddingRuntimeBundle.model_validate(bundle.model_dump(mode="json"))
    pinned = EmbeddingRuntimeBundlePointer.model_validate(pointer.model_dump(mode="json"))
    if (
        pinned.bundle_id != checked.bundle_id
        or pinned.bundle_revision_id != checked.bundle_revision_id
        or pinned.bundle_sha256 != checked.bundle_sha256
        or raw_manifest != embedding_runtime_bundle_bytes(checked)
        or sha256_bytes(raw_manifest) != pinned.bundle_raw_sha256
    ):
        raise ValueError("runtime bundle pointer identity, semantic hash or raw bytes differ")


def parse_embedding_runtime_bundle(document: dict[str, Any]) -> EmbeddingRuntimeBundle:
    validate_contract(RUNTIME_BUNDLE_SCHEMA, document)
    return EmbeddingRuntimeBundle.model_validate(document)


def parse_embedding_numerical_runtime(
    document: dict[str, Any],
) -> EmbeddingNumericalRuntimeDescriptor:
    validate_contract(RUNTIME_BUNDLE_SCHEMA, document)
    return EmbeddingNumericalRuntimeDescriptor.model_validate(document)

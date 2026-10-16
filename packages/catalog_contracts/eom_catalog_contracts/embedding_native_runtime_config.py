"""Small installation metadata; no factory, authority, paths or runtime activation."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    parse_host_configuration_pointer,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    EmbeddingInstalledRuntimeProof,
    EmbeddingInstalledRuntimeProofPointer,
    EmbeddingRuntimeProfile,
    parse_installed_runtime_proof,
    validate_installed_runtime_proof_pointer,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA: Final = "embedding-native-runtime-config"
EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA_REF: Final = (
    "eom://schemas/knowledge/embedding-native-runtime-config/1.0"
)
EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA: Final = "embedding-native-runtime-config-v1.1"
EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA_REF: Final = (
    "eom://schemas/knowledge/embedding-native-runtime-config/1.1"
)
MAX_NATIVE_RUNTIME_CONFIG_BYTES: Final = 64 * 1024


def _named_values(value: object, expected: type[BaseModel]) -> dict[str, object]:
    """Read a fixed tiny shape raw; never recursively dump an untrusted model."""
    fields = expected.model_fields
    if isinstance(value, BaseModel):
        if (
            not isinstance(value, expected)
            or value.__pydantic_extra__
            or len(value.__dict__) > len(fields)
            or set(value.__dict__) - set(fields)
        ):
            raise ValueError(
                "native configuration has copied/constructed extra or wrong model fields"
            )
        try:
            result = {name: getattr(value, name) for name in fields}
        except AttributeError as exc:
            raise ValueError(
                "native configuration constructed model lacks a declared field"
            ) from exc
    elif isinstance(value, dict):
        if len(value) > len(fields) or set(value) - set(fields):
            raise ValueError("native configuration contains undeclared fields")
        result = dict(value)
    else:
        raise ValueError("native configuration requires its exact small object shape")
    return result


def _strings(values: dict[str, object], excluded: set[str]) -> None:
    if any(
        not isinstance(value, str) or len(value) > 512
        for name, value in values.items()
        if name not in excluded
    ):
        raise ValueError("native configuration scalar fields must be bounded strings")


def _resource_values(value: object) -> dict[str, object]:
    values = _named_values(value, EmbeddingNativeRuntimeResources)
    if any(type(number) is not int for name, number in values.items() if name != "resource_sha256"):
        raise ValueError("native resource values must be exact raw integers, not bool or float")
    _strings(values, set(values) - {"resource_sha256"})
    return values


def _config_values(value: object, *, expected: type[BaseModel] | None = None) -> dict[str, object]:
    values = _named_values(value, EmbeddingNativeRuntimeConfig if expected is None else expected)
    _strings(values, {"bundle", "installed_proof", "resources", "host_configuration"})
    if "bundle" in values:
        bundle = _named_values(values["bundle"], EmbeddingRuntimeBundlePointer)
        _strings(bundle, {"manifest_member"})
        if "manifest_member" in bundle:
            member = _named_values(bundle["manifest_member"], ArtifactMemberPointer)
            _strings(member, set())
            bundle["manifest_member"] = member
        values["bundle"] = bundle
    if "installed_proof" in values:
        proof = _named_values(values["installed_proof"], EmbeddingInstalledRuntimeProofPointer)
        _strings(proof, set())
        values["installed_proof"] = proof
    if "resources" in values:
        values["resources"] = _resource_values(values["resources"])
    if "host_configuration" in values:
        values["host_configuration"] = parse_host_configuration_pointer(
            values["host_configuration"]
        ).model_dump(mode="json")
    return values


def _hash(value: FrozenModel, field: str) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > MAX_NATIVE_RUNTIME_CONFIG_BYTES:
        raise ValueError("native configuration exceeds its metadata byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("native configuration/resource canonical hash differs")


class EmbeddingNativeRuntimeResources(FrozenModel):
    """Exact fixed resource recipe, not effective sandbox policy or a compute grant."""

    model_config = ConfigDict(revalidate_instances="always")
    batch_size: int = Field(default=4, ge=4, le=4, strict=True)
    threads: int = Field(default=4, ge=4, le=4, strict=True)
    interop_threads: int = Field(default=1, ge=1, le=1, strict=True)
    cpu_quota_percent: int = Field(default=400, ge=400, le=400, strict=True)
    tasks_max: int = Field(default=64, ge=64, le=64, strict=True)
    ram_limit_bytes: int = Field(default=6 * 1024**3, ge=6 * 1024**3, le=6 * 1024**3, strict=True)
    timeout_seconds: int = Field(default=180, ge=180, le=180, strict=True)
    maximum_active_launches: int = Field(default=1, ge=1, le=1, strict=True)
    index_output_limit_bytes: int = Field(
        default=64 * 1024**2, ge=64 * 1024**2, le=64 * 1024**2, strict=True
    )
    benchmark_output_limit_bytes: int = Field(
        default=16 * 1024**2, ge=16 * 1024**2, le=16 * 1024**2, strict=True
    )
    vram_limit_bytes: int = Field(ge=0, le=8 * 1024**3, strict=True)
    resource_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def raw_resource_fields(cls, value: object) -> object:
        return _resource_values(value)

    @model_validator(mode="after")
    def exact_resources(self) -> EmbeddingNativeRuntimeResources:
        if self.vram_limit_bytes not in (0, 8 * 1024**3):
            raise ValueError("native resource VRAM must be fixed CPU0 or CUDA8GiB")
        _hash(self, "resource_sha256")
        return self


class _NativeRuntimeConfigurationFields(FrozenModel):
    """One authoritative device/resource/hash rule for both explicit configuration versions."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_resource: ClassVar[str | None] = None
    configuration_id: str = Field(pattern=r"^embeddingnativeconfig_[0-9a-f]{32}$")
    configuration_revision_id: str = Field(pattern=r"^embeddingnativeconfigrev_[0-9a-f]{32}$")
    profile: EmbeddingRuntimeProfile
    bundle: EmbeddingRuntimeBundlePointer
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    runtime_sha256: Sha256
    resources: EmbeddingNativeRuntimeResources
    config_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def raw_configuration_fields(cls, value: object) -> object:
        values = _config_values(value, expected=cls)
        if cls.schema_resource is not None:
            validate_contract(cls.schema_resource, values)
        return values

    @model_validator(mode="after")
    def exact_configuration(self) -> Self:
        if self.installed_proof.profile != self.profile or self.resources.vram_limit_bytes != (
            0 if self.profile == "CPU_INDEX_FP32" else 8 * 1024**3
        ):
            raise ValueError("native configuration proof/profile/resource device differs")
        _hash(self, "config_sha256")
        return self


class EmbeddingNativeRuntimeConfig(_NativeRuntimeConfigurationFields):
    """Strict1.0 metadata; snapshot fields remain invalid in the predecessor family."""

    schema_version: Literal["embedding-native-runtime-config/1.0"] = (
        "embedding-native-runtime-config/1.0"
    )


class EmbeddingNativeRuntimeConfigV11(_NativeRuntimeConfigurationFields):
    """Explicit installed successor; metadata does not create or authorize its OS mount."""

    schema_resource = EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA
    schema_version: Literal["embedding-native-runtime-config/1.1"]
    host_configuration: EmbeddingHostConfigurationPointer


type InstalledEmbeddingNativeRuntimeConfig = (
    EmbeddingNativeRuntimeConfig | EmbeddingNativeRuntimeConfigV11
)


def parse_installed_embedding_native_runtime_config(
    document: object,
) -> InstalledEmbeddingNativeRuntimeConfig:
    """Only this explicit installation-family reader supports the two released shapes."""
    if isinstance(document, BaseModel):
        version = document.__dict__.get("schema_version")
    elif isinstance(document, dict):
        version = document.get("schema_version")
    else:
        raise ValueError("installed native configuration requires a bounded object")
    if type(version) is not str:
        raise ValueError("installed native configuration requires an explicit version")
    if version == "embedding-native-runtime-config/1.0":
        values = _config_values(document)
        validate_contract(EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA, values)
        return EmbeddingNativeRuntimeConfig.model_validate(values)
    if version == "embedding-native-runtime-config/1.1":
        return EmbeddingNativeRuntimeConfigV11.model_validate(document)
    raise ValueError("installed native configuration version is unsupported")


def installed_embedding_native_runtime_config_bytes(
    config: InstalledEmbeddingNativeRuntimeConfig,
) -> bytes:
    checked = parse_installed_embedding_native_runtime_config(config)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_embedding_native_runtime_config(document: dict[str, Any]) -> EmbeddingNativeRuntimeConfig:
    values = _config_values(document)
    validate_contract(EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA, values)
    return EmbeddingNativeRuntimeConfig.model_validate(values)


def embedding_native_runtime_config_bytes(config: EmbeddingNativeRuntimeConfig) -> bytes:
    checked = EmbeddingNativeRuntimeConfig.model_validate(_config_values(config))
    return canonical_json_bytes(checked.model_dump(mode="json"))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value or len(value) >= 64:
            raise ValueError("native metadata repeats a field or exceeds its object bound")
        value[key] = child
    return value


def _integer(value: str) -> int:
    if len(value) > 20:
        raise ValueError("native metadata integer exceeds its lexical bound")
    return int(value)


def _no_float(value: str) -> object:
    raise ValueError("native metadata cannot contain floating/nonfinite JSON numbers")


def _document(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > maximum:
        raise ValueError("native metadata exceeds its external byte bound")
    depth, quoted, escaped = 0, False, False
    for character in raw:
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
        elif character == 34:
            quoted = True
        elif character in (91, 123):
            depth += 1
            if depth > 16:
                raise ValueError("native metadata nesting exceeds its pre-allocation bound")
        elif character in (93, 125):
            depth -= 1
    if depth or quoted:
        raise ValueError("native metadata JSON framing is incomplete")
    value: object = json.loads(
        raw,
        object_pairs_hook=_object,
        parse_int=_integer,
        parse_float=_no_float,
        parse_constant=_no_float,
    )
    if not isinstance(value, dict):
        raise ValueError("native metadata requires one JSON object")
    return value


def parse_embedding_native_runtime_config_bytes(raw: bytes) -> EmbeddingNativeRuntimeConfig:
    return parse_embedding_native_runtime_config(_document(raw, MAX_NATIVE_RUNTIME_CONFIG_BYTES))


def parse_installed_embedding_native_runtime_config_bytes(
    raw: bytes,
) -> InstalledEmbeddingNativeRuntimeConfig:
    return parse_installed_embedding_native_runtime_config(
        _document(raw, MAX_NATIVE_RUNTIME_CONFIG_BYTES)
    )


def validate_installed_embedding_native_runtime_config_raw(
    config: InstalledEmbeddingNativeRuntimeConfig, raw: bytes, expected_raw_sha256: str
) -> None:
    if (
        type(raw) is not bytes
        or len(raw) > MAX_NATIVE_RUNTIME_CONFIG_BYTES
        or raw != installed_embedding_native_runtime_config_bytes(config)
        or sha256_bytes(raw) != expected_raw_sha256
    ):
        raise ValueError("installed configuration canonical bytes or independent raw pin differ")


def validate_embedding_native_runtime_config_raw(
    config: EmbeddingNativeRuntimeConfig, raw: bytes, expected_raw_sha256: str
) -> None:
    """Expected raw pin comes from trusted installation/owner configuration, never this body."""
    if (
        type(raw) is not bytes
        or len(raw) > MAX_NATIVE_RUNTIME_CONFIG_BYTES
        or raw != embedding_native_runtime_config_bytes(config)
        or sha256_bytes(raw) != expected_raw_sha256
    ):
        raise ValueError("native configuration canonical bytes or independent raw pin differ")


def validate_embedding_native_runtime_config_references(
    config: EmbeddingNativeRuntimeConfig,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    """Resolved metadata closure only; no protected installation, files, authority or live PASS."""
    config = EmbeddingNativeRuntimeConfig.model_validate(_config_values(config))
    _validate_native_runtime_references(config, bundle, bundle_raw, proof, proof_raw)


def validate_installed_embedding_native_runtime_config_references(
    config: InstalledEmbeddingNativeRuntimeConfig,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    _validate_native_runtime_references(
        parse_installed_embedding_native_runtime_config(config),
        bundle,
        bundle_raw,
        proof,
        proof_raw,
    )


def _validate_native_runtime_references(
    config: InstalledEmbeddingNativeRuntimeConfig,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
) -> None:
    # Both families retain the same authoritative raw/numerical closure rules.
    resolved_bundle = parse_embedding_runtime_bundle(
        _document(bundle_raw, MAX_RUNTIME_BUNDLE_BYTES)
    )
    resolved_proof = parse_installed_runtime_proof(
        _document(proof_raw, MAX_INSTALLED_RUNTIME_PROOF_BYTES)
    )
    validate_embedding_runtime_bundle_pointer(resolved_bundle, config.bundle, bundle_raw)
    validate_installed_runtime_proof_pointer(resolved_proof, config.installed_proof, proof_raw)
    if bundle != resolved_bundle or proof != resolved_proof:
        raise ValueError("native resolved metadata objects differ from their exact raw documents")
    runtime = resolved_bundle.numerical_runtime
    expected_device = "CPU" if config.profile == "CPU_INDEX_FP32" else "CUDA"
    if (
        runtime.runtime_sha256 != config.runtime_sha256
        or runtime.device.kind != expected_device
        or runtime.device != resolved_proof.device_capture.numeric_device
        or runtime.python_version != resolved_proof.python_version
        or runtime.torch_build_cuda_version != resolved_proof.torch_build_cuda_version
        or runtime.recipe.batch_size != config.resources.batch_size
        or runtime.recipe.threads != config.resources.threads
        or tuple((pin.name, pin.version, pin.distribution_sha256) for pin in runtime.libraries)
        != tuple(
            (pin.name, pin.version, pin.archive.sha256) for pin in resolved_proof.numeric_libraries
        )
    ):
        raise ValueError("native configuration/bundle/proof numeric runtime closure differs")

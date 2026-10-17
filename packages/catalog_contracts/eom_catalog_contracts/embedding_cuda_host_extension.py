"""Closed CUDA host metadata; file, loader, kernel and device admission are separate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Final, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    EmbeddingHostConfigurationSnapshot,
    EmbeddingLoaderCacheMember,
    validate_host_configuration_pointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

CUDA_HOST_SCHEMA: Final = "embedding-cuda-host-extension"
CUDA_HOST_MANIFEST_REF: Final = (
    "eom://schemas/knowledge/embedding-cuda-host-extension/1.0#/$defs/snapshot"
)
CUDA_HOST_NVML_SCHEMA: Final = "embedding-cuda-host-extension-v1.1"
CUDA_HOST_NVML_MANIFEST_REF: Final = (
    "eom://schemas/knowledge/embedding-cuda-host-extension/1.1#/$defs/snapshot"
)
MAX_CUDA_HOST_MANIFEST_BYTES: Final = 8192
type CudaHostConfigurationId = Annotated[str, Field(pattern=r"^embeddingcudahost_[0-9a-f]{32}$")]
type CudaHostConfigurationRevisionId = Annotated[
    str, Field(pattern=r"^embeddingcudahostrev_[0-9a-f]{32}$")
]
type CudaHostLibraryRole = Literal[
    "CUDA_DRIVER", "RDMACM", "IBVERBS", "MLX5", "NL_CORE", "NL_ROUTE"
]
_LIBRARIES = MappingProxyType(
    {
        "CUDA_DRIVER": ("libcuda.so.1", 128 * 1024 * 1024),
        "RDMACM": ("librdmacm.so.1", 8 * 1024 * 1024),
        "IBVERBS": ("libibverbs.so.1", 8 * 1024 * 1024),
        "MLX5": ("libmlx5.so.1", 8 * 1024 * 1024),
        "NL_CORE": ("libnl-3.so.200", 8 * 1024 * 1024),
        "NL_ROUTE": ("libnl-route-3.so.200", 8 * 1024 * 1024),
    }
)


def _raw(value: object, depth: int = 0) -> Any:
    if depth > 5:
        raise ValueError("CUDA host metadata exceeds fixed depth")
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        if value.__pydantic_extra__ or set(value.__dict__) != set(fields):
            raise ValueError("CUDA host metadata has extra or missing constructed fields")
        return {name: _raw(value.__dict__[name], depth + 1) for name in fields}
    if isinstance(value, dict):
        if len(value) > 12 or any(type(name) is not str for name in value):
            raise ValueError("CUDA host metadata object exceeds fixed shape")
        return {name: _raw(child, depth + 1) for name, child in value.items()}
    if isinstance(value, tuple | list):
        if len(value) > 7:
            raise ValueError("CUDA host metadata array exceeds seven library members")
        return [_raw(child, depth + 1) for child in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("CUDA host metadata timestamps require UTC")
        return value.isoformat().replace("+00:00", "Z")
    if type(value) is int or (type(value) is str and len(value) <= 512):
        return value
    raise ValueError("CUDA host metadata requires exact bounded scalar values")


class _CudaHostValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_root: ClassVar[bool] = False
    schema_name: ClassVar[str] = CUDA_HOST_SCHEMA

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        raw = _raw(value)
        if (
            not isinstance(raw, dict)
            or len(canonical_json_bytes(raw)) > MAX_CUDA_HOST_MANIFEST_BYTES
        ):
            raise ValueError("CUDA host metadata exceeds fixed byte budget")
        if cls.schema_root:
            validate_contract(cls.schema_name, raw)
        return raw


class CudaHostLibraryMember(_CudaHostValue):
    role: CudaHostLibraryRole
    member_name: str
    byte_count: int = Field(ge=1, le=128 * 1024 * 1024, strict=True)
    sha256: Sha256

    @model_validator(mode="after")
    def closed_member(self) -> CudaHostLibraryMember:
        name, maximum = _LIBRARIES[self.role]
        if self.member_name != name or self.byte_count > maximum:
            raise ValueError("CUDA host library member or role-specific bound differs")
        return self


class CudaHostNvmlLibraryMember(_CudaHostValue):
    role: Literal["CUDA_NVML"]
    member_name: Literal["libnvidia-ml.so.1"]
    byte_count: int = Field(ge=1, le=8 * 1024 * 1024, strict=True)
    sha256: Sha256


class _CudaHostSnapshot(_CudaHostValue):
    schema_root = True
    schema_version: str
    configuration_id: CudaHostConfigurationId
    configuration_revision_id: CudaHostConfigurationRevisionId
    captured_at: UtcDatetime
    base_configuration: EmbeddingHostConfigurationPointer
    base_host_seed_sha256: Sha256
    driver_release: str = Field(pattern=r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
    libraries: tuple[CudaHostLibraryMember | CudaHostNvmlLibraryMember, ...]
    loader_cache: EmbeddingLoaderCacheMember
    host_seed_sha256: Sha256
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def canonical_closure(self) -> Self:
        body = self.model_dump(mode="json")
        seed = {
            name: body[name]
            for name in ("base_host_seed_sha256", "driver_release", "libraries", "loader_cache")
        }
        if self.host_seed_sha256 != content_sha256(seed):
            raise ValueError("CUDA host seed differs from exact runtime members")
        if self.snapshot_sha256 != content_sha256(
            {name: value for name, value in body.items() if name != "snapshot_sha256"}
        ):
            raise ValueError("CUDA host snapshot semantic hash differs")
        return self


class CudaHostExtensionSnapshot(_CudaHostSnapshot):
    schema_version: Literal["embedding-cuda-host-extension/1.0"]
    libraries: tuple[CudaHostLibraryMember, ...] = Field(min_length=6, max_length=6)


class CudaHostExtensionSnapshotV11(_CudaHostSnapshot):
    schema_name = CUDA_HOST_NVML_SCHEMA
    schema_version: Literal["embedding-cuda-host-extension/1.1"]
    libraries: tuple[CudaHostLibraryMember | CudaHostNvmlLibraryMember, ...] = Field(
        min_length=7, max_length=7
    )


class _CudaHostPointer(_CudaHostValue):
    schema_root = True
    schema_ref: str
    configuration_id: CudaHostConfigurationId
    configuration_revision_id: CudaHostConfigurationRevisionId
    manifest_byte_count: int = Field(ge=1, le=MAX_CUDA_HOST_MANIFEST_BYTES, strict=True)
    manifest_raw_sha256: Sha256
    snapshot_sha256: Sha256


class CudaHostExtensionPointer(_CudaHostPointer):
    schema_ref: Literal["eom://schemas/knowledge/embedding-cuda-host-extension/1.0#/$defs/snapshot"]


class CudaHostExtensionPointerV11(_CudaHostPointer):
    schema_name = CUDA_HOST_NVML_SCHEMA
    schema_ref: Literal["eom://schemas/knowledge/embedding-cuda-host-extension/1.1#/$defs/snapshot"]


type CudaHostExtensionSnapshotValue = CudaHostExtensionSnapshot | CudaHostExtensionSnapshotV11
type CudaHostExtensionPointerValue = CudaHostExtensionPointer | CudaHostExtensionPointerV11


def _snapshot(value: object) -> CudaHostExtensionSnapshotValue:
    raw = _raw(value)
    if isinstance(raw, dict) and raw.get("schema_version") == "embedding-cuda-host-extension/1.1":
        return CudaHostExtensionSnapshotV11.model_validate(raw)
    return CudaHostExtensionSnapshot.model_validate(raw)


def parse_cuda_host_extension_pointer(value: object) -> CudaHostExtensionPointerValue:
    """Select only an explicitly named released format; never substitute latest."""
    raw = _raw(value)
    if isinstance(raw, dict) and raw.get("schema_ref") == CUDA_HOST_NVML_MANIFEST_REF:
        return CudaHostExtensionPointerV11.model_validate(raw)
    return CudaHostExtensionPointer.model_validate(raw)


def cuda_host_extension_bytes(value: CudaHostExtensionSnapshotValue) -> bytes:
    return canonical_json_bytes(_snapshot(value).model_dump(mode="json"))


def parse_cuda_host_extension_bytes(raw: bytes) -> CudaHostExtensionSnapshotValue:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CUDA_HOST_MANIFEST_BYTES:
        raise ValueError("CUDA host manifest bytes exceed fixed budget")
    try:
        snapshot = _snapshot(json.loads(raw))
    except (RecursionError, UnicodeError):
        raise ValueError("CUDA host manifest is not bounded valid JSON") from None
    # Exact canonical bytes also reject duplicate keys, whitespace and alternate numbers.
    if raw != cuda_host_extension_bytes(snapshot):
        raise ValueError("CUDA host manifest bytes are not canonical")
    return snapshot


def validate_cuda_host_extension_pointer(
    pointer: CudaHostExtensionPointerValue,
    snapshot: CudaHostExtensionSnapshotValue,
    raw: bytes,
    base_snapshot: EmbeddingHostConfigurationSnapshot,
    base_raw: bytes,
) -> CudaHostExtensionSnapshotValue:
    """Pure pointer closure, not a filesystem, mapping, kernel or device permission grant."""
    pointer = parse_cuda_host_extension_pointer(pointer)
    snapshot = _snapshot(snapshot)
    base = validate_host_configuration_pointer(snapshot.base_configuration, base_snapshot, base_raw)
    if (
        type(raw) is not bytes
        or raw != cuda_host_extension_bytes(snapshot)
        or pointer.schema_ref
        != "eom://schemas/knowledge/" + snapshot.schema_version + "#/$defs/snapshot"
        or snapshot.base_host_seed_sha256 != base.host_seed_sha256
        or pointer.configuration_id != snapshot.configuration_id
        or pointer.configuration_revision_id != snapshot.configuration_revision_id
        or pointer.manifest_byte_count != len(raw)
        or pointer.manifest_raw_sha256 != sha256_bytes(raw)
        or pointer.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("CUDA host pointer/base/revision/raw/semantic closure differs")
    return snapshot

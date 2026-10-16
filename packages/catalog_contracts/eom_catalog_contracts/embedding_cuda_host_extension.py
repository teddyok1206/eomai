"""Closed CUDA host metadata; file, loader, kernel and device admission are separate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Final, Literal

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
        if len(value) > 6:
            raise ValueError("CUDA host metadata array exceeds six library members")
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
            validate_contract(CUDA_HOST_SCHEMA, raw)
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


class CudaHostExtensionSnapshot(_CudaHostValue):
    schema_root = True
    schema_version: Literal["embedding-cuda-host-extension/1.0"]
    configuration_id: CudaHostConfigurationId
    configuration_revision_id: CudaHostConfigurationRevisionId
    captured_at: UtcDatetime
    base_configuration: EmbeddingHostConfigurationPointer
    base_host_seed_sha256: Sha256
    driver_release: str = Field(pattern=r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
    libraries: tuple[CudaHostLibraryMember, ...] = Field(min_length=6, max_length=6)
    loader_cache: EmbeddingLoaderCacheMember
    host_seed_sha256: Sha256
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def canonical_closure(self) -> CudaHostExtensionSnapshot:
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


class CudaHostExtensionPointer(_CudaHostValue):
    schema_root = True
    schema_ref: Literal["eom://schemas/knowledge/embedding-cuda-host-extension/1.0#/$defs/snapshot"]
    configuration_id: CudaHostConfigurationId
    configuration_revision_id: CudaHostConfigurationRevisionId
    manifest_byte_count: int = Field(ge=1, le=MAX_CUDA_HOST_MANIFEST_BYTES, strict=True)
    manifest_raw_sha256: Sha256
    snapshot_sha256: Sha256


def cuda_host_extension_bytes(value: CudaHostExtensionSnapshot) -> bytes:
    return canonical_json_bytes(
        CudaHostExtensionSnapshot.model_validate(value).model_dump(mode="json")
    )


def parse_cuda_host_extension_bytes(raw: bytes) -> CudaHostExtensionSnapshot:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CUDA_HOST_MANIFEST_BYTES:
        raise ValueError("CUDA host manifest bytes exceed fixed budget")
    try:
        snapshot = CudaHostExtensionSnapshot.model_validate(json.loads(raw))
    except (RecursionError, UnicodeError):
        raise ValueError("CUDA host manifest is not bounded valid JSON") from None
    # Exact canonical bytes also reject duplicate keys, whitespace and alternate numbers.
    if raw != cuda_host_extension_bytes(snapshot):
        raise ValueError("CUDA host manifest bytes are not canonical")
    return snapshot


def validate_cuda_host_extension_pointer(
    pointer: CudaHostExtensionPointer,
    snapshot: CudaHostExtensionSnapshot,
    raw: bytes,
    base_snapshot: EmbeddingHostConfigurationSnapshot,
    base_raw: bytes,
) -> CudaHostExtensionSnapshot:
    """Pure pointer closure, not a filesystem, mapping, kernel or device permission grant."""
    pointer = CudaHostExtensionPointer.model_validate(pointer)
    snapshot = CudaHostExtensionSnapshot.model_validate(snapshot)
    base = validate_host_configuration_pointer(snapshot.base_configuration, base_snapshot, base_raw)
    if (
        type(raw) is not bytes
        or raw != cuda_host_extension_bytes(snapshot)
        or snapshot.base_host_seed_sha256 != base.host_seed_sha256
        or pointer.configuration_id != snapshot.configuration_id
        or pointer.configuration_revision_id != snapshot.configuration_revision_id
        or pointer.manifest_byte_count != len(raw)
        or pointer.manifest_raw_sha256 != sha256_bytes(raw)
        or pointer.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("CUDA host pointer/base/revision/raw/semantic closure differs")
    return snapshot

"""Small reviewed host configuration values, not runtime/source/device admission."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Any, ClassVar, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

HOST_CONFIGURATION_SCHEMA = "embedding-host-configuration-snapshot"
HOST_CONFIGURATION_SCHEMA_REF = "eom://schemas/knowledge/embedding-host-configuration-snapshot/1.0"
HOST_CONFIGURATION_MANIFEST_REF: Final = (
    "eom://schemas/knowledge/embedding-host-configuration-snapshot/1.0#/$defs/snapshot"
)
MAX_HOST_CONFIGURATION_BYTES = 8192
MAX_LOADER_CACHE_BYTES = 128 * 1024
type HostConfigurationId = Annotated[str, Field(pattern=r"^embeddinghostconfig_[0-9a-f]{32}$")]
type HostConfigurationRevisionId = Annotated[
    str, Field(pattern=r"^embeddinghostconfigrev_[0-9a-f]{32}$")
]


def _raw(value: object, depth: int = 0) -> Any:
    """Closed tiny object tree; inspect copied/constructed scalars before coercion."""
    if depth > 3:
        raise ValueError("host configuration exceeds its fixed object depth")
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        if len(fields) > 8 or value.__pydantic_extra__ or set(value.__dict__) != set(fields):
            raise ValueError("host configuration has extra or missing constructed fields")
        return {name: _raw(value.__dict__[name], depth + 1) for name in fields}
    if isinstance(value, dict):
        if len(value) > 8 or any(type(key) is not str for key in value):
            raise ValueError("host configuration keys or fixed object size differ")
        return {key: _raw(child, depth + 1) for key, child in value.items()}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("host configuration timestamps require UTC")
        return value.isoformat().replace("+00:00", "Z")
    if type(value) is str and len(value) <= 512:
        return value
    if type(value) is int:
        return value
    raise ValueError("host configuration requires exact string, integer or UTC fields")


class _HostConfigurationValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_root: ClassVar[bool] = False

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        raw = _raw(value)
        if (
            not isinstance(raw, dict)
            or len(canonical_json_bytes(raw)) > MAX_HOST_CONFIGURATION_BYTES
        ):
            raise ValueError("host configuration must be a bounded object")
        if cls.schema_root:
            validate_contract(HOST_CONFIGURATION_SCHEMA, raw)
        return raw


class EmbeddingLoaderCacheMember(_HostConfigurationValue):
    role: Literal["LD_SO_CACHE"]
    member_name: Literal["ld.so.cache"]
    byte_count: int = Field(ge=48, le=MAX_LOADER_CACHE_BYTES, strict=True)
    sha256: Sha256


class EmbeddingHostConfigurationSnapshot(_HostConfigurationValue):
    schema_root = True
    schema_version: Literal["embedding-host-configuration-snapshot/1.0"]
    configuration_id: HostConfigurationId
    configuration_revision_id: HostConfigurationRevisionId
    captured_at: UtcDatetime
    baseline_host_seed_sha256: Sha256
    host_seed_sha256: Sha256
    loader_cache: EmbeddingLoaderCacheMember
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def canonical_snapshot_hash(self) -> EmbeddingHostConfigurationSnapshot:
        if self.snapshot_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"snapshot_sha256"})
        ):
            raise ValueError("host configuration semantic hash differs")
        return self


class EmbeddingHostConfigurationPointer(_HostConfigurationValue):
    schema_root = True
    schema_ref: Literal[
        "eom://schemas/knowledge/embedding-host-configuration-snapshot/1.0#/$defs/snapshot"
    ]
    configuration_id: HostConfigurationId
    configuration_revision_id: HostConfigurationRevisionId
    manifest_byte_count: int = Field(ge=1, le=MAX_HOST_CONFIGURATION_BYTES, strict=True)
    manifest_raw_sha256: Sha256
    snapshot_sha256: Sha256


def parse_host_configuration_snapshot(value: object) -> EmbeddingHostConfigurationSnapshot:
    return EmbeddingHostConfigurationSnapshot.model_validate(value)


def parse_host_configuration_pointer(value: object) -> EmbeddingHostConfigurationPointer:
    return EmbeddingHostConfigurationPointer.model_validate(value)


def host_configuration_snapshot_bytes(value: EmbeddingHostConfigurationSnapshot) -> bytes:
    return canonical_json_bytes(parse_host_configuration_snapshot(value).model_dump(mode="json"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("host configuration JSON has duplicate keys")
        result[key] = value
    return result


def _invalid_number(_value: str) -> object:
    raise ValueError("host configuration JSON requires exact integer counts")


def parse_host_configuration_snapshot_bytes(raw: bytes) -> EmbeddingHostConfigurationSnapshot:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_HOST_CONFIGURATION_BYTES:
        raise ValueError("host configuration raw bytes exceed their fixed bound")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_float=_invalid_number,
            parse_constant=_invalid_number,
        )
    except (RecursionError, UnicodeError):
        raise ValueError("host configuration JSON is not a bounded valid object") from None
    snapshot = parse_host_configuration_snapshot(value)
    if raw != host_configuration_snapshot_bytes(snapshot):
        raise ValueError("host configuration manifest bytes must be canonical")
    return snapshot


def validate_host_configuration_pointer(
    pointer: EmbeddingHostConfigurationPointer,
    snapshot: EmbeddingHostConfigurationSnapshot,
    raw: bytes,
) -> EmbeddingHostConfigurationSnapshot:
    """Pure exact closure only; existence, namespace and admission remain owner checks."""
    pointer = parse_host_configuration_pointer(pointer)
    snapshot = parse_host_configuration_snapshot(snapshot)
    if (
        type(raw) is not bytes
        or raw != host_configuration_snapshot_bytes(snapshot)
        or pointer.configuration_id != snapshot.configuration_id
        or pointer.configuration_revision_id != snapshot.configuration_revision_id
        or pointer.manifest_byte_count != len(raw)
        or pointer.manifest_raw_sha256 != sha256_bytes(raw)
        or pointer.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("host configuration pointer/revision/raw/semantic closure differs")
    return snapshot

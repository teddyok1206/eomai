"""Closed non-secret runtime configuration; parsing never authenticates a service."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final, Literal

from eom_identifiers import canonical_json_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Registry, Resource

from eom_operator_identity.local_indexing_service import (
    LOCAL_INDEXING_SERVICE_SCHEMA_REF,
    LocalIndexingServiceReference,
    Sha256,
    local_indexing_service_bytes,
    local_indexing_service_schema,
)

LOCAL_INDEXING_RUNTIME_SCHEMA_REF: Final = "eom://schemas/identity/local-indexing-runtime/1.0"
MAX_LOCAL_INDEXING_RUNTIME_BYTES: Final = 4 * 1024
_RESOURCE: Final = "local-indexing-runtime-v1.schema.json"


class LocalIndexingRuntimeContractError(ValueError):
    """Content-free metadata failure, never runtime admission or a source grant."""


@lru_cache(maxsize=1)
def _schema_bytes() -> bytes:
    with files("eom_operator_identity").joinpath("resources", _RESOURCE).open("rb") as source:
        raw = source.read(16 * 1024 + 1)
    if not raw or len(raw) > 16 * 1024:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    return raw


def local_indexing_runtime_schema() -> dict[str, Any]:
    value: object = json.loads(_schema_bytes())
    if type(value) is not dict:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = local_indexing_runtime_schema()
    Draft202012Validator.check_schema(schema)
    registry: Registry[bool | Mapping[str, Any]] = Registry().with_resource(
        LOCAL_INDEXING_SERVICE_SCHEMA_REF, Resource.from_contents(local_indexing_service_schema())
    )
    # No remote registry or retrieval callback. Only the pinned local service family resolves.
    return Draft202012Validator(schema, registry=registry)


def _raw_values(value: object) -> dict[str, object]:
    names = LocalIndexingRuntimeConfiguration.model_fields
    if type(value) is LocalIndexingRuntimeConfiguration:
        if value.__pydantic_extra__ or set(value.__dict__) != set(names):
            raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
        values = {name: getattr(value, name) for name in names}
    elif type(value) is dict and len(value) == len(names) and set(value) == set(names):
        values = dict(value)
    else:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    for name, member in values.items():
        if name == "service":
            if type(member) is LocalIndexingServiceReference:
                values[name] = json.loads(local_indexing_service_bytes(member))
            elif type(member) is not dict or set(member) != {
                "service_id",
                "service_revision_id",
                "service_identity_sha256",
            }:
                raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
        elif type(member) is not str or len(member) > 128:
            raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    return values


class LocalIndexingRuntimeConfiguration(BaseModel):
    """Root-selected small metadata, NOT an authenticated runtime/capability."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    schema_version: Literal["local-indexing-runtime/1.0"]
    service: LocalIndexingServiceReference
    runtime_source_commit: str = Field(
        strict=True, pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40
    )
    platform_wheel_sha256: Sha256
    api_contracts_wheel_sha256: Sha256
    interpreter_sha256: Sha256
    unit_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, object]:
        values = _raw_values(value)
        try:
            _validator().validate(values)
        except SchemaError:
            raise LocalIndexingRuntimeContractError(
                "LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID"
            ) from None
        return values


def local_indexing_runtime_bytes(value: LocalIndexingRuntimeConfiguration) -> bytes:
    checked = LocalIndexingRuntimeConfiguration.model_validate(_raw_values(value))
    raw = canonical_json_bytes(_raw_values(checked))
    if len(raw) > MAX_LOCAL_INDEXING_RUNTIME_BYTES:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    return raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
        result[name] = value
    return result


def _reject_constant(_value: str) -> object:
    raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")


def parse_local_indexing_runtime_configuration(raw: bytes) -> LocalIndexingRuntimeConfiguration:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_RUNTIME_BYTES:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked = LocalIndexingRuntimeConfiguration.model_validate(value)
    except (UnicodeError, ValueError, RecursionError):
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID") from None
    if local_indexing_runtime_bytes(checked) != raw:
        raise LocalIndexingRuntimeContractError("LOCAL_INDEXING_RUNTIME_CONTRACT_INVALID")
    return checked

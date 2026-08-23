"""Package-owned JSON Schema registry for Codex execution control-plane contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


@dataclass(frozen=True)
class ControlSchemaResource:
    """Immutable identity for one installed control-plane schema resource."""

    canonical_path: str
    resource_path: str
    schema_version: str
    sha256: str


CONTROL_SCHEMA_RESOURCES: Mapping[str, ControlSchemaResource] = MappingProxyType(
    {
        "control-plane-types": ControlSchemaResource(
            "schemas/workflow/control-plane/control-plane-types-v1.schema.json",
            "resources/control-plane/control-plane-types-v1.schema.json",
            "1.0",
            "sha256:6132fb5243af979c1f7d77ee877dd24353f859a06962a439a6e3b9f386040f1f",
        ),
        "execution-preset-revision": ControlSchemaResource(
            "schemas/workflow/control-plane/execution-preset-revision-v1.schema.json",
            "resources/control-plane/execution-preset-revision-v1.schema.json",
            "1.0",
            "sha256:80db05c8001285e4a74b5d9554e60f0f3f95fb386350f3f0d2f1d42b7f43ca9b",
        ),
        "instruction-bundle-manifest": ControlSchemaResource(
            "schemas/workflow/control-plane/instruction-bundle-manifest-v1.schema.json",
            "resources/control-plane/instruction-bundle-manifest-v1.schema.json",
            "1.0",
            "sha256:27f7e9bdb6550d95307b35c6887f0b8b227776c3f75ed9f77987bcef9a5470cf",
        ),
        "reference-bundle-manifest": ControlSchemaResource(
            "schemas/workflow/control-plane/reference-bundle-manifest-v1.schema.json",
            "resources/control-plane/reference-bundle-manifest-v1.schema.json",
            "1.0",
            "sha256:2445460316c928661655e250af078533ef46805b73ef4b20bb7415b88be98bfd",
        ),
        "resolved-execution-plan": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v1.schema.json",
            "resources/control-plane/resolved-execution-plan-v1.schema.json",
            "1.0",
            "sha256:9540b950402bf28eaba6d7a489227c5d90dce20d125c9489203cbc4a6d0e9d6d",
        ),
        "codex-auth-health-view": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-health-view-v1.schema.json",
            "resources/control-plane/codex-auth-health-view-v1.schema.json",
            "1.0",
            "sha256:406330f2e44da43f9f559183c2204a2c7ba50796531bfc7886f9c1d1dfaf613c",
        ),
        "codex-capability-snapshot": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-capability-snapshot-v1.schema.json",
            "resources/control-plane/codex-capability-snapshot-v1.schema.json",
            "1.0",
            "sha256:b6f5c1496f5d8cfbf38ef423aec64bf872f652d425b5de68af76356401f1cb77",
        ),
        "worker-capacity-policy": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-capacity-policy-v1.schema.json",
            "resources/control-plane/worker-capacity-policy-v1.schema.json",
            "1.0",
            "sha256:c412da0b7ee04a1c90b03db71ad5092577cb22a201ba246ea078242c022abc11",
        ),
        "worker-lease-view": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-lease-view-v1.schema.json",
            "resources/control-plane/worker-lease-view-v1.schema.json",
            "1.0",
            "sha256:b7a85bd9833b6ce29b238dc1f68a4fd63efa11ed1917f470d58cbbdaa82975f7",
        ),
    }
)

_RESOURCE_ROOT = resources.files("eom_workflow").joinpath("resources")


class ControlSchemaError(ValueError):
    """Raised when an installed control-plane contract is unavailable or malformed."""


def _distribution_version() -> str:
    try:
        return metadata.version("eom-platform")
    except metadata.PackageNotFoundError:
        return "source"


def _resource_error(name: str, reason: str) -> ControlSchemaError:
    return ControlSchemaError(
        f"control-plane schema resource unavailable: {name} ({reason}; "
        f"package=eom_workflow, distribution=eom-platform@{_distribution_version()})"
    )


def _schema_resource(name: str) -> tuple[ControlSchemaResource, Traversable]:
    try:
        entry = CONTROL_SCHEMA_RESOURCES[name]
    except KeyError as exc:
        raise ControlSchemaError(f"unknown control-plane contract schema: {name}") from exc
    parts = entry.resource_path.split("/")
    if parts[:2] != ["resources", "control-plane"] or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise ControlSchemaError(f"control-plane schema resource path is unsafe: {name}")
    resource: Traversable = _RESOURCE_ROOT
    for part in parts[1:]:
        resource = resource.joinpath(part)
    return entry, resource


@lru_cache(maxsize=len(CONTROL_SCHEMA_RESOURCES))
def load_control_schema(name: str) -> dict[str, Any]:
    entry, resource = _schema_resource(name)
    try:
        raw = resource.read_bytes()
    except OSError as exc:
        raise _resource_error(name, "package resource is missing or unreadable") from exc
    if "sha256:" + hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise _resource_error(name, "package resource hash mismatch")
    try:
        value: object = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ControlSchemaError(f"control-plane schema is not an object: {name}")
        Draft202012Validator.check_schema(value)
    except (UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        raise _resource_error(name, "package resource is malformed") from exc
    return value


def control_schema_inventory() -> tuple[tuple[str, ControlSchemaResource], ...]:
    """Return the deterministic installed control-plane schema inventory."""

    return tuple(sorted(CONTROL_SCHEMA_RESOURCES.items()))


@lru_cache(maxsize=1)
def _control_schema_registry() -> Registry[Any]:
    installed: list[tuple[str, Resource[Any]]] = []
    for name in CONTROL_SCHEMA_RESOURCES:
        schema = load_control_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise _resource_error(name, "schema identifier is missing")
        installed.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(installed)


def validate_control_contract(name: str, value: object) -> None:
    """Validate a value against a closed installed JSON Schema 2020-12 contract."""

    Draft202012Validator(
        load_control_schema(name),
        format_checker=FormatChecker(),
        registry=_control_schema_registry(),
    ).validate(value)

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
        "execution-preset-revision-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/execution-preset-revision-v2.schema.json",
            "resources/control-plane/execution-preset-revision-v2.schema.json",
            "2.0",
            "sha256:a05ed05270b170fb1e1207c6c4709df81f7ac436a2142489a40d140fdf6d72ea",
        ),
        "knowledge-item-control-bootstrap": ControlSchemaResource(
            "schemas/workflow/control-plane/knowledge-item-control-bootstrap-v1.schema.json",
            "resources/control-plane/knowledge-item-control-bootstrap-v1.schema.json",
            "1.0",
            "sha256:0b7d102659015fbbfdad0b81ecd0a0857198ca5d353758e4ca5382f3a583f4a4",
        ),
        "legacy-item-extraction-control-bootstrap": ControlSchemaResource(
            "schemas/workflow/control-plane/legacy-item-extraction-control-bootstrap-v1.schema.json",
            "resources/control-plane/legacy-item-extraction-control-bootstrap-v1.schema.json",
            "1.0",
            "sha256:487d26ccd825de39737f202cfa336896ecfdb0bbec128cc274cd72c35dc60dbb",
        ),
        "standard-control-bootstrap-v3": ControlSchemaResource(
            "schemas/workflow/control-plane/standard-control-bootstrap-v3.schema.json",
            "resources/control-plane/standard-control-bootstrap-v3.schema.json",
            "3.0",
            "sha256:cb83aa2124fc1116f55b08daa080ade2ff849c6623d78632c0db64f57732fd68",
        ),
        "standard-control-bootstrap-v4": ControlSchemaResource(
            "schemas/workflow/control-plane/standard-control-bootstrap-v4.schema.json",
            "resources/control-plane/standard-control-bootstrap-v4.schema.json",
            "4.0",
            "sha256:45d327d0e5f03f8d26d479d46feffd5e6dccbdb6f4dfd33cf9a2e576a81fdb4d",
        ),
        "standard-control-bootstrap-v5": ControlSchemaResource(
            "schemas/workflow/control-plane/standard-control-bootstrap-v5.schema.json",
            "resources/control-plane/standard-control-bootstrap-v5.schema.json",
            "5.0",
            "sha256:c6841eadcc68fa11f2191b8777400b48c15556489bb31c30628116d3b672ff4e",
        ),
        "standard-control-bootstrap-v6": ControlSchemaResource(
            "schemas/workflow/control-plane/standard-control-bootstrap-v6.schema.json",
            "resources/control-plane/standard-control-bootstrap-v6.schema.json",
            "6.0",
            "sha256:d76a82760b67dcb99ccc96870c163ba6c6ad48e9883e1f58a83c50a022753b34",
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
        "resolved-execution-plan-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v2.schema.json",
            "resources/control-plane/resolved-execution-plan-v2.schema.json",
            "2.0",
            "sha256:70a000d38ef80ecf78765744673655b9e261b51ed17dfa6ec189ef277245364e",
        ),
        "resolved-execution-plan-v3": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v3.schema.json",
            "resources/control-plane/resolved-execution-plan-v3.schema.json",
            "3.0",
            "sha256:6cd0700e97c595cb52f9fea40df3f530f11e333a69d167a0b4fc9d2e45767d9b",
        ),
        "resolved-execution-plan-v4": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v4.schema.json",
            "resources/control-plane/resolved-execution-plan-v4.schema.json",
            "4.0",
            "sha256:3ea326016ebba09cd221b0108cb9cd70262ae6e447e484357234b14109529220",
        ),
        "resolved-execution-plan-v5": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v5.schema.json",
            "resources/control-plane/resolved-execution-plan-v5.schema.json",
            "5.0",
            "sha256:78e648052b9837a2ae5ae9d0d99b910f559c7188f274485b56f7c667ae8b7a7f",
        ),
        "resolved-execution-plan-v6": ControlSchemaResource(
            "schemas/workflow/control-plane/resolved-execution-plan-v6.schema.json",
            "resources/control-plane/resolved-execution-plan-v6.schema.json",
            "6.0",
            "sha256:89a1b022d15e0d62fd5716a40119cb6dd2f15fd36daddc2ffbd80eec231db308",
        ),
        "codex-invocation": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-invocation-v1.schema.json",
            "resources/control-plane/codex-invocation-v1.schema.json",
            "1.0",
            "sha256:639f448062f265d4bfe82af6e02237891109827071f701b8825bc556a4b0b7eb",
        ),
        "codex-image-input-manifest": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-image-input-manifest-v1.schema.json",
            "resources/control-plane/codex-image-input-manifest-v1.schema.json",
            "1.0",
            "sha256:40ce920b7e5719b9d0cc56c3034a5e8f24d43e2d5a73e797f294d98be7dcb9dc",
        ),
        "codex-image-input-manifest-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-image-input-manifest-v2.schema.json",
            "resources/control-plane/codex-image-input-manifest-v2.schema.json",
            "2.0",
            "sha256:b11c648682f67884f23c38d76348accfd657a62d5b1cb220405b8580cc3d53c7",
        ),
        "codex-auth-health-view": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-health-view-v1.schema.json",
            "resources/control-plane/codex-auth-health-view-v1.schema.json",
            "1.0",
            "sha256:406330f2e44da43f9f559183c2204a2c7ba50796531bfc7886f9c1d1dfaf613c",
        ),
        "codex-auth-enrollment-request": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-enrollment-request-v1.schema.json",
            "resources/control-plane/codex-auth-enrollment-request-v1.schema.json",
            "1.0",
            "sha256:4cc5734efd39d06c06b79f2585811672687629fedbadb51833bae66d97ad3f6e",
        ),
        "codex-auth-enrollment-request-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-enrollment-request-v2.schema.json",
            "resources/control-plane/codex-auth-enrollment-request-v2.schema.json",
            "1.1",
            "sha256:7722fba51d97abe6f74d2a2143ed8931ecc55426e487e5dfbc51b26fb685305b",
        ),
        "codex-auth-enrollment-status": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-enrollment-status-v1.schema.json",
            "resources/control-plane/codex-auth-enrollment-status-v1.schema.json",
            "1.0",
            "sha256:ad4a3e527f547280235d28c80582939533b4409c54f9ed0b58e042961e0055cd",
        ),
        "codex-auth-enrollment-status-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-enrollment-status-v2.schema.json",
            "resources/control-plane/codex-auth-enrollment-status-v2.schema.json",
            "1.1",
            "sha256:90e509651f5440dff9008719b1ea490b45a227da5358d81d8832592c05b3939f",
        ),
        "codex-device-challenge": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-device-challenge-v1.schema.json",
            "resources/control-plane/codex-device-challenge-v1.schema.json",
            "1.0",
            "sha256:d9ef194d5832b4a61fc9ed44f6a7a7faeeea510b5e0bbe4ccbe6825df977ab72",
        ),
        "codex-device-challenge-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-device-challenge-v2.schema.json",
            "resources/control-plane/codex-device-challenge-v2.schema.json",
            "1.1",
            "sha256:ad5839177c86cb98d1e4d07524a7069d7cebf329c6631a84b2ea82ea99ee7367",
        ),
        "codex-device-login-status": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-device-login-status-v1.schema.json",
            "resources/control-plane/codex-device-login-status-v1.schema.json",
            "1.0",
            "sha256:9c0a4893930c7a3355e92a08c1e4b0aee25f216783abb0c6b9fca57d112b3abe",
        ),
        "codex-device-login-status-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-device-login-status-v2.schema.json",
            "resources/control-plane/codex-device-login-status-v2.schema.json",
            "1.1",
            "sha256:f990f7fa5042cf963c1a355c16e57e4d755ef852818fda9b7527097088bb794a",
        ),
        "codex-auth-broker-request": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-broker-request-v1.schema.json",
            "resources/control-plane/codex-auth-broker-request-v1.schema.json",
            "1.0",
            "sha256:59e05f2f7c8e4f6a32909459ca369b6f070ddb1b786a78746a22a086549df492",
        ),
        "codex-auth-broker-request-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-broker-request-v2.schema.json",
            "resources/control-plane/codex-auth-broker-request-v2.schema.json",
            "1.1",
            "sha256:324f395ab714578615a05cc4c7ae536c50c6e5c5b7dddb753caf8468b4f99768",
        ),
        "codex-auth-broker-response": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-broker-response-v1.schema.json",
            "resources/control-plane/codex-auth-broker-response-v1.schema.json",
            "1.0",
            "sha256:46a6e4bae0b5011accf1b1a8a3ae5c21edd99a04ac49bea86b1ef3d51caf3d20",
        ),
        "codex-auth-broker-response-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-auth-broker-response-v2.schema.json",
            "resources/control-plane/codex-auth-broker-response-v2.schema.json",
            "1.1",
            "sha256:c3d67e6006962f6edb6ddf9ac2ecfd1102b3c1c6758c190907bc5c97d088312e",
        ),
        "codex-control-command": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-control-command-v1.schema.json",
            "resources/control-plane/codex-control-command-v1.schema.json",
            "1.0",
            "sha256:76f21384e8c15169d1a8329a717e4bc9b4a73d37004816c22511b27b5a8ce32e",
        ),
        "codex-control-command-result": ControlSchemaResource(
            "schemas/workflow/control-plane/codex-control-command-result-v1.schema.json",
            "resources/control-plane/codex-control-command-result-v1.schema.json",
            "1.0",
            "sha256:d6576027af477c9cfc9c96a578810d31731b3bc8196a430cfc8fccdf28ef76ee",
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
        "worker-capacity-policy-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-capacity-policy-v2.schema.json",
            "resources/control-plane/worker-capacity-policy-v2.schema.json",
            "1.1",
            "sha256:c58e43df5add41e956d13cba9207b4e43a919a9d78c32e7b7da8f85218c465a7",
        ),
        "worker-capacity-policy-v3": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-capacity-policy-v3.schema.json",
            "resources/control-plane/worker-capacity-policy-v3.schema.json",
            "1.2",
            "sha256:83d8c3f258b0aa5b660c7dd75dda3b486e36564d4736767ca01c7a62cf9ee439",
        ),
        "worker-slot-inventory-v2": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-slot-inventory-v2.schema.json",
            "resources/control-plane/worker-slot-inventory-v2.schema.json",
            "2.0",
            "sha256:48bdd2c0007d324fb99702e31172379d69e7c3de6fe1a27dfb2f734c482507f2",
        ),
        "worker-lease-view": ControlSchemaResource(
            "schemas/workflow/control-plane/worker-lease-view-v1.schema.json",
            "resources/control-plane/worker-lease-view-v1.schema.json",
            "1.0",
            "sha256:b7a85bd9833b6ce29b238dc1f68a4fd63efa11ed1917f470d58cbbdaa82975f7",
        ),
        "execution-preset-evaluation-report": ControlSchemaResource(
            "schemas/workflow/control-plane/execution-preset-evaluation-report-v1.schema.json",
            "resources/control-plane/execution-preset-evaluation-report-v1.schema.json",
            "1.0",
            "sha256:0f02de7729ab8c87ea4152144c60fe3167920811f90f7678f50655ac66eca8d3",
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
    # V4 plans reuse the Catalog-owned document-source definition instead of duplicating it.
    from eom_catalog_contracts import load_schema

    for name in (
        "knowledge-types",
        "knowledge-analysis-types-v2",
        "knowledge-analysis-types-v3",
        "knowledge-analysis-types-v4",
        "item-origin-types",
        "legacy-assessment-types",
        "legacy-item-extraction-request",
    ):
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise _resource_error(name, "Catalog schema identifier is missing")
        installed.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(installed)


def validate_control_contract(name: str, value: object) -> None:
    """Validate a value against a closed installed JSON Schema 2020-12 contract."""

    Draft202012Validator(
        load_control_schema(name),
        format_checker=FormatChecker(),
        registry=_control_schema_registry(),
    ).validate(value)

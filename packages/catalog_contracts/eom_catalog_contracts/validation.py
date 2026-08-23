"""JSON Schema 2020-12 validation backed by package-owned resources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


@dataclass(frozen=True)
class CatalogSchemaResource:
    """Immutable identity for one runtime Catalog Contract schema."""

    canonical_path: str
    resource_path: str
    schema_version: str
    sha256: str


CATALOG_SCHEMA_RESOURCES: Mapping[str, CatalogSchemaResource] = MappingProxyType(
    {
        "intake-manifest": CatalogSchemaResource(
            "schemas/content-intake/intake-manifest-v1.schema.json",
            "resources/content-intake/intake-manifest-v1.schema.json",
            "1.0",
            "sha256:5f3b9dcd459988143491557ccf5f220a53c0467d461235ba22de587d0c8b63f0",
        ),
        "mapping-proposal": CatalogSchemaResource(
            "schemas/content-intake/mapping-proposal-v1.schema.json",
            "resources/content-intake/mapping-proposal-v1.schema.json",
            "1.0",
            "sha256:4e2699ca42b8fe0c4ecb0993ce4119110cbebf273eecb135d57414c7e1e40a83",
        ),
        "uncertainties": CatalogSchemaResource(
            "schemas/content-intake/uncertainties-v1.schema.json",
            "resources/content-intake/uncertainties-v1.schema.json",
            "1.0",
            "sha256:6cbe845ff766076ce64d76c7c9483f164a454fac92f8e5ba6dc374c89d79bebf",
        ),
        "human-decision": CatalogSchemaResource(
            "schemas/content-intake/human-decision-v1.schema.json",
            "resources/content-intake/human-decision-v1.schema.json",
            "1.0",
            "sha256:7d8c6f988229f0f6036d586716b228f1c1082ead7bccf02dc2ba66d25f2f8f26",
        ),
        "content-pack": CatalogSchemaResource(
            "schemas/content-pack/content-pack-v1.schema.json",
            "resources/content-pack/content-pack-v1.schema.json",
            "1.0",
            "sha256:8d121d187885a9c1c2b588493d9d7337856614db6d5011306d63b16a9219fb8b",
        ),
        "content-pack-v2": CatalogSchemaResource(
            "schemas/content-pack/content-pack-v2.schema.json",
            "resources/content-pack/content-pack-v2.schema.json",
            "1.1",
            "sha256:c2f7e5456ac15eaa2526a33ba9de8bef81e9640925a05b1531e9abf80744a664",
        ),
        "content-pack-profile": CatalogSchemaResource(
            "schemas/content-pack/profile-v1.schema.json",
            "resources/content-pack/profile-v1.schema.json",
            "1.0",
            "sha256:d8af117b56737b3e9355284665be0d4775f39f6a9230974255c540725f44fcfb",
        ),
        "prompt-envelope": CatalogSchemaResource(
            "schemas/content-pack/prompt-envelope-v1.schema.json",
            "resources/content-pack/prompt-envelope-v1.schema.json",
            "1.0",
            "sha256:ac60d0750780f5b13149e40163823f39773376322bf4f7b7173bb2c9282210dc",
        ),
        "item-revision-manifest": CatalogSchemaResource(
            "schemas/item-registry/item-revision-manifest-v1.schema.json",
            "resources/item-registry/item-revision-manifest-v1.schema.json",
            "1.0",
            "sha256:9c6be99f5331d72fa43d3112f37bda45c0337829d44e8f91a05e145030a2c399",
        ),
        "assessment-item-content": CatalogSchemaResource(
            "schemas/item-registry/assessment-item-content-v1.schema.json",
            "resources/item-registry/assessment-item-content-v1.schema.json",
            "1.0",
            "sha256:ca0d360c209d26cce7e9283d42509204ccd8e50f519a85be871a2bbfc625a4bd",
        ),
        "catalog-application-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v1.schema.json",
            "resources/catalog-application/catalog-application-request-v1.schema.json",
            "1.0",
            "sha256:ab395b09afc99bbee7a25b0c15d9f8f63eb22b73b2a5e62586f0f8d80f8d3855",
        ),
        "catalog-application-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v1.schema.json",
            "resources/catalog-application/catalog-application-response-v1.schema.json",
            "1.0",
            "sha256:ad549c7b25c1e620e7cf54fa46cb4891f322d69f65bd5c5104bf9e50f4582ff8",
        ),
        "knowledge-types": CatalogSchemaResource(
            "schemas/knowledge/knowledge-types-v1.schema.json",
            "resources/knowledge/knowledge-types-v1.schema.json",
            "1.0",
            "sha256:d1d0e842b75a263470ef7403f3117a3c23f52f3c5f5f181477f0f2b422312456",
        ),
        "knowledge-analysis-request": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v1.schema.json",
            "resources/knowledge/knowledge-analysis-request-v1.schema.json",
            "1.0",
            "sha256:1e4b982fc6bd91448ce014e4b7160a5bfd5008b1985e7318e1e102e29b4ce233",
        ),
        "knowledge-analysis-result": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v1.schema.json",
            "resources/knowledge/knowledge-analysis-result-v1.schema.json",
            "1.0",
            "sha256:fc496fe1f9d8b663b33677e24cf0e2158b0f20bb815f69dfd9551a625820c3f3",
        ),
        "knowledge-graph-snapshot-manifest": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
            "1.0",
            "sha256:daaf1dffca162018bead549399927e6429a7dac34775fb969c675207d9920f9a",
        ),
        "education-retrieval-request": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-request-v1.schema.json",
            "resources/knowledge/education-retrieval-request-v1.schema.json",
            "1.0",
            "sha256:92bb7b8aa224a00eb7c2eb6f95d4c94465d8ccc19e4be2de010fc0512a800043",
        ),
        "evidence-bundle-manifest": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v1.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v1.schema.json",
            "1.0",
            "sha256:5a575aa08788eb5a4ec6961c214872b4e6ed103fa0c9db78edcf47b791d9539e",
        ),
    }
)

_RESOURCE_ROOT = files("eom_catalog_contracts").joinpath("resources")


class CatalogSchemaError(ValueError):
    """Raised when a Catalog Contract schema is unknown, missing, or invalid."""


def _distribution_version() -> str:
    try:
        return metadata.version("eom-platform")
    except metadata.PackageNotFoundError:
        return "source"


def _resource_error(name: str, reason: str) -> CatalogSchemaError:
    return CatalogSchemaError(
        f"catalog schema resource unavailable: {name} ({reason}; "
        f"package=eom_catalog_contracts, distribution=eom-platform@{_distribution_version()})"
    )


def _schema_resource(name: str) -> tuple[CatalogSchemaResource, Traversable]:
    try:
        entry = CATALOG_SCHEMA_RESOURCES[name]
    except KeyError as exc:
        raise CatalogSchemaError(f"unknown catalog contract schema: {name}") from exc
    parts = entry.resource_path.split("/")
    if parts[0] != "resources" or any(part in {"", ".", ".."} for part in parts):
        raise CatalogSchemaError(f"catalog schema resource path is unsafe: {name}")
    resource: Traversable = _RESOURCE_ROOT
    for part in parts[1:]:
        resource = resource.joinpath(part)
    return entry, resource


@lru_cache(maxsize=len(CATALOG_SCHEMA_RESOURCES))
def load_schema(name: str) -> dict[str, Any]:
    entry, resource = _schema_resource(name)
    try:
        raw = resource.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise _resource_error(name, "package resource is missing or unreadable") from exc
    actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_hash != entry.sha256:
        raise _resource_error(name, "package resource hash mismatch")
    try:
        value: object = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise CatalogSchemaError(f"catalog schema is not an object: {name}")
        Draft202012Validator.check_schema(value)
    except (UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        raise _resource_error(name, "package resource is malformed") from exc
    return value


def catalog_schema_inventory() -> tuple[tuple[str, CatalogSchemaResource], ...]:
    """Return the deterministic logical schema inventory for release checks."""

    return tuple(sorted(CATALOG_SCHEMA_RESOURCES.items()))


@lru_cache(maxsize=1)
def _catalog_schema_registry() -> Registry[Any]:
    resources: list[tuple[str, Resource[Any]]] = []
    for name in CATALOG_SCHEMA_RESOURCES:
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise _resource_error(name, "schema identifier is missing")
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(
        load_schema(name),
        format_checker=FormatChecker(),
        registry=_catalog_schema_registry(),
    ).validate(value)

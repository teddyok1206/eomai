"""Independent JSON Schema 2020-12 validation for API responses."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = REPOSITORY_ROOT / "schemas" / "observe"

SCHEMA_FILES = {
    "health": "observe-health.schema.json",
    "snapshot": "observe-snapshot.schema.json",
    "node": "observe-node.schema.json",
    "edge": "observe-edge.schema.json",
    "event": "observe-event.schema.json",
    "workflow-detail": "observe-workflow-detail.schema.json",
    "job-detail": "observe-job-detail.schema.json",
    "artifact-detail": "observe-artifact-detail.schema.json",
}


@lru_cache(maxsize=1)
def _schemas() -> tuple[dict[str, dict[str, Any]], Registry[Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    registry: Registry[Any] = Registry()
    for name, filename in SCHEMA_FILES.items():
        schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        loaded[name] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return loaded, registry


def validate_contract(name: str, value: dict[str, Any]) -> None:
    schemas, registry = _schemas()
    try:
        schema = schemas[name]
    except KeyError as exc:
        raise ValueError(f"unknown observability contract: {name}") from exc
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(value)

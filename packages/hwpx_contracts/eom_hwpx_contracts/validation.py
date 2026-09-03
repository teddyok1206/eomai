"""JSON Schema 2020-12 validation backed by wheel resources."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "content-team-editorial-question": "hwpx-content-team-editorial-question-v1.schema.json",
    "item-document": "hwpx-item-document-v1.schema.json",
    "build-result": "hwpx-build-result-v1.schema.json",
    "kordoc-render-request": "hwpx-kordoc-render-request-v1.schema.json",
    "kordoc-build-result": "hwpx-kordoc-build-result-v1.schema.json",
    "manager-download": "hwpx-manager-download-v1.schema.json",
}


@lru_cache(maxsize=len(SCHEMA_FILES))
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown HWPX contract: {name}") from exc
    resource = files("eom_hwpx_contracts").joinpath("schemas", filename)
    value: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any], *, definition: str | None = None) -> None:
    schema = load_schema(name)
    if definition is not None:
        definitions = schema.get("$defs", {})
        if not isinstance(definitions, dict) or definition not in definitions:
            raise ValueError(f"unknown HWPX contract definition: {name}:{definition}")
        schema = definitions[definition]
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)

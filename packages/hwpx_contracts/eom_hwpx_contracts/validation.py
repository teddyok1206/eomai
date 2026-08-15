"""JSON Schema 2020-12 validation backed by wheel resources."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "item-document": "hwpx-item-document-v1.schema.json",
    "build-result": "hwpx-build-result-v1.schema.json",
}


@lru_cache(maxsize=2)
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown HWPX contract: {name}") from exc
    resource = files("eom_hwpx_contracts").joinpath("schemas", filename)
    value: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(load_schema(name), format_checker=FormatChecker()).validate(value)

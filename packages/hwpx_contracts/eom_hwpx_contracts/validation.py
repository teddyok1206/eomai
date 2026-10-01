"""JSON Schema 2020-12 validation backed by wheel resources."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "content-team-editorial-question": "hwpx-content-team-editorial-question-v1.schema.json",
    "content-team-editorial-question-v2": "hwpx-content-team-editorial-question-v2.schema.json",
    "content-team-render-request": "hwpx-content-team-render-request-v1.schema.json",
    "content-team-build-result": "hwpx-content-team-build-result-v1.schema.json",
    "content-team-render-request-v2": "hwpx-content-team-render-request-v2.schema.json",
    "content-team-build-result-v2": "hwpx-content-team-build-result-v2.schema.json",
    "content-team-render-request-v3": "hwpx-content-team-render-request-v3.schema.json",
    "content-team-build-result-v3": "hwpx-content-team-build-result-v3.schema.json",
    "content-team-exam-render-request": "hwpx-content-team-exam-render-request-v1.schema.json",
    "content-team-exam-build-result": "hwpx-content-team-exam-build-result-v1.schema.json",
    "content-team-exam-render-request-v2": "hwpx-content-team-exam-render-request-v2.schema.json",
    "content-team-exam-build-result-v2": "hwpx-content-team-exam-build-result-v2.schema.json",
    "content-team-exam-render-request-v3": "hwpx-content-team-exam-render-request-v3.schema.json",
    "content-team-exam-build-result-v3": "hwpx-content-team-exam-build-result-v3.schema.json",
    "content-team-output-acceptance-v1": ("hwpx-content-team-output-acceptance-v1.schema.json"),
    "item-document": "hwpx-item-document-v1.schema.json",
    "build-result": "hwpx-build-result-v1.schema.json",
    "render-request": "hwpx-render-request-v1.schema.json",
    "template-binding-manifest": "hwpx-template-binding-manifest-v1.schema.json",
    "kordoc-render-request": "hwpx-kordoc-render-request-v1.schema.json",
    "kordoc-build-result": "hwpx-kordoc-build-result-v1.schema.json",
    "kordoc-bridge-report": "hwpx-kordoc-bridge-report-v1.schema.json",
    "manager-download": "hwpx-manager-download-v1.schema.json",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


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


def parse_contract_json(
    name: str,
    payload: bytes | str,
    *,
    definition: str | None = None,
) -> dict[str, Any]:
    """Parse one untrusted JSON object once, rejecting duplicate keys before validation."""

    value: Any = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("HWPX contract payload must be a JSON object")
    validate_contract(name, value, definition=definition)
    return value

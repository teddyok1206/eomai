#!/usr/bin/env python3
"""Generate additive selected-material authority mock-exam plan and execution schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eom_api_contracts import MockExamProductionExecutionV5
from eom_catalog_contracts import MockExamProductionPlanV5
from jsonschema import Draft202012Validator
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


def _close(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties)
        for child in value.values():
            _close(child)
    elif isinstance(value, list):
        for child in value:
            _close(child)


def _schema(model: type[BaseModel], schema_id: str) -> dict[str, Any]:
    value: dict[str, Any] = model.model_json_schema(mode="validation")
    value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    value["$id"] = schema_id
    _close(value)
    return value


def _strict_api_sha256_patterns(value: object) -> None:
    if isinstance(value, dict):
        if value.get("pattern") == r"^(?:sha256:)?[0-9a-f]{64}$":
            value["pattern"] = r"^sha256:[0-9a-f]{64}$"
        for child in value.values():
            _strict_api_sha256_patterns(child)
    elif isinstance(value, list):
        for child in value:
            _strict_api_sha256_patterns(child)


def _payload(schema: dict[str, Any]) -> bytes:
    Draft202012Validator.check_schema(schema)
    return (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write(schema: dict[str, Any], *destinations: Path) -> None:
    payload = _payload(schema)
    for destination in destinations:
        destination.write_bytes(payload)


def main() -> None:
    plan = _schema(
        MockExamProductionPlanV5,
        "eom://schemas/assessment-assembly/mock-exam-production-plan/5.0",
    )
    _write(
        plan,
        ROOT / "schemas/assessment-assembly/mock-exam-production-plan-v5.schema.json",
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
        "mock-exam-production-plan-v5.schema.json",
    )

    execution = _schema(
        MockExamProductionExecutionV5,
        "https://eom.local/schemas/api/v1/mock-exam-production-execution-v5.schema.json",
    )
    _strict_api_sha256_patterns(execution)
    _write(
        execution,
        ROOT / "schemas/api/v1/mock-exam-production-execution-v5.schema.json",
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/"
        "mock-exam-production-execution-v5.schema.json",
    )


if __name__ == "__main__":
    main()

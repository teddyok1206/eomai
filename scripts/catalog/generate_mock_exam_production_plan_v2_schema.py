#!/usr/bin/env python3
"""Generate the additive mock-exam production-plan V2 schema mirrors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eom_catalog_contracts import MockExamProductionPlanV2
from jsonschema import Draft202012Validator

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


def main() -> None:
    schema: dict[str, Any] = MockExamProductionPlanV2.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "eom://schemas/assessment-assembly/mock-exam-production-plan/2.0"
    _close(schema)
    schema["$defs"]["mock_exam_slot"] = {"$ref": "#/$defs/ContentTeamMockExamSlotV1"}
    Draft202012Validator.check_schema(schema)
    payload = (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    for destination in (
        ROOT / "schemas/assessment-assembly/mock-exam-production-plan-v2.schema.json",
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
        / "mock-exam-production-plan-v2.schema.json",
    ):
        destination.write_bytes(payload)


if __name__ == "__main__":
    main()

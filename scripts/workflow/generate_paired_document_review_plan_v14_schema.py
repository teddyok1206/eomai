#!/usr/bin/env python3
"""Generate the exact paired-document resolved execution plan V14 schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v13.schema.json"
TARGETS = (
    ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v14.schema.json",
    ROOT
    / (
        "packages/workflow/eom_workflow/resources/control-plane/"
        "resolved-execution-plan-v14.schema.json"
    ),
)


def schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(json.loads(SOURCE.read_text(encoding="utf-8")))
    value["$id"] = "eom://schemas/workflow/resolved-execution-plan/14.0"
    value["title"] = "EOM Paired Document Review Resolved Execution Plan V14"
    value["required"].remove("document")
    value["required"].insert(value["required"].index("capacity_policy_revision_id"), "documents")
    value["properties"].pop("document")
    value["properties"]["schema_version"] = {"const": "resolved-execution-plan/14.0"}
    value["properties"]["resolver_version"] = {"const": "14.0.0"}
    value["properties"]["documents"] = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "prefixItems": [
            {
                "allOf": [
                    {"$ref": "#/$defs/review_document"},
                    {"properties": {"role": {"const": "QUESTION"}}},
                ]
            },
            {
                "allOf": [
                    {"$ref": "#/$defs/review_document"},
                    {"properties": {"role": {"const": "SOLUTION"}}},
                ]
            },
        ],
        "items": False,
    }
    page = value["$defs"]["page"]
    page["properties"]["page_number"]["maximum"] = 64
    document = value["$defs"]["document"]
    document["properties"]["page_count"]["maximum"] = 64
    document["properties"]["pages"]["maxItems"] = 64
    value["$defs"]["review_document"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["role", "document"],
        "properties": {
            "role": {"enum": ["QUESTION", "SOLUTION"]},
            "document": {"$ref": "#/$defs/document"},
        },
    }
    return value


def main() -> None:
    payload = json.dumps(schema(), ensure_ascii=False, indent=2) + "\n"
    for target in TARGETS:
        target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

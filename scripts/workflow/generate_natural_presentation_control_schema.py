#!/usr/bin/env python3
"""Generate the immutable execution-plan V17 schema for natural presentation."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v16.schema.json"
TARGETS = (
    ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v17.schema.json",
    ROOT / "packages/workflow/eom_workflow/resources/control-plane/"
    "resolved-execution-plan-v17.schema.json",
)


def main() -> None:
    schema = json.loads(SOURCE.read_text(encoding="utf-8"))
    schema["$id"] = "eom://schemas/workflow/resolved-execution-plan/17.0"
    schema["properties"]["schema_version"]["const"] = "resolved-execution-plan/17.0"
    schema["properties"]["workflow_definition_version"]["const"] = "1.15.0"
    schema["properties"]["resolver_version"]["const"] = "17.0.0"
    schema["properties"]["retrieval_requirement"] = {
        "oneOf": [
            {"$ref": "eom://schemas/knowledge/educational-retrieval-requirement/1.0"},
            {"$ref": "eom://schemas/knowledge/educational-retrieval-requirement/2.0"},
        ]
    }
    payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for target in TARGETS:
        target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

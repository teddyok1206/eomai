#!/usr/bin/env python3
"""Generate the additive workflow-start V3 contract for review protocol 1.24."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/api/v1"
PACKAGED = ROOT / "packages/api_contracts/eom_api_contracts/schemas"
NAME = "workflow-start-v3.schema.json"


def _schema() -> dict[str, object]:
    value = json.loads((CANONICAL / "workflow-start-v2.schema.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("workflow-start V2 schema is not an object")
    successor = deepcopy(value)
    successor["$id"] = "eom://schemas/api/v1/workflow-start/3.0"
    successor["title"] = "Workflow Start Request V3"
    successor["oneOf"] = [
        {"$ref": "eom://schemas/api/v1/workflow-start/2.0"},
        {"$ref": "#/$defs/content_team_v4_start"},
    ]
    definitions = successor["$defs"]
    assert isinstance(definitions, dict)
    content_start = definitions["content_team_v4_start"]
    assert isinstance(content_start, dict)
    properties = content_start["properties"]
    assert isinstance(properties, dict)
    definition_version = properties["definition_version"]
    assert isinstance(definition_version, dict)
    definition_version.clear()
    definition_version["const"] = "1.13.0"
    return successor


def main() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    payload = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
    for root in (CANONICAL, PACKAGED):
        path = root / NAME
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"generated workflow-start V3 schema drifted: {path}")
        path.write_bytes(payload)


if __name__ == "__main__":
    main()

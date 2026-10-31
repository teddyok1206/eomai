#!/usr/bin/env python3
"""Exact metadata carriers over unchanged numerical INDEX2 execution.

Closed predecessor resources are referenced, not rewritten. Only the new
provenance-bearing value shapes get a successor.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas/workflow"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources"
SOURCE3 = "eom://schemas/workflow/local-embedding-source-plan/3.0"
INDEX3 = "eom://schemas/knowledge/public-solution-embedding-index/3.0"
INDEX4 = "eom://schemas/knowledge/public-solution-embedding-index/4.0"
ENTRY2 = "eom://schemas/knowledge/public-solution-embedding-entry/2.0"


def externalize(value: Any, schema_id: str) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            value["$ref"] = schema_id + reference
        for child in value.values():
            externalize(child, schema_id)
    elif isinstance(value, list):
        for child in value:
            externalize(child, schema_id)


def source_plan() -> dict[str, Any]:
    old = json.loads((SCHEMAS / "local-embedding-source-plan-v3.schema.json").read_bytes())
    if not isinstance(old, dict):
        raise ValueError("source schema must be an object")
    value = {name: copy.deepcopy(part) for name, part in old.items() if name != "$defs"}
    externalize(value, SOURCE3)
    demand = copy.deepcopy(old["$defs"]["PublicSolutionEncodingDemand"])
    externalize(demand, SOURCE3)
    profile1 = {"$ref": INDEX3 + "#/$defs/PublicSolutionProfilePointer"}
    profile2 = {"$ref": INDEX4 + "#/$defs/registeredProfile"}
    evidence1 = {
        "$ref": "eom://schemas/knowledge/public-solution-embedding-entry/1.0#/properties/evidence"
    }
    evidence2 = {"$ref": ENTRY2 + "#/$defs/registeredEvidence"}
    demand["properties"]["profile"] = {"oneOf": [profile1, profile2]}
    demand["properties"]["evidence"] = {"oneOf": [evidence1, evidence2]}
    demand["oneOf"] = [
        {"properties": {"profile": profile1, "evidence": evidence1}},
        {"properties": {"profile": profile2, "evidence": evidence2}},
    ]
    value.update(
        {
            "$id": "eom://schemas/workflow/local-embedding-source-plan/4.0",
            "title": "Exact past/creative/registered full report demands in one numeric space",
            "$defs": {"demand": demand},
        }
    )
    value["properties"]["schema_version"] = {"const": "local-embedding-source-plan/4.0"}
    value["properties"]["demands"]["items"] = {"$ref": "#/$defs/demand"}
    value["required"] = list(value["properties"])
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    for name, schema in {"local-embedding-source-plan-v4.schema.json": source_plan()}.items():
        payload = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
        for directory in (SCHEMAS, PACKAGED):
            path = directory / name
            if arguments.check:
                if not path.is_file() or path.read_bytes() != payload:
                    raise SystemExit(f"generated schema differs: {path.relative_to(ROOT)}")
            else:
                path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

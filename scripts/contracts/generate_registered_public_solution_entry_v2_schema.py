#!/usr/bin/env python3
"""Derive a closed AI report envelope, never alter historical numeric inputs.

The registered Item's accepted V11 result and receipt10 are not past-exam
result10/receipt9. This explicit successor preserves the real provenance while
referencing the unchanged public-text1 and recipe2 contracts.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "schemas/knowledge"
PACKAGED = ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"


def build_contract() -> dict[str, Any]:
    entry = json.loads((KNOWLEDGE / "public-solution-embedding-entry-v1.schema.json").read_bytes())
    evidence = json.loads((KNOWLEDGE / "evidence-bundle-manifest-v5.schema.json").read_bytes())
    if not isinstance(entry, dict) or not isinstance(evidence, dict):
        raise ValueError("schema source must be an object")
    solution = copy.deepcopy(evidence["$defs"]["solutionEvidence"])
    # Resolve this one local reference into a separate closed entry envelope;
    # all field constraints remain intact, only the released family differs.
    properties = solution["properties"]
    properties["schema_version"] = {"const": "registered-item-solution-evidence-pointer/1.0"}
    for name, path, logical, schema in (
        (
            "accepted_result_artifact",
            "evidence/accepted-result.json",
            "accepted-result.json",
            "knowledge-analysis-result/11.0",
        ),
        (
            "proposal_receipt",
            "normalized/proposal-receipt.json",
            "proposal-receipt.json",
            "knowledge-analysis-proposal-receipt/10.0",
        ),
        (
            "solution_report",
            "normalized/solution-report.json",
            "solution-report.json",
            "knowledge-analysis-solution-report/1.0",
        ),
    ):
        field = properties[name]
        field["properties"] = {
            "member_path": {"const": path},
            "logical_name": {"const": logical},
            "schema_ref": {"const": "eom://schemas/knowledge/" + schema},
            "media_type": {"const": "application/json"},
        }
    # Its referenced value object is immutable and has no separate lifecycle.
    definitions = entry["$defs"]
    definitions.pop("acceptedEvidence")
    definitions.pop("creativeEvidence")
    definitions["registeredSolution"] = solution
    definitions["registeredEvidence"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "solution"],
        "properties": {
            "kind": {"const": "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"},
            "solution": {"$ref": "#/$defs/registeredSolution"},
        },
    }
    entry["$id"] = "eom://schemas/knowledge/public-solution-embedding-entry/2.0"
    entry["title"] = "Registered Item full report over unchanged public text and numeric recipe"
    entry["properties"]["schema_version"] = {"const": "public-solution-embedding-entry/2.0"}
    entry["properties"]["source"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/approvedItemSource",
        "properties": {"source_class": {"const": "APPROVED_ITEM"}},
    }
    entry["properties"]["evidence"] = {"$ref": "#/$defs/registeredEvidence"}
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = (json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (KNOWLEDGE, PACKAGED):
        path = directory / "public-solution-embedding-entry-v2.schema.json"
        if arguments.check:
            if not path.is_file() or path.read_bytes() != payload:
                raise SystemExit(f"generated schema differs: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

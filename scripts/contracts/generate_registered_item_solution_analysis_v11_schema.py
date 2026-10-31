#!/usr/bin/env python3
"""Protocol-first candidate for an additive full solution over an approved Item V2 base.

This does not activate a Workflow, producer or embedding source family. Released
past-exam V9/V10 and public report1 resources are inputs and remain unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "schemas/knowledge"
KNOWLEDGE_PACKAGE = ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
ROLES = ROOT / "schemas/workflow/roles"
ROLES_PACKAGE = ROOT / "packages/workflow/eom_workflow/resources/roles"
CONTROL = ROOT / "schemas/workflow/control-plane"
CONTROL_PACKAGE = ROOT / "packages/workflow/eom_workflow/resources/control-plane"
TYPES = "eom://schemas/knowledge/knowledge-analysis-solution-types/2.0"
BASE_REF = {"$ref": TYPES + "#/$defs/baseAnalysis"}
APPROVED_SOURCE = {
    "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/approvedItemSource",
    "properties": {"source_class": {"const": "APPROVED_ITEM"}},
}
BASE_MEMBER_SHAPES = {
    "normalized_markdown": ("normalized/document.md", "normalized-markdown/1.0", "text/markdown"),
    "anchors": ("normalized/anchors.jsonl", "source-anchor/2.0", "application/x-ndjson"),
    "nodes": ("normalized/nodes.jsonl", "proposed-node/2.0", "application/x-ndjson"),
    "edges": ("normalized/edges.jsonl", "proposed-edge/2.0", "application/x-ndjson"),
    "claims": ("normalized/claims.jsonl", "proposed-claim/2.0", "application/x-ndjson"),
    "component_observations": (
        "normalized/components.jsonl",
        "component-observation/2.0",
        "application/x-ndjson",
    ),
    "unresolved_ambiguities": (
        "normalized/ambiguities.jsonl",
        "ambiguity/2.0",
        "application/x-ndjson",
    ),
}


def load(directory: Path, name: str) -> dict[str, Any]:
    value = json.loads((directory / name).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("schema must be an object")
    return value


def build_contracts() -> dict[str, dict[str, Any]]:
    original_types = load(KNOWLEDGE, "knowledge-analysis-solution-types-v1.schema.json")
    base = copy.deepcopy(original_types["$defs"]["baseAnalysis"])
    fields = base["properties"]
    fields["accepted_result_artifact"]["properties"]["schema_ref"] = {
        "const": "eom://schemas/knowledge/knowledge-analysis-result/2.0"
    }
    fields["proposal_receipt"]["properties"]["schema_ref"] = {
        "const": "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0"
    }
    receipt = load(KNOWLEDGE, "knowledge-analysis-proposal-receipt-v1.schema.json")
    fields["base_members"] = copy.deepcopy(receipt["properties"]["members"])
    for name, (path, schema, media) in BASE_MEMBER_SHAPES.items():
        fields["base_members"]["properties"][name]["properties"] = {
            "member_path": {"const": path},
            "schema_ref": {"const": "eom://schemas/knowledge/" + schema},
            "media_type": {"const": media},
        }
    fields["base_counts"] = copy.deepcopy(receipt["properties"]["counts"])
    fields["reference_index"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/referenceIndex"
    }
    types = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": TYPES,
        "title": "EOM Approved Item Additive Solution Base Types V2",
        "$ref": "#/$defs/baseAnalysis",
        "$defs": {"baseAnalysis": base},
    }

    request = load(KNOWLEDGE, "knowledge-analysis-request-v10.schema.json")
    request["$id"] = "eom://schemas/knowledge/knowledge-analysis-request/11.0"
    request["title"] = "EOM Approved Item Full Solution Analysis Request V11"
    props = request["properties"]
    props["schema_version"] = {"const": "knowledge-analysis-request/11.0"}
    props["source"] = copy.deepcopy(APPROVED_SOURCE)
    props["accepted_result_schema_ref"] = {
        "const": "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    }
    props["base_analysis"] = copy.deepcopy(BASE_REF)

    report_receipt = load(KNOWLEDGE, "knowledge-analysis-proposal-receipt-v9.schema.json")
    report_receipt["$id"] = "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/10.0"
    report_receipt["title"] = "EOM Approved Item Full Solution Receipt V10"
    props = report_receipt["properties"]
    props["schema_version"] = {"const": "knowledge-analysis-proposal-receipt/10.0"}
    props["source"] = copy.deepcopy(APPROVED_SOURCE)
    props["base_analysis"] = copy.deepcopy(BASE_REF)

    result = load(KNOWLEDGE, "knowledge-analysis-result-v10.schema.json")
    result["$id"] = "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    result["title"] = "EOM Accepted Approved Item Full Solution Result V11"
    props = result["properties"]
    props["schema_version"] = {"const": "knowledge-analysis-result/11.0"}
    props["source"] = copy.deepcopy(APPROVED_SOURCE)
    props["base_analysis"] = copy.deepcopy(BASE_REF)
    props["counts"] = copy.deepcopy(receipt["properties"]["counts"])
    return {
        "knowledge-analysis-solution-types-v2.schema.json": types,
        "knowledge-analysis-request-v11.schema.json": request,
        "knowledge-analysis-proposal-receipt-v10.schema.json": report_receipt,
        "knowledge-analysis-result-v11.schema.json": result,
    }


def build_role_contracts() -> dict[str, dict[str, Any]]:
    schemas = {}
    for stem in ("knowledge-analysis-input", "knowledge-analysis-proposal-result"):
        value = load(ROLES, stem + "-v10.schema.json")
        value["$id"] = "https://eom.local/schemas/workflow/roles/" + stem + "-v11.schema.json"
        value["title"] = "EOM Approved Item Full Solution " + stem + " V11"
        value["properties"]["protocol_version"] = {"const": "workflow-role/1.35.0"}
        if stem == "knowledge-analysis-input":
            value["$defs"]["request"]["properties"]["analysis_request"] = {
                "$ref": "eom://schemas/knowledge/knowledge-analysis-request/11.0"
            }
        schemas[stem + "-v11.schema.json"] = value
    return schemas


def build_control_contracts() -> dict[str, dict[str, Any]]:
    plan = load(CONTROL, "resolved-execution-plan-v9.schema.json")
    plan["$id"] = "eom://schemas/workflow/resolved-execution-plan/29.0"
    plan["title"] = "EOM Approved Item Full Solution Resolved Plan V29"
    plan["properties"]["schema_version"] = {"const": "resolved-execution-plan/29.0"}
    plan["properties"]["resolver_version"] = {"const": "29.0.0"}
    plan["properties"]["base_analysis"] = copy.deepcopy(BASE_REF)
    plan["properties"]["item_source"] = copy.deepcopy(APPROVED_SOURCE)
    return {"resolved-execution-plan-v29.schema.json": plan}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    groups = (
        ((KNOWLEDGE, KNOWLEDGE_PACKAGE), build_contracts()),
        ((ROLES, ROLES_PACKAGE), build_role_contracts()),
        ((CONTROL, CONTROL_PACKAGE), build_control_contracts()),
    )
    mismatches = []
    for directories, schemas in groups:
        for name, schema in schemas.items():
            encoded = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
            for directory in directories:
                target = directory / name
                if check:
                    if not target.is_file() or target.read_bytes() != encoded:
                        mismatches.append(str(target.relative_to(ROOT)))
                else:
                    target.write_bytes(encoded)
    if mismatches:
        print("Candidate schema mismatch: " + ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

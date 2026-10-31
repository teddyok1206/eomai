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
REQUEST3 = "eom://schemas/workflow/local-embedding-workflow-request/3.0"
OWNERSHIP3 = "eom://schemas/workflow/embedding-encoding-ownership/3.0"


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


def request() -> dict[str, Any]:
    old = json.loads((SCHEMAS / "local-embedding-workflow-request-v3.schema.json").read_bytes())
    value = {name: copy.deepcopy(part) for name, part in old.items() if name != "$defs"}
    externalize(value, REQUEST3)
    value.update(
        {
            "$id": "eom://schemas/workflow/local-embedding-workflow-request/4.0",
            "title": "Registered full-report request over unchanged INDEX2 numerical execution",
        }
    )
    value["properties"]["schema_version"] = {"const": "local-embedding-workflow-request/4.0"}
    value["properties"]["source_plan"] = {
        "allOf": [
            {"$ref": REQUEST3 + "#/$defs/ArtifactMemberPointer"},
            {
                "properties": {
                    "member_path": {"const": "source-plan.json"},
                    "schema_ref": {
                        "const": "eom://schemas/workflow/local-embedding-source-plan/4.0"
                    },
                    "media_type": {"const": "application/json"},
                }
            },
        ]
    }
    value["required"] = list(value["properties"])
    return value


def ownership() -> dict[str, Any]:
    old = json.loads((SCHEMAS / "embedding-encoding-ownership-v3.schema.json").read_bytes())
    names = {
        "LocalEmbeddingLaunchIntentV3": "LocalEmbeddingLaunchIntentV4",
        "LocalEmbeddingLaunchAssociationV3": "LocalEmbeddingLaunchAssociationV4",
        "EmbeddingEncodingAttachedEventV3": "EmbeddingEncodingAttachedEventV4",
        "EmbeddingEncodingCompletedEventV3": "EmbeddingEncodingCompletedEventV4",
        "EmbeddingEncodingReadResultV3": "EmbeddingEncodingReadResultV4",
    }
    references = {
        OWNERSHIP3 + "#/$defs/" + name: "#/$defs/" + successor for name, successor in names.items()
    }

    def retarget(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference in references:
                value["$ref"] = references[reference]
            discriminator = value.get("discriminator")
            if isinstance(discriminator, dict):
                for tag, target in discriminator.get("mapping", {}).items():
                    if target.startswith("#/$defs/"):
                        target = OWNERSHIP3 + target
                    discriminator["mapping"][tag] = references.get(target, target)
            for child in value.values():
                retarget(child)
        elif isinstance(value, list):
            for child in value:
                retarget(child)

    value = {name: copy.deepcopy(part) for name, part in old.items() if name != "$defs"}
    externalize(value, OWNERSHIP3)
    definitions = {}
    for name, successor in names.items():
        definition = copy.deepcopy(old["$defs"][name])
        externalize(definition, OWNERSHIP3)
        definition["title"] = successor
        if "schema_version" in definition["properties"]:
            definition["properties"]["schema_version"] = {
                "const": "embedding-encoding-ownership/4.0"
            }
        definitions[successor] = definition
    definitions["LocalEmbeddingLaunchIntentV4"]["properties"]["source_plan"] = {
        "allOf": [
            {"$ref": OWNERSHIP3 + "#/$defs/ArtifactMemberPointer"},
            {
                "properties": {
                    "member_path": {"const": "source-plan.json"},
                    "schema_ref": {
                        "const": "eom://schemas/workflow/local-embedding-source-plan/4.0"
                    },
                    "media_type": {"const": "application/json"},
                }
            },
        ]
    }
    value.update(
        {
            "$id": "eom://schemas/workflow/embedding-encoding-ownership/4.0",
            "title": "Source-plan4 ownership metadata over unchanged numerical Job/input/result1",
            "$defs": definitions,
        }
    )
    retarget(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    documents = {
        "local-embedding-source-plan-v4.schema.json": source_plan(),
        "local-embedding-workflow-request-v4.schema.json": request(),
        "embedding-encoding-ownership-v4.schema.json": ownership(),
    }
    for name, schema in documents.items():
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

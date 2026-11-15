#!/usr/bin/env python3
"""Publish only the score successor; never regenerate or change released predecessor bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCORE = "eom://schemas/external-item/source-score/2.0#/oneOf/0"
BASE_HASHES = {
    "roles/material-learning-input-v2.schema.json": (
        "750e44b96ba210bacf2414814515990e5bc8d34b860b2e1f118a27bc7c99eb18"
    ),
    "roles/material-learning-result-v2.schema.json": (
        "9f96f91e4b804618b1792c6880548344407e730029c04a46e0e11b5bbc18fe42"
    ),
    "control-plane/resolved-execution-plan-v40.schema.json": (
        "7b181ed22687d8e6bb31a6abc6e44a785cf6d871850b524d2552d62c3144a960"
    ),
}


def predecessor(path: str) -> dict[str, Any]:
    raw = (ROOT / "schemas/workflow" / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_HASHES[path]:
        raise ValueError("released material predecessor schema changed")
    document: object = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("released material predecessor is not a schema object")
    return document


def score_fields(container: dict[str, Any]) -> None:
    """A value is present exactly when its independently resolved Native scope is present."""
    container["properties"]["native_printed_score"] = {"oneOf": [{"$ref": SCORE}, {"type": "null"}]}
    container["required"].append("native_printed_score")
    container.setdefault("allOf", []).append(
        {
            "if": {
                "properties": {"native_visual_scope": {"type": "null"}},
                "required": ["native_visual_scope"],
            },
            "then": {"properties": {"native_printed_score": {"type": "null"}}},
            "else": {"properties": {"native_printed_score": {"$ref": SCORE}}},
        }
    )


def schemas() -> dict[str, dict[str, Any]]:
    request = predecessor("roles/material-learning-input-v2.schema.json")
    request["$id"] = (
        "https://eom.local/schemas/workflow/roles/material-learning-input-v3.schema.json"
    )
    request["properties"]["protocol_version"] = {"const": "workflow-role/1.40.0"}
    score_fields(request["properties"]["request"])

    result = predecessor("roles/material-learning-result-v2.schema.json")
    result["$id"] = (
        "https://eom.local/schemas/workflow/roles/material-learning-result-v3.schema.json"
    )
    result["properties"]["protocol_version"] = {"const": "workflow-role/1.40.0"}
    result["properties"]["output"]["properties"]["learning_result"]["oneOf"] = [
        {"$ref": "eom://schemas/material-learning/discovery-result/1.0"},
        {"$ref": "eom://schemas/material-learning/extraction-result/2.0"},
    ]

    plan = predecessor("control-plane/resolved-execution-plan-v40.schema.json")
    plan["$id"] = "eom://schemas/workflow/resolved-execution-plan/41.0"
    plan["title"] = "Material learning exact-score execution plan V41"
    for key, value in (
        ("schema_version", "resolved-execution-plan/41.0"),
        ("resolver_version", "41.0.0"),
        ("workflow_definition_version", "3.0.0"),
    ):
        plan["properties"][key] = {"const": value}
    score_fields(plan)
    return {
        "roles/material-learning-input-v3.schema.json": request,
        "roles/material-learning-result-v3.schema.json": result,
        "control-plane/resolved-execution-plan-v41.schema.json": plan,
    }


def main() -> None:
    for relative, document in schemas().items():
        raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        for directory in (
            ROOT / "schemas/workflow",
            ROOT / "packages/workflow/eom_workflow/resources",
        ):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        print(relative + " sha256:" + hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build immutable stable-identity knowledge-analysis V6/V8 contracts."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPOSITORY_ROOT / "schemas/knowledge"
KNOWLEDGE_RESOURCE_ROOT = (
    REPOSITORY_ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
)
ROLE_ROOT = REPOSITORY_ROOT / "schemas/workflow/roles"
ROLE_RESOURCE_ROOT = REPOSITORY_ROOT / "packages/workflow/eom_workflow/resources/roles"


def _load(root: Path, name: str) -> dict[str, object]:
    return json.loads((root / name).read_text(encoding="utf-8"))


def _typed_stable_node(proposal: dict[str, object]) -> dict[str, object]:
    definitions = proposal["$defs"]
    assert isinstance(definitions, dict)
    typed_node = copy.deepcopy(definitions["typedNode"])
    assert isinstance(typed_node, dict)
    all_of = typed_node["allOf"]
    assert isinstance(all_of, list)
    alternatives = all_of[1]["anyOf"]
    assert isinstance(alternatives, list)
    for alternative in alternatives:
        properties = alternative["properties"]
        node_type = properties["node_type"]["const"]
        prefix = str(node_type).lower()
        properties["stable_key"] = {
            "type": "string",
            "pattern": rf"^{prefix}:[a-z0-9][a-z0-9._:-]{{0,159}}$",
        }
    return typed_node


def _versioned_copy(
    source_name: str, *, schema_id: str, title: str, schema_version: str
) -> dict[str, object]:
    schema = _load(KNOWLEDGE_ROOT, source_name)
    schema["$id"] = schema_id
    schema["title"] = title
    schema["properties"]["schema_version"]["const"] = schema_version
    return schema


def build_contracts() -> dict[str, dict[str, object]]:
    proposal = _load(KNOWLEDGE_ROOT, "knowledge-analysis-worker-proposal-v5.schema.json")
    proposal["$id"] = "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
    proposal["title"] = "EOM Stable-Identity Multimodal Knowledge Analysis Worker Proposal V6"
    proposal["properties"]["schema_version"]["const"] = "knowledge-analysis-worker-proposal/6.0"
    typed_node = _typed_stable_node(proposal)
    proposal["$defs"]["typedNode"] = typed_node

    node = copy.deepcopy(typed_node)
    node.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/proposed-node/4.0",
            "title": "EOM Stable-Identity Proposed Knowledge Node V4",
        }
    )

    request = _versioned_copy(
        "knowledge-analysis-request-v7.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-request/8.0",
        title="EOM Stable-Identity Multimodal Knowledge Analysis Request V8",
        schema_version="knowledge-analysis-request/8.0",
    )
    request["properties"]["worker_proposal_schema_ref"]["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
    )
    request["properties"]["accepted_result_schema_ref"]["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/8.0"
    )

    receipt = _versioned_copy(
        "knowledge-analysis-proposal-receipt-v6.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/7.0",
        title="EOM Stable-Identity Multimodal Knowledge Analysis Proposal Receipt V7",
        schema_version="knowledge-analysis-proposal-receipt/7.0",
    )
    result = _versioned_copy(
        "knowledge-analysis-result-v7.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-result/8.0",
        title="EOM Accepted Stable-Identity Multimodal Knowledge Analysis Result V8",
        schema_version="knowledge-analysis-result/8.0",
    )
    return {
        "knowledge-analysis-worker-proposal-v6.schema.json": proposal,
        "knowledge-analysis-proposed-node-v4.schema.json": node,
        "knowledge-analysis-request-v8.schema.json": request,
        "knowledge-analysis-proposal-receipt-v7.schema.json": receipt,
        "knowledge-analysis-result-v8.schema.json": result,
    }


def build_workflow_contracts() -> dict[str, dict[str, object]]:
    worker_input = _load(ROLE_ROOT, "knowledge-analysis-input-v7.schema.json")
    worker_input["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-input-v8.schema.json"
    )
    worker_input["properties"]["protocol_version"]["const"] = "workflow-role/1.11.0"
    worker_input["$defs"]["request"]["properties"]["analysis_request"]["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-request/8.0"
    )

    worker_result = _load(ROLE_ROOT, "knowledge-analysis-proposal-result-v7.schema.json")
    worker_result["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-proposal-result-v8.schema.json"
    )
    worker_result["properties"]["protocol_version"]["const"] = "workflow-role/1.11.0"
    worker_result["$defs"]["output"]["properties"]["proposal"]["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
    )
    return {
        "knowledge-analysis-input-v8.schema.json": worker_input,
        "knowledge-analysis-proposal-result-v8.schema.json": worker_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_contracts().items()
    }
    targets = {name: (KNOWLEDGE_ROOT / name, KNOWLEDGE_RESOURCE_ROOT / name) for name in rendered}
    workflow_rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_workflow_contracts().items()
    }
    rendered.update(workflow_rendered)
    targets.update(
        {name: (ROLE_ROOT / name, ROLE_RESOURCE_ROOT / name) for name in workflow_rendered}
    )
    if args.check:
        return (
            0
            if all(
                path.is_file() and path.read_bytes() == rendered[name]
                for name, paths in targets.items()
                for path in paths
            )
            else 1
        )
    for name, paths in targets.items():
        for path in paths:
            path.write_bytes(rendered[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

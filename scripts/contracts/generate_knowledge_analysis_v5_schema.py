#!/usr/bin/env python3
"""Build the reviewed typed-identity proposal schema from immutable V4 and the ontology map."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from eom_catalog_contracts.knowledge import KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY_ROOT / "schemas/knowledge/knowledge-analysis-worker-proposal-v4.schema.json"
CANONICAL_ROOT = REPOSITORY_ROOT / "schemas/knowledge"
RESOURCE_ROOT = (
    REPOSITORY_ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
)
WORKFLOW_CANONICAL_ROOT = REPOSITORY_ROOT / "schemas/workflow/roles"
WORKFLOW_RESOURCE_ROOT = REPOSITORY_ROOT / "packages/workflow/eom_workflow/resources/roles"

NODE_TYPES = (
    "CURRICULUM_FRAMEWORK_REVISION",
    "CURRICULUM_UNIT",
    "ACHIEVEMENT_STANDARD",
    "CONCEPT",
    "CLAIM",
    "PROCESS",
    "OBSERVABLE_PROPERTY",
    "FORMULA",
    "DATA_REPRESENTATION",
    "DOCUMENT_REVISION",
    "DOCUMENT_SECTION",
    "FIGURE",
    "TABLE",
    "EQUATION",
    "ITEM_REVISION",
    "ITEM_ELEMENT",
    "ASSESSMENT_PATTERN",
)


def _node_pattern(node_types: tuple[str, ...]) -> str:
    prefixes = "|".join(value.lower() for value in node_types)
    return rf"^knode_(?:{prefixes})_[a-z0-9][a-z0-9_-]{{0,31}}$"


def _typed_node() -> dict[str, object]:
    alternatives = []
    for node_type in NODE_TYPES:
        alternatives.append(
            {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "pattern": _node_pattern((node_type,))},
                    "node_type": {"type": "string", "const": node_type},
                },
            }
        )
    return {
        "allOf": [
            {"$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/proposedNode"},
            {"anyOf": alternatives},
        ]
    }


def _typed_edge() -> dict[str, object]:
    alternatives = []
    for edge_type, pairs in KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY.items():
        source_types = tuple(sorted({str(source) for source, _ in pairs}))
        target_types = tuple(sorted({str(target) for _, target in pairs}))
        alternatives.append(
            {
                "type": "object",
                "properties": {
                    "relationship": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["edge_type", "from_node_type", "to_node_type"],
                        "properties": {
                            "edge_type": {"type": "string", "const": str(edge_type)},
                            "from_node_type": {"type": "string", "enum": list(source_types)},
                            "to_node_type": {"type": "string", "enum": list(target_types)},
                        },
                    },
                    "from_node_id": {"type": "string", "pattern": _node_pattern(source_types)},
                    "to_node_id": {"type": "string", "pattern": _node_pattern(target_types)},
                },
            }
        )
    return {"allOf": [{"$ref": "#/$defs/proposedEdgeV2"}, {"anyOf": alternatives}]}


def build_schema() -> dict[str, object]:
    schema = json.loads(SOURCE.read_text(encoding="utf-8"))
    schema["$id"] = "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0"
    schema["title"] = "EOM Typed-Identity Multimodal Knowledge Analysis Worker Proposal V5"
    schema["properties"]["schema_version"]["const"] = "knowledge-analysis-worker-proposal/5.0"
    schema["properties"]["nodes"]["items"] = {"$ref": "#/$defs/typedNode"}
    schema["properties"]["edges"]["items"] = {"$ref": "#/$defs/typedEdge"}
    definitions = copy.deepcopy(schema["$defs"])
    definitions["typedNode"] = _typed_node()
    definitions["typedEdge"] = _typed_edge()
    schema["$defs"] = definitions
    return schema


def _versioned_copy(
    source_name: str,
    *,
    schema_id: str,
    title: str,
    schema_version: str,
) -> dict[str, object]:
    schema = json.loads((CANONICAL_ROOT / source_name).read_text(encoding="utf-8"))
    schema["$id"] = schema_id
    schema["title"] = title
    schema["properties"]["schema_version"]["const"] = schema_version
    return schema


def build_contracts() -> dict[str, dict[str, object]]:
    proposal = build_schema()
    node = copy.deepcopy(proposal["$defs"]["typedNode"])
    node.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/proposed-node/3.0",
            "title": "EOM Typed-Identity Proposed Knowledge Node V3",
        }
    )
    edge = copy.deepcopy(proposal["$defs"]["typedEdge"])
    edge.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/proposed-edge/4.0",
            "title": "EOM Typed-Identity Proposed Knowledge Edge V4",
            "$defs": {
                "edgeEndpointContract": copy.deepcopy(proposal["$defs"]["edgeEndpointContract"]),
                "proposedEdgeV2": copy.deepcopy(proposal["$defs"]["proposedEdgeV2"]),
            },
        }
    )
    request = _versioned_copy(
        "knowledge-analysis-request-v6.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-request/7.0",
        title="EOM Typed-Identity Multimodal Knowledge Analysis Request V7",
        schema_version="knowledge-analysis-request/7.0",
    )
    request["properties"]["worker_proposal_schema_ref"]["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0"
    )
    request["properties"]["accepted_result_schema_ref"]["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/7.0"
    )
    receipt = _versioned_copy(
        "knowledge-analysis-proposal-receipt-v5.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/6.0",
        title="EOM Typed-Identity Multimodal Knowledge Analysis Proposal Receipt V6",
        schema_version="knowledge-analysis-proposal-receipt/6.0",
    )
    result = _versioned_copy(
        "knowledge-analysis-result-v6.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-result/7.0",
        title="EOM Accepted Typed-Identity Multimodal Knowledge Analysis Result V7",
        schema_version="knowledge-analysis-result/7.0",
    )
    return {
        "knowledge-analysis-worker-proposal-v5.schema.json": proposal,
        "knowledge-analysis-proposed-node-v3.schema.json": node,
        "knowledge-analysis-proposed-edge-v4.schema.json": edge,
        "knowledge-analysis-request-v7.schema.json": request,
        "knowledge-analysis-proposal-receipt-v6.schema.json": receipt,
        "knowledge-analysis-result-v7.schema.json": result,
    }


def build_workflow_contracts() -> dict[str, dict[str, object]]:
    worker_input = json.loads(
        (WORKFLOW_CANONICAL_ROOT / "knowledge-analysis-input-v6.schema.json").read_text()
    )
    worker_input["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-input-v7.schema.json"
    )
    worker_input["properties"]["protocol_version"]["const"] = "workflow-role/1.10.0"
    worker_input["$defs"]["request"]["properties"]["analysis_request"]["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-request/7.0"
    )
    worker_result = json.loads(
        (WORKFLOW_CANONICAL_ROOT / "knowledge-analysis-proposal-result-v6.schema.json").read_text()
    )
    worker_result["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-proposal-result-v7.schema.json"
    )
    worker_result["properties"]["protocol_version"]["const"] = "workflow-role/1.10.0"
    worker_result["$defs"]["output"]["properties"]["proposal"]["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0"
    )
    return {
        "knowledge-analysis-input-v7.schema.json": worker_input,
        "knowledge-analysis-proposal-result-v7.schema.json": worker_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_contracts().items()
    }
    targets = {name: (CANONICAL_ROOT / name, RESOURCE_ROOT / name) for name in rendered}
    workflow_rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_workflow_contracts().items()
    }
    rendered.update(workflow_rendered)
    targets.update(
        {
            name: (WORKFLOW_CANONICAL_ROOT / name, WORKFLOW_RESOURCE_ROOT / name)
            for name in workflow_rendered
        }
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

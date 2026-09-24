#!/usr/bin/env python3
"""Generate the Graph-grounded PDF document-review bootstrap V5 schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "schemas/workflow/control-plane/pdf-document-review-control-bootstrap-v4.schema.json"
)
DESTINATIONS = (
    ROOT / "schemas/workflow/control-plane/pdf-document-review-control-bootstrap-v5.schema.json",
    ROOT / "packages/workflow/eom_workflow/resources/control-plane/"
    "pdf-document-review-control-bootstrap-v5.schema.json",
)


def main() -> None:
    value = copy.deepcopy(json.loads(SOURCE.read_text(encoding="utf-8")))
    value["$id"] = "eom://schemas/workflow/pdf-document-review-control-bootstrap/5.0"
    value["title"] = "EOM Graph-Grounded PDF Document Review Control Bootstrap V5"
    value["properties"]["schema_version"] = {"const": "pdf-document-review-control-bootstrap/5.0"}
    protocols = value["properties"]["compatible_workflow_protocols"]
    protocols["prefixItems"].append({"const": "workflow-role/1.27.0"})
    protocols["minItems"] = protocols["maxItems"] = 3
    value["properties"]["instruction_revision_number"] = {"const": 5}
    value["required"].extend(["evidence_access", "retrieval_policy"])
    value["properties"]["evidence_access"] = {"const": "EVIDENCE_CONTEXT"}
    value["properties"]["retrieval_policy"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "access_policy_revision_id",
            "access_policy_sha256",
            "allowed_corpus_keys",
            "allowed_query_kinds",
            "allowed_source_classes",
            "maximum_budget",
        ],
        "properties": {
            "access_policy_revision_id": {"const": "accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9"},
            "access_policy_sha256": {
                "const": "sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0"
            },
            "allowed_corpus_keys": {
                "type": "array",
                "prefixItems": [{"const": "integrated-science-textbooks"}],
                "items": False,
                "minItems": 1,
                "maxItems": 1,
            },
            "allowed_query_kinds": {
                "type": "array",
                "prefixItems": [{"const": "ITEM_PREPARATION"}],
                "items": False,
                "minItems": 1,
                "maxItems": 1,
            },
            "allowed_source_classes": {
                "type": "array",
                "prefixItems": [
                    {"const": "APPROVED_ITEM"},
                    {"const": "PAST_EXAM"},
                    {"const": "TEXTBOOK"},
                ],
                "items": False,
                "minItems": 3,
                "maxItems": 3,
            },
            "maximum_budget": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "max_documents",
                    "max_item_revisions",
                    "max_graph_nodes",
                    "max_claims",
                    "max_context_tokens",
                ],
                "properties": {
                    "max_documents": {"const": 16},
                    "max_item_revisions": {"const": 32},
                    "max_graph_nodes": {"const": 128},
                    "max_claims": {"const": 64},
                    "max_context_tokens": {"const": 16000},
                },
            },
        },
    }
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    for destination in DESTINATIONS:
        destination.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate Graph-grounded paired-review plan and validation-receipt schemas."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v14.schema.json"
EVIDENCE_SOURCE = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v11.schema.json"
DIRECTORIES = (
    ROOT / "schemas/workflow/control-plane",
    ROOT / "packages/workflow/eom_workflow/resources/control-plane",
)
TYPES = "eom://schemas/workflow/control-plane-types-v1"
SHA = {"$ref": f"{TYPES}#/$defs/sha256"}
RECEIPT_SOURCE = (
    ROOT / "schemas/workflow/control-plane/evidence-usage-validation-receipt-v1.schema.json"
)


def plan_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(json.loads(SOURCE.read_text(encoding="utf-8")))
    evidence: dict[str, Any] = json.loads(EVIDENCE_SOURCE.read_text(encoding="utf-8"))
    value["$id"] = "eom://schemas/workflow/resolved-execution-plan/15.0"
    value["title"] = "EOM Graph-Grounded Paired Document Review Plan V15"
    value["properties"]["schema_version"] = {"const": "resolved-execution-plan/15.0"}
    value["properties"]["workflow_definition_version"] = {"const": "1.2.0"}
    value["properties"]["resolver_version"] = {"const": "15.0.0"}
    evidence_fields = (
        "retrieval_requirement",
        "retrieval_requirement_sha256",
        "retrieval_request_id",
        "retrieval_request_sha256",
        "graph_snapshot",
        "access_policy_revision_id",
        "access_policy_sha256",
        "requester_permissions_sha256",
        "evidence_bundle_id",
        "evidence_bundle_revision_id",
        "evidence_manifest_artifact",
        "evidence_manifest_sha256",
        "evidence_context_artifact",
    )
    insertion = value["required"].index("capacity_policy_revision_id")
    value["required"][insertion:insertion] = ["evidence_plan_sha256", *evidence_fields]
    value["properties"]["evidence_plan_sha256"] = SHA
    for field in evidence_fields:
        value["properties"][field] = copy.deepcopy(evidence["properties"][field])
    value["$defs"].update(copy.deepcopy(evidence["$defs"]))
    step = value["properties"]["steps"]["items"]
    step["required"].append("evidence_access")
    step["properties"]["evidence_access"] = {"const": "EVIDENCE_CONTEXT"}
    return value


def receipt_schema() -> dict[str, Any]:
    source: dict[str, Any] = json.loads(RECEIPT_SOURCE.read_text(encoding="utf-8"))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/workflow/document-review-evidence-validation-receipt/1.0",
        "title": "EOM Document Review Evidence Validation Receipt V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "plan_id",
            "plan_sha256",
            "workflow_id",
            "step_run_id",
            "job_id",
            "attempt",
            "review_request_sha256",
            "evidence_plan_sha256",
            "retrieval_request_id",
            "graph_snapshot_revision_id",
            "evidence_bundle_id",
            "evidence_bundle_revision_id",
            "evidence_manifest_artifact",
            "evidence_manifest_sha256",
            "evidence_context_artifact",
            "result_artifact_id",
            "result_artifact_revision_id",
            "result_content_sha256",
            "citation_set_sha256",
            "receipt_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-evidence-validation-receipt/1.0"},
            "plan_id": {"type": "string", "pattern": "^execplan_[0-9a-f]{32}$"},
            "plan_sha256": SHA,
            "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
            "step_run_id": {"type": "string", "pattern": "^steprun_[0-9a-f]{32}$"},
            "job_id": {"type": "string", "pattern": "^job_[0-9a-f]{32}$"},
            "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
            "review_request_sha256": SHA,
            "evidence_plan_sha256": SHA,
            "retrieval_request_id": {
                "type": "string",
                "pattern": "^retrieval_[0-9a-f]{32}$",
            },
            "graph_snapshot_revision_id": {
                "type": "string",
                "pattern": "^graphrev_[0-9a-f]{32}$",
            },
            "evidence_bundle_id": {
                "type": "string",
                "pattern": "^evidence_[0-9a-f]{32}$",
            },
            "evidence_bundle_revision_id": {
                "type": "string",
                "pattern": "^evidencerev_[0-9a-f]{32}$",
            },
            "evidence_manifest_artifact": {"$ref": "#/$defs/manifestArtifactMemberPointer"},
            "evidence_manifest_sha256": SHA,
            "evidence_context_artifact": {"$ref": "#/$defs/contextArtifactMemberPointer"},
            "result_artifact_id": {
                "type": "string",
                "pattern": "^artifact_[0-9a-f]{32}$",
            },
            "result_artifact_revision_id": {
                "type": "string",
                "pattern": "^rev_[0-9a-f]{32}$",
            },
            "result_content_sha256": SHA,
            "citation_set_sha256": SHA,
            "receipt_sha256": SHA,
        },
        "$defs": {
            "knowledgeArtifactMemberPointer": copy.deepcopy(
                source["$defs"]["knowledgeArtifactMemberPointer"]
            ),
            "manifestArtifactMemberPointer": {
                "allOf": [
                    {"$ref": "#/$defs/knowledgeArtifactMemberPointer"},
                    {
                        "properties": {
                            "member_path": {"const": "evidence/manifest.json"},
                            "media_type": {"const": "application/json"},
                            "schema_ref": {
                                "const": ("eom://schemas/knowledge/evidence-bundle-manifest/5.0")
                            },
                        }
                    },
                ]
            },
            "contextArtifactMemberPointer": copy.deepcopy(
                source["$defs"]["contextArtifactMemberPointer"]
            ),
        },
    }


def _write(name: str, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    for directory in DIRECTORIES:
        (directory / name).write_text(payload, encoding="utf-8")


def main() -> None:
    _write("resolved-execution-plan-v15.schema.json", plan_schema())
    _write("document-review-evidence-validation-receipt-v1.schema.json", receipt_schema())


if __name__ == "__main__":
    main()

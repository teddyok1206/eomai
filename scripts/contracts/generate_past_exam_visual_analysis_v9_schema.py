#!/usr/bin/env python3
"""Build immutable past-exam visual knowledge-analysis V9 contracts."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPOSITORY_ROOT / "schemas/knowledge"
KNOWLEDGE_RESOURCE_ROOT = (
    REPOSITORY_ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
)
ROLE_ROOT = REPOSITORY_ROOT / "schemas/workflow/roles"
ROLE_RESOURCE_ROOT = REPOSITORY_ROOT / "packages/workflow/eom_workflow/resources/roles"
CONTROL_ROOT = REPOSITORY_ROOT / "schemas/workflow/control-plane"
CONTROL_RESOURCE_ROOT = REPOSITORY_ROOT / "packages/workflow/eom_workflow/resources/control-plane"


def _load(root: Path, name: str) -> dict[str, object]:
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("schema root must be an object")
    return cast(dict[str, object], value)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("schema member must be an object")
    return cast(dict[str, object], value)


def _versioned_copy(
    root: Path,
    source_name: str,
    *,
    schema_id: str,
    title: str,
    schema_version: str,
) -> dict[str, object]:
    schema = _load(root, source_name)
    schema["$id"] = schema_id
    schema["title"] = title
    properties = _mapping(schema["properties"])
    schema_version_property = _mapping(properties["schema_version"])
    schema_version_property["const"] = schema_version
    return schema


def _past_exam_types() -> dict[str, object]:
    sha = {"$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/sha256"}
    artifact = {
        "$ref": "eom://schemas/legacy-assessment/legacy-assessment-types/1.0#/$defs/artifactMemberPointer"
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/knowledge/knowledge-analysis-types/5.0",
        "title": "EOM Past-Exam Visual Knowledge Analysis Shared Types V5",
        "$defs": {
            "assessmentPageImageObservation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "page_input_id",
                    "source_role",
                    "physical_page",
                    "image_sha256",
                    "observation_state",
                    "anchor_ids",
                ],
                "properties": {
                    "page_input_id": {
                        "type": "string",
                        "pattern": "^assessmentpage_[0-9a-f]{32}$",
                    },
                    "source_role": {"enum": ["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"]},
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
                    "image_sha256": sha,
                    "observation_state": {"enum": ["OBSERVED", "UNCLEAR"]},
                    "anchor_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^anchor_[a-z0-9][a-z0-9_-]{0,63}$",
                        },
                    },
                },
            },
            "pastExamItemSource": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_kind",
                    "source_class",
                    "item_id",
                    "item_revision_id",
                    "lifecycle_state",
                    "artifact_member",
                    "extraction_acceptance_id",
                    "extraction_acceptance_sha256",
                    "extraction_acceptance_artifact",
                    "extraction_result_id",
                    "extraction_result_sha256",
                    "extraction_result_artifact",
                    "item_proposal_id",
                    "item_number",
                    "bundle",
                    "layout_observation",
                    "page_inputs",
                    "page_image_count",
                ],
                "properties": {
                    "source_kind": {"const": "APPROVED_ITEM_REVISION"},
                    "source_class": {"const": "PAST_EXAM"},
                    "item_id": {"type": "string", "pattern": "^item_[0-9a-f]{32}$"},
                    "item_revision_id": {
                        "type": "string",
                        "pattern": "^itemrev_[0-9a-f]{32}$",
                    },
                    "lifecycle_state": {"const": "APPROVED"},
                    "artifact_member": {
                        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/sourceArtifactMember"
                    },
                    "extraction_acceptance_id": {
                        "type": "string",
                        "pattern": "^itemacceptance_[0-9a-f]{32}$",
                    },
                    "extraction_acceptance_sha256": sha,
                    "extraction_acceptance_artifact": artifact,
                    "extraction_result_id": {
                        "type": "string",
                        "pattern": "^itemextractresult_[0-9a-f]{32}$",
                    },
                    "extraction_result_sha256": sha,
                    "extraction_result_artifact": artifact,
                    "item_proposal_id": {
                        "type": "string",
                        "pattern": "^itemproposal_[0-9a-f]{32}$",
                    },
                    "item_number": {"type": "integer", "minimum": 1, "maximum": 10000},
                    "bundle": {
                        "$ref": "eom://schemas/legacy-assessment/legacy-assessment-types/1.0#/$defs/assessmentSourceBundlePointer"
                    },
                    "layout_observation": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "assessment_layout_observation_id",
                            "artifact",
                            "workspace_relative_path",
                            "observation_sha256",
                        ],
                        "properties": {
                            "assessment_layout_observation_id": {
                                "type": "string",
                                "pattern": "^assessmentlayout_[0-9a-f]{32}$",
                            },
                            "artifact": artifact,
                            "workspace_relative_path": {"const": "source/layout-observation.json"},
                            "observation_sha256": sha,
                        },
                    },
                    "page_inputs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {
                            "$ref": "eom://schemas/legacy-assessment/legacy-assessment-types/1.0#/$defs/pageImageInput"
                        },
                    },
                    "page_image_count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 32,
                    },
                },
            },
        },
    }


def build_contracts() -> dict[str, dict[str, object]]:
    types = _past_exam_types()
    definitions = _mapping(types["$defs"])
    observation = copy.deepcopy(_mapping(definitions["assessmentPageImageObservation"]))
    observation.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/assessment-page-image-observation/2.0",
            "title": "EOM Past-Exam Page Image Observation V2",
        }
    )

    proposal = _versioned_copy(
        KNOWLEDGE_ROOT,
        "knowledge-analysis-worker-proposal-v6.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-worker-proposal/7.0",
        title="EOM Past-Exam Visual Knowledge Analysis Worker Proposal V7",
        schema_version="knowledge-analysis-worker-proposal/7.0",
    )
    proposal_properties = _mapping(proposal["properties"])
    _mapping(proposal_properties["anchors"])["minItems"] = 1
    _mapping(proposal_properties["page_image_observations"])["items"] = {
        "$ref": (
            "eom://schemas/knowledge/knowledge-analysis-types/5.0"
            "#/$defs/assessmentPageImageObservation"
        )
    }

    request = _versioned_copy(
        KNOWLEDGE_ROOT,
        "knowledge-analysis-request-v8.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-request/9.0",
        title="EOM Past-Exam Visual Knowledge Analysis Request V9",
        schema_version="knowledge-analysis-request/9.0",
    )
    request_properties = _mapping(request["properties"])
    request_properties["source"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/5.0#/$defs/pastExamItemSource"
    }
    _mapping(request_properties["worker_proposal_schema_ref"])["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/7.0"
    )
    _mapping(request_properties["accepted_result_schema_ref"])["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/9.0"
    )

    receipt = _versioned_copy(
        KNOWLEDGE_ROOT,
        "knowledge-analysis-proposal-receipt-v7.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/8.0",
        title="EOM Past-Exam Visual Knowledge Analysis Proposal Receipt V8",
        schema_version="knowledge-analysis-proposal-receipt/8.0",
    )
    receipt_properties = _mapping(receipt["properties"])
    receipt_properties["source"] = request_properties["source"]

    result = _versioned_copy(
        KNOWLEDGE_ROOT,
        "knowledge-analysis-result-v8.schema.json",
        schema_id="eom://schemas/knowledge/knowledge-analysis-result/9.0",
        title="EOM Accepted Past-Exam Visual Knowledge Analysis Result V9",
        schema_version="knowledge-analysis-result/9.0",
    )
    result_properties = _mapping(result["properties"])
    result_properties["source"] = request_properties["source"]
    return {
        "knowledge-analysis-types-v5.schema.json": types,
        "knowledge-assessment-page-image-observation-v2.schema.json": observation,
        "knowledge-analysis-worker-proposal-v7.schema.json": proposal,
        "knowledge-analysis-request-v9.schema.json": request,
        "knowledge-analysis-proposal-receipt-v8.schema.json": receipt,
        "knowledge-analysis-result-v9.schema.json": result,
    }


def build_workflow_contracts() -> dict[str, dict[str, object]]:
    worker_input = _versioned_copy(
        ROLE_ROOT,
        "knowledge-analysis-input-v8.schema.json",
        schema_id="https://eom.local/schemas/workflow/roles/knowledge-analysis-input-v9.schema.json",
        title="EOM Past-Exam Visual Knowledge Analysis Worker Input V9",
        schema_version="1.0",
    )
    worker_input_properties = _mapping(worker_input["properties"])
    _mapping(worker_input_properties["protocol_version"])["const"] = "workflow-role/1.18.0"
    worker_input_defs = _mapping(worker_input["$defs"])
    worker_input_request = _mapping(worker_input_defs["request"])
    worker_input_request_properties = _mapping(worker_input_request["properties"])
    _mapping(worker_input_request_properties["analysis_request"])["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-request/9.0"
    )

    worker_result = _versioned_copy(
        ROLE_ROOT,
        "knowledge-analysis-proposal-result-v8.schema.json",
        schema_id=(
            "https://eom.local/schemas/workflow/roles/"
            "knowledge-analysis-proposal-result-v9.schema.json"
        ),
        title="EOM Past-Exam Visual Knowledge Analysis Proposal Result V9",
        schema_version="1.0",
    )
    worker_result_properties = _mapping(worker_result["properties"])
    _mapping(worker_result_properties["protocol_version"])["const"] = "workflow-role/1.18.0"
    worker_result_defs = _mapping(worker_result["$defs"])
    worker_result_output = _mapping(worker_result_defs["output"])
    worker_result_output_properties = _mapping(worker_result_output["properties"])
    _mapping(worker_result_output_properties["proposal"])["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/7.0"
    )
    return {
        "knowledge-analysis-input-v9.schema.json": worker_input,
        "knowledge-analysis-proposal-result-v9.schema.json": worker_result,
    }


def build_control_contracts() -> dict[str, dict[str, object]]:
    plan = _versioned_copy(
        CONTROL_ROOT,
        "resolved-execution-plan-v5.schema.json",
        schema_id="eom://schemas/workflow/resolved-execution-plan/8.0",
        title="EOM Past-Exam Visual Item Analysis Resolved Execution Plan V8",
        schema_version="resolved-execution-plan/8.0",
    )
    properties = _mapping(plan["properties"])
    required = plan["required"]
    if not isinstance(required, list) or required.count("document_source") != 1:
        raise ValueError("resolved plan source requirement is not projectable")
    plan["required"] = ["item_source" if item == "document_source" else item for item in required]
    properties["item_source"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/5.0#/$defs/pastExamItemSource"
    }
    del properties["document_source"]
    _mapping(properties["resolver_version"])["const"] = "8.0.0"
    return {"resolved-execution-plan-v8.schema.json": plan}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_contracts().items()
    }
    targets = {name: (KNOWLEDGE_ROOT / name, KNOWLEDGE_RESOURCE_ROOT / name) for name in rendered}
    role_rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_workflow_contracts().items()
    }
    rendered.update(role_rendered)
    targets.update({name: (ROLE_ROOT / name, ROLE_RESOURCE_ROOT / name) for name in role_rendered})
    control_rendered = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for name, value in build_control_contracts().items()
    }
    rendered.update(control_rendered)
    targets.update(
        {name: (CONTROL_ROOT / name, CONTROL_RESOURCE_ROOT / name) for name in control_rendered}
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

#!/usr/bin/env python3
"""Build additive past-exam solution-analysis V10 contracts."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "schemas/knowledge"
KNOWLEDGE_PACKAGE = ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
ROLES = ROOT / "schemas/workflow/roles"
ROLES_PACKAGE = ROOT / "packages/workflow/eom_workflow/resources/roles"
CONTROL = ROOT / "schemas/workflow/control-plane"
CONTROL_PACKAGE = ROOT / "packages/workflow/eom_workflow/resources/control-plane"

SCHEMA = "https://json-schema.org/draft/2020-12/schema"
SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
UTC = {
    "type": "string",
    "format": "date-time",
    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$",
}


def _load(root: Path, name: str) -> dict[str, object]:
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("schema root must be an object")
    return cast(dict[str, object], value)


def _map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("schema member must be an object")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("schema member must be an array")
    return cast(list[object], value)


def _artifact_member(*, path: str, schema_ref: str) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "artifact_id",
            "artifact_revision_id",
            "member_path",
            "sha256",
            "bytes",
            "schema_ref",
            "media_type",
            "logical_name",
        ],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {"type": "string", "pattern": "^rev_[0-9a-f]{32}$"},
            "member_path": {"const": path},
            "sha256": SHA,
            "bytes": {"type": "integer", "minimum": 1, "maximum": 2 * 1024 * 1024},
            "schema_ref": {"const": schema_ref},
            "media_type": {"const": "application/json"},
            "logical_name": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"},
        },
    }


def _solution_types() -> dict[str, object]:
    node_id = {
        "type": "string",
        "pattern": (
            "^knode_(?:concept|claim|process|observable_property|formula|item_element|"
            "assessment_pattern)_[a-z0-9][a-z0-9_-]{0,31}$"
        ),
    }
    anchor_id = {"type": "string", "pattern": "^anchor_[a-z0-9][a-z0-9_-]{0,63}$"}
    step_id = {"type": "string", "pattern": "^solutionstep_[a-z0-9][a-z0-9_-]{0,47}$"}
    text = {"type": "string", "minLength": 1, "maxLength": 4000}
    short_text = {"type": "string", "minLength": 1, "maxLength": 1000}
    typed_node = {
        "type": "object",
        "additionalProperties": False,
        "required": ["node_id", "node_type"],
        "properties": {
            "node_id": node_id,
            "node_type": {
                "enum": [
                    "CONCEPT",
                    "CLAIM",
                    "PROCESS",
                    "OBSERVABLE_PROPERTY",
                    "FORMULA",
                    "ITEM_ELEMENT",
                    "ASSESSMENT_PATTERN",
                ]
            },
        },
    }
    pointer_ref = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/proposalArtifactMember"
    }
    base_members = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "normalized_markdown",
            "anchors",
            "nodes",
            "edges",
            "claims",
            "component_observations",
            "page_image_observations",
            "unresolved_ambiguities",
        ],
        "properties": {
            name: copy.deepcopy(pointer_ref)
            for name in (
                "normalized_markdown",
                "anchors",
                "nodes",
                "edges",
                "claims",
                "component_observations",
                "page_image_observations",
                "unresolved_ambiguities",
            )
        },
    }
    base_counts = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-types/4.0#/$defs/proposalCountsV2"
    }
    reference_index = {
        "type": "object",
        "additionalProperties": False,
        "required": ["anchor_ids", "nodes", "index_sha256"],
        "properties": {
            "anchor_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1024,
                "uniqueItems": True,
                "items": anchor_id,
            },
            "nodes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 512,
                "uniqueItems": True,
                "items": typed_node,
            },
            "index_sha256": SHA,
        },
    }
    base_analysis = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "analysis_run_id",
            "analysis_result_id",
            "analysis_request_id",
            "accepted_result_sha256",
            "accepted_result_artifact",
            "proposal_receipt",
            "proposal_content_set_sha256",
            "base_members",
            "base_counts",
            "reference_index",
        ],
        "properties": {
            "analysis_run_id": {
                "type": "string",
                "pattern": "^analysisrun_[0-9a-f]{32}$",
            },
            "analysis_result_id": {
                "type": "string",
                "pattern": "^knowledgeanalysisresult_[0-9a-f]{32}$",
            },
            "analysis_request_id": {
                "type": "string",
                "pattern": "^knowledgeanalysis_[0-9a-f]{32}$",
            },
            "accepted_result_sha256": SHA,
            "accepted_result_artifact": _artifact_member(
                path="evidence/accepted-result.json",
                schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
            ),
            "proposal_receipt": _artifact_member(
                path="normalized/proposal-receipt.json",
                schema_ref="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/8.0",
            ),
            "proposal_content_set_sha256": SHA,
            "base_members": base_members,
            "base_counts": base_counts,
            "reference_index": reference_index,
        },
    }
    solution_step = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "step_id",
            "ordinal",
            "operation",
            "rationale",
            "outcome",
            "depends_on_step_ids",
            "node_ids",
            "item_element_node_ids",
            "anchor_ids",
        ],
        "properties": {
            "step_id": step_id,
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 64},
            "operation": {
                "enum": [
                    "INTERPRET_GIVEN",
                    "APPLY_CONCEPT",
                    "TRANSFORM_RELATION",
                    "CALCULATE",
                    "EVALUATE_STATEMENT",
                    "EVALUATE_CHOICE",
                    "CONCLUDE",
                ]
            },
            "rationale": text,
            "outcome": text,
            "depends_on_step_ids": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": step_id,
            },
            "node_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": node_id,
            },
            "item_element_node_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^knode_item_element_[a-z0-9][a-z0-9_-]{0,31}$",
                },
            },
            "anchor_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": anchor_id,
            },
        },
    }
    concept_link = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "concept_node_id",
            "role",
            "reasoning_step_ids",
            "assessment_pattern_node_ids",
            "item_element_node_ids",
            "summary",
        ],
        "properties": {
            "concept_node_id": {
                "type": "string",
                "pattern": (
                    "^knode_(?:concept|process|observable_property|formula)_"
                    "[a-z0-9][a-z0-9_-]{0,31}$"
                ),
            },
            "role": {
                "enum": [
                    "GIVEN_INTERPRETATION",
                    "REQUIRED_KNOWLEDGE",
                    "INFERENCE_OPERATION",
                    "ANSWER_CRITERION",
                    "DISTRACTOR_TARGET",
                ]
            },
            "reasoning_step_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": step_id,
            },
            "assessment_pattern_node_ids": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^knode_assessment_pattern_[a-z0-9][a-z0-9_-]{0,31}$",
                },
            },
            "item_element_node_ids": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^knode_item_element_[a-z0-9][a-z0-9_-]{0,31}$",
                },
            },
            "summary": short_text,
        },
        "anyOf": [
            {"properties": {"assessment_pattern_node_ids": {"minItems": 1}}},
            {"properties": {"item_element_node_ids": {"minItems": 1}}},
        ],
    }
    choice = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "choice_key",
            "verdict",
            "rationale",
            "targeted_misconception",
            "reasoning_step_ids",
            "node_ids",
            "anchor_ids",
        ],
        "properties": {
            "choice_key": {"type": "string", "minLength": 1, "maxLength": 64},
            "verdict": {"enum": ["CORRECT", "INCORRECT", "NOT_APPLICABLE"]},
            "rationale": text,
            "targeted_misconception": {
                "oneOf": [short_text, {"type": "null"}],
            },
            "reasoning_step_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": step_id,
            },
            "node_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": node_id,
            },
            "anchor_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": anchor_id,
            },
        },
    }
    comparison = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "summary", "answer_explanation_anchor_ids"],
        "properties": {
            "status": {"enum": ["CONSISTENT", "PARTIAL", "CONFLICT", "UNAVAILABLE"]},
            "summary": text,
            "answer_explanation_anchor_ids": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": anchor_id,
            },
        },
    }
    issue = {
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "summary", "anchor_ids"],
        "properties": {
            "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,63}$"},
            "summary": short_text,
            "anchor_ids": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": anchor_id,
            },
        },
    }
    report = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "analysis_request_id",
            "base_analysis_result_id",
            "rationale_kind",
            "solution_steps",
            "concept_assessment_links",
            "choice_diagnostics",
            "official_explanation_comparison",
            "final_answer_summary",
            "solution_summary",
            "assessment_design_summary",
            "reusable_generation_guidance",
            "unresolved_issues",
            "general_knowledge_used",
        ],
        "properties": {
            "schema_version": {"const": "knowledge-analysis-solution-report/1.0"},
            "analysis_request_id": {
                "type": "string",
                "pattern": "^knowledgeanalysis_[0-9a-f]{32}$",
            },
            "base_analysis_result_id": {
                "type": "string",
                "pattern": "^knowledgeanalysisresult_[0-9a-f]{32}$",
            },
            "rationale_kind": {"const": "VERIFIABLE_SOLUTION_RATIONALE"},
            "solution_steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "uniqueItems": True,
                "items": solution_step,
            },
            "concept_assessment_links": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "uniqueItems": True,
                "items": concept_link,
            },
            "choice_diagnostics": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": choice,
            },
            "official_explanation_comparison": comparison,
            "final_answer_summary": text,
            "solution_summary": {"type": "string", "minLength": 1, "maxLength": 8000},
            "assessment_design_summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 8000,
            },
            "reusable_generation_guidance": {
                "type": "string",
                "minLength": 1,
                "maxLength": 8000,
            },
            "unresolved_issues": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": issue,
            },
            "general_knowledge_used": {"type": "boolean"},
        },
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0",
        "title": "EOM Past-Exam Solution Analysis Shared Types V1",
        "$defs": {
            "typedReferenceNode": typed_node,
            "referenceIndex": reference_index,
            "baseAnalysis": base_analysis,
            "solutionStep": solution_step,
            "conceptAssessmentLink": concept_link,
            "choiceDiagnostic": choice,
            "officialExplanationComparison": comparison,
            "unresolvedIssue": issue,
            "solutionReport": report,
        },
    }


def build_contracts() -> dict[str, dict[str, object]]:
    types = _solution_types()
    report = copy.deepcopy(_map(_map(types["$defs"])["solutionReport"]))
    report.update(
        {
            "$schema": SCHEMA,
            "$id": "eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
            "title": "EOM Verifiable Past-Exam Solution Report V1",
        }
    )
    request = _load(KNOWLEDGE, "knowledge-analysis-request-v9.schema.json")
    request["$id"] = "eom://schemas/knowledge/knowledge-analysis-request/10.0"
    request["title"] = "EOM Additive Past-Exam Solution Analysis Request V10"
    props = _map(request["properties"])
    _map(props["schema_version"])["const"] = "knowledge-analysis-request/10.0"
    _map(props["worker_proposal_schema_ref"])["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0"
    )
    _map(props["accepted_result_schema_ref"])["const"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/10.0"
    )
    props["predecessor_analysis_run_id"] = {
        "type": "string",
        "pattern": "^analysisrun_[0-9a-f]{32}$",
    }
    props["requested_outputs"] = {
        "type": "array",
        "prefixItems": [{"const": "SOLUTION_REPORT"}],
        "items": False,
        "minItems": 1,
        "maxItems": 1,
    }
    props["base_analysis"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/baseAnalysis"
    }
    required = _array(request["required"])
    if "base_analysis" not in required:
        required.append("base_analysis")

    proposal = {
        "$schema": SCHEMA,
        "$id": "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0",
        "title": "EOM Additive Past-Exam Solution Worker Proposal V8",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "analysis_request_id",
            "base_analysis_result_id",
            "solution_report",
            "completed_at",
        ],
        "properties": {
            "schema_version": {"const": "knowledge-analysis-worker-proposal/8.0"},
            "analysis_request_id": {
                "type": "string",
                "pattern": "^knowledgeanalysis_[0-9a-f]{32}$",
            },
            "base_analysis_result_id": {
                "type": "string",
                "pattern": "^knowledgeanalysisresult_[0-9a-f]{32}$",
            },
            "solution_report": {
                "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/solutionReport"
            },
            "completed_at": UTC,
        },
    }
    counts = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "solution_steps",
            "concept_assessment_links",
            "choice_diagnostics",
            "unresolved_issues",
        ],
        "properties": {
            "solution_steps": {"type": "integer", "minimum": 1, "maximum": 64},
            "concept_assessment_links": {"type": "integer", "minimum": 1, "maximum": 64},
            "choice_diagnostics": {"type": "integer", "minimum": 0, "maximum": 32},
            "unresolved_issues": {"type": "integer", "minimum": 0, "maximum": 32},
        },
    }
    receipt = {
        "$schema": SCHEMA,
        "$id": "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0",
        "title": "EOM Additive Past-Exam Solution Proposal Receipt V9",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "analysis_request_id",
            "source",
            "base_analysis",
            "status",
            "solution_report",
            "solution_counts",
            "general_knowledge_used",
            "content_set_sha256",
            "completed_at",
        ],
        "properties": {
            "schema_version": {"const": "knowledge-analysis-proposal-receipt/9.0"},
            "analysis_request_id": {
                "type": "string",
                "pattern": "^knowledgeanalysis_[0-9a-f]{32}$",
            },
            "source": {
                "$ref": "eom://schemas/knowledge/knowledge-analysis-types/5.0#/$defs/pastExamItemSource"
            },
            "base_analysis": {
                "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/baseAnalysis"
            },
            "status": {"const": "PROPOSED_VALIDATED"},
            "solution_report": {
                "$ref": "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/proposalArtifactMember"
            },
            "solution_counts": counts,
            "general_knowledge_used": {"type": "boolean"},
            "content_set_sha256": SHA,
            "completed_at": UTC,
        },
    }
    result = _load(KNOWLEDGE, "knowledge-analysis-result-v9.schema.json")
    result["$id"] = "eom://schemas/knowledge/knowledge-analysis-result/10.0"
    result["title"] = "EOM Accepted Additive Past-Exam Solution Analysis Result V10"
    rprops = _map(result["properties"])
    _map(rprops["schema_version"])["const"] = "knowledge-analysis-result/10.0"
    rprops["base_analysis"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/baseAnalysis"
    }
    rprops["solution_counts"] = counts
    rrequired = _array(result["required"])
    for field in ("base_analysis", "solution_counts"):
        if field not in rrequired:
            rrequired.append(field)
    return {
        "knowledge-analysis-solution-types-v1.schema.json": types,
        "knowledge-analysis-solution-report-v1.schema.json": report,
        "knowledge-analysis-worker-proposal-v8.schema.json": proposal,
        "knowledge-analysis-request-v10.schema.json": request,
        "knowledge-analysis-proposal-receipt-v9.schema.json": receipt,
        "knowledge-analysis-result-v10.schema.json": result,
    }


def build_role_contracts() -> dict[str, dict[str, object]]:
    worker_input = _load(ROLES, "knowledge-analysis-input-v9.schema.json")
    worker_input["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-input-v10.schema.json"
    )
    worker_input["title"] = "EOM Additive Past-Exam Solution Analysis Worker Input V10"
    iprops = _map(worker_input["properties"])
    _map(iprops["protocol_version"])["const"] = "workflow-role/1.21.0"
    idefs = _map(worker_input["$defs"])
    request_props = _map(_map(idefs["request"])["properties"])
    _map(request_props["analysis_request"])["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-request/10.0"
    )

    worker_result = _load(ROLES, "knowledge-analysis-proposal-result-v9.schema.json")
    worker_result["$id"] = (
        "https://eom.local/schemas/workflow/roles/knowledge-analysis-proposal-result-v10.schema.json"
    )
    worker_result["title"] = "EOM Additive Past-Exam Solution Analysis Result V10"
    oprops = _map(worker_result["properties"])
    _map(oprops["protocol_version"])["const"] = "workflow-role/1.21.0"
    odefs = _map(worker_result["$defs"])
    output_props = _map(_map(odefs["output"])["properties"])
    _map(output_props["proposal"])["$ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0"
    )
    return {
        "knowledge-analysis-input-v10.schema.json": worker_input,
        "knowledge-analysis-proposal-result-v10.schema.json": worker_result,
    }


def build_control_contracts() -> dict[str, dict[str, object]]:
    plan = _load(CONTROL, "resolved-execution-plan-v8.schema.json")
    plan["$id"] = "eom://schemas/workflow/resolved-execution-plan/9.0"
    plan["title"] = "EOM Additive Past-Exam Solution Analysis Resolved Plan V9"
    props = _map(plan["properties"])
    _map(props["schema_version"])["const"] = "resolved-execution-plan/9.0"
    _map(props["resolver_version"])["const"] = "9.0.0"
    props["base_analysis"] = {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/baseAnalysis"
    }
    required = _array(plan["required"])
    if "base_analysis" not in required:
        required.append("base_analysis")
    return {"resolved-execution-plan-v9.schema.json": plan}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    groups = (
        (build_contracts(), KNOWLEDGE, KNOWLEDGE_PACKAGE),
        (build_role_contracts(), ROLES, ROLES_PACKAGE),
        (build_control_contracts(), CONTROL, CONTROL_PACKAGE),
    )
    mismatched = False
    for documents, canonical_root, package_root in groups:
        for name, document in documents.items():
            payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
            for path in (canonical_root / name, package_root / name):
                if args.check:
                    mismatched = mismatched or not path.is_file() or path.read_bytes() != payload
                else:
                    path.write_bytes(payload)
    return int(mismatched)


if __name__ == "__main__":
    raise SystemExit(main())

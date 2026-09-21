#!/usr/bin/env python3
"""Generate protocol-first verification-planned review schemas without changing V11 bytes."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROLE_ROOT = ROOT / "schemas/workflow/roles"
PACKAGE_ROLE_ROOT = ROOT / "packages/workflow/eom_workflow/resources/roles"
CANONICAL_CONTROL_ROOT = ROOT / "schemas/workflow/control-plane"
PACKAGE_CONTROL_ROOT = ROOT / "packages/workflow/eom_workflow/resources/control-plane"
CANONICAL_WORKFLOW_ROOT = ROOT / "schemas/workflow"
PACKAGE_WORKFLOW_ROOT = ROOT / "packages/workflow/eom_workflow/resources"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"schema is not an object: {path}")
    return value


def _bytes(value: dict[str, Any]) -> bytes:
    Draft202012Validator.check_schema(value)
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_pair(
    file_name: str,
    value: dict[str, Any],
    *,
    control: bool = False,
    workflow: bool = False,
) -> None:
    if control and workflow:
        raise ValueError("schema output family is ambiguous")
    if control:
        roots = (CANONICAL_CONTROL_ROOT, PACKAGE_CONTROL_ROOT)
    elif workflow:
        roots = (CANONICAL_WORKFLOW_ROOT, PACKAGE_WORKFLOW_ROOT)
    else:
        roots = (CANONICAL_ROLE_ROOT, PACKAGE_ROLE_ROOT)
    payload = _bytes(value)
    for root in roots:
        (root / file_name).write_bytes(payload)


def _replace_exact(value: object, old: str, new: str) -> object:
    if isinstance(value, dict):
        return {key: _replace_exact(child, old, new) for key, child in value.items()}
    if isinstance(value, list):
        return [_replace_exact(child, old, new) for child in value]
    return new if value == old else value


def _role_wrapper(role: str) -> dict[str, Any]:
    value = _replace_exact(
        _load(PACKAGE_ROLE_ROOT / f"{role}-result-v11.schema.json"),
        "workflow-role/1.23.0",
        "workflow-role/1.24.0",
    )
    value = _replace_exact(value, f"{role}-result@11.0", f"{role}-result@12.0")
    if not isinstance(value, dict):
        raise TypeError("role schema replacement is not an object")
    value["$id"] = f"https://eom.local/schemas/workflow/roles/{role}-result-v12.schema.json"
    value["title"] = str(value["title"]).replace("V11", "V12")
    return value


def _string_array(*, minimum: int, maximum: int, pattern: str | None = None) -> dict[str, Any]:
    items: dict[str, Any] = {"type": "string"}
    if pattern is not None:
        items["pattern"] = pattern
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "items": items,
    }


def _draft_paths(*, minimum: int = 1, maximum: int = 32) -> dict[str, Any]:
    return _string_array(
        minimum=minimum,
        maximum=maximum,
        pattern=r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
    )


def _review_schema() -> dict[str, Any]:
    value = _role_wrapper("review")
    definitions = value["$defs"]
    if not isinstance(definitions, dict):
        raise TypeError("review schema definitions are missing")

    # The V12 review is still bound to exactly one V12 authoring Artifact.
    authoring_pointer = copy.deepcopy(definitions["EvidenceAuthoringArtifactPointerV2"])
    authoring_pointer["title"] = "EvidenceAuthoringArtifactPointerV3"
    authoring_pointer["properties"]["result_schema"] = {
        "const": "authoring-result@12.0",
        "title": "Result Schema",
        "type": "string",
    }
    definitions["EvidenceAuthoringArtifactPointerV3"] = authoring_pointer

    attestation = copy.deepcopy(definitions["EvidenceUsageReviewAttestationV2"])
    attestation["title"] = "EvidenceUsageReviewAttestationV3"
    attestation["properties"]["schema_version"] = {
        "const": "evidence-usage-review-attestation/3.0",
        "title": "Schema Version",
        "type": "string",
    }
    attestation["properties"]["authoring_artifact"] = {
        "$ref": "#/$defs/EvidenceAuthoringArtifactPointerV3"
    }
    definitions["EvidenceUsageReviewAttestationV3"] = attestation

    definitions["ReviewVerificationTargetV2"] = {
        "type": "object",
        "title": "ReviewVerificationTargetV2",
        "additionalProperties": False,
        "required": [
            "target_id",
            "target_kind",
            "draft_json_paths",
            "verification_terms",
            "required_source_classes",
            "selected_evidence_ids",
            "evidence_status",
            "conclusion",
        ],
        "properties": {
            "target_id": {
                "type": "string",
                "pattern": r"^target_[a-z0-9][a-z0-9_]{0,47}$",
            },
            "target_kind": {
                "enum": [
                    "SCIENTIFIC_CLAIM",
                    "ANSWER_DERIVATION",
                    "CHOICE_DIAGNOSTIC",
                    "STATEMENT_DIAGNOSTIC",
                    "EXPLANATION_CONSISTENCY",
                    "CURRICULUM_SCOPE",
                    "ORIGINALITY",
                    "VISUAL_RELATION",
                ]
            },
            "draft_json_paths": _draft_paths(maximum=16),
            "verification_terms": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "pattern": r"^[^\x00-\x1f\x7f]+$",
                },
            },
            "required_source_classes": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "CURRICULUM",
                        "TEXTBOOK",
                        "APPROVED_ITEM",
                        "PAST_EXAM",
                        "INTERNAL_GUIDE",
                    ]
                },
            },
            "selected_evidence_ids": _string_array(
                minimum=0,
                maximum=16,
                pattern=r"^evidenceitem_[0-9a-f]{32}$",
            ),
            "evidence_status": {"enum": ["SUPPORTED", "INSUFFICIENT", "NOT_APPLICABLE"]},
            "conclusion": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    }
    definitions["ReviewCandidateFindingV2"] = {
        "type": "object",
        "title": "ReviewCandidateFindingV2",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "finding_code",
            "axis",
            "draft_json_paths",
            "evidence_ids",
            "initial_observation",
            "disposition",
            "conclusion",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": r"^candidate_[a-z0-9][a-z0-9_]{0,47}$",
            },
            "finding_code": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,63}$"},
            "axis": {
                "enum": [
                    "ANSWER",
                    "CHOICE",
                    "STATEMENT",
                    "EXPLANATION",
                    "CURRICULUM",
                    "ORIGINALITY",
                    "VISUAL",
                    "MATERIAL",
                    "POLICY",
                ]
            },
            "draft_json_paths": _draft_paths(minimum=0, maximum=16),
            "evidence_ids": _string_array(
                minimum=0,
                maximum=16,
                pattern=r"^evidenceitem_[0-9a-f]{32}$",
            ),
            "initial_observation": {"type": "string", "minLength": 1, "maxLength": 2000},
            "disposition": {"enum": ["CONFIRMED", "DEMOTED", "UNCERTAIN"]},
            "conclusion": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    }
    definitions["ReviewSourceArtifactPointerV1"] = {
        "type": "object",
        "title": "ReviewSourceArtifactPointerV1",
        "additionalProperties": False,
        "required": [
            "logical_artifact_id",
            "revision_id",
            "content_hash",
            "result_schema",
        ],
        "properties": {
            "logical_artifact_id": {"type": "string", "pattern": r"^artifact_[0-9a-f]{32}$"},
            "revision_id": {"type": "string", "pattern": r"^rev_[0-9a-f]{32}$"},
            "content_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
            "result_schema": {"const": "review-result@12.0"},
        },
    }
    definitions["ReviewEscalationAssessmentV1"] = {
        "type": "object",
        "title": "ReviewEscalationAssessmentV1",
        "additionalProperties": False,
        "required": [
            "review_pass",
            "inspection_order",
            "structural_complexity_score",
            "reason_codes",
            "decision",
            "source_review_artifact",
        ],
        "properties": {
            "review_pass": {"enum": ["PRIMARY", "ESCALATED"]},
            "inspection_order": {"enum": ["VISUAL_FIRST", "CONTENT_FIRST"]},
            "structural_complexity_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "reason_codes": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "CANDIDATE_FINDING_PRESENT",
                        "COMPLEX_ITEM",
                        "EVIDENCE_GAP",
                        "EVIDENCE_UNCERTAINTY",
                        "VISUAL_RISK",
                    ]
                },
            },
            "decision": {"enum": ["NOT_REQUIRED", "REQUIRED", "COMPLETED"]},
            "source_review_artifact": {
                "anyOf": [
                    {"$ref": "#/$defs/ReviewSourceArtifactPointerV1"},
                    {"type": "null"},
                ]
            },
        },
    }

    report = copy.deepcopy(definitions["IndependentReviewReportV1"])
    report["title"] = "IndependentReviewReportV2"
    report["properties"]["schema_version"] = {"const": "independent-item-review/2.0"}
    report["required"].extend(
        ["verification_targets", "candidate_findings", "escalation_assessment"]
    )
    report["properties"].update(
        {
            "verification_targets": {
                "type": "array",
                "minItems": 8,
                "maxItems": 32,
                "items": {"$ref": "#/$defs/ReviewVerificationTargetV2"},
            },
            "candidate_findings": {
                "type": "array",
                "minItems": 0,
                "maxItems": 32,
                "items": {"$ref": "#/$defs/ReviewCandidateFindingV2"},
            },
            "escalation_assessment": {"$ref": "#/$defs/ReviewEscalationAssessmentV1"},
        }
    )
    definitions["IndependentReviewReportV2"] = report

    definitions["KnowledgeReviewOutputV12"] = {
        "type": "object",
        "title": "KnowledgeReviewOutputV12",
        "additionalProperties": False,
        "required": ["review", "independent_review_report", "evidence_usage_attestation"],
        "properties": {
            "review": {"$ref": "#/$defs/KnowledgeReview"},
            "independent_review_report": {"$ref": "#/$defs/IndependentReviewReportV2"},
            "evidence_usage_attestation": {
                "anyOf": [
                    {"$ref": "#/$defs/EvidenceUsageReviewAttestationV3"},
                    {"type": "null"},
                ]
            },
        },
    }
    value["properties"]["output"] = {"$ref": "#/$defs/KnowledgeReviewOutputV12"}
    value["title"] = "ContentTeamReviewRoleResultV12"
    return value


def _receipt_schema() -> dict[str, Any]:
    value = _replace_exact(
        _load(CANONICAL_CONTROL_ROOT / "evidence-usage-validation-receipt-v2.schema.json"),
        "evidence-usage-validation-receipt/2.0",
        "evidence-usage-validation-receipt/3.0",
    )
    value = _replace_exact(value, "authoring-result@11.0", "authoring-result@12.0")
    value = _replace_exact(value, "review-result@11.0", "review-result@12.0")
    if not isinstance(value, dict):
        raise TypeError("receipt schema replacement is not an object")
    value["$id"] = "eom://schemas/workflow/evidence-usage-validation-receipt/3.0"
    return value


def _plan_schema() -> dict[str, Any]:
    value = copy.deepcopy(_load(CANONICAL_CONTROL_ROOT / "resolved-execution-plan-v11.schema.json"))
    value["$id"] = "eom://schemas/workflow/resolved-execution-plan/12.0"
    value["properties"]["schema_version"] = {"const": "resolved-execution-plan/12.0"}
    step = value["properties"]["steps"]["items"]
    step["required"].append("escalation_candidate")
    step["properties"]["escalation_candidate"] = {
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["model", "reasoning_effort"],
                "properties": {
                    "model": {
                        "type": "string",
                        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                    },
                    "reasoning_effort": {"enum": ["minimal", "low", "medium", "high", "xhigh"]},
                },
            },
            {"type": "null"},
        ]
    }
    return value


def _directive_schema() -> dict[str, Any]:
    source = _load(CANONICAL_WORKFLOW_ROOT / "workflow-review-rework-directive-v1.schema.json")
    base_pointer = copy.deepcopy(source["$defs"]["basePointer"])
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/workflow/review-escalation-directive/1.0",
        "title": "Workflow Review Escalation Directive V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "workflow_id",
            "reviewed_authoring",
            "source_review",
            "source_attempt",
            "next_attempt",
            "reason_codes",
            "structural_complexity_score",
            "primary_model",
            "primary_reasoning_effort",
            "escalation_model",
            "escalation_reasoning_effort",
            "decision_sha256",
        ],
        "properties": {
            "schema_version": {"const": "workflow-review-escalation-directive/1.0"},
            "workflow_id": {"type": "string", "pattern": r"^workflow_[0-9a-f]{32}$"},
            "reviewed_authoring": {"$ref": "#/$defs/authoringPointer"},
            "source_review": {"$ref": "#/$defs/reviewPointer"},
            "source_attempt": {"type": "integer", "minimum": 1, "maximum": 10},
            "next_attempt": {"type": "integer", "minimum": 2, "maximum": 10},
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "CANDIDATE_FINDING_PRESENT",
                        "COMPLEX_ITEM",
                        "EVIDENCE_GAP",
                        "EVIDENCE_UNCERTAINTY",
                        "VISUAL_RISK",
                    ]
                },
            },
            "structural_complexity_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "primary_model": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            "primary_reasoning_effort": {"enum": ["minimal", "low", "medium", "high", "xhigh"]},
            "escalation_model": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
            },
            "escalation_reasoning_effort": {"enum": ["minimal", "low", "medium", "high", "xhigh"]},
            "decision_sha256": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        },
        "$defs": {
            "basePointer": base_pointer,
            "authoringPointer": {
                "allOf": [
                    {"$ref": "#/$defs/basePointer"},
                    {
                        "properties": {
                            "step_key": {"const": "authoring"},
                            "result_schema": {"const": "authoring-result@12.0"},
                        }
                    },
                ]
            },
            "reviewPointer": {
                "allOf": [
                    {"$ref": "#/$defs/basePointer"},
                    {
                        "properties": {
                            "step_key": {"const": "review"},
                            "result_schema": {"const": "review-result@12.0"},
                        }
                    },
                ]
            },
        },
    }


def _rework_directive_schema() -> dict[str, Any]:
    value = _replace_exact(
        _load(CANONICAL_WORKFLOW_ROOT / "workflow-review-rework-directive-v1.schema.json"),
        "workflow-review-rework-directive/1.0",
        "workflow-review-rework-directive/2.0",
    )
    value = _replace_exact(value, "authoring-result@11.0", "authoring-result@12.0")
    value = _replace_exact(value, "review-result@11.0", "review-result@12.0")
    if not isinstance(value, dict):
        raise TypeError("review rework schema replacement is not an object")
    value["$id"] = "eom://schemas/workflow/review-rework-directive/2.0"
    value["title"] = "Workflow Review Rework Directive V2"
    return value


def main() -> None:
    for role in ("authoring", "image", "registration"):
        _write_pair(f"{role}-result-v12.schema.json", _role_wrapper(role))
    _write_pair("review-result-v12.schema.json", _review_schema())
    _write_pair(
        "evidence-usage-validation-receipt-v3.schema.json",
        _receipt_schema(),
        control=True,
    )
    _write_pair("resolved-execution-plan-v12.schema.json", _plan_schema(), control=True)
    _write_pair(
        "workflow-review-escalation-directive-v1.schema.json",
        _directive_schema(),
        workflow=True,
    )
    _write_pair(
        "workflow-review-rework-directive-v2.schema.json",
        _rework_directive_schema(),
        workflow=True,
    )


if __name__ == "__main__":
    main()

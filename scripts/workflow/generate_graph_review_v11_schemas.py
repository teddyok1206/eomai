#!/usr/bin/env python3
"""Generate protocol-first Graph review successor schemas without touching V10 bytes."""

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


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"schema is not an object: {path}")
    return value


def _bytes(value: dict[str, Any]) -> bytes:
    Draft202012Validator.check_schema(value)
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_pair(file_name: str, value: dict[str, Any], *, control: bool = False) -> None:
    roots = (
        (CANONICAL_CONTROL_ROOT, PACKAGE_CONTROL_ROOT)
        if control
        else (CANONICAL_ROLE_ROOT, PACKAGE_ROLE_ROOT)
    )
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
    source_name = f"{role}-result-v10.schema.json"
    replaced = _replace_exact(
        _load(PACKAGE_ROLE_ROOT / source_name),
        "workflow-role/1.20.0",
        "workflow-role/1.23.0",
    )
    assert isinstance(replaced, dict)
    value: dict[str, Any] = replaced
    value["$id"] = f"https://eom.local/schemas/workflow/roles/{role}-result-v11.schema.json"
    value["title"] = str(value["title"]).replace("V10", "V11")
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

    authoring_pointer = copy.deepcopy(definitions["EvidenceAuthoringArtifactPointerV1"])
    authoring_pointer["title"] = "EvidenceAuthoringArtifactPointerV2"
    authoring_pointer["properties"]["result_schema"] = {
        "const": "authoring-result@11.0",
        "title": "Result Schema",
        "type": "string",
    }
    definitions["EvidenceAuthoringArtifactPointerV2"] = authoring_pointer

    attestation = copy.deepcopy(definitions["EvidenceUsageReviewAttestationV1"])
    attestation["title"] = "EvidenceUsageReviewAttestationV2"
    attestation["properties"]["schema_version"] = {
        "const": "evidence-usage-review-attestation/2.0",
        "title": "Schema Version",
        "type": "string",
    }
    attestation["properties"]["authoring_artifact"] = {
        "$ref": "#/$defs/EvidenceAuthoringArtifactPointerV2"
    }
    definitions["EvidenceUsageReviewAttestationV2"] = attestation

    definitions["ReviewEvidenceReferenceV1"] = {
        "type": "object",
        "title": "ReviewEvidenceReferenceV1",
        "additionalProperties": False,
        "required": ["evidence_id", "anchor_ids", "purposes"],
        "properties": {
            "evidence_id": {"type": "string", "pattern": r"^evidenceitem_[0-9a-f]{32}$"},
            "anchor_ids": _string_array(
                minimum=1,
                maximum=32,
                pattern=r"^anchor_[a-z0-9][a-z0-9_-]{0,63}$",
            ),
            "purposes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "SCIENTIFIC_VALIDATION",
                        "CURRICULUM_SCOPE",
                        "ORIGINALITY_CHECK",
                        "VISUAL_VALIDATION",
                    ]
                },
            },
        },
    }
    definitions["ReviewVerificationClaimV1"] = {
        "type": "object",
        "title": "ReviewVerificationClaimV1",
        "additionalProperties": False,
        "required": ["claim_key", "conclusion", "draft_json_paths", "evidence_ids"],
        "properties": {
            "claim_key": {"type": "string", "pattern": r"^claim_[a-z0-9][a-z0-9_]{0,31}$"},
            "conclusion": {"type": "string", "minLength": 1, "maxLength": 2000},
            "draft_json_paths": _draft_paths(maximum=16),
            "evidence_ids": _string_array(
                minimum=0,
                maximum=16,
                pattern=r"^evidenceitem_[0-9a-f]{32}$",
            ),
        },
    }
    definitions["IndependentAnswerReviewV1"] = {
        "type": "object",
        "title": "IndependentAnswerReviewV1",
        "additionalProperties": False,
        "required": [
            "authored_answer_number",
            "derived_answer_number",
            "alignment",
            "verification_summary",
            "claims",
        ],
        "properties": {
            "authored_answer_number": {"enum": ["①", "②", "③", "④", "⑤"]},
            "derived_answer_number": {"enum": ["①", "②", "③", "④", "⑤"]},
            "alignment": {"enum": ["MATCH", "MISMATCH"]},
            "verification_summary": {"type": "string", "minLength": 1, "maxLength": 4000},
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/ReviewVerificationClaimV1"},
            },
        },
    }
    definitions["ChoiceDiagnosticV1"] = {
        "type": "object",
        "title": "ChoiceDiagnosticV1",
        "additionalProperties": False,
        "required": ["number", "verdict", "rationale", "draft_json_paths", "evidence_ids"],
        "properties": {
            "number": {"enum": ["①", "②", "③", "④", "⑤"]},
            "verdict": {"enum": ["CORRECT", "DISTRACTOR"]},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
            "draft_json_paths": _draft_paths(maximum=8),
            "evidence_ids": _string_array(
                minimum=0,
                maximum=16,
                pattern=r"^evidenceitem_[0-9a-f]{32}$",
            ),
        },
    }
    definitions["StatementDiagnosticV1"] = {
        "type": "object",
        "title": "StatementDiagnosticV1",
        "additionalProperties": False,
        "required": ["label", "verdict", "rationale", "draft_json_paths", "evidence_ids"],
        "properties": {
            "label": {"enum": ["ㄱ", "ㄴ", "ㄷ"]},
            "verdict": {"enum": ["TRUE", "FALSE"]},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
            "draft_json_paths": _draft_paths(maximum=8),
            "evidence_ids": _string_array(
                minimum=0,
                maximum=16,
                pattern=r"^evidenceitem_[0-9a-f]{32}$",
            ),
        },
    }

    def assessment(name: str, statuses: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "title": name,
            "additionalProperties": False,
            "required": ["status", "rationale", "draft_json_paths", "evidence_ids"],
            "properties": {
                "status": {"enum": statuses},
                "rationale": {"type": "string", "minLength": 1, "maxLength": 3000},
                "draft_json_paths": _draft_paths(minimum=0, maximum=16),
                "evidence_ids": _string_array(
                    minimum=0,
                    maximum=16,
                    pattern=r"^evidenceitem_[0-9a-f]{32}$",
                ),
            },
        }

    definitions["ExplanationAssessmentV1"] = assessment("ExplanationAssessmentV1", ["PASS", "FAIL"])
    definitions["CurriculumAssessmentV1"] = assessment(
        "CurriculumAssessmentV1", ["IN_SCOPE", "OUT_OF_SCOPE", "UNCERTAIN"]
    )
    definitions["OriginalityAssessmentV1"] = assessment(
        "OriginalityAssessmentV1", ["DISTINCT", "TOO_SIMILAR", "INSUFFICIENT_EVIDENCE"]
    )
    definitions["VisualAssessmentV1"] = assessment(
        "VisualAssessmentV1", ["CONSISTENT", "INCONSISTENT", "NOT_APPLICABLE"]
    )
    definitions["IndependentReviewReportV1"] = {
        "type": "object",
        "title": "IndependentReviewReportV1",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "evidence_references",
            "answer_review",
            "choice_diagnostics",
            "statement_diagnostics",
            "explanation_assessment",
            "curriculum_assessment",
            "originality_assessment",
            "visual_assessment",
        ],
        "properties": {
            "schema_version": {"const": "independent-item-review/1.0"},
            "evidence_references": {
                "type": "array",
                "minItems": 0,
                "maxItems": 64,
                "items": {"$ref": "#/$defs/ReviewEvidenceReferenceV1"},
            },
            "answer_review": {"$ref": "#/$defs/IndependentAnswerReviewV1"},
            "choice_diagnostics": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {"$ref": "#/$defs/ChoiceDiagnosticV1"},
            },
            "statement_diagnostics": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {"$ref": "#/$defs/StatementDiagnosticV1"},
            },
            "explanation_assessment": {"$ref": "#/$defs/ExplanationAssessmentV1"},
            "curriculum_assessment": {"$ref": "#/$defs/CurriculumAssessmentV1"},
            "originality_assessment": {"$ref": "#/$defs/OriginalityAssessmentV1"},
            "visual_assessment": {"$ref": "#/$defs/VisualAssessmentV1"},
        },
    }
    definitions["KnowledgeReviewOutputV11"] = {
        "type": "object",
        "title": "KnowledgeReviewOutputV11",
        "additionalProperties": False,
        "required": ["review", "independent_review_report", "evidence_usage_attestation"],
        "properties": {
            "review": {"$ref": "#/$defs/KnowledgeReview"},
            "independent_review_report": {"$ref": "#/$defs/IndependentReviewReportV1"},
            "evidence_usage_attestation": {
                "anyOf": [
                    {"$ref": "#/$defs/EvidenceUsageReviewAttestationV2"},
                    {"type": "null"},
                ]
            },
        },
    }
    value["properties"]["output"] = {"$ref": "#/$defs/KnowledgeReviewOutputV11"}
    value["title"] = "ContentTeamReviewRoleResultV11"
    return value


def _receipt_schema() -> dict[str, Any]:
    value = _load(CANONICAL_CONTROL_ROOT / "evidence-usage-validation-receipt-v1.schema.json")
    value["$id"] = "eom://schemas/workflow/evidence-usage-validation-receipt/2.0"
    value["properties"]["schema_version"] = {"const": "evidence-usage-validation-receipt/2.0"}
    value["$defs"]["manifestArtifactMemberPointer"]["allOf"][1]["properties"]["schema_ref"] = {
        "const": "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
    }
    value["$defs"]["resultArtifactPointer"]["properties"]["result_schema"]["enum"] = [
        "authoring-result@11.0",
        "review-result@11.0",
    ]
    value["properties"]["independent_review_report_sha256"] = {
        "anyOf": [
            {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
            {"type": "null"},
        ]
    }
    value["properties"]["review_evidence_set_sha256"] = {
        "anyOf": [
            {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
            {"type": "null"},
        ]
    }
    conditional = value["allOf"][0]
    conditional["then"]["not"]["anyOf"].extend(
        [
            {"required": ["independent_review_report_sha256"]},
            {"required": ["review_evidence_set_sha256"]},
        ]
    )
    conditional["then"]["properties"]["result_artifact"]["properties"]["result_schema"] = {
        "const": "authoring-result@11.0"
    }
    conditional["else"]["required"].extend(
        ["independent_review_report_sha256", "review_evidence_set_sha256"]
    )
    conditional["else"]["properties"]["result_artifact"]["properties"]["result_schema"] = {
        "const": "review-result@11.0"
    }
    conditional["else"]["properties"]["authoring_artifact"]["properties"]["result_schema"] = {
        "const": "authoring-result@11.0"
    }
    conditional["else"]["properties"]["independent_review_report_sha256"] = {
        "type": "string",
        "pattern": r"^sha256:[0-9a-f]{64}$",
    }
    conditional["else"]["properties"]["review_evidence_set_sha256"] = {
        "type": "string",
        "pattern": r"^sha256:[0-9a-f]{64}$",
    }
    return value


def main() -> None:
    for role in ("authoring", "image", "registration"):
        _write_pair(f"{role}-result-v11.schema.json", _role_wrapper(role))
    _write_pair("review-result-v11.schema.json", _review_schema())
    _write_pair(
        "evidence-usage-validation-receipt-v2.schema.json",
        _receipt_schema(),
        control=True,
    )
    plan = _load(CANONICAL_CONTROL_ROOT / "resolved-execution-plan-v3.schema.json")
    plan["$id"] = "eom://schemas/workflow/resolved-execution-plan/11.0"
    plan["properties"]["schema_version"] = {"const": "resolved-execution-plan/11.0"}
    plan["properties"]["evidence_manifest_artifact"] = {
        "allOf": [
            {"$ref": "#/$defs/knowledgeArtifactPointer"},
            {
                "properties": {
                    "member_path": {"const": "evidence/manifest.json"},
                    "media_type": {"const": "application/json"},
                    "schema_ref": {"const": "eom://schemas/knowledge/evidence-bundle-manifest/5.0"},
                }
            },
        ]
    }
    _write_pair("resolved-execution-plan-v11.schema.json", plan, control=True)


if __name__ == "__main__":
    main()

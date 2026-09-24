#!/usr/bin/env python3
"""Generate the exhaustive Graph-grounded paired document-review role schemas."""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/roles"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/roles"
V2 = runpy.run_path(str(Path(__file__).with_name("generate_paired_document_review_v2_schemas.py")))
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
NO_CONTROL = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"
AXES = [
    "SCIENTIFIC_ACCURACY",
    "ANSWER_UNIQUENESS",
    "SOLUTION_CONSISTENCY",
    "CURRICULUM_SCOPE",
    "ORIGINALITY",
    "VISUAL_CONTENT",
    "EDITORIAL_CLARITY",
    "TYPOGRAPHY",
    "DOCUMENT_STRUCTURE",
    "ASSESSMENT_BALANCE",
]


def _text(*, maximum: int = 4000, minimum: int = 1) -> dict[str, object]:
    return {
        "type": "string",
        "minLength": minimum,
        "maxLength": maximum,
        "pattern": NO_CONTROL,
    }


def _anchor_list(*, minimum: int = 0, maximum: int = 16) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {"$ref": "#/$defs/anchor"},
    }


def input_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(V2["input_schema"]())
    value["$id"] = (
        "https://eom.local/schemas/workflow/roles/paired-document-review-input-v3.schema.json"
    )
    value["title"] = "EOM Graph-Grounded Paired Document Review Worker Input V3"
    value["properties"]["protocol_version"] = {"const": "workflow-role/1.27.0"}
    review_request = value["$defs"]["review_request"]
    review_request["properties"]["schema_version"] = {"const": "paired-document-review-request/2.0"}
    review_request["required"].append("evidence_plan")
    review_request["properties"]["evidence_plan"] = {
        "$ref": "eom://schemas/document-review/document-review-evidence-plan/1.0"
    }
    return value


def result_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(V2["result_schema"]())
    value["$id"] = (
        "https://eom.local/schemas/workflow/roles/paired-document-review-result-v3.schema.json"
    )
    value["title"] = "EOM Exhaustive Graph-Grounded Paired Document Review Result V3"
    value["properties"]["protocol_version"] = {"const": "workflow-role/1.27.0"}
    defs = value["$defs"]
    cross = defs["cross_document_check"]
    cross["required"].insert(1, "item_key")
    cross["properties"]["item_key"] = {
        "type": "string",
        "pattern": "^reviewitem_[0-9a-f]{32}$",
    }

    defs["unit_check"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "check_id",
            "quantity",
            "value_expression",
            "expected_unit",
            "observed_unit",
            "status",
            "anchors",
            "conclusion",
        ],
        "properties": {
            "check_id": {"type": "string", "pattern": "^reviewunit_[0-9a-f]{32}$"},
            "quantity": _text(maximum=160),
            "value_expression": {"anyOf": [_text(maximum=500), {"type": "null"}]},
            "expected_unit": {"anyOf": [_text(maximum=160), {"type": "null"}]},
            "observed_unit": {"anyOf": [_text(maximum=160), {"type": "null"}]},
            "status": {"enum": ["VERIFIED", "FAILED", "INSUFFICIENT", "NOT_APPLICABLE"]},
            "anchors": _anchor_list(minimum=1, maximum=8),
            "conclusion": _text(),
        },
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "NOT_APPLICABLE"}}},
                "then": {
                    "properties": {
                        "value_expression": {"type": "null"},
                        "expected_unit": {"type": "null"},
                        "observed_unit": {"type": "null"},
                    }
                },
                "else": {
                    "properties": {
                        "value_expression": _text(maximum=500),
                        "expected_unit": _text(maximum=160),
                    }
                },
            }
        ],
    }
    defs["solve_step_check"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "ordinal",
            "status",
            "claim_summary",
            "verification_summary",
            "question_anchors",
        ],
        "properties": {
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 64},
            "status": {"enum": ["VERIFIED", "FAILED", "INSUFFICIENT"]},
            "claim_summary": _text(maximum=1000),
            "verification_summary": _text(),
            "question_anchors": _anchor_list(minimum=1, maximum=8),
        },
    }
    defs["choice_check"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "ordinal",
            "choice_key",
            "verdict",
            "question_anchors",
            "solution_anchors",
            "rationale",
        ],
        "properties": {
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 10},
            "choice_key": _text(maximum=32),
            "verdict": {"enum": ["CORRECT", "INCORRECT", "AMBIGUOUS", "INSUFFICIENT"]},
            "question_anchors": _anchor_list(minimum=1, maximum=8),
            "solution_anchors": _anchor_list(maximum=8),
            "rationale": _text(),
        },
    }
    defs["explanation_step_check"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "ordinal",
            "status",
            "claim_summary",
            "verification_summary",
            "question_anchors",
            "solution_anchors",
        ],
        "properties": {
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 64},
            "status": {"enum": ["VERIFIED", "FAILED", "MISSING", "INSUFFICIENT"]},
            "claim_summary": _text(maximum=1000),
            "verification_summary": _text(),
            "question_anchors": _anchor_list(maximum=8),
            "solution_anchors": _anchor_list(maximum=8),
        },
    }
    defs["item_review"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_key",
            "ordinal",
            "question_label",
            "response_format",
            "question_anchors",
            "solution_anchors",
            "solve_summary",
            "solve_steps",
            "final_answer",
            "answer_status",
            "condition_sufficiency",
            "unit_checks",
            "choice_checks",
            "explanation_steps",
            "evidence_status",
            "evidence_citation_ids",
            "conclusion",
        ],
        "properties": {
            "item_key": {"type": "string", "pattern": "^reviewitem_[0-9a-f]{32}$"},
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 256},
            "question_label": _text(maximum=64),
            "response_format": {
                "enum": ["MULTIPLE_CHOICE", "STATEMENT_COMBINATION", "SHORT_ANSWER", "OTHER"]
            },
            "question_anchors": _anchor_list(minimum=1, maximum=16),
            "solution_anchors": _anchor_list(maximum=16),
            "solve_summary": _text(),
            "solve_steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"$ref": "#/$defs/solve_step_check"},
            },
            "final_answer": _text(maximum=500),
            "answer_status": {"enum": ["VERIFIED", "FAILED", "INSUFFICIENT"]},
            "condition_sufficiency": {"enum": ["VERIFIED", "FAILED", "INSUFFICIENT"]},
            "unit_checks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"$ref": "#/$defs/unit_check"},
            },
            "choice_checks": {
                "type": "array",
                "maxItems": 10,
                "items": {"$ref": "#/$defs/choice_check"},
            },
            "explanation_steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"$ref": "#/$defs/explanation_step_check"},
            },
            "evidence_status": {"enum": ["SUPPORTED", "INSUFFICIENT"]},
            "evidence_citation_ids": {
                "type": "array",
                "maxItems": 32,
                "items": {"type": "string", "pattern": "^evidenceitem_[0-9a-f]{32}$"},
            },
            "conclusion": _text(),
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "response_format": {"enum": ["MULTIPLE_CHOICE", "STATEMENT_COMBINATION"]}
                    }
                },
                "then": {"properties": {"choice_checks": {"minItems": 2}}},
                "else": {"properties": {"choice_checks": {"maxItems": 0}}},
            },
            {
                "if": {"properties": {"evidence_status": {"const": "SUPPORTED"}}},
                "then": {"properties": {"evidence_citation_ids": {"minItems": 1}}},
                "else": {"properties": {"evidence_citation_ids": {"maxItems": 0}}},
            },
        ],
    }
    defs["evidence_citation"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "evidence_id",
            "anchor_ids",
            "application",
            "item_keys",
            "review_json_paths",
        ],
        "properties": {
            "evidence_id": {
                "type": "string",
                "pattern": "^evidenceitem_[0-9a-f]{32}$",
            },
            "anchor_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {
                    "type": "string",
                    "pattern": "^anchor_[a-z0-9][a-z0-9_-]{0,63}$",
                },
            },
            "application": {
                "enum": [
                    "CONCEPT_VERIFICATION",
                    "SOLUTION_VERIFICATION",
                    "ORIGINALITY_COMPARISON",
                    "AVOID_COPY_CHECK",
                ]
            },
            "item_keys": {
                "type": "array",
                "minItems": 1,
                "maxItems": 256,
                "items": {"type": "string", "pattern": "^reviewitem_[0-9a-f]{32}$"},
            },
            "review_json_paths": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "pattern": "^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
                },
            },
        },
    }
    defs["evidence_usage"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "evidence_bundle_id",
            "evidence_bundle_revision_id",
            "retrieval_request_id",
            "graph_snapshot_revision_id",
            "manifest_sha256",
            "context_sha256",
            "citations",
        ],
        "properties": {
            "evidence_bundle_id": {"type": "string", "pattern": "^evidence_[0-9a-f]{32}$"},
            "evidence_bundle_revision_id": {
                "type": "string",
                "pattern": "^evidencerev_[0-9a-f]{32}$",
            },
            "retrieval_request_id": {"type": "string", "pattern": "^retrieval_[0-9a-f]{32}$"},
            "graph_snapshot_revision_id": {
                "type": "string",
                "pattern": "^graphrev_[0-9a-f]{32}$",
            },
            "manifest_sha256": HASH,
            "context_sha256": HASH,
            "citations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "items": {"$ref": "#/$defs/evidence_citation"},
            },
        },
    }

    target_items = defs["output"]["properties"]["verification_targets"]
    target_items.update({"minItems": len(AXES), "maxItems": len(AXES)})
    target_items["allOf"] = [
        {
            "contains": {"properties": {"axis": {"const": axis}}, "required": ["axis"]},
            "minContains": 1,
            "maxContains": 1,
        }
        for axis in AXES
    ]
    output = defs["output"]
    output["required"].extend(["page_coverage", "item_reviews", "evidence_usage"])
    output["properties"]["page_coverage"] = {
        "type": "array",
        "minItems": 2,
        "maxItems": 4000,
        "items": {"$ref": "#/$defs/page_ref"},
    }
    output["properties"]["item_reviews"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 256,
        "items": {"$ref": "#/$defs/item_review"},
    }
    output["properties"]["evidence_usage"] = {"$ref": "#/$defs/evidence_usage"}
    return value


def write(name: str, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    for directory in (CANONICAL, PACKAGED):
        (directory / name).write_text(payload, encoding="utf-8")


def main() -> None:
    write("paired-document-review-input-v3.schema.json", input_schema())
    write("paired-document-review-result-v3.schema.json", result_schema())


if __name__ == "__main__":
    main()

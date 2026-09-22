#!/usr/bin/env python3
"""Generate the canonical and packaged PDF document-review V1 role schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/roles"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/roles"

HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
NO_CONTROL = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"


def artifact_spec() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["logical_artifact_id", "revision_id", "file_name", "media_type"],
        "properties": {
            "logical_artifact_id": {
                "type": "string",
                "pattern": "^artifact_[0-9a-f]{32}$",
            },
            "revision_id": {"type": "string", "pattern": "^rev_[0-9a-f]{32}$"},
            "file_name": {"const": "result.json"},
            "media_type": {"const": "application/json"},
        },
    }


def member_pointer(*, media_types: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "artifact_id",
            "artifact_revision_id",
            "member_path",
            "sha256",
            "schema_ref",
            "media_type",
            "content_length",
        ],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {
                "type": "string",
                "pattern": "^rev_[0-9a-f]{32}$",
            },
            "member_path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))[A-Za-z0-9._/-]+$",
            },
            "sha256": HASH,
            "schema_ref": {
                "type": "string",
                "pattern": "^eom://schemas/document-review/[a-z0-9-]+/1\\.0$",
            },
            "media_type": {"enum": media_types},
            "content_length": {"type": "integer", "minimum": 1, "maximum": 268435456},
        },
    }


def input_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/workflow/roles/pdf-document-review-input-v1.schema.json",
        "title": "EOM PDF Document Review Worker Input V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "attempt",
            "role",
            "request",
            "upstream_artifacts",
            "artifact",
        ],
        "properties": {
            "schema_version": {"const": "1.0"},
            "protocol_version": {"const": "workflow-role/1.25.0"},
            "job_id": {"type": "string", "pattern": "^job_[0-9a-f]{32}$"},
            "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
            "step_run_id": {"type": "string", "pattern": "^steprun_[0-9a-f]{32}$"},
            "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
            "role": {"const": "support"},
            "request": {"$ref": "#/$defs/worker_request"},
            "upstream_artifacts": {"type": "array", "maxItems": 0},
            "artifact": {"$ref": "#/$defs/artifact"},
        },
        "$defs": {
            "artifact": artifact_spec(),
            "member_pointer": member_pointer(
                media_types=["application/pdf", "image/png", "application/json"]
            ),
            "document": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "document_id",
                    "document_revision_id",
                    "original_filename",
                    "source_pdf",
                    "page_count",
                    "pages",
                ],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "pattern": "^document_[0-9a-f]{32}$",
                    },
                    "document_revision_id": {
                        "type": "string",
                        "pattern": "^documentrev_[0-9a-f]{32}$",
                    },
                    "original_filename": {
                        "type": "string",
                        "minLength": 5,
                        "maxLength": 240,
                        "pattern": "^[^/\\\\\\u0000-\\u001F]+\\.[Pp][Dd][Ff]$",
                    },
                    "source_pdf": {"$ref": "#/$defs/member_pointer"},
                    "page_count": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "pages": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2000,
                        "items": {"$ref": "#/$defs/page"},
                    },
                },
            },
            "page": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "page_number",
                    "width_px",
                    "height_px",
                    "rotation_degrees",
                    "page_image",
                    "text_layer",
                ],
                "properties": {
                    "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "width_px": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "height_px": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "rotation_degrees": {"enum": [0, 90, 180, 270]},
                    "page_image": {"$ref": "#/$defs/member_pointer"},
                    "text_layer": {"oneOf": [{"$ref": "#/$defs/member_pointer"}, {"type": "null"}]},
                },
            },
            "preset": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "preset_key",
                    "preset_revision_id",
                    "display_name",
                    "criteria",
                    "preset_sha256",
                ],
                "properties": {
                    "schema_version": {"const": "pdf-review-preset/1.0"},
                    "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
                    "preset_revision_id": {
                        "type": "string",
                        "pattern": "^reviewpresetrev_[0-9a-f]{32}$",
                    },
                    "display_name": {"enum": ["N제", "주간지", "모의고사"]},
                    "criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 500,
                            "pattern": NO_CONTROL,
                        },
                    },
                    "preset_sha256": HASH,
                },
            },
            "review_request": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "document",
                    "preset",
                    "additional_guidance",
                    "additional_guidance_sha256",
                    "locale",
                    "request_sha256",
                ],
                "properties": {
                    "schema_version": {"const": "pdf-document-review-request/1.0"},
                    "document": {"$ref": "#/$defs/document"},
                    "preset": {"$ref": "#/$defs/preset"},
                    "additional_guidance": {
                        "type": ["string", "null"],
                        "minLength": 1,
                        "maxLength": 8000,
                        "pattern": NO_CONTROL,
                    },
                    "additional_guidance_sha256": {"oneOf": [HASH, {"type": "null"}]},
                    "locale": {"const": "ko-KR"},
                    "request_sha256": HASH,
                },
                "allOf": [
                    {
                        "if": {"properties": {"additional_guidance": {"type": "string"}}},
                        "then": {"properties": {"additional_guidance_sha256": HASH}},
                        "else": {"properties": {"additional_guidance_sha256": {"type": "null"}}},
                    }
                ],
            },
            "worker_request": {
                "type": "object",
                "additionalProperties": False,
                "required": ["request_name", "review_request"],
                "properties": {
                    "request_name": {"const": "PDF_DOCUMENT_REVIEW_REQUEST"},
                    "review_request": {"$ref": "#/$defs/review_request"},
                },
            },
        },
    }


def result_schema() -> dict[str, Any]:
    string = {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": NO_CONTROL}
    enums = {
        "axis": [
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
        ],
        "category": [
            "SCIENTIFIC_ACCURACY",
            "ANSWER_CORRECTNESS",
            "EXPLANATION_CONSISTENCY",
            "CURRICULUM_SCOPE",
            "ORIGINALITY",
            "VISUAL_CONTENT",
            "EDITORIAL_CLARITY",
            "TYPOGRAPHY",
            "STRUCTURE",
            "ASSESSMENT_BALANCE",
            "OTHER",
        ],
        "severity": ["BLOCKER", "HIGH", "MEDIUM", "LOW", "NOTE"],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
        "title": "EOM PDF Document Review Result V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "status",
            "artifact",
            "completed_at",
            "role",
            "output",
        ],
        "properties": {
            "schema_version": {"const": "1.0"},
            "protocol_version": {"const": "workflow-role/1.25.0"},
            "job_id": {"type": "string", "pattern": "^job_[0-9a-f]{32}$"},
            "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
            "step_run_id": {"type": "string", "pattern": "^steprun_[0-9a-f]{32}$"},
            "status": {"const": "ok"},
            "artifact": {"$ref": "#/$defs/artifact"},
            "completed_at": {"type": "string", "format": "date-time"},
            "role": {"const": "support"},
            "output": {"$ref": "#/$defs/output"},
        },
        "$defs": {
            "artifact": artifact_spec(),
            "region": {
                "type": "object",
                "additionalProperties": False,
                "required": ["x_ppm", "y_ppm", "width_ppm", "height_ppm"],
                "properties": {
                    "x_ppm": {"type": "integer", "minimum": 0, "maximum": 999999},
                    "y_ppm": {"type": "integer", "minimum": 0, "maximum": 999999},
                    "width_ppm": {"type": "integer", "minimum": 1, "maximum": 1000000},
                    "height_ppm": {"type": "integer", "minimum": 1, "maximum": 1000000},
                },
            },
            "anchor": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "anchor_id",
                    "page_number",
                    "page_image_sha256",
                    "region",
                    "quote",
                    "quote_sha256",
                ],
                "properties": {
                    "anchor_id": {"type": "string", "pattern": "^reviewanchor_[0-9a-f]{32}$"},
                    "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "page_image_sha256": HASH,
                    "region": {"$ref": "#/$defs/region"},
                    "quote": {
                        "anyOf": [
                            {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1000,
                                "pattern": NO_CONTROL,
                            },
                            {"type": "null"},
                        ]
                    },
                    "quote_sha256": {"anyOf": [HASH, {"type": "null"}]},
                },
                "allOf": [
                    {
                        "if": {"properties": {"quote": {"type": "string"}}},
                        "then": {"properties": {"quote_sha256": HASH}},
                        "else": {"properties": {"quote_sha256": {"type": "null"}}},
                    }
                ],
            },
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "target_id",
                    "axis",
                    "page_numbers",
                    "anchors",
                    "status",
                    "conclusion",
                ],
                "properties": {
                    "target_id": {"type": "string", "pattern": "^reviewtarget_[0-9a-f]{32}$"},
                    "axis": {"enum": enums["axis"]},
                    "page_numbers": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2000,
                        "items": {"type": "integer", "minimum": 1, "maximum": 2000},
                    },
                    "anchors": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {"$ref": "#/$defs/anchor"},
                    },
                    "status": {"enum": ["VERIFIED", "FAILED", "INSUFFICIENT"]},
                    "conclusion": string,
                },
            },
            "candidate": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "finding_code",
                    "category",
                    "severity",
                    "title",
                    "anchors",
                    "disposition",
                    "rationale",
                ],
                "properties": {
                    "candidate_id": {"type": "string", "pattern": "^reviewcandidate_[0-9a-f]{32}$"},
                    "finding_code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,63}$"},
                    "category": {"enum": enums["category"]},
                    "severity": {"enum": enums["severity"]},
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 160,
                        "pattern": NO_CONTROL,
                    },
                    "anchors": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"$ref": "#/$defs/anchor"},
                    },
                    "disposition": {"enum": ["CONFIRMED", "DEMOTED", "UNCERTAIN"]},
                    "rationale": string,
                },
            },
            "recommendation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "instruction", "before_text", "after_text"],
                "properties": {
                    "operation": {
                        "enum": ["REPLACE", "INSERT", "DELETE", "MOVE", "REDRAW", "VERIFY", "NONE"]
                    },
                    "instruction": string,
                    "before_text": {
                        "anyOf": [
                            {"type": "string", "maxLength": 2000, "pattern": NO_CONTROL},
                            {"type": "null"},
                        ]
                    },
                    "after_text": {
                        "anyOf": [
                            {"type": "string", "maxLength": 2000, "pattern": NO_CONTROL},
                            {"type": "null"},
                        ]
                    },
                },
            },
            "finding": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "finding_id",
                    "candidate_id",
                    "ordinal",
                    "finding_code",
                    "category",
                    "severity",
                    "title",
                    "description",
                    "anchors",
                    "recommendation",
                ],
                "properties": {
                    "finding_id": {"type": "string", "pattern": "^reviewfinding_[0-9a-f]{32}$"},
                    "candidate_id": {"type": "string", "pattern": "^reviewcandidate_[0-9a-f]{32}$"},
                    "ordinal": {"type": "integer", "minimum": 1, "maximum": 512},
                    "finding_code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,63}$"},
                    "category": {"enum": enums["category"]},
                    "severity": {"enum": enums["severity"]},
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 160,
                        "pattern": NO_CONTROL,
                    },
                    "description": string,
                    "anchors": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"$ref": "#/$defs/anchor"},
                    },
                    "recommendation": {"$ref": "#/$defs/recommendation"},
                },
            },
            "output": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "review_request_sha256",
                    "document_id",
                    "document_revision_id",
                    "source_pdf_sha256",
                    "preset_key",
                    "preset_revision_id",
                    "preset_sha256",
                    "additional_guidance_sha256",
                    "review_status",
                    "summary",
                    "verification_targets",
                    "candidate_findings",
                    "findings",
                    "mutation_performed",
                ],
                "properties": {
                    "review_request_sha256": HASH,
                    "document_id": {"type": "string", "pattern": "^document_[0-9a-f]{32}$"},
                    "document_revision_id": {
                        "type": "string",
                        "pattern": "^documentrev_[0-9a-f]{32}$",
                    },
                    "source_pdf_sha256": HASH,
                    "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
                    "preset_revision_id": {
                        "type": "string",
                        "pattern": "^reviewpresetrev_[0-9a-f]{32}$",
                    },
                    "preset_sha256": HASH,
                    "additional_guidance_sha256": {"anyOf": [HASH, {"type": "null"}]},
                    "review_status": {"enum": ["COMPLETE", "NEEDS_HUMAN_DECISION"]},
                    "summary": string,
                    "verification_targets": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 256,
                        "items": {"$ref": "#/$defs/target"},
                    },
                    "candidate_findings": {
                        "type": "array",
                        "maxItems": 512,
                        "items": {"$ref": "#/$defs/candidate"},
                    },
                    "findings": {
                        "type": "array",
                        "maxItems": 512,
                        "items": {"$ref": "#/$defs/finding"},
                    },
                    "mutation_performed": {"const": False},
                },
            },
        },
    }


def write(name: str, document: dict[str, Any]) -> None:
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for directory in (CANONICAL, PACKAGED):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(payload)


def main() -> None:
    write("pdf-document-review-input-v1.schema.json", input_schema())
    write("pdf-document-review-result-v1.schema.json", result_schema())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate public API schemas for paired document-review upload sets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / "schemas/api/v1",
    ROOT / "packages/api_contracts/eom_api_contracts/schemas",
)
NO_CONTROL = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"


def source(role: str | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "role": {"enum": [role] if role is not None else ["QUESTION", "SOLUTION"]},
        "original_filename": {
            "type": "string",
            "minLength": 5,
            "maxLength": 240,
            "pattern": r"^[^/\\\u0000-\u001f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
        },
        "source_format": {"enum": ["PDF", "HWP", "HWPX"]},
        "media_type": {
            "enum": [
                "application/pdf",
                "application/vnd.hancom.hwp",
                "application/vnd.hancom.hwpx",
            ]
        },
        "content_length": {"type": "integer", "minimum": 8, "maximum": 268435456},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def create_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/api/v1/document-review-set-create-v1.schema.json",
        "title": "EOM Paired Document Review Set Create V1",
        "type": "object",
        "additionalProperties": False,
        "required": ["documents", "preset_key", "additional_guidance", "locale"],
        "properties": {
            "documents": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [source("QUESTION"), source("SOLUTION")],
                "items": False,
            },
            "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
            "additional_guidance": {
                "type": ["string", "null"],
                "minLength": 1,
                "maxLength": 8000,
                "pattern": NO_CONTROL,
            },
            "locale": {"const": "ko-KR"},
        },
    }


def view_schema() -> dict[str, Any]:
    member = source()
    member["required"].extend(
        [
            "state",
            "upload_sha256",
            "document_id",
            "document_revision_id",
            "source_pdf_sha256",
            "page_count",
            "failure_code",
            "upload_url",
        ]
    )
    member["properties"].update(
        {
            "state": {
                "enum": [
                    "AWAITING_UPLOAD",
                    "PROCESSING",
                    "COMMITTED",
                    "FAILED_RETRYABLE",
                    "FAILED_FINAL",
                ]
            },
            "upload_sha256": {"type": ["string", "null"], "pattern": "^sha256:[0-9a-f]{64}$"},
            "document_id": {
                "type": ["string", "null"],
                "pattern": "^document_[0-9a-f]{32}$",
            },
            "document_revision_id": {
                "type": ["string", "null"],
                "pattern": "^documentrev_[0-9a-f]{32}$",
            },
            "source_pdf_sha256": {
                "type": ["string", "null"],
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "page_count": {"type": ["integer", "null"], "minimum": 1, "maximum": 2000},
            "failure_code": {
                "type": ["string", "null"],
                "pattern": "^[A-Z][A-Z0-9_]{2,63}$",
            },
            "upload_url": {
                "type": "string",
                "pattern": (
                    "^/api/v1/pdf-document-reviews/sets/docreviewset_[0-9a-f]{32}/"
                    "documents/(QUESTION|SOLUTION)/content$"
                ),
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/api/v1/document-review-set-view-v1.schema.json",
        "title": "EOM Paired Document Review Set View V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "review_set_id",
            "state",
            "documents",
            "preset_key",
            "additional_guidance_sha256",
            "workflow_id",
            "failure_code",
            "review_url",
            "created_at",
            "updated_at",
            "expires_at",
            "resource_version",
        ],
        "properties": {
            "review_set_id": {"type": "string", "pattern": "^docreviewset_[0-9a-f]{32}$"},
            "state": {
                "enum": [
                    "AWAITING_UPLOADS",
                    "STARTING",
                    "STARTED",
                    "FAILED_RETRYABLE",
                    "FAILED_FINAL",
                ]
            },
            "documents": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [
                    {"allOf": [member, {"properties": {"role": {"const": "QUESTION"}}}]},
                    {"allOf": [member, {"properties": {"role": {"const": "SOLUTION"}}}]},
                ],
                "items": False,
            },
            "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
            "additional_guidance_sha256": {
                "type": ["string", "null"],
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "workflow_id": {
                "type": ["string", "null"],
                "pattern": "^workflow_[0-9a-f]{32}$",
            },
            "failure_code": {
                "type": ["string", "null"],
                "pattern": "^[A-Z][A-Z0-9_]{2,63}$",
            },
            "review_url": {
                "type": ["string", "null"],
                "pattern": "^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}$",
            },
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "expires_at": {"type": "string", "format": "date-time"},
            "resource_version": {"type": "integer", "minimum": 1},
        },
    }


def paired_review_view_schema() -> dict[str, Any]:
    page = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "document_role",
            "page_number",
            "width_px",
            "height_px",
            "rotation_degrees",
            "image_sha256",
            "image_content_length",
            "image_url",
        ],
        "properties": {
            "document_role": {"enum": ["QUESTION", "SOLUTION"]},
            "page_number": {"type": "integer", "minimum": 1, "maximum": 64},
            "width_px": {"type": "integer", "minimum": 64, "maximum": 16384},
            "height_px": {"type": "integer", "minimum": 64, "maximum": 16384},
            "rotation_degrees": {"enum": [0, 90, 180, 270]},
            "image_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "image_content_length": {
                "type": "integer",
                "minimum": 1,
                "maximum": 16777216,
            },
            "image_url": {
                "type": "string",
                "pattern": (
                    "^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/documents/"
                    "(QUESTION|SOLUTION)/pages/([1-9]|[1-5][0-9]|6[0-4])/image$"
                ),
            },
        },
    }
    document = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role",
            "document_id",
            "document_revision_id",
            "original_filename",
            "source_format",
            "source_pdf_sha256",
            "page_count",
            "pages",
        ],
        "properties": {
            "role": {"enum": ["QUESTION", "SOLUTION"]},
            "document_id": {"type": "string", "pattern": "^document_[0-9a-f]{32}$"},
            "document_revision_id": {
                "type": "string",
                "pattern": "^documentrev_[0-9a-f]{32}$",
            },
            "original_filename": source()["properties"]["original_filename"],
            "source_format": {"enum": ["PDF", "HWP", "HWPX"]},
            "source_pdf_sha256": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "page_count": {"type": "integer", "minimum": 1, "maximum": 64},
            "pages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": page,
            },
        },
    }
    artifact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["artifact_id", "artifact_revision_id", "sha256"],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {
                "type": "string",
                "pattern": "^rev_[0-9a-f]{32}$",
            },
            "sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/api/v1/paired-document-review-view-v1.schema.json",
        "title": "EOM Paired Document Review View V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "workflow_id",
            "state",
            "documents",
            "preset_key",
            "preset_display_name",
            "additional_guidance_sha256",
            "result_artifact",
            "result",
            "failure_code",
            "created_at",
            "updated_at",
            "resource_version",
        ],
        "properties": {
            "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
            "state": {"enum": ["SUBMITTED", "REVIEWING", "COMPLETED", "FAILED"]},
            "documents": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [
                    {"allOf": [document, {"properties": {"role": {"const": "QUESTION"}}}]},
                    {"allOf": [document, {"properties": {"role": {"const": "SOLUTION"}}}]},
                ],
                "items": False,
            },
            "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
            "preset_display_name": {"enum": ["N제", "주간지", "모의고사"]},
            "additional_guidance_sha256": {
                "type": ["string", "null"],
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "result_artifact": {"oneOf": [artifact, {"type": "null"}]},
            "result": {
                "oneOf": [
                    {
                        "$ref": (
                            "https://eom.local/schemas/workflow/roles/"
                            "paired-document-review-result-v2.schema.json#/$defs/output"
                        )
                    },
                    {"type": "null"},
                ]
            },
            "failure_code": {
                "type": ["string", "null"],
                "pattern": "^[A-Z][A-Z0-9_]{2,63}$",
            },
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "resource_version": {"type": "integer", "minimum": 1},
        },
    }


def main() -> None:
    values = {
        "document-review-set-create-v1.schema.json": create_schema(),
        "document-review-set-view-v1.schema.json": view_schema(),
        "paired-document-review-view-v1.schema.json": paired_review_view_schema(),
    }
    for name, value in values.items():
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        for directory in TARGETS:
            (directory / name).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

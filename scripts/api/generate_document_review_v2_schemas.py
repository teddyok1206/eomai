#!/usr/bin/env python3
"""Generate additive Office document-review upload and correction API schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
SHA = {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}
WORKFLOW_ID = {"type": "string", "pattern": r"^workflow_[0-9a-f]{32}$"}
FINDING_ID = {"type": "string", "pattern": r"^reviewfinding_[0-9a-f]{32}$"}
CORRECTION_ID = {"type": "string", "pattern": r"^doccorrection_[0-9a-f]{32}$"}
SOURCE_FORMAT = {"enum": ["PDF", "HWP", "HWPX"]}
MEDIA_TYPE = {
    "enum": [
        "application/pdf",
        "application/vnd.hancom.hwp",
        "application/vnd.hancom.hwpx",
    ]
}
FILENAME = {
    "type": "string",
    "minLength": 5,
    "maxLength": 240,
    "pattern": r"^[^/\\\u0000-\u001f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
}


def _format_constraints() -> list[dict[str, Any]]:
    return [
        {
            "if": {"properties": {"source_format": {"const": source_format}}},
            "then": {
                "properties": {
                    "original_filename": {"pattern": suffix},
                    "media_type": {"const": media_type},
                }
            },
        }
        for source_format, suffix, media_type in (
            ("PDF", r"\.[Pp][Dd][Ff]$", "application/pdf"),
            ("HWP", r"\.[Hh][Ww][Pp]$", "application/vnd.hancom.hwp"),
            ("HWPX", r"\.[Hh][Ww][Pp][Xx]$", "application/vnd.hancom.hwpx"),
        )
    ]


def upload_schema() -> dict[str, Any]:
    request = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "original_filename",
            "source_format",
            "media_type",
            "content_length",
            "preset_key",
            "locale",
        ],
        "properties": {
            "original_filename": FILENAME,
            "source_format": SOURCE_FORMAT,
            "media_type": MEDIA_TYPE,
            "content_length": {"type": "integer", "minimum": 8, "maximum": 268435456},
            "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
            "additional_guidance": {
                "type": ["string", "null"],
                "minLength": 1,
                "maxLength": 8000,
                "pattern": r"^[^\u0000-\u0008\u000b\u000c\u000e-\u001f]+$",
            },
            "locale": {"const": "ko-KR"},
        },
        "allOf": _format_constraints(),
    }
    view = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "upload_intent_id",
            "state",
            "original_filename",
            "source_format",
            "media_type",
            "content_length",
            "preset_key",
            "upload_url",
            "created_at",
            "updated_at",
            "expires_at",
            "resource_version",
        ],
        "properties": {
            "upload_intent_id": {
                "type": "string",
                "pattern": r"^pdfreviewintent_[0-9a-f]{32}$",
            },
            "state": {
                "enum": [
                    "AWAITING_UPLOAD",
                    "PROCESSING",
                    "STARTED",
                    "FAILED_RETRYABLE",
                    "FAILED_FINAL",
                ]
            },
            "original_filename": FILENAME,
            "source_format": SOURCE_FORMAT,
            "media_type": MEDIA_TYPE,
            "content_length": {"type": "integer", "minimum": 8, "maximum": 268435456},
            "preset_key": {"enum": ["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]},
            "additional_guidance_sha256": {"oneOf": [SHA, {"type": "null"}]},
            "upload_sha256": {"oneOf": [SHA, {"type": "null"}]},
            "workflow_id": {"oneOf": [WORKFLOW_ID, {"type": "null"}]},
            "failure_code": {
                "oneOf": [
                    {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,63}$"},
                    {"type": "null"},
                ]
            },
            "upload_url": {
                "type": "string",
                "pattern": (
                    r"^/api/v1/pdf-document-reviews/upload-intents/"
                    r"pdfreviewintent_[0-9a-f]{32}/content$"
                ),
            },
            "review_url": {
                "oneOf": [
                    {
                        "type": "string",
                        "pattern": r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}$",
                    },
                    {"type": "null"},
                ]
            },
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "expires_at": {"type": "string", "format": "date-time"},
            "resource_version": {"type": "integer", "minimum": 1},
        },
        "allOf": [
            *_format_constraints(),
            {
                "if": {"properties": {"state": {"const": "AWAITING_UPLOAD"}}},
                "then": {
                    "properties": {
                        "upload_sha256": {"type": "null"},
                        "workflow_id": {"type": "null"},
                        "failure_code": {"type": "null"},
                        "review_url": {"type": "null"},
                    }
                },
            },
            {
                "if": {"properties": {"state": {"const": "PROCESSING"}}},
                "then": {
                    "properties": {
                        "upload_sha256": SHA,
                        "workflow_id": {"type": "null"},
                        "failure_code": {"type": "null"},
                        "review_url": {"type": "null"},
                    },
                    "required": ["upload_sha256"],
                },
            },
            {
                "if": {"properties": {"state": {"const": "STARTED"}}},
                "then": {
                    "properties": {
                        "upload_sha256": SHA,
                        "workflow_id": WORKFLOW_ID,
                        "failure_code": {"type": "null"},
                        "review_url": {
                            "type": "string",
                            "pattern": (
                                r"^/api/v1/pdf-document-reviews/"
                                r"workflow_[0-9a-f]{32}$"
                            ),
                        },
                    },
                    "required": ["upload_sha256", "workflow_id", "review_url"],
                },
            },
            {
                "if": {"properties": {"state": {"enum": ["FAILED_RETRYABLE", "FAILED_FINAL"]}}},
                "then": {
                    "properties": {
                        "upload_sha256": SHA,
                        "workflow_id": {"type": "null"},
                        "failure_code": {
                            "type": "string",
                            "pattern": r"^[A-Z][A-Z0-9_]{2,63}$",
                        },
                        "review_url": {"type": "null"},
                    },
                    "required": ["upload_sha256", "failure_code"],
                },
            },
        ],
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/api/document-review-upload/2.0",
        "title": "EOM Office Document Review Upload API V2",
        "type": "object",
        "oneOf": [{"$ref": "#/$defs/request"}, {"$ref": "#/$defs/view"}],
        "$defs": {"request": request, "view": view},
    }


def correction_schema() -> dict[str, Any]:
    request = {
        "type": "object",
        "additionalProperties": False,
        "required": ["finding_ids"],
        "properties": {
            "finding_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": FINDING_ID,
            }
        },
    }
    eligibility = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "workflow_id",
            "source_format",
            "correction_available",
            "eligible_finding_ids",
            "unavailable_reason",
        ],
        "properties": {
            "workflow_id": WORKFLOW_ID,
            "source_format": SOURCE_FORMAT,
            "correction_available": {"type": "boolean"},
            "eligible_finding_ids": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": FINDING_ID,
            },
            "unavailable_reason": {
                "oneOf": [
                    {"enum": ["SOURCE_NOT_HWPX", "REVIEW_NOT_COMPLETED", "NO_SAFE_REPLACEMENTS"]},
                    {"type": "null"},
                ]
            },
        },
        "allOf": [
            {
                "if": {"properties": {"correction_available": {"const": True}}},
                "then": {
                    "properties": {
                        "source_format": {"const": "HWPX"},
                        "eligible_finding_ids": {"minItems": 1},
                        "unavailable_reason": {"type": "null"},
                    }
                },
                "else": {
                    "properties": {
                        "unavailable_reason": {
                            "enum": [
                                "SOURCE_NOT_HWPX",
                                "REVIEW_NOT_COMPLETED",
                                "NO_SAFE_REPLACEMENTS",
                            ]
                        }
                    }
                },
            }
        ],
    }
    view = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "correction_id",
            "workflow_id",
            "state",
            "applied_finding_ids",
            "text_color",
            "output_sha256",
            "output_content_length",
            "download_url",
            "created_at",
            "resource_version",
        ],
        "properties": {
            "correction_id": CORRECTION_ID,
            "workflow_id": WORKFLOW_ID,
            "state": {"const": "COMPLETED"},
            "applied_finding_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": FINDING_ID,
            },
            "text_color": {"const": "#FF0000"},
            "output_sha256": SHA,
            "output_content_length": {
                "type": "integer",
                "minimum": 1,
                "maximum": 268435456,
            },
            "download_url": {
                "type": "string",
                "pattern": (
                    r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/corrections/"
                    r"doccorrection_[0-9a-f]{32}/download$"
                ),
            },
            "created_at": {"type": "string", "format": "date-time"},
            "resource_version": {"type": "integer", "minimum": 1},
        },
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/api/document-review-hwpx-correction/1.0",
        "title": "EOM Document Review HWPX Correction API V1",
        "type": "object",
        "oneOf": [
            {"$ref": "#/$defs/request"},
            {"$ref": "#/$defs/eligibility"},
            {"$ref": "#/$defs/view"},
        ],
        "$defs": {"request": request, "eligibility": eligibility, "view": view},
    }


SCHEMAS = {
    "document-review-upload-v2.schema.json": upload_schema(),
    "document-review-hwpx-correction-v1.schema.json": correction_schema(),
}


def main() -> None:
    for name, schema in SCHEMAS.items():
        payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for target in (
            ROOT / "schemas/api/v1" / name,
            ROOT / "packages/api_contracts/eom_api_contracts/schemas" / name,
        ):
            target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

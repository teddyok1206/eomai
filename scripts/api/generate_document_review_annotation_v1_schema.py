#!/usr/bin/env python3
"""Generate public API schema for immutable annotated document-review PDFs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    ROOT / "schemas/api/v1",
    ROOT / "packages/api_contracts/eom_api_contracts/schemas",
)


def schema() -> dict[str, Any]:
    output = {
        "type": "object",
        "additionalProperties": False,
        "required": ["document_role", "sha256", "content_length", "download_url"],
        "properties": {
            "document_role": {"enum": ["DOCUMENT", "QUESTION", "SOLUTION"]},
            "sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "content_length": {"type": "integer", "minimum": 1, "maximum": 536870912},
            "download_url": {
                "type": "string",
                "pattern": (
                    "^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/annotations/"
                    "docannotation_[0-9a-f]{32}/documents/(DOCUMENT|QUESTION|SOLUTION)/download$"
                ),
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://eom.local/schemas/api/v1/document-review-annotation-v1.schema.json",
        "title": "EOM Document Review Annotation V1",
        "$defs": {"output": output},
        "oneOf": [
            {
                "title": "Create request",
                "type": "object",
                "additionalProperties": False,
                "required": ["include_all_findings"],
                "properties": {"include_all_findings": {"const": True}},
            },
            {
                "title": "Annotation view",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "annotation_id",
                    "workflow_id",
                    "outputs",
                    "created_at",
                    "resource_version",
                ],
                "properties": {
                    "annotation_id": {
                        "type": "string",
                        "pattern": "^docannotation_[0-9a-f]{32}$",
                    },
                    "workflow_id": {
                        "type": "string",
                        "pattern": "^workflow_[0-9a-f]{32}$",
                    },
                    "outputs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "items": {"$ref": "#/$defs/output"},
                    },
                    "created_at": {"type": "string", "format": "date-time"},
                    "resource_version": {"type": "integer", "minimum": 1},
                },
            },
        ],
    }


def main() -> None:
    payload = (json.dumps(schema(), ensure_ascii=False, indent=2) + "\n").encode()
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        (target / "document-review-annotation-v1.schema.json").write_bytes(payload)


if __name__ == "__main__":
    main()

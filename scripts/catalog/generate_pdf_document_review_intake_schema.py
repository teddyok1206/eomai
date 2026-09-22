#!/usr/bin/env python3
"""Generate the canonical and packaged PDF document-review intake schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/document-review/pdf-document-review-intake-manifest-v1.schema.json"
PACKAGED = (
    ROOT
    / "packages/catalog_contracts/eom_catalog_contracts/resources/document-review"
    / CANONICAL.name
)
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}


def schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/document-review/pdf-document-review-intake-manifest/1.0",
        "title": "EOM PDF Document Review Intake Manifest V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "document_id",
            "document_revision_id",
            "original_filename",
            "source_pdf_sha256",
            "source_pdf_bytes",
            "renderer",
            "page_count",
            "pages",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "pdf-document-review-intake-manifest/1.0"},
            "document_id": {"type": "string", "pattern": "^document_[0-9a-f]{32}$"},
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
            "source_pdf_sha256": HASH,
            "source_pdf_bytes": {
                "type": "integer",
                "minimum": 8,
                "maximum": 268435456,
            },
            "renderer": {"$ref": "#/$defs/renderer"},
            "page_count": {"type": "integer", "minimum": 1, "maximum": 2000},
            "pages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2000,
                "items": {"$ref": "#/$defs/page"},
            },
            "manifest_sha256": HASH,
        },
        "$defs": {
            "renderer": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "renderer_key",
                    "pdfinfo_sha256",
                    "pdftoppm_sha256",
                    "scale_to_px",
                    "output_format",
                ],
                "properties": {
                    "renderer_key": {"const": "poppler-pdftoppm"},
                    "pdfinfo_sha256": HASH,
                    "pdftoppm_sha256": HASH,
                    "scale_to_px": {"const": 2400},
                    "output_format": {"const": "PNG"},
                },
            },
            "page": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "page_number",
                    "member_path",
                    "sha256",
                    "content_length",
                    "width_px",
                    "height_px",
                    "rotation_degrees",
                ],
                "properties": {
                    "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "member_path": {
                        "type": "string",
                        "pattern": "^pages/page-[0-9]{4}\\.png$",
                    },
                    "sha256": HASH,
                    "content_length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 67108864,
                    },
                    "width_px": {"type": "integer", "minimum": 64, "maximum": 2400},
                    "height_px": {"type": "integer", "minimum": 64, "maximum": 2400},
                    "rotation_degrees": {"const": 0},
                },
            },
        },
    }


def main() -> None:
    payload = json.dumps(schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for target in (CANONICAL, PACKAGED):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

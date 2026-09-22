#!/usr/bin/env python3
"""Generate successor Office-document review and HWPX correction schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
SHA = {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}
ARTIFACT_ID = {"type": "string", "pattern": r"^artifact_[0-9a-f]{32}$"}
REVISION_ID = {"type": "string", "pattern": r"^rev_[0-9a-f]{32}$"}
DOCUMENT_ID = {"type": "string", "pattern": r"^document_[0-9a-f]{32}$"}
DOCUMENT_REVISION_ID = {"type": "string", "pattern": r"^documentrev_[0-9a-f]{32}$"}
WORKFLOW_ID = {"type": "string", "pattern": r"^workflow_[0-9a-f]{32}$"}
FINDING_ID = {"type": "string", "pattern": r"^reviewfinding_[0-9a-f]{32}$"}


def member_descriptor() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["member_path", "sha256", "content_length", "media_type", "schema_ref"],
        "properties": {
            "member_path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "pattern": r"^[A-Za-z0-9._/-]+$",
            },
            "sha256": SHA,
            "content_length": {"type": "integer", "minimum": 1, "maximum": 268435456},
            "media_type": {
                "enum": [
                    "application/pdf",
                    "application/vnd.hancom.hwp",
                    "application/vnd.hancom.hwpx",
                    "image/png",
                    "application/json",
                ]
            },
            "schema_ref": {
                "type": "string",
                "pattern": r"^eom://schemas/document-review/[a-z0-9-]+/[12]\.0$",
            },
        },
    }


def member_pointer() -> dict[str, Any]:
    value = member_descriptor()
    value["required"] = [
        "artifact_id",
        "artifact_revision_id",
        *value["required"],
    ]
    value["properties"] = {
        "artifact_id": ARTIFACT_ID,
        "artifact_revision_id": REVISION_ID,
        **value["properties"],
    }
    return value


def conversion() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "conversion_kind",
            "review_pdf_sha256",
            "libreoffice_version",
            "libreoffice_sha256",
            "h2orestart_sha256",
        ],
        "properties": {
            "conversion_kind": {"enum": ["IDENTITY_PDF", "LIBREOFFICE_H2ORESTART_PDF"]},
            "review_pdf_sha256": SHA,
            "libreoffice_version": {
                "oneOf": [
                    {"type": "string", "minLength": 1, "maxLength": 128},
                    {"type": "null"},
                ]
            },
            "libreoffice_sha256": {"oneOf": [SHA, {"type": "null"}]},
            "h2orestart_sha256": {"oneOf": [SHA, {"type": "null"}]},
        },
    }


def page_descriptor() -> dict[str, Any]:
    return {
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
            "member_path": {"type": "string", "pattern": r"^pages/page-[0-9]{4}\.png$"},
            "sha256": SHA,
            "content_length": {"type": "integer", "minimum": 1, "maximum": 67108864},
            "width_px": {"type": "integer", "minimum": 64, "maximum": 2400},
            "height_px": {"type": "integer", "minimum": 64, "maximum": 2400},
            "rotation_degrees": {"const": 0},
        },
    }


def page_pointer() -> dict[str, Any]:
    return {
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
            "page_image": {"$ref": "#/$defs/memberPointer"},
            "text_layer": {"oneOf": [{"$ref": "#/$defs/memberPointer"}, {"type": "null"}]},
        },
    }


def review_document_pointer() -> dict[str, Any]:
    return {
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
            "document_id": DOCUMENT_ID,
            "document_revision_id": DOCUMENT_REVISION_ID,
            "original_filename": {
                "type": "string",
                "minLength": 5,
                "maxLength": 240,
                "pattern": r"^[^/\\\u0000-\u001f]+\.[Pp][Dd][Ff]$",
            },
            "source_pdf": {"$ref": "#/$defs/memberPointer"},
            "page_count": {"type": "integer", "minimum": 1, "maximum": 2000},
            "pages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2000,
                "items": {"$ref": "#/$defs/pagePointer"},
            },
        },
    }


def source_filename_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 5,
        "maxLength": 240,
        "pattern": r"^[^/\\\u0000-\u001f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    }


def intake_manifest() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-intake-manifest/2.0",
        "title": "EOM Office Document Review Intake Manifest V2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "document_id",
            "document_revision_id",
            "original_filename",
            "source_format",
            "original_source",
            "review_pdf",
            "editable_hwpx",
            "conversion",
            "renderer",
            "page_count",
            "pages",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-intake-manifest/2.0"},
            "document_id": DOCUMENT_ID,
            "document_revision_id": DOCUMENT_REVISION_ID,
            "original_filename": source_filename_schema(),
            "source_format": {"enum": ["PDF", "HWP", "HWPX"]},
            "original_source": {"$ref": "#/$defs/memberDescriptor"},
            "review_pdf": {"$ref": "#/$defs/memberDescriptor"},
            "editable_hwpx": {"oneOf": [{"$ref": "#/$defs/memberDescriptor"}, {"type": "null"}]},
            "conversion": {"$ref": "#/$defs/conversion"},
            "renderer": {"$ref": "#/$defs/renderer"},
            "page_count": {"type": "integer", "minimum": 1, "maximum": 2000},
            "pages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2000,
                "items": {"$ref": "#/$defs/pageDescriptor"},
            },
            "manifest_sha256": SHA,
        },
        "$defs": {
            "memberDescriptor": member_descriptor(),
            "conversion": conversion(),
            "pageDescriptor": page_descriptor(),
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
                    "pdfinfo_sha256": SHA,
                    "pdftoppm_sha256": SHA,
                    "scale_to_px": {"const": 2400},
                    "output_format": {"const": "PNG"},
                },
            },
        },
    }


def intake_request() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-intake-request/2.0",
        "title": "EOM Office Document Review Intake Request V2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "actor_id",
            "original_filename",
            "source_format",
            "media_type",
            "idempotency_key",
            "content_length",
            "sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-intake-request/2.0"},
            "operation": {"const": "INGEST_DOCUMENT_REVIEW_SOURCE"},
            "actor_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
            },
            "original_filename": source_filename_schema(),
            "source_format": {"enum": ["PDF", "HWP", "HWPX"]},
            "media_type": {
                "enum": [
                    "application/pdf",
                    "application/vnd.hancom.hwp",
                    "application/vnd.hancom.hwpx",
                ]
            },
            "idempotency_key": {
                "type": "string",
                "minLength": 16,
                "maxLength": 256,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,255}$",
            },
            "content_length": {"type": "integer", "minimum": 8, "maximum": 268435456},
            "sha256": SHA,
        },
        "allOf": [
            {
                "if": {"properties": {"source_format": {"const": "PDF"}}},
                "then": {
                    "properties": {
                        "original_filename": {"pattern": r"\.[Pp][Dd][Ff]$"},
                        "media_type": {"const": "application/pdf"},
                    }
                },
            },
            {
                "if": {"properties": {"source_format": {"const": "HWP"}}},
                "then": {
                    "properties": {
                        "original_filename": {"pattern": r"\.[Hh][Ww][Pp]$"},
                        "media_type": {"const": "application/vnd.hancom.hwp"},
                    }
                },
            },
            {
                "if": {"properties": {"source_format": {"const": "HWPX"}}},
                "then": {
                    "properties": {
                        "original_filename": {"pattern": r"\.[Hh][Ww][Pp][Xx]$"},
                        "media_type": {"const": "application/vnd.hancom.hwpx"},
                    }
                },
            },
        ],
    }


def intake_response() -> dict[str, Any]:
    source_document = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "document_id",
            "document_revision_id",
            "original_filename",
            "source_format",
            "original_source",
            "review_document",
            "editable_hwpx",
            "intake_manifest",
            "conversion",
        ],
        "properties": {
            "document_id": DOCUMENT_ID,
            "document_revision_id": DOCUMENT_REVISION_ID,
            "original_filename": source_filename_schema(),
            "source_format": {"enum": ["PDF", "HWP", "HWPX"]},
            "original_source": {"$ref": "#/$defs/memberPointer"},
            "review_document": {"$ref": "#/$defs/reviewDocumentPointer"},
            "editable_hwpx": {"oneOf": [{"$ref": "#/$defs/memberPointer"}, {"type": "null"}]},
            "intake_manifest": {"$ref": "#/$defs/memberPointer"},
            "conversion": {"$ref": "#/$defs/conversion"},
        },
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-intake-response/2.0",
        "title": "EOM Office Document Review Intake Response V2",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "document"],
                "properties": {
                    "schema_version": {"const": "document-review-intake-response/2.0"},
                    "operation": {"const": "INGEST_DOCUMENT_REVIEW_SOURCE"},
                    "status": {"const": "OK"},
                    "document": {"$ref": "#/$defs/sourceDocument"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "error_code"],
                "properties": {
                    "schema_version": {"const": "document-review-intake-response/2.0"},
                    "operation": {"const": "INGEST_DOCUMENT_REVIEW_SOURCE"},
                    "status": {"const": "ERROR"},
                    "error_code": {
                        "type": "string",
                        "pattern": r"^[A-Z][A-Z0-9_]{2,63}$",
                    },
                },
            },
        ],
        "$defs": {
            "memberPointer": member_pointer(),
            "pagePointer": page_pointer(),
            "reviewDocumentPointer": review_document_pointer(),
            "conversion": conversion(),
            "sourceDocument": source_document,
        },
    }


def correction_request() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-hwpx-correction-request/1.0",
        "title": "EOM Document Review HWPX Correction Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "actor_id",
            "idempotency_key",
            "workflow_id",
            "review_result",
            "base_hwpx",
            "finding_ids",
        ],
        "properties": {
            "schema_version": {"const": "document-review-hwpx-correction-request/1.0"},
            "operation": {"const": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"},
            "actor_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
            },
            "idempotency_key": {
                "type": "string",
                "minLength": 16,
                "maxLength": 256,
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,255}$",
            },
            "workflow_id": WORKFLOW_ID,
            "review_result": {"$ref": "#/$defs/memberPointer"},
            "base_hwpx": {"$ref": "#/$defs/memberPointer"},
            "finding_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": FINDING_ID,
            },
        },
        "$defs": {"memberPointer": member_pointer()},
    }


def correction_response() -> dict[str, Any]:
    result = correction_result()
    result.pop("$schema")
    result.pop("$id")
    result.pop("title")
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-hwpx-correction-response/1.0",
        "title": "EOM Document Review HWPX Correction Response V1",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "output", "result"],
                "properties": {
                    "schema_version": {"const": "document-review-hwpx-correction-response/1.0"},
                    "operation": {"const": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"},
                    "status": {"const": "OK"},
                    "output": {"$ref": "#/$defs/memberPointer"},
                    "result": result,
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "error_code"],
                "properties": {
                    "schema_version": {"const": "document-review-hwpx-correction-response/1.0"},
                    "operation": {"const": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"},
                    "status": {"const": "ERROR"},
                    "error_code": {
                        "type": "string",
                        "pattern": r"^[A-Z][A-Z0-9_]{2,63}$",
                    },
                },
            },
        ],
        "$defs": {"memberPointer": member_pointer()},
    }


def correction_media_request() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-hwpx-correction-media-request/1.0",
        "title": "EOM Document Review HWPX Correction Media Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "workflow_id",
            "correction_id",
            "output",
        ],
        "properties": {
            "schema_version": {"const": "document-review-hwpx-correction-media-request/1.0"},
            "operation": {"const": "GET_DOCUMENT_REVIEW_CORRECTED_HWPX"},
            "workflow_id": WORKFLOW_ID,
            "correction_id": {
                "type": "string",
                "pattern": r"^doccorrection_[0-9a-f]{32}$",
            },
            "output": {"$ref": "#/$defs/memberPointer"},
        },
        "$defs": {"memberPointer": member_pointer()},
    }


def correction_media_response() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-hwpx-correction-media-response/1.0",
        "title": "EOM Document Review HWPX Correction Media Response V1",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "operation",
                    "status",
                    "media_type",
                    "content_length",
                    "sha256",
                ],
                "properties": {
                    "schema_version": {
                        "const": "document-review-hwpx-correction-media-response/1.0"
                    },
                    "operation": {"const": "GET_DOCUMENT_REVIEW_CORRECTED_HWPX"},
                    "status": {"const": "OK"},
                    "media_type": {"const": "application/vnd.hancom.hwpx"},
                    "content_length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 268435456,
                    },
                    "sha256": SHA,
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "error_code"],
                "properties": {
                    "schema_version": {
                        "const": "document-review-hwpx-correction-media-response/1.0"
                    },
                    "operation": {"const": "GET_DOCUMENT_REVIEW_CORRECTED_HWPX"},
                    "status": {"const": "ERROR"},
                    "error_code": {
                        "type": "string",
                        "pattern": r"^[A-Z][A-Z0-9_]{2,63}$",
                    },
                },
            },
        ],
    }


def correction_plan() -> dict[str, Any]:
    address = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "section_member",
            "paragraph_ordinal",
            "paragraph_sha256",
            "start_offset",
            "end_offset",
            "source_char_property_id",
        ],
        "properties": {
            "section_member": {
                "type": "string",
                "pattern": r"^Contents/section[0-9]+\.xml$",
            },
            "paragraph_ordinal": {"type": "integer", "minimum": 0, "maximum": 1000000},
            "paragraph_sha256": SHA,
            "start_offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
            "end_offset": {"type": "integer", "minimum": 1, "maximum": 10000000},
            "source_char_property_id": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1000000,
            },
        },
    }
    edit = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "finding_id",
            "finding_code",
            "before_text",
            "before_sha256",
            "after_text",
            "after_sha256",
            "address",
        ],
        "properties": {
            "finding_id": FINDING_ID,
            "finding_code": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,63}$"},
            "before_text": {"type": "string", "minLength": 1, "maxLength": 2000},
            "before_sha256": SHA,
            "after_text": {"type": "string", "minLength": 1, "maxLength": 2000},
            "after_sha256": SHA,
            "address": address,
        },
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-hwpx-correction-plan/1.0",
        "title": "EOM Document Review HWPX Correction Plan V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "correction_id",
            "workflow_id",
            "review_result",
            "base_hwpx",
            "text_color",
            "edits",
            "plan_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-hwpx-correction-plan/1.0"},
            "correction_id": {
                "type": "string",
                "pattern": r"^doccorrection_[0-9a-f]{32}$",
            },
            "workflow_id": WORKFLOW_ID,
            "review_result": {"$ref": "#/$defs/memberPointer"},
            "base_hwpx": {"$ref": "#/$defs/memberPointer"},
            "text_color": {"const": "#FF0000"},
            "edits": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": edit,
            },
            "plan_sha256": SHA,
        },
        "$defs": {"memberPointer": member_pointer()},
    }


def correction_result() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-hwpx-correction-result/1.0",
        "title": "EOM Document Review HWPX Correction Result V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "correction_id",
            "workflow_id",
            "plan_sha256",
            "base_hwpx_sha256",
            "output_member",
            "applied_finding_ids",
            "text_color",
            "result_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-hwpx-correction-result/1.0"},
            "correction_id": {
                "type": "string",
                "pattern": r"^doccorrection_[0-9a-f]{32}$",
            },
            "workflow_id": WORKFLOW_ID,
            "plan_sha256": SHA,
            "base_hwpx_sha256": SHA,
            "output_member": {
                "type": "object",
                "additionalProperties": False,
                "required": ["member_path", "sha256", "content_length", "media_type"],
                "properties": {
                    "member_path": {"const": "corrected/document-review-redline.hwpx"},
                    "sha256": SHA,
                    "content_length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 268435456,
                    },
                    "media_type": {"const": "application/vnd.hancom.hwpx"},
                },
            },
            "applied_finding_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": FINDING_ID,
            },
            "text_color": {"const": "#FF0000"},
            "result_sha256": SHA,
        },
    }


SCHEMAS = {
    "schemas/document-review/document-review-intake-manifest-v2.schema.json": intake_manifest(),
    "schemas/catalog/catalog-application/document-review-intake-request-v2.schema.json": (
        intake_request()
    ),
    "schemas/catalog/catalog-application/document-review-intake-response-v2.schema.json": (
        intake_response()
    ),
    "schemas/catalog/catalog-application/document-review-hwpx-correction-request-v1.schema.json": (
        correction_request()
    ),
    "schemas/catalog/catalog-application/document-review-hwpx-correction-response-v1.schema.json": (
        correction_response()
    ),
    (
        "schemas/catalog/catalog-application/"
        "document-review-hwpx-correction-media-request-v1.schema.json"
    ): (correction_media_request()),
    (
        "schemas/catalog/catalog-application/"
        "document-review-hwpx-correction-media-response-v1.schema.json"
    ): (correction_media_response()),
    "schemas/document-review/document-review-hwpx-correction-plan-v1.schema.json": (
        correction_plan()
    ),
    "schemas/document-review/document-review-hwpx-correction-result-v1.schema.json": (
        correction_result()
    ),
}


def package_path(canonical: str) -> Path:
    name = Path(canonical).name
    if "/catalog-application/" in canonical:
        return (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
            / name
        )
    return (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/document-review" / name
    )


def main() -> None:
    for relative, schema in SCHEMAS.items():
        payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        targets = (ROOT / relative, package_path(relative))
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

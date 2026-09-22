#!/usr/bin/env python3
"""Generate immutable document-review PDF annotation schemas."""

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
ANNOTATION_ID = {"type": "string", "pattern": r"^docannotation_[0-9a-f]{32}$"}
ROLE = {"enum": ["DOCUMENT", "QUESTION", "SOLUTION"]}


def member_pointer() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "artifact_id",
            "artifact_revision_id",
            "member_path",
            "sha256",
            "content_length",
            "media_type",
            "schema_ref",
        ],
        "properties": {
            "artifact_id": ARTIFACT_ID,
            "artifact_revision_id": REVISION_ID,
            "member_path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "pattern": r"^[A-Za-z0-9._/-]+$",
            },
            "sha256": SHA,
            "content_length": {"type": "integer", "minimum": 1, "maximum": 536870912},
            "media_type": {"enum": ["application/pdf", "application/json", "image/png"]},
            "schema_ref": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "pattern": r"^(?:eom://|https://eom\.local/)[A-Za-z0-9._:/-]+$",
            },
        },
    }


def region() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["x_ppm", "y_ppm", "width_ppm", "height_ppm"],
        "properties": {
            "x_ppm": {"type": "integer", "minimum": 0, "maximum": 999999},
            "y_ppm": {"type": "integer", "minimum": 0, "maximum": 999999},
            "width_ppm": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "height_ppm": {"type": "integer", "minimum": 1, "maximum": 1000000},
        },
    }


def page() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["page_number", "page_image"],
        "properties": {
            "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
            "page_image": {"$ref": "#/$defs/memberPointer"},
        },
    }


def source() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role",
            "document_id",
            "document_revision_id",
            "source_pdf",
            "page_count",
            "pages",
        ],
        "properties": {
            "role": ROLE,
            "document_id": DOCUMENT_ID,
            "document_revision_id": DOCUMENT_REVISION_ID,
            "source_pdf": {"$ref": "#/$defs/memberPointer"},
            "page_count": {"type": "integer", "minimum": 1, "maximum": 2000},
            "pages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2000,
                "items": {"$ref": "#/$defs/page"},
            },
        },
    }


def mark() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "finding_id",
            "anchor_id",
            "ordinal",
            "document_role",
            "page_number",
            "page_image_sha256",
            "region",
        ],
        "properties": {
            "finding_id": {"type": "string", "pattern": r"^reviewfinding_[0-9a-f]{32}$"},
            "anchor_id": {"type": "string", "pattern": r"^reviewanchor_[0-9a-f]{32}$"},
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 512},
            "document_role": ROLE,
            "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
            "page_image_sha256": SHA,
            "region": {"$ref": "#/$defs/region"},
        },
    }


def review_result_pointer() -> dict[str, Any]:
    value = member_pointer()
    value["properties"]["member_path"] = {"const": "result.json"}
    value["properties"]["media_type"] = {"const": "application/json"}
    value["properties"]["schema_ref"] = {
        "enum": [
            "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
            "https://eom.local/schemas/workflow/roles/paired-document-review-result-v2.schema.json",
        ]
    }
    value["properties"]["content_length"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 16777216,
    }
    return value


def output_descriptor(pointer: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "document_role": ROLE,
        "member_path": {
            "enum": [
                "annotated/document.pdf",
                "annotated/question.pdf",
                "annotated/solution.pdf",
            ]
        },
        "sha256": SHA,
        "content_length": {"type": "integer", "minimum": 1, "maximum": 536870912},
        "media_type": {"const": "application/pdf"},
        "schema_ref": {"const": "eom://schemas/document-review/annotated-pdf/1.0"},
    }
    required = list(properties)
    if pointer:
        properties = {
            "artifact_id": ARTIFACT_ID,
            "artifact_revision_id": REVISION_ID,
            **properties,
        }
        required = ["artifact_id", "artifact_revision_id", *required]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def renderer() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "renderer_key",
            "qpdf_version",
            "qpdf_sha256",
            "rsvg_convert_version",
            "rsvg_convert_sha256",
            "pdfinfo_version",
            "pdfinfo_sha256",
            "stroke_color",
        ],
        "properties": {
            "renderer_key": {"const": "qpdf-rsvg-document-review-annotation"},
            "qpdf_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "qpdf_sha256": SHA,
            "rsvg_convert_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "rsvg_convert_sha256": SHA,
            "pdfinfo_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "pdfinfo_sha256": SHA,
            "stroke_color": {"const": "#D70015"},
        },
    }


def request_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-request/1.0",
        "title": "EOM Document Review PDF Annotation Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "actor_id",
            "idempotency_key",
            "workflow_id",
            "review_result",
            "sources",
            "annotations",
            "annotation_set_sha256",
            "request_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-request/1.0"},
            "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"},
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
            "review_result": {"$ref": "#/$defs/reviewResultPointer"},
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"$ref": "#/$defs/source"},
            },
            "annotations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4096,
                "items": {"$ref": "#/$defs/mark"},
            },
            "annotation_set_sha256": SHA,
            "request_sha256": SHA,
        },
        "$defs": {
            "memberPointer": member_pointer(),
            "reviewResultPointer": review_result_pointer(),
            "page": page(),
            "source": source(),
            "region": region(),
            "mark": mark(),
        },
    }


def result_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-pdf-annotation-result/1.0",
        "title": "EOM Document Review PDF Annotation Result V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "annotation_id",
            "workflow_id",
            "request_sha256",
            "review_result_sha256",
            "annotation_set_sha256",
            "outputs",
            "manifest_sha256",
            "result_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-result/1.0"},
            "annotation_id": ANNOTATION_ID,
            "workflow_id": WORKFLOW_ID,
            "request_sha256": SHA,
            "review_result_sha256": SHA,
            "annotation_set_sha256": SHA,
            "outputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"$ref": "#/$defs/output"},
            },
            "manifest_sha256": SHA,
            "result_sha256": SHA,
        },
        "$defs": {"output": output_descriptor()},
    }


def manifest_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-pdf-annotation-manifest/1.0",
        "title": "EOM Document Review PDF Annotation Manifest V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "annotation_id",
            "workflow_id",
            "request_sha256",
            "review_result_sha256",
            "sources",
            "annotations",
            "annotation_set_sha256",
            "renderer",
            "outputs",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-manifest/1.0"},
            "annotation_id": ANNOTATION_ID,
            "workflow_id": WORKFLOW_ID,
            "request_sha256": SHA,
            "review_result_sha256": SHA,
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"$ref": "#/$defs/source"},
            },
            "annotations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4096,
                "items": {"$ref": "#/$defs/mark"},
            },
            "annotation_set_sha256": SHA,
            "renderer": {"$ref": "#/$defs/renderer"},
            "outputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"$ref": "#/$defs/output"},
            },
            "manifest_sha256": SHA,
        },
        "$defs": {
            "memberPointer": member_pointer(),
            "page": page(),
            "source": source(),
            "region": region(),
            "mark": mark(),
            "renderer": renderer(),
            "output": output_descriptor(),
        },
    }


def response_schema() -> dict[str, Any]:
    embedded_result = result_schema()
    for key in ("$schema", "$id", "title"):
        embedded_result.pop(key)
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-response/1.0",
        "title": "EOM Document Review PDF Annotation Response V1",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "operation",
                    "status",
                    "outputs",
                    "manifest",
                    "result",
                ],
                "properties": {
                    "schema_version": {"const": "document-review-pdf-annotation-response/1.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"},
                    "status": {"const": "OK"},
                    "outputs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "items": {"$ref": "#/$defs/outputPointer"},
                    },
                    "manifest": {"$ref": "#/$defs/memberPointer"},
                    "result": embedded_result,
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "error_code"],
                "properties": {
                    "schema_version": {"const": "document-review-pdf-annotation-response/1.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"},
                    "status": {"const": "ERROR"},
                    "error_code": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,63}$"},
                },
            },
        ],
        "$defs": {
            "memberPointer": member_pointer(),
            "outputPointer": output_descriptor(pointer=True),
            "output": output_descriptor(),
        },
    }


def media_request_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-media-request/1.0",
        "title": "EOM Document Review PDF Annotation Media Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "workflow_id",
            "annotation_id",
            "document_role",
            "output",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-media-request/1.0"},
            "operation": {"const": "GET_DOCUMENT_REVIEW_ANNOTATED_PDF"},
            "workflow_id": WORKFLOW_ID,
            "annotation_id": ANNOTATION_ID,
            "document_role": ROLE,
            "output": {"$ref": "#/$defs/outputPointer"},
        },
        "$defs": {"outputPointer": output_descriptor(pointer=True)},
    }


def media_response_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-media-response/1.0",
        "title": "EOM Document Review PDF Annotation Media Response V1",
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
                        "const": "document-review-pdf-annotation-media-response/1.0"
                    },
                    "operation": {"const": "GET_DOCUMENT_REVIEW_ANNOTATED_PDF"},
                    "status": {"const": "OK"},
                    "media_type": {"const": "application/pdf"},
                    "content_length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 536870912,
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
                        "const": "document-review-pdf-annotation-media-response/1.0"
                    },
                    "operation": {"const": "GET_DOCUMENT_REVIEW_ANNOTATED_PDF"},
                    "status": {"const": "ERROR"},
                    "error_code": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{2,63}$"},
                },
            },
        ],
    }


def write(name: str, value: dict[str, Any], *, application: bool) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    canonical = ROOT / (
        "schemas/catalog/catalog-application" if application else "schemas/document-review"
    )
    packaged = ROOT / (
        "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
        if application
        else "packages/catalog_contracts/eom_catalog_contracts/resources/document-review"
    )
    for directory in (canonical, packaged):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(payload, encoding="ascii")


def main() -> None:
    write(
        "document-review-pdf-annotation-request-v1.schema.json", request_schema(), application=True
    )
    write(
        "document-review-pdf-annotation-response-v1.schema.json",
        response_schema(),
        application=True,
    )
    write(
        "document-review-pdf-annotation-media-request-v1.schema.json",
        media_request_schema(),
        application=True,
    )
    write(
        "document-review-pdf-annotation-media-response-v1.schema.json",
        media_response_schema(),
        application=True,
    )
    write(
        "document-review-pdf-annotation-manifest-v1.schema.json",
        manifest_schema(),
        application=False,
    )
    write(
        "document-review-pdf-annotation-result-v1.schema.json",
        result_schema(),
        application=False,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate native-comment-panel document-review PDF annotation schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from generate_document_review_pdf_annotation_v1_schemas import (
    ANNOTATION_ID,
    ROLE,
    SCHEMA,
    SHA,
    WORKFLOW_ID,
    member_pointer,
    output_descriptor,
    page,
    region,
    review_result_pointer,
    source,
)

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "NUMBERED_BOXES_WITH_NATIVE_COMMENTS"


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


def panel_comment() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "comment_id",
            "finding_id",
            "anchor_id",
            "ordinal",
            "document_role",
            "page_number",
            "contents_sha256",
            "contents_utf8_length",
        ],
        "properties": {
            "comment_id": {"type": "string", "pattern": r"^reviewcomment_[0-9a-f]{32}$"},
            "finding_id": {"type": "string", "pattern": r"^reviewfinding_[0-9a-f]{32}$"},
            "anchor_id": {"type": "string", "pattern": r"^reviewanchor_[0-9a-f]{32}$"},
            "ordinal": {"type": "integer", "minimum": 1, "maximum": 512},
            "document_role": ROLE,
            "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
            "contents_sha256": SHA,
            "contents_utf8_length": {"type": "integer", "minimum": 1, "maximum": 65536},
        },
    }


def renderer() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "renderer_key",
            "annotation_profile",
            "qpdf_version",
            "qpdf_sha256",
            "rsvg_convert_version",
            "rsvg_convert_sha256",
            "pdfinfo_version",
            "pdfinfo_sha256",
            "pymupdf_version",
            "pymupdf_module_sha256",
            "pymupdf_native_sha256",
            "stroke_color",
            "native_annotation_subtype",
        ],
        "properties": {
            "renderer_key": {"const": "pymupdf-qpdf-rsvg-document-review-annotation"},
            "annotation_profile": {"const": PROFILE},
            "qpdf_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "qpdf_sha256": SHA,
            "rsvg_convert_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "rsvg_convert_sha256": SHA,
            "pdfinfo_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "pdfinfo_sha256": SHA,
            "pymupdf_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "pymupdf_module_sha256": SHA,
            "pymupdf_native_sha256": SHA,
            "stroke_color": {"const": "#D70015"},
            "native_annotation_subtype": {"const": "Square"},
        },
    }


def request_schema() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-request/2.0",
        "title": "EOM Document Review PDF Annotation Request V2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "annotation_profile",
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
            "schema_version": {"const": "document-review-pdf-annotation-request/2.0"},
            "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"},
            "annotation_profile": {"const": PROFILE},
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
        "$id": "eom://schemas/document-review/document-review-pdf-annotation-result/2.0",
        "title": "EOM Document Review PDF Annotation Result V2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "annotation_profile",
            "annotation_id",
            "workflow_id",
            "request_sha256",
            "review_result_sha256",
            "annotation_set_sha256",
            "panel_comment_set_sha256",
            "panel_comment_count",
            "outputs",
            "manifest_sha256",
            "result_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-result/2.0"},
            "annotation_profile": {"const": PROFILE},
            "annotation_id": ANNOTATION_ID,
            "workflow_id": WORKFLOW_ID,
            "request_sha256": SHA,
            "review_result_sha256": SHA,
            "annotation_set_sha256": SHA,
            "panel_comment_set_sha256": SHA,
            "panel_comment_count": {"type": "integer", "minimum": 1, "maximum": 1024},
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
        "$id": "eom://schemas/document-review/document-review-pdf-annotation-manifest/2.0",
        "title": "EOM Document Review PDF Annotation Manifest V2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "annotation_profile",
            "annotation_id",
            "workflow_id",
            "request_sha256",
            "review_result_sha256",
            "sources",
            "annotations",
            "annotation_set_sha256",
            "panel_comments",
            "panel_comment_set_sha256",
            "renderer",
            "outputs",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-pdf-annotation-manifest/2.0"},
            "annotation_profile": {"const": PROFILE},
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
            "panel_comments": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1024,
                "items": {"$ref": "#/$defs/panelComment"},
            },
            "panel_comment_set_sha256": SHA,
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
            "panelComment": panel_comment(),
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
        "$id": "eom://schemas/catalog/document-review-pdf-annotation-response/2.0",
        "title": "EOM Document Review PDF Annotation Response V2",
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
                    "schema_version": {"const": "document-review-pdf-annotation-response/2.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"},
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
                    "schema_version": {"const": "document-review-pdf-annotation-response/2.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"},
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
        "document-review-pdf-annotation-request-v2.schema.json",
        request_schema(),
        application=True,
    )
    write(
        "document-review-pdf-annotation-response-v2.schema.json",
        response_schema(),
        application=True,
    )
    write(
        "document-review-pdf-annotation-manifest-v2.schema.json",
        manifest_schema(),
        application=False,
    )
    write(
        "document-review-pdf-annotation-result-v2.schema.json",
        result_schema(),
        application=False,
    )


if __name__ == "__main__":
    main()

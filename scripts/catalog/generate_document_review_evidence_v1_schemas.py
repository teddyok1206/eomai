#!/usr/bin/env python3
"""Generate Catalog contracts for Graph-grounded paired document review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_REVIEW = ROOT / "schemas/document-review"
PACKAGED_REVIEW = (
    ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/document-review"
)
CANONICAL_APPLICATION = ROOT / "schemas/catalog-application"
PACKAGED_APPLICATION = (
    ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
)
SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
DOCUMENT = {
    "$ref": ("eom://schemas/catalog/pdf-document-review-intake-response/1.0#/$defs/documentPointer")
}


def _review_document(*, full: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "role": {"enum": ["QUESTION", "SOLUTION"]},
        "document_id": {"type": "string", "pattern": "^document_[0-9a-f]{32}$"},
        "document_revision_id": {
            "type": "string",
            "pattern": "^documentrev_[0-9a-f]{32}$",
        },
        "source_pdf_sha256": SHA,
    }
    required = ["role", "document_id", "document_revision_id", "source_pdf_sha256"]
    if full:
        properties = {"role": properties["role"], "document": DOCUMENT}
        required = ["role", "document"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _documents(*, full: bool) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "prefixItems": [
            {
                "allOf": [
                    _review_document(full=full),
                    {"properties": {"role": {"const": "QUESTION"}}},
                ]
            },
            {
                "allOf": [
                    _review_document(full=full),
                    {"properties": {"role": {"const": "SOLUTION"}}},
                ]
            },
        ],
        "items": False,
    }


def _budget() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "max_documents",
            "max_item_revisions",
            "max_graph_nodes",
            "max_claims",
            "max_context_tokens",
        ],
        "properties": {
            "max_documents": {"type": "integer", "minimum": 1, "maximum": 32},
            "max_item_revisions": {"type": "integer", "minimum": 0, "maximum": 64},
            "max_graph_nodes": {"type": "integer", "minimum": 1, "maximum": 256},
            "max_claims": {"type": "integer", "minimum": 1, "maximum": 128},
            "max_context_tokens": {"type": "integer", "minimum": 1000, "maximum": 32000},
        },
    }


def plan_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/document-review/document-review-evidence-plan/1.0",
        "title": "EOM Document Review Evidence Plan V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "documents",
            "term_set_sha256",
            "topic_keys",
            "extractor",
            "requirement",
            "publication",
            "plan_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-evidence-plan/1.0"},
            "documents": _documents(full=False),
            "term_set_sha256": SHA,
            "topic_keys": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9._:-]{0,127}$",
                },
            },
            "extractor": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "extractor_key",
                    "executable_sha256",
                    "max_text_bytes",
                    "max_terms",
                ],
                "properties": {
                    "extractor_key": {"const": "poppler-pdftotext"},
                    "executable_sha256": SHA,
                    "max_text_bytes": {"const": 8388608},
                    "max_terms": {"const": 512},
                },
            },
            "requirement": {
                "$ref": "eom://schemas/knowledge/educational-retrieval-requirement/1.0"
            },
            "publication": {
                "$ref": "eom://schemas/knowledge/evidence-bundle-publication-result/5.0"
            },
            "plan_sha256": SHA,
        },
    }


def request_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog/document-review-evidence-request/1.0",
        "title": "EOM Document Review Evidence Request V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "operation",
            "documents",
            "corpus_key",
            "source_classes",
            "evidence_budget",
            "access_policy_revision_id",
            "access_policy_sha256",
            "requester_role",
            "requester_permission_keys",
            "requested_by",
            "idempotency_key",
            "submission_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-evidence-request/1.0"},
            "operation": {"const": "CREATE_DOCUMENT_REVIEW_EVIDENCE"},
            "documents": _documents(full=True),
            "corpus_key": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9_-]{1,63}$",
            },
            "source_classes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "CURRICULUM",
                        "TEXTBOOK",
                        "PAST_EXAM",
                        "APPROVED_ITEM",
                        "INTERNAL_GUIDE",
                    ]
                },
            },
            "evidence_budget": _budget(),
            "access_policy_revision_id": {
                "type": "string",
                "pattern": "^accessrev_[0-9a-f]{32}$",
            },
            "access_policy_sha256": SHA,
            "requester_role": {"enum": ["ADMIN", "EDITOR", "REVIEWER"]},
            "requester_permission_keys": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$",
                    "maxLength": 128,
                },
            },
            "requested_by": {
                "type": "string",
                "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
            },
            "idempotency_key": {
                "type": "string",
                "minLength": 16,
                "maxLength": 128,
                "pattern": "^[!-~]+$",
            },
            "submission_sha256": SHA,
        },
    }


def response_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/catalog/document-review-evidence-response/1.0",
        "title": "EOM Document Review Evidence Response V1",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "plan"],
                "properties": {
                    "schema_version": {"const": "document-review-evidence-response/1.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_EVIDENCE"},
                    "status": {"const": "OK"},
                    "plan": {
                        "$ref": ("eom://schemas/document-review/document-review-evidence-plan/1.0")
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema_version", "operation", "status", "error_code"],
                "properties": {
                    "schema_version": {"const": "document-review-evidence-response/1.0"},
                    "operation": {"const": "CREATE_DOCUMENT_REVIEW_EVIDENCE"},
                    "status": {"const": "ERROR"},
                    "error_code": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]{2,127}$",
                    },
                },
            },
        ],
    }


def _write(directory: Path, name: str, value: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    for directory in (CANONICAL_REVIEW, PACKAGED_REVIEW):
        _write(directory, "document-review-evidence-plan-v1.schema.json", plan_schema())
    for directory in (CANONICAL_APPLICATION, PACKAGED_APPLICATION):
        _write(directory, "document-review-evidence-request-v1.schema.json", request_schema())
        _write(directory, "document-review-evidence-response-v1.schema.json", response_schema())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate canonical and packaged paired document-review role schemas."""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/roles"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/roles"
V1 = runpy.run_path(str(Path(__file__).with_name("generate_pdf_document_review_v1_schemas.py")))
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
NO_CONTROL = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"


def input_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(V1["input_schema"]())
    value["$id"] = (
        "https://eom.local/schemas/workflow/roles/paired-document-review-input-v2.schema.json"
    )
    value["title"] = "EOM Paired Document Review Worker Input V2"
    value["properties"]["protocol_version"] = {"const": "workflow-role/1.26.0"}
    defs = value["$defs"]
    defs["review_document"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["role", "document"],
        "properties": {
            "role": {"enum": ["QUESTION", "SOLUTION"]},
            "document": {"$ref": "#/$defs/document"},
        },
    }
    review_request = defs["review_request"]
    review_request["required"] = [
        "schema_version",
        "documents",
        "preset",
        "additional_guidance",
        "additional_guidance_sha256",
        "locale",
        "request_sha256",
    ]
    review_request["properties"].pop("document")
    review_request["properties"]["schema_version"] = {"const": "paired-document-review-request/1.0"}
    review_request["properties"]["documents"] = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "prefixItems": [
            {
                "allOf": [
                    {"$ref": "#/$defs/review_document"},
                    {"properties": {"role": {"const": "QUESTION"}}},
                ]
            },
            {
                "allOf": [
                    {"$ref": "#/$defs/review_document"},
                    {"properties": {"role": {"const": "SOLUTION"}}},
                ]
            },
        ],
        "items": False,
    }
    worker_request = defs["worker_request"]
    worker_request["properties"]["request_name"] = {"const": "PAIRED_DOCUMENT_REVIEW_REQUEST"}
    return value


def result_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(V1["result_schema"]())
    value["$id"] = (
        "https://eom.local/schemas/workflow/roles/paired-document-review-result-v2.schema.json"
    )
    value["title"] = "EOM Paired Document Review Result V2"
    value["properties"]["protocol_version"] = {"const": "workflow-role/1.26.0"}
    defs = value["$defs"]
    anchor = defs["anchor"]
    anchor["required"].insert(1, "document_role")
    anchor["properties"]["document_role"] = {"enum": ["QUESTION", "SOLUTION"]}
    defs["page_ref"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["document_role", "page_number"],
        "properties": {
            "document_role": {"enum": ["QUESTION", "SOLUTION"]},
            "page_number": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
    }
    target = defs["target"]
    target["required"].remove("page_numbers")
    target["required"].insert(2, "page_refs")
    target["properties"].pop("page_numbers")
    target["properties"]["page_refs"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 4000,
        "items": {"$ref": "#/$defs/page_ref"},
    }
    defs["document_identity"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role",
            "document_id",
            "document_revision_id",
            "source_pdf_sha256",
        ],
        "properties": {
            "role": {"enum": ["QUESTION", "SOLUTION"]},
            "document_id": {"type": "string", "pattern": "^document_[0-9a-f]{32}$"},
            "document_revision_id": {
                "type": "string",
                "pattern": "^documentrev_[0-9a-f]{32}$",
            },
            "source_pdf_sha256": HASH,
        },
    }
    defs["cross_document_check"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "check_id",
            "question_anchors",
            "solution_anchors",
            "status",
            "conclusion",
        ],
        "properties": {
            "check_id": {"type": "string", "pattern": "^reviewcross_[0-9a-f]{32}$"},
            "question_anchors": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/anchor"},
            },
            "solution_anchors": {
                "type": "array",
                "maxItems": 16,
                "items": {"$ref": "#/$defs/anchor"},
            },
            "status": {"enum": ["MATCHED", "MISMATCH", "MISSING", "INSUFFICIENT"]},
            "conclusion": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "pattern": NO_CONTROL,
            },
        },
    }
    output = defs["output"]
    for name in ("document_id", "document_revision_id", "source_pdf_sha256"):
        output["required"].remove(name)
        output["properties"].pop(name)
    output["required"].insert(1, "documents")
    output["required"].insert(-1, "cross_document_checks")
    output["properties"]["documents"] = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "prefixItems": [
            {
                "allOf": [
                    {"$ref": "#/$defs/document_identity"},
                    {"properties": {"role": {"const": "QUESTION"}}},
                ]
            },
            {
                "allOf": [
                    {"$ref": "#/$defs/document_identity"},
                    {"properties": {"role": {"const": "SOLUTION"}}},
                ]
            },
        ],
        "items": False,
    }
    output["properties"]["cross_document_checks"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 512,
        "items": {"$ref": "#/$defs/cross_document_check"},
    }
    return value


def write(name: str, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    for directory in (CANONICAL, PACKAGED):
        path = directory / name
        path.write_text(payload, encoding="utf-8")


def main() -> None:
    write("paired-document-review-input-v2.schema.json", input_schema())
    write("paired-document-review-result-v2.schema.json", result_schema())


if __name__ == "__main__":
    main()

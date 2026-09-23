#!/usr/bin/env python3
"""Generate durable-source Office-document intake and conversion schemas."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
SHA = {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}


def _load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def intake_request() -> dict[str, Any]:
    value = _load(
        "schemas/catalog/catalog-application/document-review-intake-request-v2.schema.json"
    )
    value["$id"] = "eom://schemas/catalog/document-review-intake-request/3.0"
    value["title"] = "EOM Office Document Review Intake Request V3"
    value["properties"]["schema_version"] = {"const": "document-review-intake-request/3.0"}
    value["properties"]["source_format"] = {"enum": ["HWP", "HWPX"]}
    value["properties"]["media_type"] = {
        "enum": ["application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"]
    }
    value["properties"]["original_filename"]["pattern"] = (
        r"^[^/\\\u0000-\u001f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$"
    )
    value["allOf"] = [
        rule
        for rule in value["allOf"]
        if rule["if"]["properties"]["source_format"]["const"] != "PDF"
    ]
    return value


def source_manifest() -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/document-review-source-upload-manifest/1.0",
        "title": "EOM Office Document Review Source Upload Manifest V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "original_filename",
            "source_format",
            "original_source",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "document-review-source-upload-manifest/1.0"},
            "original_filename": {
                "type": "string",
                "minLength": 5,
                "maxLength": 240,
                "pattern": r"^[^/\\\u0000-\u001f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$",
            },
            "source_format": {"enum": ["HWP", "HWPX"]},
            "original_source": {"$ref": "#/$defs/memberDescriptor"},
            "manifest_sha256": SHA,
        },
        "$defs": {
            "memberDescriptor": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "member_path",
                    "sha256",
                    "content_length",
                    "media_type",
                    "schema_ref",
                ],
                "properties": {
                    "member_path": {
                        "type": "string",
                        "pattern": r"^source/original\.(?:pdf|hwp|hwpx)$",
                    },
                    "sha256": SHA,
                    "content_length": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 268435456,
                    },
                    "media_type": {
                        "enum": [
                            "application/pdf",
                            "application/vnd.hancom.hwp",
                            "application/vnd.hancom.hwpx",
                        ]
                    },
                    "schema_ref": {
                        "enum": [
                            "eom://schemas/document-review/pdf-source/1.0",
                            "eom://schemas/document-review/hwp-source/2.0",
                            "eom://schemas/document-review/editable-hwpx/1.0",
                        ]
                    },
                },
            }
        },
    }


def intake_manifest() -> dict[str, Any]:
    value = _load("schemas/document-review/document-review-intake-manifest-v2.schema.json")
    value["$id"] = "eom://schemas/document-review/document-review-intake-manifest/3.0"
    value["title"] = "EOM Office Document Review Intake Manifest V3"
    value["properties"]["schema_version"] = {"const": "document-review-intake-manifest/3.0"}
    value["properties"]["source_format"] = {"enum": ["HWP", "HWPX"]}
    value["properties"]["original_filename"]["pattern"] = (
        r"^[^/\\\u0000-\u001f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$"
    )
    pointer = copy.deepcopy(value["$defs"]["memberDescriptor"])
    pointer["required"] = ["artifact_id", "artifact_revision_id", *pointer["required"]]
    pointer["properties"] = {
        "artifact_id": {"type": "string", "pattern": r"^artifact_[0-9a-f]{32}$"},
        "artifact_revision_id": {"type": "string", "pattern": r"^rev_[0-9a-f]{32}$"},
        **pointer["properties"],
    }
    value["$defs"]["memberPointer"] = pointer
    value["properties"]["original_source"] = {"$ref": "#/$defs/memberPointer"}
    value["properties"]["editable_hwpx"] = {
        "oneOf": [{"$ref": "#/$defs/memberPointer"}, {"type": "null"}]
    }
    return value


def intake_response() -> dict[str, Any]:
    value = _load(
        "schemas/catalog/catalog-application/document-review-intake-response-v2.schema.json"
    )
    value["$id"] = "eom://schemas/catalog/document-review-intake-response/3.0"
    value["title"] = "EOM Office Document Review Intake Response V3"
    value["$defs"]["memberPointer"]["properties"]["schema_ref"]["pattern"] = (
        r"^eom://schemas/document-review/[a-z0-9-]+/[123]\.0$"
    )
    source_document = value["$defs"]["sourceDocument"]
    source_document["properties"]["source_format"] = {"enum": ["HWP", "HWPX"]}
    source_document["properties"]["original_filename"]["pattern"] = (
        r"^[^/\\\u0000-\u001f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$"
    )
    for branch in value["oneOf"]:
        branch["properties"]["schema_version"] = {"const": "document-review-intake-response/3.0"}
        if branch["properties"]["status"]["const"] == "ERROR":
            branch["properties"]["retained_source"] = {
                "oneOf": [{"$ref": "#/$defs/memberPointer"}, {"type": "null"}]
            }
            branch["required"].append("retained_source")
    return value


def conversion_outcome() -> dict[str, Any]:
    error_stages = {
        "OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID": "DEPENDENCY_VALIDATION",
        "OFFICE_DOCUMENT_CONVERSION_EXTENSION_FAILED": "EXTENSION_REGISTRATION",
        "OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED": "LIBREOFFICE_EXECUTION",
        "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE": "LIBREOFFICE_EXECUTION",
        "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING": "OUTPUT_VALIDATION",
        "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID": "OUTPUT_VALIDATION",
        "OFFICE_DOCUMENT_CONVERSION_SOURCE_INVALID": "SOURCE_VALIDATION",
    }
    return {
        "$schema": SCHEMA,
        "$id": "eom://schemas/document-review/office-document-conversion-outcome/1.0",
        "title": "EOM Office Document Conversion Outcome V1",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "instance_id",
                    "status",
                    "stage",
                    "source_format",
                    "source_sha256",
                    "source_bytes",
                    "h2orestart_sha256",
                    "stdout_sha256",
                    "stdout_bytes",
                    "stderr_sha256",
                    "stderr_bytes",
                    "output_sha256",
                    "output_bytes",
                    "outcome_sha256",
                ],
                "properties": {
                    "schema_version": {"const": "office-document-conversion-outcome/1.0"},
                    "instance_id": {
                        "type": "string",
                        "pattern": r"^officeconv_[0-9a-f]{32}$",
                    },
                    "status": {"const": "OK"},
                    "stage": {"const": "OUTPUT_VALIDATED"},
                    "source_format": {"enum": ["HWP", "HWPX"]},
                    "source_sha256": SHA,
                    "source_bytes": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 268435456,
                    },
                    "h2orestart_sha256": SHA,
                    "stdout_sha256": SHA,
                    "stdout_bytes": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 262144,
                    },
                    "stderr_sha256": SHA,
                    "stderr_bytes": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 262144,
                    },
                    "output_sha256": SHA,
                    "output_bytes": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 268435456,
                    },
                    "outcome_sha256": SHA,
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "instance_id",
                    "status",
                    "stage",
                    "error_code",
                    "source_format",
                    "source_sha256",
                    "source_bytes",
                    "h2orestart_sha256",
                    "stdout_sha256",
                    "stdout_bytes",
                    "stderr_sha256",
                    "stderr_bytes",
                    "outcome_sha256",
                ],
                "properties": {
                    "schema_version": {"const": "office-document-conversion-outcome/1.0"},
                    "instance_id": {
                        "type": "string",
                        "pattern": r"^officeconv_[0-9a-f]{32}$",
                    },
                    "status": {"const": "ERROR"},
                    "stage": {"enum": sorted(set(error_stages.values()))},
                    "error_code": {"enum": sorted(error_stages)},
                    "source_format": {"enum": ["HWP", "HWPX"]},
                    "source_sha256": SHA,
                    "source_bytes": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 268435456,
                    },
                    "h2orestart_sha256": SHA,
                    "stdout_sha256": SHA,
                    "stdout_bytes": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 262144,
                    },
                    "stderr_sha256": SHA,
                    "stderr_bytes": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 262144,
                    },
                    "outcome_sha256": SHA,
                },
                "allOf": [
                    {
                        "if": {"properties": {"error_code": {"const": code}}},
                        "then": {"properties": {"stage": {"const": stage}}},
                    }
                    for code, stage in error_stages.items()
                ],
            },
        ],
    }


SCHEMAS = {
    "schemas/document-review/document-review-source-upload-manifest-v1.schema.json": (
        source_manifest()
    ),
    "schemas/document-review/document-review-intake-manifest-v3.schema.json": intake_manifest(),
    "schemas/document-review/office-document-conversion-outcome-v1.schema.json": (
        conversion_outcome()
    ),
    "schemas/catalog/catalog-application/document-review-intake-request-v3.schema.json": (
        intake_request()
    ),
    "schemas/catalog/catalog-application/document-review-intake-response-v3.schema.json": (
        intake_response()
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
        for target in (ROOT / relative, package_path(relative)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

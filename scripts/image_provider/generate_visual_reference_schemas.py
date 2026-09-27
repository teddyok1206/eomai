#!/usr/bin/env python3
"""Generate additive visual-reference contracts without changing released image schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/image-provider"
PACKAGED = ROOT / "packages/image_contracts/eom_image_contracts/schemas"

SHA256 = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
UTC = {
    "type": "string",
    "format": "date-time",
    "pattern": "Z$",
}


def _header(identifier: str, title: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": identifier,
        "title": title,
        "type": "object",
        "additionalProperties": False,
    }


def _artifact_member(*, path_pattern: str, schema_const: str, media_const: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "artifact_id",
            "artifact_revision_id",
            "member_path",
            "schema_ref",
            "media_type",
            "sha256",
            "size_bytes",
        ],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {"type": "string", "pattern": "^rev_[0-9a-f]{32}$"},
            "member_path": {"type": "string", "pattern": path_pattern},
            "schema_ref": {"const": schema_const},
            "media_type": {"const": media_const},
            "sha256": SHA256,
            "size_bytes": {"type": "integer", "minimum": 1, "maximum": 16777216},
        },
    }


def intent_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-intent/1.0",
        "EOM local image visual reference intent v1",
    )
    value["$defs"] = {
        "candidate": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "rank",
                "provider",
                "page_id",
                "file_title",
                "canonical_page_url",
                "selection_rationale",
                "intended_use",
                "license_expectation",
            ],
            "properties": {
                "rank": {"type": "integer", "minimum": 1, "maximum": 5},
                "provider": {"const": "WIKIMEDIA_COMMONS"},
                "page_id": {"type": "integer", "minimum": 1},
                "file_title": {
                    "type": "string",
                    "minLength": 6,
                    "maxLength": 240,
                    "pattern": "^File:[^\\x00-\\x1f\\x7f]+$",
                },
                "canonical_page_url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https://commons\\.wikimedia\\.org/wiki/File:",
                    "maxLength": 1000,
                },
                "selection_rationale": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "pattern": "^[^\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]+$",
                },
                "intended_use": {"const": "SUBJECT_MORPHOLOGY_REFERENCE"},
                "license_expectation": {"const": "PUBLIC_DOMAIN_OR_CC0"},
            },
        }
    }
    value["required"] = [
        "schema_version",
        "intent_id",
        "workflow_id",
        "image_step_run_id",
        "image_job_id",
        "visual_ordinal",
        "drawing_sha256",
        "subject",
        "query_terms",
        "candidates",
        "primary_candidate_page_id",
        "intent_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-intent/1.0"},
        "intent_id": {"type": "string", "pattern": "^imgrefintent_[0-9a-f]{32}$"},
        "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
        "image_step_run_id": {"type": "string", "pattern": "^steprun_[0-9a-f]{32}$"},
        "image_job_id": {"type": "string", "pattern": "^job_[0-9a-f]{32}$"},
        "visual_ordinal": {"type": "integer", "minimum": 0, "maximum": 1},
        "drawing_sha256": SHA256,
        "subject": {
            "type": "string",
            "minLength": 3,
            "maxLength": 180,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
        },
        "query_terms": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9 .()/_-]{0,79}$",
            },
        },
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"$ref": "#/$defs/candidate"},
        },
        "primary_candidate_page_id": {"type": "integer", "minimum": 1},
        "intent_sha256": SHA256,
    }
    return value


def bundle_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0",
        "EOM local image visual reference bundle v1",
    )
    value["$defs"] = {
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "reference_id",
                "rank",
                "provider",
                "page_id",
                "page_revision_id",
                "file_title",
                "canonical_page_url",
                "original_file_url",
                "original_media_type",
                "original_size_bytes",
                "original_sha256",
                "original_width_px",
                "original_height_px",
                "license_id",
                "license_url",
                "license_short_name",
                "attribution_required",
                "intended_use",
                "disposition",
            ],
            "properties": {
                "reference_id": {"type": "string", "pattern": "^imgref_[0-9a-f]{32}$"},
                "rank": {"type": "integer", "minimum": 1, "maximum": 5},
                "provider": {"const": "WIKIMEDIA_COMMONS"},
                "page_id": {"type": "integer", "minimum": 1},
                "page_revision_id": {"type": "integer", "minimum": 1},
                "file_title": {
                    "type": "string",
                    "minLength": 6,
                    "maxLength": 240,
                    "pattern": "^File:[^\\x00-\\x1f\\x7f]+$",
                },
                "canonical_page_url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https://commons\\.wikimedia\\.org/wiki/File:",
                    "maxLength": 1000,
                },
                "original_file_url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https://upload\\.wikimedia\\.org/",
                    "maxLength": 2000,
                },
                "original_media_type": {"enum": ["image/jpeg", "image/png", "image/webp"]},
                "original_size_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 16777216,
                },
                "original_sha256": SHA256,
                "original_width_px": {"type": "integer", "minimum": 64, "maximum": 12000},
                "original_height_px": {"type": "integer", "minimum": 64, "maximum": 12000},
                "license_id": {"enum": ["CC0-1.0", "PUBLIC-DOMAIN"]},
                "license_url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https://",
                    "maxLength": 1000,
                },
                "license_short_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                    "pattern": "^[^\\x00-\\x1f\\x7f]+$",
                },
                "attribution_required": {"const": False},
                "intended_use": {"const": "SUBJECT_MORPHOLOGY_REFERENCE"},
                "disposition": {"enum": ["PRIMARY_CONDITIONING", "VERIFIED_ALTERNATE"]},
            },
        },
        "normalized_member": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "member_path",
                "schema_ref",
                "media_type",
                "width_px",
                "height_px",
                "mode",
                "size_bytes",
                "sha256",
            ],
            "properties": {
                "member_path": {"const": "references/primary.png"},
                "schema_ref": {
                    "const": "eom://schemas/image-provider/normalized-visual-reference/1.0"
                },
                "media_type": {"const": "image/png"},
                "width_px": {"const": 800},
                "height_px": {"const": 504},
                "mode": {"const": "RGB"},
                "size_bytes": {"type": "integer", "minimum": 1, "maximum": 8388608},
                "sha256": SHA256,
            },
        },
        "intent_pointer": _artifact_member(
            path_pattern="^manifests/visual-reference-intent\\.json$",
            schema_const="eom://schemas/image-provider/local-image-visual-reference-intent/1.0",
            media_const="application/json",
        ),
    }
    value["required"] = [
        "schema_version",
        "bundle_id",
        "bundle_revision_id",
        "state",
        "intent",
        "subject",
        "provider_api_revision",
        "observed_at",
        "sources",
        "primary_reference_id",
        "normalization_policy",
        "normalized_member",
        "bundle_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-bundle/1.0"},
        "bundle_id": {"type": "string", "pattern": "^imgrefbundle_[0-9a-f]{32}$"},
        "bundle_revision_id": {
            "type": "string",
            "pattern": "^imgrefbundlerev_[0-9a-f]{32}$",
        },
        "state": {"const": "APPROVED"},
        "intent": {"$ref": "#/$defs/intent_pointer"},
        "subject": {
            "type": "string",
            "minLength": 3,
            "maxLength": 180,
            "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
        },
        "provider_api_revision": {"const": "wikimedia-commons-api/1.0"},
        "observed_at": UTC,
        "sources": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"$ref": "#/$defs/source"},
        },
        "primary_reference_id": {"type": "string", "pattern": "^imgref_[0-9a-f]{32}$"},
        "normalization_policy": {"const": "reference-raster-normalization/1.0"},
        "normalized_member": {"$ref": "#/$defs/normalized_member"},
        "bundle_sha256": SHA256,
    }
    return value


def _conditioning_pointer() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "bundle_id",
            "bundle_revision_id",
            "bundle_manifest",
            "primary_reference_id",
            "reference_member",
        ],
        "properties": {
            "bundle_id": {"type": "string", "pattern": "^imgrefbundle_[0-9a-f]{32}$"},
            "bundle_revision_id": {
                "type": "string",
                "pattern": "^imgrefbundlerev_[0-9a-f]{32}$",
            },
            "bundle_manifest": _artifact_member(
                path_pattern="^manifests/visual-reference-bundle\\.json$",
                schema_const=(
                    "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
                ),
                media_const="application/json",
            ),
            "primary_reference_id": {
                "type": "string",
                "pattern": "^imgref_[0-9a-f]{32}$",
            },
            "reference_member": _artifact_member(
                path_pattern="^references/primary\\.png$",
                schema_const="eom://schemas/image-provider/normalized-visual-reference/1.0",
                media_const="image/png",
            ),
        },
    }


def conditioned_request_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-request/1.0",
        "EOM local image reference-conditioned composite request v1",
    )
    value["$defs"] = {
        "reference_pointer": _conditioning_pointer(),
        "conditioning": {
            "type": "object",
            "additionalProperties": False,
            "required": ["contract", "strength", "fit_policy"],
            "properties": {
                "contract": {"const": "sdxl-img2img/1.0"},
                "strength": {"const": 0.35},
                "fit_policy": {"const": "CONTAIN_WHITE_NO_UPSCALE"},
            },
        },
    }
    value["required"] = [
        "schema_version",
        "composite_request",
        "visual_reference",
        "conditioning",
        "request_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-reference-conditioned-composite-request/1.0"},
        "composite_request": {
            "$ref": "eom://schemas/image-provider/local-image-composite-request/1.0"
        },
        "visual_reference": {"$ref": "#/$defs/reference_pointer"},
        "conditioning": {"$ref": "#/$defs/conditioning"},
        "request_sha256": SHA256,
    }
    return value


def conditioned_receipt_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-receipt/1.0",
        "EOM local image reference-conditioned composite receipt v1",
    )
    value["$defs"] = {
        "reference_pointer": _conditioning_pointer(),
        "conditioning": {
            "type": "object",
            "additionalProperties": False,
            "required": ["contract", "strength", "fit_policy"],
            "properties": {
                "contract": {"const": "sdxl-img2img/1.0"},
                "strength": {"const": 0.35},
                "fit_policy": {"const": "CONTAIN_WHITE_NO_UPSCALE"},
            },
        },
    }
    value["required"] = [
        "schema_version",
        "request_sha256",
        "composite_receipt",
        "visual_reference",
        "conditioning",
        "completed_at",
        "receipt_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-reference-conditioned-composite-receipt/1.0"},
        "request_sha256": SHA256,
        "composite_receipt": {
            "$ref": "eom://schemas/image-provider/local-image-composite-receipt/1.0"
        },
        "visual_reference": {"$ref": "#/$defs/reference_pointer"},
        "conditioning": {"$ref": "#/$defs/conditioning"},
        "completed_at": UTC,
        "receipt_sha256": SHA256,
    }
    return value


SCHEMAS = {
    "local-image-visual-reference-intent-v1.schema.json": intent_schema(),
    "local-image-visual-reference-bundle-v1.schema.json": bundle_schema(),
    "local-image-reference-conditioned-composite-request-v1.schema.json": (
        conditioned_request_schema()
    ),
    "local-image-reference-conditioned-composite-receipt-v1.schema.json": (
        conditioned_receipt_schema()
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    failed: list[str] = []
    for name, schema in SCHEMAS.items():
        payload = (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode()
        for root in (CANONICAL, PACKAGED):
            path = root / name
            if arguments.check:
                if not path.is_file() or path.read_bytes() != payload:
                    failed.append(str(path))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
    if failed:
        raise SystemExit("visual-reference schema drift: " + ", ".join(failed))


if __name__ == "__main__":
    main()

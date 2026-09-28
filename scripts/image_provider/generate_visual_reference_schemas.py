#!/usr/bin/env python3
"""Generate additive visual-reference contracts without changing released image schemas."""

from __future__ import annotations

import argparse
import copy
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


def discovery_command_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-discovery-command/1.0",
        "EOM local image visual reference discovery command v1",
    )
    value["required"] = [
        "schema_version",
        "command_id",
        "workflow_id",
        "image_step_run_id",
        "image_job_id",
        "visual_ordinal",
        "drawing_sha256",
        "subject",
        "query_terms",
        "candidate_limit",
        "observed_at",
        "timeout_seconds",
        "command_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-discovery-command/1.0"},
        "command_id": {"type": "string", "pattern": "^imgrefdiscover_[0-9a-f]{32}$"},
        "workflow_id": {"type": "string", "pattern": "^workflow_[0-9a-f]{32}$"},
        "image_step_run_id": {"type": "string", "pattern": "^steprun_[0-9a-f]{32}$"},
        "image_job_id": {"type": "string", "pattern": "^job_[0-9a-f]{32}$"},
        "visual_ordinal": {"type": "integer", "minimum": 0, "maximum": 1},
        "drawing_sha256": SHA256,
        "subject": intent_schema()["properties"]["subject"],
        "query_terms": intent_schema()["properties"]["query_terms"],
        "candidate_limit": {"const": 5},
        "observed_at": UTC,
        "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 180},
        "command_sha256": SHA256,
    }
    return value


def discovery_result_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-discovery-result/1.0",
        "EOM local image visual reference discovery result v1",
    )
    value["$defs"] = {"candidate": intent_schema()["$defs"]["candidate"]}
    value["required"] = [
        "schema_version",
        "command_id",
        "command_sha256",
        "status",
        "candidates",
        "error_code",
        "started_at",
        "completed_at",
        "duration_ms",
        "result_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-discovery-result/1.0"},
        "command_id": {"type": "string", "pattern": "^imgrefdiscover_[0-9a-f]{32}$"},
        "command_sha256": SHA256,
        "status": {"enum": ["SUCCEEDED", "FAILED"]},
        "candidates": {
            "type": "array",
            "maxItems": 5,
            "uniqueItems": True,
            "items": {"$ref": "#/$defs/candidate"},
        },
        "error_code": {
            "oneOf": [
                {
                    "enum": [
                        "VISUAL_REFERENCE_INPUT_INVALID",
                        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
                        "VISUAL_REFERENCE_SOURCE_REJECTED",
                        "VISUAL_REFERENCE_LICENSE_REJECTED",
                    ]
                },
                {"type": "null"},
            ]
        },
        "started_at": UTC,
        "completed_at": UTC,
        "duration_ms": {"type": "integer", "minimum": 1, "maximum": 180000},
        "result_sha256": SHA256,
    }
    value["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
            "then": {
                "properties": {
                    "candidates": {"minItems": 1, "maxItems": 5},
                    "error_code": {"type": "null"},
                }
            },
            "else": {
                "properties": {
                    "candidates": {"maxItems": 0},
                    "error_code": {"type": "string"},
                }
            },
        }
    ]
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


def acquisition_command_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-acquisition-command/1.0",
        "EOM local image visual reference acquisition command v1",
    )
    value["$defs"] = {
        "intent_pointer": _artifact_member(
            path_pattern="^manifests/visual-reference-intent\\.json$",
            schema_const="eom://schemas/image-provider/local-image-visual-reference-intent/1.0",
            media_const="application/json",
        )
    }
    value["required"] = [
        "schema_version",
        "command_id",
        "attempt_id",
        "intent",
        "intent_member_path",
        "observed_at",
        "max_original_bytes",
        "timeout_seconds",
        "command_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-acquisition-command/1.0"},
        "command_id": {"type": "string", "pattern": "^imgrefcmd_[0-9a-f]{32}$"},
        "attempt_id": {"type": "string", "pattern": "^imgrefattempt_[0-9a-f]{32}$"},
        "intent": {"$ref": "#/$defs/intent_pointer"},
        "intent_member_path": {"const": "input/visual-reference-intent.json"},
        "observed_at": UTC,
        "max_original_bytes": {"const": 16777216},
        "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 180},
        "command_sha256": SHA256,
    }
    return value


def acquisition_result_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-visual-reference-acquisition-result/1.0",
        "EOM local image visual reference acquisition result v1",
    )
    value["$defs"] = {
        "output_file": {
            "type": "object",
            "additionalProperties": False,
            "required": ["member_path", "schema_ref", "media_type", "size_bytes", "sha256"],
            "properties": {
                "member_path": {
                    "enum": [
                        "manifests/visual-reference-bundle.json",
                        "references/primary.png",
                    ]
                },
                "schema_ref": {
                    "enum": [
                        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0",
                        "eom://schemas/image-provider/normalized-visual-reference/1.0",
                    ]
                },
                "media_type": {"enum": ["application/json", "image/png"]},
                "size_bytes": {"type": "integer", "minimum": 1, "maximum": 16777216},
                "sha256": SHA256,
            },
        }
    }
    value["required"] = [
        "schema_version",
        "command_id",
        "attempt_id",
        "command_sha256",
        "status",
        "bundle",
        "output_files",
        "error_code",
        "started_at",
        "completed_at",
        "duration_ms",
        "result_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-visual-reference-acquisition-result/1.0"},
        "command_id": {"type": "string", "pattern": "^imgrefcmd_[0-9a-f]{32}$"},
        "attempt_id": {"type": "string", "pattern": "^imgrefattempt_[0-9a-f]{32}$"},
        "command_sha256": SHA256,
        "status": {"enum": ["SUCCEEDED", "FAILED"]},
        "bundle": {
            "oneOf": [
                {"$ref": ("eom://schemas/image-provider/local-image-visual-reference-bundle/1.0")},
                {"type": "null"},
            ]
        },
        "output_files": {
            "type": "array",
            "maxItems": 2,
            "items": {"$ref": "#/$defs/output_file"},
        },
        "error_code": {
            "oneOf": [
                {
                    "enum": [
                        "VISUAL_REFERENCE_INPUT_INVALID",
                        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
                        "VISUAL_REFERENCE_SOURCE_REJECTED",
                        "VISUAL_REFERENCE_LICENSE_REJECTED",
                        "VISUAL_REFERENCE_IMAGE_INVALID",
                        "VISUAL_REFERENCE_OUTPUT_INVALID",
                    ]
                },
                {"type": "null"},
            ]
        },
        "started_at": UTC,
        "completed_at": UTC,
        "duration_ms": {"type": "integer", "minimum": 1, "maximum": 180000},
        "result_sha256": SHA256,
    }
    value["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
            "then": {
                "properties": {
                    "bundle": {
                        "$ref": (
                            "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
                        )
                    },
                    "output_files": {"minItems": 2, "maxItems": 2},
                    "error_code": {"type": "null"},
                }
            },
            "else": {
                "properties": {
                    "bundle": {"type": "null"},
                    "output_files": {"maxItems": 0},
                    "error_code": {"type": "string"},
                }
            },
        }
    ]
    return value


def style_adapter_release_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-style-adapter-release/1.0",
        "EOM local image production style adapter release v1",
    )

    def artifact_member(
        *, member_path: str, schema_ref: str, maximum_bytes: int = 16777216
    ) -> dict[str, Any]:
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
                "artifact_revision_id": {
                    "type": "string",
                    "pattern": "^rev_[0-9a-f]{32}$",
                },
                "member_path": {"const": member_path},
                "schema_ref": {"const": schema_ref},
                "media_type": {"const": "application/json"},
                "sha256": SHA256,
                "size_bytes": {"type": "integer", "minimum": 1, "maximum": maximum_bytes},
            },
        }

    model_pointer = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "model_id",
            "model_revision_id",
            "manifest_sha256",
            "provider_family",
            "runtime_contract_version",
        ],
        "properties": {
            "model_id": {"type": "string", "pattern": "^imgmodel_[0-9a-f]{32}$"},
            "model_revision_id": {
                "type": "string",
                "pattern": "^imgmodelrev_[0-9a-f]{32}$",
            },
            "manifest_sha256": SHA256,
            "provider_family": {"const": "diffusers-ssd-1b"},
            "runtime_contract_version": {"const": "eom-local-image-provider/1.0"},
        },
    }
    value["$defs"] = {
        "source_adapter_manifest": artifact_member(
            member_path="manifests/adapter-manifest.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
            ),
        ),
        "evaluation_result": artifact_member(
            member_path="result.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-evaluation-result/1.1"
            ),
        ),
        "model_pointer": model_pointer,
        "adapter_file": {
            "type": "object",
            "additionalProperties": False,
            "required": ["relative_path", "size_bytes", "sha256"],
            "properties": {
                "relative_path": {"enum": ["adapter_config.json", "adapter_model.safetensors"]},
                "size_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1073741824,
                },
                "sha256": SHA256,
            },
        },
    }
    value["required"] = [
        "schema_version",
        "release_id",
        "release_revision_id",
        "state",
        "adapter_contract",
        "adapter_id",
        "adapter_revision_id",
        "base_model",
        "source_adapter_manifest",
        "evaluation_result",
        "files",
        "lora_scale",
        "approved_at",
        "approved_by",
        "release_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-style-adapter-release/1.0"},
        "release_id": {"type": "string", "pattern": "^imgstylerelease_[0-9a-f]{32}$"},
        "release_revision_id": {
            "type": "string",
            "pattern": "^imgstylereleaserev_[0-9a-f]{32}$",
        },
        "state": {"const": "RELEASED"},
        "adapter_contract": {"const": "eom-assessment-style-lora/1.0"},
        "adapter_id": {"type": "string", "pattern": "^imgadapter_[0-9a-f]{32}$"},
        "adapter_revision_id": {
            "type": "string",
            "pattern": "^imgadapterrev_[0-9a-f]{32}$",
        },
        "base_model": {"$ref": "#/$defs/model_pointer"},
        "source_adapter_manifest": {"$ref": "#/$defs/source_adapter_manifest"},
        "evaluation_result": {"$ref": "#/$defs/evaluation_result"},
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "uniqueItems": True,
            "items": {"$ref": "#/$defs/adapter_file"},
        },
        "lora_scale": {"const": 0.8},
        "approved_at": UTC,
        "approved_by": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9._:@-]+$",
        },
        "release_sha256": SHA256,
    }
    return value


def provider_binding_v2_schema() -> dict[str, Any]:
    predecessor: dict[str, Any] = json.loads(
        (CANONICAL / "local-image-provider-binding-v1.schema.json").read_text()
    )
    value: dict[str, Any] = copy.deepcopy(predecessor)
    value["$id"] = "eom://schemas/image-provider/local-image-provider-binding/2.0"
    value["title"] = "EOM reference-conditioned local image provider binding v2"
    value["required"] = [
        "schema_version",
        "state",
        "route_contract",
        "model",
        "style_adapter",
        "reference_policy",
        "sampler",
        "timeout_seconds",
        "binding_sha256",
    ]
    value["properties"]["schema_version"] = {"const": "local-image-provider-binding/2.0"}
    value["properties"]["route_contract"] = {
        "const": "eom-local-reference-conditioned-background/2.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/1.0"
    }
    value["properties"]["reference_policy"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "intent_source",
            "provider",
            "license_policy",
            "candidate_limit",
            "conditioning_contract",
            "conditioning_strength",
            "failure_policy",
        ],
        "properties": {
            "intent_source": {"const": "DRAWING_ALT_TEXT"},
            "provider": {"const": "WIKIMEDIA_COMMONS"},
            "license_policy": {"const": "PUBLIC_DOMAIN_OR_CC0"},
            "candidate_limit": {"const": 5},
            "conditioning_contract": {"const": "sdxl-img2img/1.0"},
            "conditioning_strength": {"const": 0.35},
            "failure_policy": {"const": "FAIL_CLOSED"},
        },
    }
    return value


def style_adapter_release_v2_schema() -> dict[str, Any]:
    value: dict[str, Any] = copy.deepcopy(style_adapter_release_schema())
    value["$id"] = "eom://schemas/image-provider/local-image-style-adapter-release/2.0"
    value["title"] = "EOM reduced-scale assessment style adapter release v2"
    value["properties"]["schema_version"] = {"const": "local-image-style-adapter-release/2.0"}
    value["properties"]["lora_scale"] = {"const": 0.45}
    return value


def conditioned_request_v2_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_request_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-request/2.0"
    )
    value["title"] = "EOM LoRA style and reference-conditioned composite request v2"
    value["required"].insert(-1, "style_adapter")
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-request/2.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/1.0"
    }
    return value


def conditioned_receipt_v2_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_receipt_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-receipt/2.0"
    )
    value["title"] = "EOM LoRA style and reference-conditioned composite receipt v2"
    value["required"].insert(-2, "style_adapter")
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-receipt/2.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/1.0"
    }
    return value


def _morphology_conditioning_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract",
            "strength",
            "fit_policy",
            "simplification",
        ],
        "properties": {
            "contract": {"const": "sdxl-morphology-img2img/2.1"},
            "strength": {"const": 0.35},
            "fit_policy": {"const": "EXACT_NORMALIZED_CANVAS"},
            "simplification": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "contract",
                    "output_member",
                    "color_policy",
                    "denoise_policy",
                    "tone_policy",
                    "foreground_luma_threshold",
                    "border_width_px",
                    "foreground_ratio_min",
                    "foreground_ratio_max",
                    "border_foreground_ratio_max",
                ],
                "properties": {
                    "contract": {"const": "local-image-reference-simplification/1.1"},
                    "output_member": {"const": "reference-conditioning.png"},
                    "color_policy": {"const": "GRAYSCALE_WHITE_BACKGROUND"},
                    "denoise_policy": {"const": "MAX_5_MEDIAN_7_GAUSSIAN_2_0"},
                    "tone_policy": {"const": "SIX_LEVEL_LIGHT_TONE_CONTOUR"},
                    "foreground_luma_threshold": {"const": 245},
                    "border_width_px": {"const": 24},
                    "foreground_ratio_min": {"const": 0.005},
                    "foreground_ratio_max": {"const": 0.8},
                    "border_foreground_ratio_max": {"const": 0.12},
                },
            },
        },
    }


def provider_binding_v3_schema() -> dict[str, Any]:
    value = copy.deepcopy(provider_binding_v2_schema())
    value["$id"] = "eom://schemas/image-provider/local-image-provider-binding/3.0"
    value["title"] = "EOM simplified-morphology local image provider binding v3"
    value["properties"]["schema_version"] = {"const": "local-image-provider-binding/3.0"}
    value["properties"]["route_contract"] = {
        "const": "eom-local-morphology-conditioned-line-art/3.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/2.0"
    }
    value["properties"]["reference_policy"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "intent_source",
            "provider",
            "license_policy",
            "candidate_limit",
            "conditioning",
            "authority_boundary",
            "failure_policy",
        ],
        "properties": {
            "intent_source": {"const": "DRAWING_ALT_TEXT"},
            "provider": {"const": "WIKIMEDIA_COMMONS"},
            "license_policy": {"const": "PUBLIC_DOMAIN_OR_CC0"},
            "candidate_limit": {"const": 5},
            "conditioning": _morphology_conditioning_schema(),
            "authority_boundary": {"const": "MORPHOLOGY_ONLY_DETERMINISTIC_OVERLAY"},
            "failure_policy": {"const": "FAIL_CLOSED"},
        },
    }
    return value


def conditioned_request_v3_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_request_v2_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-request/3.0"
    )
    value["title"] = "EOM simplified-morphology reference composite request v3"
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-request/3.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/2.0"
    }
    value["$defs"]["conditioning"] = _morphology_conditioning_schema()
    return value


def conditioned_receipt_v3_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_receipt_v2_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-receipt/3.0"
    )
    value["title"] = "EOM simplified-morphology reference composite receipt v3"
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-receipt/3.0"
    }
    value["properties"]["style_adapter"] = {
        "$ref": "eom://schemas/image-provider/local-image-style-adapter-release/2.0"
    }
    value["$defs"]["conditioning"] = _morphology_conditioning_schema()
    value["$defs"]["conditioning_output"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "member_path",
            "media_type",
            "sha256",
            "size_bytes",
            "width_px",
            "height_px",
        ],
        "properties": {
            "member_path": {"const": "reference-conditioning.png"},
            "media_type": {"const": "image/png"},
            "sha256": SHA256,
            "size_bytes": {"type": "integer", "minimum": 64, "maximum": 8388608},
            "width_px": {"const": 800},
            "height_px": {"const": 504},
        },
    }
    value["$defs"]["simplification_metrics"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_foreground_ratio",
            "conditioning_foreground_ratio",
            "border_foreground_ratio",
            "source_edge_density",
            "conditioning_edge_density",
            "edge_density_ratio",
        ],
        "properties": {
            "source_foreground_ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "conditioning_foreground_ratio": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "border_foreground_ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "source_edge_density": {"type": "number", "minimum": 0, "maximum": 1},
            "conditioning_edge_density": {"type": "number", "minimum": 0, "maximum": 1},
            "edge_density_ratio": {"type": "number", "minimum": 0, "maximum": 16},
        },
    }
    value["$defs"]["simplifier_runtime"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract", "pillow_version"],
        "properties": {
            "contract": {"const": "local-image-reference-simplifier/1.0"},
            "pillow_version": {"type": "string", "minLength": 1, "maxLength": 64},
        },
    }
    value["required"].insert(-2, "conditioning_output")
    value["required"].insert(-2, "simplification_metrics")
    value["required"].insert(-2, "simplifier_runtime")
    value["properties"]["conditioning_output"] = {"$ref": "#/$defs/conditioning_output"}
    value["properties"]["simplification_metrics"] = {"$ref": "#/$defs/simplification_metrics"}
    value["properties"]["simplifier_runtime"] = {"$ref": "#/$defs/simplifier_runtime"}
    return value


def provider_binding_v4_schema() -> dict[str, Any]:
    value = copy.deepcopy(provider_binding_v3_schema())
    value["$id"] = "eom://schemas/image-provider/local-image-provider-binding/4.0"
    value["title"] = "EOM base-only simplified-morphology provider binding v4"
    value["properties"]["schema_version"] = {"const": "local-image-provider-binding/4.0"}
    value["properties"]["route_contract"] = {
        "const": "eom-local-morphology-conditioned-base-line-art/4.0"
    }
    value["required"].remove("style_adapter")
    del value["properties"]["style_adapter"]
    return value


def conditioned_request_v4_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_request_v3_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-request/4.0"
    )
    value["title"] = "EOM base-only simplified-morphology reference request v4"
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-request/4.0"
    }
    value["required"].remove("style_adapter")
    del value["properties"]["style_adapter"]
    return value


def conditioned_receipt_v4_schema() -> dict[str, Any]:
    value = copy.deepcopy(conditioned_receipt_v3_schema())
    value["$id"] = (
        "eom://schemas/image-provider/local-image-reference-conditioned-composite-receipt/4.0"
    )
    value["title"] = "EOM base-only simplified-morphology reference receipt v4"
    value["properties"]["schema_version"] = {
        "const": "local-image-reference-conditioned-composite-receipt/4.0"
    }
    value["required"].remove("style_adapter")
    del value["properties"]["style_adapter"]
    value["required"].insert(-2, "output_palette")
    value["properties"]["output_palette"] = {"const": "ASSESSMENT_GRAYSCALE"}
    return value


def reference_composition_evaluation_schema() -> dict[str, Any]:
    value = _header(
        "eom://schemas/image-provider/local-image-reference-composition-evaluation/1.0",
        "EOM reference composition-preservation evaluation v1",
    )

    def member(*, member_path: str, height_px: int) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "member_path",
                "media_type",
                "sha256",
                "size_bytes",
                "width_px",
                "height_px",
            ],
            "properties": {
                "member_path": {"const": member_path},
                "media_type": {"const": "image/png"},
                "sha256": SHA256,
                "size_bytes": {"type": "integer", "minimum": 64, "maximum": 67108864},
                "width_px": {"const": 800},
                "height_px": {"const": height_px},
            },
        }

    metrics = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "edge_precision",
            "edge_recall",
            "edge_f1",
            "foreground_bbox_iou",
            "center_shift_ratio",
            "width_scale_ratio",
            "height_scale_ratio",
            "edge_occupancy_delta_ratio",
            "mean_chroma_ratio",
        ],
        "properties": {
            "edge_precision": {"type": "number", "minimum": 0, "maximum": 1},
            "edge_recall": {"type": "number", "minimum": 0, "maximum": 1},
            "edge_f1": {"type": "number", "minimum": 0, "maximum": 1},
            "foreground_bbox_iou": {"type": "number", "minimum": 0, "maximum": 1},
            "center_shift_ratio": {"type": "number", "minimum": 0, "maximum": 1.5},
            "width_scale_ratio": {"type": "number", "minimum": 0.25, "maximum": 4},
            "height_scale_ratio": {"type": "number", "minimum": 0.25, "maximum": 4},
            "edge_occupancy_delta_ratio": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "mean_chroma_ratio": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    thresholds = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "edge_recall_min",
            "foreground_bbox_iou_min",
            "center_shift_ratio_max",
            "width_scale_ratio_min",
            "width_scale_ratio_max",
            "height_scale_ratio_min",
            "height_scale_ratio_max",
            "edge_occupancy_delta_ratio_max",
            "mean_chroma_ratio_max",
        ],
        "properties": {
            "edge_recall_min": {"const": 0.8},
            "foreground_bbox_iou_min": {"const": 0.7},
            "center_shift_ratio_max": {"const": 0.08},
            "width_scale_ratio_min": {"const": 0.75},
            "width_scale_ratio_max": {"const": 1.25},
            "height_scale_ratio_min": {"const": 0.75},
            "height_scale_ratio_max": {"const": 1.25},
            "edge_occupancy_delta_ratio_max": {"const": 0.2},
            "mean_chroma_ratio_max": {"const": 0.04},
        },
    }
    evaluator = {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract", "source_commit", "pillow_version", "numpy_version"],
        "properties": {
            "contract": {"const": "local-image-reference-composition-evaluator/1.0"},
            "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "pillow_version": {"type": "string", "minLength": 1, "maxLength": 64},
            "numpy_version": {"type": "string", "minLength": 1, "maxLength": 64},
        },
    }
    value["$defs"] = {
        "reference_pointer": _conditioning_pointer(),
        "reference_member": member(
            member_path="inputs/reference-conditioning.png",
            height_px=504,
        ),
        "candidate_member": member(
            member_path="outputs/candidate.png",
            height_px=500,
        ),
        "metrics": metrics,
        "thresholds": thresholds,
        "evaluator": evaluator,
    }
    value["required"] = [
        "schema_version",
        "evaluation_id",
        "policy",
        "visual_reference",
        "reference_conditioning",
        "candidate_output",
        "metrics",
        "thresholds",
        "failure_reasons",
        "outcome",
        "evaluator",
        "evaluated_at",
        "evaluation_sha256",
    ]
    value["properties"] = {
        "schema_version": {"const": "local-image-reference-composition-evaluation/1.0"},
        "evaluation_id": {"type": "string", "pattern": "^imgcompositioneval_[0-9a-f]{32}$"},
        "policy": {"const": "COMPOSITION_PRESERVING_LINE_ART"},
        "visual_reference": {"$ref": "#/$defs/reference_pointer"},
        "reference_conditioning": {"$ref": "#/$defs/reference_member"},
        "candidate_output": {"$ref": "#/$defs/candidate_member"},
        "metrics": {"$ref": "#/$defs/metrics"},
        "thresholds": {"$ref": "#/$defs/thresholds"},
        "failure_reasons": {
            "type": "array",
            "maxItems": 8,
            "uniqueItems": True,
            "items": {
                "enum": [
                    "CENTER_SHIFT_HIGH",
                    "COLOR_REMAINS",
                    "EDGE_OCCUPANCY_DRIFT",
                    "EDGE_RECALL_LOW",
                    "FOREGROUND_BBOX_IOU_LOW",
                    "HEIGHT_SCALE_DRIFT",
                    "WIDTH_SCALE_DRIFT",
                ]
            },
        },
        "outcome": {"enum": ["PASS", "FAIL"]},
        "evaluator": {"$ref": "#/$defs/evaluator"},
        "evaluated_at": UTC,
        "evaluation_sha256": SHA256,
    }
    value["allOf"] = [
        {
            "if": {"properties": {"outcome": {"const": "PASS"}}},
            "then": {"properties": {"failure_reasons": {"maxItems": 0}}},
            "else": {"properties": {"failure_reasons": {"minItems": 1}}},
        }
    ]
    return value


SCHEMAS = {
    "local-image-visual-reference-intent-v1.schema.json": intent_schema(),
    "local-image-visual-reference-bundle-v1.schema.json": bundle_schema(),
    "local-image-visual-reference-discovery-command-v1.schema.json": (discovery_command_schema()),
    "local-image-visual-reference-discovery-result-v1.schema.json": discovery_result_schema(),
    "local-image-reference-conditioned-composite-request-v1.schema.json": (
        conditioned_request_schema()
    ),
    "local-image-reference-conditioned-composite-receipt-v1.schema.json": (
        conditioned_receipt_schema()
    ),
    "local-image-visual-reference-acquisition-command-v1.schema.json": (
        acquisition_command_schema()
    ),
    "local-image-visual-reference-acquisition-result-v1.schema.json": (acquisition_result_schema()),
    "local-image-style-adapter-release-v1.schema.json": style_adapter_release_schema(),
    "local-image-style-adapter-release-v2.schema.json": style_adapter_release_v2_schema(),
    "local-image-provider-binding-v2.schema.json": provider_binding_v2_schema(),
    "local-image-reference-conditioned-composite-request-v2.schema.json": (
        conditioned_request_v2_schema()
    ),
    "local-image-reference-conditioned-composite-receipt-v2.schema.json": (
        conditioned_receipt_v2_schema()
    ),
    "local-image-reference-composition-evaluation-v1.schema.json": (
        reference_composition_evaluation_schema()
    ),
    "local-image-provider-binding-v3.schema.json": provider_binding_v3_schema(),
    "local-image-reference-conditioned-composite-request-v3.schema.json": (
        conditioned_request_v3_schema()
    ),
    "local-image-reference-conditioned-composite-receipt-v3.schema.json": (
        conditioned_receipt_v3_schema()
    ),
    "local-image-provider-binding-v4.schema.json": provider_binding_v4_schema(),
    "local-image-reference-conditioned-composite-request-v4.schema.json": (
        conditioned_request_v4_schema()
    ),
    "local-image-reference-conditioned-composite-receipt-v4.schema.json": (
        conditioned_receipt_v4_schema()
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

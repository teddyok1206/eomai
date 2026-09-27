#!/usr/bin/env python3
"""Generate contracts for bounded multi-seed science-subject evaluation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas" / "image-provider"
PACKAGED = ROOT / "packages" / "image_contracts" / "eom_image_contracts" / "schemas"

SHA256 = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
UTC = {"type": "string", "format": "date-time"}
RASTER_ROUTES = ["HYBRID", "LORA_RASTER"]


def _artifact_member() -> dict[str, Any]:
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
        ],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {"type": "string", "pattern": "^rev_[0-9a-f]{32}$"},
            "member_path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "pattern": "^(?!/)(?!.*\\\\)[^\\u0000-\\u001f\\u007f]+$",
            },
            "schema_ref": {
                "type": "string",
                "pattern": "^eom://schemas/[A-Za-z0-9._/-]{1,220}$",
            },
            "media_type": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$",
            },
            "sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _model_pointer() -> dict[str, Any]:
    return {
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
            "manifest_sha256": {"$ref": "#/$defs/sha256"},
            "provider_family": {"const": "diffusers-ssd-1b"},
            "runtime_contract_version": {"const": "eom-local-image-provider/1.0"},
        },
    }


def _base(title: str, identifier: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": identifier,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "$defs": {"sha256": deepcopy(SHA256), "artifactMember": _artifact_member()},
    }


def _case() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "subject_id",
            "subject_key",
            "render_route",
            "seed_ordinal",
            "seed",
            "prompt_en",
            "prompt_sha256",
            "negative_prompt_en",
            "negative_prompt_sha256",
        ],
        "properties": {
            "case_id": {
                "type": "string",
                "pattern": "^imgscisubjectseedcase_[0-9a-f]{32}$",
            },
            "subject_id": {"type": "string", "pattern": "^imgscisubject_[0-9a-f]{32}$"},
            "subject_key": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{1,63}$"},
            "render_route": {"enum": RASTER_ROUTES},
            "seed_ordinal": {"type": "integer", "minimum": 1, "maximum": 2},
            "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
            "prompt_en": {
                "type": "string",
                "minLength": 20,
                "maxLength": 2000,
                "pattern": "^[ -~]+$",
            },
            "prompt_sha256": {"$ref": "#/$defs/sha256"},
            "negative_prompt_en": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "pattern": "^[ -~]+$",
            },
            "negative_prompt_sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _plan() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Multi-seed Plan V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-plan/1.0",
    )
    schema["$defs"].update({"case": _case(), "modelPointer": _model_pointer()})
    schema.update(
        {
            "required": [
                "schema_version",
                "plan_id",
                "subject_inventory",
                "initial_benchmark_plan",
                "initial_quality_review",
                "base_model",
                "adapter_manifest",
                "generation_width_px",
                "generation_height_px",
                "delivery_width_px",
                "delivery_height_px",
                "inference_steps",
                "guidance_scale_milli",
                "seeds_per_subject",
                "cases",
                "activation_policy",
                "created_at",
                "created_by",
                "plan_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-multiseed-plan/1.0"
                },
                "plan_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectmultiseed_[0-9a-f]{32}$",
                },
                "subject_inventory": {"$ref": "#/$defs/artifactMember"},
                "initial_benchmark_plan": {"$ref": "#/$defs/artifactMember"},
                "initial_quality_review": {"$ref": "#/$defs/artifactMember"},
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "adapter_manifest": {"$ref": "#/$defs/artifactMember"},
                "generation_width_px": {"const": 800},
                "generation_height_px": {"const": 504},
                "delivery_width_px": {"const": 800},
                "delivery_height_px": {"const": 500},
                "inference_steps": {"const": 20},
                "guidance_scale_milli": {"const": 7500},
                "seeds_per_subject": {"const": 2},
                "cases": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 128,
                    "items": {"$ref": "#/$defs/case"},
                },
                "activation_policy": {"const": "FORBIDDEN"},
                "created_at": deepcopy(UTC),
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "plan_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _command() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Multi-seed Command V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-command/1.0",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "run_id",
                "plan",
                "plan_sha256",
                "staged_plan_path",
                "staged_subject_inventory_path",
                "staged_initial_benchmark_plan_path",
                "staged_initial_quality_review_path",
                "staged_adapter_manifest_path",
                "staged_adapter_model_path",
                "staged_adapter_config_path",
                "output_directory",
                "source_commit",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-multiseed-command/1.0"
                },
                "run_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectmultiseedrun_[0-9a-f]{32}$",
                },
                "plan": {"$ref": "#/$defs/artifactMember"},
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "staged_plan_path": {"const": "inputs/subject-multiseed-plan.json"},
                "staged_subject_inventory_path": {
                    "const": "inputs/science-visual-subject-inventory.json"
                },
                "staged_initial_benchmark_plan_path": {
                    "const": "inputs/science-visual-subject-benchmark-plan.json"
                },
                "staged_initial_quality_review_path": {
                    "const": "inputs/science-visual-subject-benchmark-review.json"
                },
                "staged_adapter_manifest_path": {"const": "inputs/adapter/adapter-manifest.json"},
                "staged_adapter_model_path": {"const": "inputs/adapter/adapter_model.safetensors"},
                "staged_adapter_config_path": {"const": "inputs/adapter/adapter_config.json"},
                "output_directory": {"const": "outputs"},
                "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _output() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "variant",
            "relative_path",
            "media_type",
            "bytes",
            "sha256",
            "width_px",
            "height_px",
        ],
        "properties": {
            "case_id": {
                "type": "string",
                "pattern": "^imgscisubjectseedcase_[0-9a-f]{32}$",
            },
            "variant": {"enum": ["ADAPTER", "BASE"]},
            "relative_path": {
                "type": "string",
                "pattern": ("^outputs/imgscisubjectseedcase_[0-9a-f]{32}-(adapter|base)\\.png$"),
            },
            "media_type": {"const": "image/png"},
            "bytes": {"type": "integer", "minimum": 1, "maximum": 67108864},
            "sha256": {"$ref": "#/$defs/sha256"},
            "width_px": {"const": 800},
            "height_px": {"const": 500},
        },
    }


def _result() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Multi-seed Result V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-result/1.0",
    )
    schema["$defs"].update({"output": _output()})
    schema.update(
        {
            "required": [
                "schema_version",
                "run_id",
                "plan_id",
                "plan_sha256",
                "command_sha256",
                "status",
                "error_code",
                "outputs",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-multiseed-result/1.0"
                },
                "run_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectmultiseedrun_[0-9a-f]{32}$",
                },
                "plan_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectmultiseed_[0-9a-f]{32}$",
                },
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "status": {"enum": ["FAILED", "SUCCEEDED"]},
                "error_code": {
                    "anyOf": [
                        {
                            "enum": [
                                "SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID",
                                "SCIENCE_SUBJECT_MULTISEED_EXEC_FAILED",
                                "SCIENCE_SUBJECT_MULTISEED_GPU_RUNTIME_DRIFT",
                                "SCIENCE_SUBJECT_MULTISEED_INPUT_HASH_MISMATCH",
                                "SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
                                "SCIENCE_SUBJECT_MULTISEED_MODEL_INVALID",
                                "SCIENCE_SUBJECT_MULTISEED_OOM",
                                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID",
                            ]
                        },
                        {"type": "null"},
                    ]
                },
                "outputs": {
                    "type": "array",
                    "maxItems": 256,
                    "items": {"$ref": "#/$defs/output"},
                },
                "started_at": deepcopy(UTC),
                "completed_at": deepcopy(UTC),
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _evaluation() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "case_id", "seed", "decision"],
        "properties": {
            "source": {"enum": ["ADDITIONAL", "INITIAL"]},
            "case_id": {
                "type": "string",
                "pattern": "^imgscisubject(seed)?case_[0-9a-f]{32}$",
            },
            "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
            "decision": {"enum": ["ADAPTER", "BASE", "NEITHER"]},
        },
    }


def _review_entry() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "subject_id",
            "subject_key",
            "render_route",
            "evaluations",
            "stability_status",
            "next_actions",
        ],
        "properties": {
            "subject_id": {"type": "string", "pattern": "^imgscisubject_[0-9a-f]{32}$"},
            "subject_key": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{1,63}$"},
            "render_route": {"enum": RASTER_ROUTES},
            "evaluations": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"$ref": "#/$defs/evaluation"},
            },
            "stability_status": {
                "enum": [
                    "MIXED",
                    "NEITHER_ACCEPTABLE",
                    "STABLE_ADAPTER_PREFERRED",
                    "STABLE_BASE_PREFERRED",
                ]
            },
            "next_actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "ADAPTER_PRODUCTION_CANARY",
                        "DATASET_AUGMENTATION",
                        "KEEP_BASE_ONLY",
                        "PROMPT_REFINEMENT",
                        "ROUTE_RECLASSIFICATION",
                    ]
                },
            },
        },
    }


def _review() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Multi-seed Review V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-review/1.0",
    )
    schema["$defs"].update({"evaluation": _evaluation(), "reviewEntry": _review_entry()})
    schema.update(
        {
            "required": [
                "schema_version",
                "review_id",
                "multiseed_plan",
                "multiseed_result",
                "initial_quality_review",
                "reviews",
                "stable_adapter_preferred_count",
                "stable_base_preferred_count",
                "mixed_count",
                "neither_acceptable_count",
                "adapter_activation_recommendation",
                "reviewed_at",
                "reviewed_by",
                "review_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-multiseed-review/1.0"
                },
                "review_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectmultiseedreview_[0-9a-f]{32}$",
                },
                "multiseed_plan": {"$ref": "#/$defs/artifactMember"},
                "multiseed_result": {"$ref": "#/$defs/artifactMember"},
                "initial_quality_review": {"$ref": "#/$defs/artifactMember"},
                "reviews": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {"$ref": "#/$defs/reviewEntry"},
                },
                "stable_adapter_preferred_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64,
                },
                "stable_base_preferred_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64,
                },
                "mixed_count": {"type": "integer", "minimum": 0, "maximum": 64},
                "neither_acceptable_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64,
                },
                "adapter_activation_recommendation": {"const": "FORBIDDEN"},
                "reviewed_at": deepcopy(UTC),
                "reviewed_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "review_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


SCHEMAS = {
    "local-image-science-visual-subject-multiseed-plan-v1.schema.json": _plan(),
    "local-image-science-visual-subject-multiseed-command-v1.schema.json": _command(),
    "local-image-science-visual-subject-multiseed-result-v1.schema.json": _result(),
    "local-image-science-visual-subject-multiseed-review-v1.schema.json": _review(),
}


def main() -> None:
    for directory in (CANONICAL, PACKAGED):
        directory.mkdir(parents=True, exist_ok=True)
        for name, schema in SCHEMAS.items():
            (directory / name).write_text(
                json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()

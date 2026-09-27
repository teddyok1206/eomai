#!/usr/bin/env python3
"""Generate protocol-first contracts for science visual subject coverage."""

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
ROUTES = ["BLOCKED", "HYBRID", "LORA_RASTER", "PYTHON_SVG"]
FAMILIES = [
    "ABSTRACT_SCIENCE_MODEL",
    "EARTH_SPACE",
    "LAB_APPARATUS",
    "LIVING_ORGANISM",
    "MICROSCOPIC_STRUCTURE",
    "PHYSICAL_OBJECT",
    "REAL_WORLD_SCENE",
]
PRIMITIVES = [
    "APPARATUS",
    "AXIS_PLOT",
    "CELL_CROSS_SECTION",
    "CIRCUIT",
    "CONTENT_TABLE",
    "FLOW_DIAGRAM",
    "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION",
    "MAP_BOUNDARY",
    "ORBITAL_SYSTEM",
    "PARTICLE_SYSTEM",
    "RAY_DIAGRAM",
    "TIMELINE",
    "VECTOR_FIELD",
]


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
            "artifact_revision_id": {
                "type": "string",
                "pattern": "^rev_[0-9a-f]{32}$",
            },
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


def _base(title: str, identifier: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": identifier,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "$defs": {"sha256": deepcopy(SHA256), "artifactMember": _artifact_member()},
    }


def _source_reference() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_revision_id",
            "accepted_analysis_result",
            "extraction_result",
            "item_proposal_id",
            "visual_pattern_id",
            "source_anchor_ids",
            "representation_kind",
            "rendering_mode",
            "composition_summary_sha256",
            "reconstruction_guidance_sha256",
        ],
        "properties": {
            "item_revision_id": {
                "type": "string",
                "pattern": "^itemrev_[0-9a-f]{32}$",
            },
            "accepted_analysis_result": {"$ref": "#/$defs/artifactMember"},
            "extraction_result": {"$ref": "#/$defs/artifactMember"},
            "item_proposal_id": {
                "type": "string",
                "pattern": "^itemproposal_[0-9a-f]{32}$",
            },
            "visual_pattern_id": {
                "type": "string",
                "pattern": "^visualpattern_[0-9a-f]{32}$",
            },
            "source_anchor_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                },
            },
            "representation_kind": {
                "enum": [
                    "APPARATUS",
                    "BAR_GRAPH",
                    "COMPOSITE",
                    "CROSS_SECTION",
                    "DIAGRAM",
                    "FLOW",
                    "LINE_GRAPH",
                    "MAP",
                    "NONE",
                    "OTHER_OBSERVED",
                    "PARTICLE_MODEL",
                    "PHOTOGRAPH",
                    "SCATTER_PLOT",
                    "TABLE",
                    "TIMELINE",
                ]
            },
            "rendering_mode": {"enum": ["MIXED", "RASTER", "TEXT_ONLY", "VECTOR_LIKE"]},
            "composition_summary_sha256": {"$ref": "#/$defs/sha256"},
            "reconstruction_guidance_sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _subject() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "subject_id",
            "subject_key",
            "label_ko",
            "label_en",
            "aliases_ko",
            "family",
            "render_route",
            "renderer_primitive",
            "raster_prompt_en",
            "raster_prompt_sha256",
            "blocked_reason",
            "references",
        ],
        "properties": {
            "subject_id": {
                "type": "string",
                "pattern": "^imgscisubject_[0-9a-f]{32}$",
            },
            "subject_key": {
                "type": "string",
                "pattern": "^[A-Z][A-Z0-9_]{1,63}$",
            },
            "label_ko": {"type": "string", "minLength": 1, "maxLength": 120},
            "label_en": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "pattern": "^[ -~]+$",
            },
            "aliases_ko": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "family": {"enum": FAMILIES},
            "render_route": {"enum": ROUTES},
            "renderer_primitive": {"anyOf": [{"enum": PRIMITIVES}, {"type": "null"}]},
            "raster_prompt_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 20,
                        "maxLength": 2000,
                        "pattern": "^[ -~]+$",
                    },
                    {"type": "null"},
                ]
            },
            "raster_prompt_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
            "blocked_reason": {
                "anyOf": [
                    {
                        "enum": [
                            "COPYRIGHT_REPRODUCTION_RISK",
                            "NO_SAFE_RENDER_ROUTE",
                            "POLICY_PROHIBITED_CONTENT",
                        ]
                    },
                    {"type": "null"},
                ]
            },
            "references": {
                "type": "array",
                "minItems": 1,
                "maxItems": 512,
                "items": {"$ref": "#/$defs/sourceReference"},
            },
        },
    }


def _omission() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["item_revision_id", "item_proposal_id", "visual_pattern_id", "reason"],
        "properties": {
            "item_revision_id": {
                "type": "string",
                "pattern": "^itemrev_[0-9a-f]{32}$",
            },
            "item_proposal_id": {
                "type": "string",
                "pattern": "^itemproposal_[0-9a-f]{32}$",
            },
            "visual_pattern_id": {
                "type": "string",
                "pattern": "^visualpattern_[0-9a-f]{32}$",
            },
            "reason": {"enum": ["NO_RENDERED_SUBJECT", "TEXT_ONLY_PATTERN"]},
        },
    }


def _inventory() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Inventory V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0",
    )
    schema["$defs"].update(
        {"sourceReference": _source_reference(), "subject": _subject(), "omission": _omission()}
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "inventory_id",
                "inventory_revision_id",
                "revision_number",
                "previous_revision_id",
                "training_authorization",
                "pattern_inventory",
                "target_set_sha256",
                "source_item_count",
                "source_visual_observation_count",
                "covered_visual_observation_count",
                "subjects",
                "omissions",
                "created_at",
                "created_by",
                "inventory_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-visual-subject-inventory/1.0"},
                "inventory_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectinventory_[0-9a-f]{32}$",
                },
                "inventory_revision_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectinventoryrev_[0-9a-f]{32}$",
                },
                "revision_number": {"type": "integer", "minimum": 1, "maximum": 100000},
                "previous_revision_id": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^imgscisubjectinventoryrev_[0-9a-f]{32}$",
                        },
                        {"type": "null"},
                    ]
                },
                "training_authorization": {"$ref": "#/$defs/artifactMember"},
                "pattern_inventory": {"$ref": "#/$defs/artifactMember"},
                "target_set_sha256": {"$ref": "#/$defs/sha256"},
                "source_item_count": {"type": "integer", "minimum": 1, "maximum": 1000000},
                "source_visual_observation_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000000,
                },
                "covered_visual_observation_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 1000000,
                },
                "subjects": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "items": {"$ref": "#/$defs/subject"},
                },
                "omissions": {
                    "type": "array",
                    "maxItems": 1024,
                    "items": {"$ref": "#/$defs/omission"},
                },
                "created_at": deepcopy(UTC),
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "inventory_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _case() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "subject_id",
            "render_route",
            "case_kind",
            "prompt_en",
            "prompt_sha256",
            "negative_prompt_en",
            "negative_prompt_sha256",
            "seed",
            "renderer_primitive",
            "expected_outcome",
        ],
        "properties": {
            "case_id": {
                "type": "string",
                "pattern": "^imgscisubjectcase_[0-9a-f]{32}$",
            },
            "subject_id": {"type": "string", "pattern": "^imgscisubject_[0-9a-f]{32}$"},
            "render_route": {"enum": ROUTES},
            "case_kind": {"enum": ["QUALITY", "ROUTE", "GPU_POLICY_NEGATIVE"]},
            "prompt_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 20,
                        "maxLength": 2000,
                        "pattern": "^[ -~]+$",
                    },
                    {"type": "null"},
                ]
            },
            "prompt_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
            "negative_prompt_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "pattern": "^[ -~]+$",
                    },
                    {"type": "null"},
                ]
            },
            "negative_prompt_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
            "seed": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": 2147483647},
                    {"type": "null"},
                ]
            },
            "renderer_primitive": {"anyOf": [{"enum": PRIMITIVES}, {"type": "null"}]},
            "expected_outcome": {
                "enum": ["BASE_ADAPTER_PAIR", "DETERMINISTIC_RENDERED", "POLICY_REJECTED"]
            },
        },
    }


def _plan() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Benchmark Plan V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0",
    )
    schema["$defs"]["case"] = _case()
    schema.update(
        {
            "required": [
                "schema_version",
                "plan_id",
                "subject_inventory",
                "subject_inventory_sha256",
                "base_model_manifest",
                "adapter_manifest",
                "width_px",
                "height_px",
                "inference_steps",
                "guidance_scale_milli",
                "cases",
                "created_at",
                "created_by",
                "plan_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-benchmark-plan/1.0"
                },
                "plan_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectbenchmark_[0-9a-f]{32}$",
                },
                "subject_inventory": {"$ref": "#/$defs/artifactMember"},
                "subject_inventory_sha256": {"$ref": "#/$defs/sha256"},
                "base_model_manifest": {"$ref": "#/$defs/artifactMember"},
                "adapter_manifest": {"$ref": "#/$defs/artifactMember"},
                "width_px": {"const": 800},
                "height_px": {"const": 500},
                "inference_steps": {"type": "integer", "minimum": 1, "maximum": 100},
                "guidance_scale_milli": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 20000,
                },
                "cases": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "items": {"$ref": "#/$defs/case"},
                },
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
        "EOM Science Visual Subject Benchmark Command V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-command/1.0",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "run_id",
                "plan",
                "plan_sha256",
                "staged_plan_path",
                "staged_model_path",
                "staged_adapter_model_path",
                "staged_adapter_config_path",
                "output_directory",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-benchmark-command/1.0"
                },
                "run_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectbenchmarkrun_[0-9a-f]{32}$",
                },
                "plan": {"$ref": "#/$defs/artifactMember"},
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "staged_plan_path": {"const": "inputs/subject-benchmark-plan.json"},
                "staged_model_path": {"const": "inputs/model"},
                "staged_adapter_model_path": {"const": "inputs/adapter/adapter_model.safetensors"},
                "staged_adapter_config_path": {"const": "inputs/adapter/adapter_config.json"},
                "output_directory": {"const": "outputs"},
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
                "pattern": "^imgscisubjectcase_[0-9a-f]{32}$",
            },
            "variant": {"enum": ["ADAPTER", "BASE", "DETERMINISTIC"]},
            "relative_path": {
                "type": "string",
                "pattern": (
                    "^outputs/imgscisubjectcase_[0-9a-f]{32}-(adapter|base|deterministic)\\.png$"
                ),
            },
            "media_type": {"const": "image/png"},
            "bytes": {"type": "integer", "minimum": 1, "maximum": 67108864},
            "sha256": {"$ref": "#/$defs/sha256"},
            "width_px": {"const": 800},
            "height_px": {"const": 500},
        },
    }


def _outcome() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["case_id", "outcome", "stable_code"],
        "properties": {
            "case_id": {
                "type": "string",
                "pattern": "^imgscisubjectcase_[0-9a-f]{32}$",
            },
            "outcome": {"enum": ["BASE_ADAPTER_PAIR", "DETERMINISTIC_RENDERED", "POLICY_REJECTED"]},
            "stable_code": {
                "anyOf": [
                    {"const": "LOCAL_IMAGE_HUMAN_SUBJECT_FORBIDDEN"},
                    {"type": "null"},
                ]
            },
        },
    }


def _result() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual Subject Benchmark Result V1",
        "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-result/1.0",
    )
    schema["$defs"].update({"output": _output(), "outcome": _outcome()})
    schema.update(
        {
            "required": [
                "schema_version",
                "run_id",
                "plan_id",
                "plan_sha256",
                "command_sha256",
                "status",
                "outcomes",
                "outputs",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-visual-subject-benchmark-result/1.0"
                },
                "run_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectbenchmarkrun_[0-9a-f]{32}$",
                },
                "plan_id": {
                    "type": "string",
                    "pattern": "^imgscisubjectbenchmark_[0-9a-f]{32}$",
                },
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "status": {"const": "SUCCEEDED"},
                "outcomes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "items": {"$ref": "#/$defs/outcome"},
                },
                "outputs": {
                    "type": "array",
                    "maxItems": 768,
                    "items": {"$ref": "#/$defs/output"},
                },
                "started_at": deepcopy(UTC),
                "completed_at": deepcopy(UTC),
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


SCHEMAS = {
    "local-image-science-visual-subject-inventory-v1.schema.json": _inventory(),
    "local-image-science-visual-subject-benchmark-plan-v1.schema.json": _plan(),
    "local-image-science-visual-subject-benchmark-command-v1.schema.json": _command(),
    "local-image-science-visual-subject-benchmark-result-v1.schema.json": _result(),
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

#!/usr/bin/env python3
"""Generate canonical and wheel-mirrored local image LoRA contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = ROOT / "schemas/image-provider"
PACKAGE_ROOT = ROOT / "packages/image_contracts/eom_image_contracts/schemas"

SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
DATE_TIME = {"type": "string", "format": "date-time"}
MEMBER_PATH_PATTERN = "^(?!/)(?!.*\\\\)[^\\u0000-\\u001f\\u007f]+/" + (
    "[^\\u0000-\\u001f\\u007f]+$"
)
ROOT_OR_NESTED_MEMBER_PATH_PATTERN = (
    "^(?!/)(?!.*\\\\)(?!\\.{1,2}(?:/|$))(?!.*(?:/)\\.{1,2}(?:/|$))"
    "[^/\\u0000-\\u001f\\u007f]+(?:/[^/\\u0000-\\u001f\\u007f]+)*$"
)


def _defs(*, allow_root_member_paths: bool = False) -> dict[str, Any]:
    return {
        "sha256": SHA,
        "modelPointer": {
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
        },
        "artifactPointer": {
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
                    "minLength": 1 if allow_root_member_paths else 3,
                    "maxLength": 512,
                    "pattern": (
                        ROOT_OR_NESTED_MEMBER_PATH_PATTERN
                        if allow_root_member_paths
                        else MEMBER_PATH_PATTERN
                    ),
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
        },
        "sourceSnapshot": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "graph_revision_id",
                "graph_snapshot_sha256",
                "graph_manifest_sha256",
                "target_count",
                "target_set_sha256",
            ],
            "properties": {
                "graph_revision_id": {
                    "type": "string",
                    "pattern": "^graphrev_[0-9a-f]{32}$",
                },
                "graph_snapshot_sha256": {"$ref": "#/$defs/sha256"},
                "graph_manifest_sha256": {"$ref": "#/$defs/sha256"},
                "target_count": {"type": "integer", "minimum": 1, "maximum": 1000000},
                "target_set_sha256": {"$ref": "#/$defs/sha256"},
            },
        },
        "rightsPolicy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "rights_policy_id",
                "rights_policy_revision_id",
                "rights_policy_sha256",
            ],
            "properties": {
                "rights_policy_id": {
                    "type": "string",
                    "pattern": "^rightspolicy_[0-9a-f]{32}$",
                },
                "rights_policy_revision_id": {
                    "type": "string",
                    "pattern": "^rightspolicyrev_[0-9a-f]{32}$",
                },
                "rights_policy_sha256": {"$ref": "#/$defs/sha256"},
            },
        },
        "boundingBox": {
            "type": "object",
            "additionalProperties": False,
            "required": ["left", "top", "right", "bottom"],
            "properties": {
                "left": {"type": "integer", "minimum": 0, "maximum": 9999},
                "top": {"type": "integer", "minimum": 0, "maximum": 9999},
                "right": {"type": "integer", "minimum": 1, "maximum": 10000},
                "bottom": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
        },
        "adapterFile": {
            "type": "object",
            "additionalProperties": False,
            "required": ["relative_path", "size_bytes", "sha256"],
            "properties": {
                "relative_path": {
                    "type": "string",
                    "pattern": "^(adapter_model\\.safetensors|adapter_config\\.json)$",
                },
                "size_bytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
                "sha256": {"$ref": "#/$defs/sha256"},
            },
        },
    }


def _base(
    identifier: str,
    title: str,
    *,
    allow_root_member_paths: bool = False,
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": identifier,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "$defs": _defs(allow_root_member_paths=allow_root_member_paths),
    }


def _runtime() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "python_version",
            "torch_version",
            "diffusers_version",
            "transformers_version",
            "accelerate_version",
            "peft_version",
            "bitsandbytes_version",
            "cuda_version",
            "gpu_name",
            "compute_capability",
            "peak_gpu_memory_bytes",
        ],
        "properties": {
            **{
                name: {"type": "string", "minLength": 1, "maxLength": 128}
                for name in (
                    "python_version",
                    "torch_version",
                    "diffusers_version",
                    "transformers_version",
                    "accelerate_version",
                    "peft_version",
                    "bitsandbytes_version",
                    "cuda_version",
                    "gpu_name",
                )
            },
            "compute_capability": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
            "peak_gpu_memory_bytes": {"type": "integer", "minimum": 1},
        },
    }


def _authorization() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-authorization/1.0",
        "EOM Local Image Training Authorization V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "authorization_id",
                "authorization_revision_id",
                "revision_number",
                "previous_revision_id",
                "source_snapshot",
                "rights_policies",
                "permitted_use",
                "derivative_output",
                "state",
                "approved_at",
                "approved_by",
                "authorization_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-authorization/1.0"},
                "authorization_id": {
                    "type": "string",
                    "pattern": "^imgtrainauth_[0-9a-f]{32}$",
                },
                "authorization_revision_id": {
                    "type": "string",
                    "pattern": "^imgtrainauthrev_[0-9a-f]{32}$",
                },
                "revision_number": {"type": "integer", "minimum": 1, "maximum": 100000},
                "previous_revision_id": {
                    "anyOf": [
                        {"type": "string", "pattern": "^imgtrainauthrev_[0-9a-f]{32}$"},
                        {"type": "null"},
                    ]
                },
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "rights_policies": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {"$ref": "#/$defs/rightsPolicy"},
                },
                "permitted_use": {"const": "INTERNAL_LORA_TRAINING"},
                "derivative_output": {"const": "LORA_ADAPTER_ONLY"},
                "state": {"const": "APPROVED"},
                "approved_at": DATE_TIME,
                "approved_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "authorization_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _crop_proposal_set() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0",
        "EOM Local Image Training Crop Proposal Set V1",
        allow_root_member_paths=True,
    )
    representation_kinds = [
        "APPARATUS",
        "COMPOSITE",
        "CROSS_SECTION",
        "DIAGRAM",
        "MAP",
        "PARTICLE_MODEL",
        "PHOTOGRAPH",
    ]
    visual_features = [
        "ARROWS",
        "AXES",
        "BOUNDARY",
        "CALLOUT",
        "DATA_POINTS",
        "ERROR_BAR",
        "GRID",
        "LABELS",
        "LEADER_LINES",
        "LEGEND",
        "MULTIPLE_PANELS",
        "NUMBERED_STEPS",
        "PATTERN_FILL",
        "SCALE",
        "SYMBOL_KEY",
        "TRAJECTORY",
    ]
    proposal = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "crop_proposal_id",
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "source_page_image",
            "physical_page",
            "context_bounding_box",
            "crop_bounding_box",
            "redaction_boxes",
            "rights_policy",
            "representation_kind",
            "rendering_mode",
            "visual_features",
            "candidate_rank",
            "ink_fraction_milli",
            "ocr_redaction_count",
        ],
        "properties": {
            "crop_proposal_id": {
                "type": "string",
                "pattern": "^imgcropproposal_[0-9a-f]{32}$",
            },
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "source_page_image": {"$ref": "#/$defs/artifactPointer"},
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
            "context_bounding_box": {"anyOf": [{"$ref": "#/$defs/boundingBox"}, {"type": "null"}]},
            "crop_bounding_box": {"$ref": "#/$defs/boundingBox"},
            "redaction_boxes": {
                "type": "array",
                "maxItems": 64,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/boundingBox"},
            },
            "rights_policy": {"$ref": "#/$defs/rightsPolicy"},
            "representation_kind": {"enum": representation_kinds},
            "rendering_mode": {"enum": ["MIXED", "RASTER", "VECTOR_LIKE"]},
            "visual_features": {
                "type": "array",
                "maxItems": 24,
                "uniqueItems": True,
                "items": {"enum": visual_features},
            },
            "candidate_rank": {"type": "integer", "minimum": 1, "maximum": 8},
            "ink_fraction_milli": {"type": "integer", "minimum": 1, "maximum": 1000},
            "ocr_redaction_count": {"type": "integer", "minimum": 0, "maximum": 64},
        },
    }
    omission = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "reason",
        ],
        "properties": {
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "reason": {
                "enum": [
                    "NO_PAGE_INPUT",
                    "NO_VISUAL_REGION",
                    "ANSWER_EXPLANATION_SOURCE",
                    "HOLDOUT_SOURCE",
                    "SOURCE_POINTER_INVALID",
                    "UNSUPPORTED_REPRESENTATION",
                ]
            },
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "proposal_set_id",
                "source_snapshot",
                "training_authorization",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "selection_query_revision",
                "locator_revision",
                "proposals",
                "omissions",
                "proposal_population_sha256",
                "created_at",
                "created_by",
                "proposal_set_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-crop-proposal-set/1.0"},
                "proposal_set_id": {
                    "type": "string",
                    "pattern": "^imgcropproposalset_[0-9a-f]{32}$",
                },
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "training_authorization": {"$ref": "#/$defs/artifactPointer"},
                "holdout_evaluation_plan": {"$ref": "#/$defs/artifactPointer"},
                "holdout_sample_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^imgsample_[0-9a-f]{32}$"},
                },
                "holdout_source_anchor_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                    },
                },
                "selection_query_revision": {"const": "local-image-lora-crop-source-query/1.0"},
                "locator_revision": {"const": "local-image-visual-crop-locator/1.0"},
                "proposals": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4096,
                    "items": proposal,
                },
                "omissions": {
                    "type": "array",
                    "maxItems": 4096,
                    "items": omission,
                },
                "proposal_population_sha256": {"$ref": "#/$defs/sha256"},
                "created_at": DATE_TIME,
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "proposal_set_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _crop_locator_command() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-crop-locator-command/1.0",
        "EOM Local Image Crop Locator Command V1",
        allow_root_member_paths=True,
    )
    representation_kinds = [
        "APPARATUS",
        "COMPOSITE",
        "CROSS_SECTION",
        "DIAGRAM",
        "MAP",
        "PARTICLE_MODEL",
        "PHOTOGRAPH",
    ]
    visual_features = [
        "ARROWS",
        "AXES",
        "BOUNDARY",
        "CALLOUT",
        "DATA_POINTS",
        "ERROR_BAR",
        "GRID",
        "LABELS",
        "LEADER_LINES",
        "LEGEND",
        "MULTIPLE_PANELS",
        "NUMBERED_STEPS",
        "PATTERN_FILL",
        "SCALE",
        "SYMBOL_KEY",
        "TRAJECTORY",
    ]
    visual_pattern_ids = {
        "type": "array",
        "minItems": 1,
        "maxItems": 32,
        "uniqueItems": True,
        "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
    }
    source = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "source_page_image",
            "staged_page_member",
            "physical_page",
            "context_bounding_box",
            "rights_policy",
            "representation_kind",
            "rendering_mode",
            "visual_features",
        ],
        "properties": {
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": visual_pattern_ids,
            "source_page_image": {"$ref": "#/$defs/artifactPointer"},
            "staged_page_member": {
                "type": "string",
                "pattern": "^pages/[0-9a-f]{64}\\.png$",
            },
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
            "context_bounding_box": {"anyOf": [{"$ref": "#/$defs/boundingBox"}, {"type": "null"}]},
            "rights_policy": {"$ref": "#/$defs/rightsPolicy"},
            "representation_kind": {"enum": representation_kinds},
            "rendering_mode": {"enum": ["MIXED", "RASTER", "VECTOR_LIKE"]},
            "visual_features": {
                "type": "array",
                "maxItems": 24,
                "uniqueItems": True,
                "items": {"enum": visual_features},
            },
        },
    }
    omission = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "reason",
        ],
        "properties": {
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": visual_pattern_ids,
            "reason": {
                "enum": [
                    "ANSWER_EXPLANATION_SOURCE",
                    "HOLDOUT_SOURCE",
                    "NO_PAGE_INPUT",
                    "NO_VISUAL_REGION",
                    "SOURCE_POINTER_INVALID",
                    "UNSUPPORTED_REPRESENTATION",
                ]
            },
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "locator_run_id",
                "source_snapshot",
                "training_authorization",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "selection_query_revision",
                "locator_revision",
                "sources",
                "preliminary_omissions",
                "created_at",
                "created_by",
                "output_member",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-crop-locator-command/1.0"},
                "locator_run_id": {
                    "type": "string",
                    "pattern": "^imgcroplocator_[0-9a-f]{32}$",
                },
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "training_authorization": {"$ref": "#/$defs/artifactPointer"},
                "holdout_evaluation_plan": {"$ref": "#/$defs/artifactPointer"},
                "holdout_sample_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^imgsample_[0-9a-f]{32}$"},
                },
                "holdout_source_anchor_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                    },
                },
                "selection_query_revision": {"const": "local-image-lora-crop-source-query/1.0"},
                "locator_revision": {"const": "local-image-visual-crop-locator/1.0"},
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4096,
                    "items": source,
                },
                "preliminary_omissions": {
                    "type": "array",
                    "maxItems": 4096,
                    "items": omission,
                },
                "created_at": DATE_TIME,
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "output_member": {"const": "outputs/crop-locator-result.json"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _crop_locator_result() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-crop-locator-result/1.0",
        "EOM Local Image Crop Locator Result V1",
        allow_root_member_paths=True,
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "locator_run_id",
                "command_sha256",
                "status",
                "proposal_set",
                "error_code",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-crop-locator-result/1.0"},
                "locator_run_id": {
                    "type": "string",
                    "pattern": "^imgcroplocator_[0-9a-f]{32}$",
                },
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "status": {"enum": ["SUCCEEDED", "FAILED"]},
                "proposal_set": {
                    "anyOf": [
                        {
                            "$ref": (
                                "eom://schemas/image-provider/"
                                "local-image-training-crop-proposal-set/1.0"
                            )
                        },
                        {"type": "null"},
                    ]
                },
                "error_code": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^IMAGE_TRAINING_[A-Z0-9_]{3,96}$",
                        },
                        {"type": "null"},
                    ]
                },
                "completed_at": DATE_TIME,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "proposal_set": {
                                "$ref": (
                                    "eom://schemas/image-provider/"
                                    "local-image-training-crop-proposal-set/1.0"
                                )
                            },
                            "error_code": {"type": "null"},
                        }
                    },
                    "else": {
                        "properties": {
                            "proposal_set": {"type": "null"},
                            "error_code": {
                                "type": "string",
                                "pattern": "^IMAGE_TRAINING_[A-Z0-9_]{3,96}$",
                            },
                        }
                    },
                }
            ],
        }
    )
    return schema


def _crop_review() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-crop-review/1.0",
        "EOM Local Image Training Crop Review V1",
        allow_root_member_paths=True,
    )
    entry = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_anchor_id",
            "proposal_ids",
            "decision",
            "selected_proposal_id",
            "exclusion_reasons",
            "caption_en",
            "caption_sha256",
        ],
        "properties": {
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "proposal_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^imgcropproposal_[0-9a-f]{32}$"},
            },
            "decision": {"enum": ["PENDING", "ELIGIBLE", "EXCLUDED"]},
            "selected_proposal_id": {
                "anyOf": [
                    {"type": "string", "pattern": "^imgcropproposal_[0-9a-f]{32}$"},
                    {"type": "null"},
                ]
            },
            "exclusion_reasons": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "ANSWER_OR_EXPLANATION_CONTENT",
                        "AUTHORITATIVE_GEOMETRY",
                        "HOLDOUT_OR_NEAR_DUPLICATE",
                        "HUMAN_SUBJECT",
                        "ITEM_NUMBER_OR_PUBLISHER_MARK",
                        "NO_VALID_CROP",
                        "OCR_REDACTION_INCOMPLETE",
                        "TABLE_OR_GRAPH",
                        "UNAUTHORIZED_SOURCE",
                        "UNSUITABLE_OTHER",
                    ]
                },
            },
            "caption_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 180,
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
                    },
                    {"type": "null"},
                ]
            },
            "caption_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
        },
        "allOf": [
            {
                "if": {"properties": {"decision": {"const": "ELIGIBLE"}}},
                "then": {
                    "properties": {
                        "selected_proposal_id": {
                            "type": "string",
                            "pattern": "^imgcropproposal_[0-9a-f]{32}$",
                        },
                        "exclusion_reasons": {"maxItems": 0},
                        "caption_en": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 180,
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
                        },
                        "caption_sha256": {"$ref": "#/$defs/sha256"},
                    }
                },
                "else": {
                    "if": {"properties": {"decision": {"const": "EXCLUDED"}}},
                    "then": {
                        "properties": {
                            "selected_proposal_id": {"type": "null"},
                            "exclusion_reasons": {"minItems": 1},
                            "caption_en": {"type": "null"},
                            "caption_sha256": {"type": "null"},
                        }
                    },
                    "else": {
                        "properties": {
                            "selected_proposal_id": {"type": "null"},
                            "exclusion_reasons": {"maxItems": 0},
                            "caption_en": {"type": "null"},
                            "caption_sha256": {"type": "null"},
                        }
                    },
                },
            }
        ],
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "crop_review_id",
                "review_state",
                "proposal_set",
                "proposal_set_sha256",
                "source_snapshot",
                "proposal_population_sha256",
                "entries",
                "eligible_proposal_set_sha256",
                "reviewed_at",
                "reviewed_by",
                "review_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-crop-review/1.0"},
                "crop_review_id": {
                    "type": "string",
                    "pattern": "^imgcropreview_[0-9a-f]{32}$",
                },
                "review_state": {"enum": ["DRAFT", "FINAL"]},
                "proposal_set": {"$ref": "#/$defs/artifactPointer"},
                "proposal_set_sha256": {"$ref": "#/$defs/sha256"},
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "proposal_population_sha256": {"$ref": "#/$defs/sha256"},
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4096,
                    "items": entry,
                },
                "eligible_proposal_set_sha256": {"$ref": "#/$defs/sha256"},
                "reviewed_at": DATE_TIME,
                "reviewed_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "review_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"review_state": {"const": "FINAL"}}},
                    "then": {
                        "properties": {
                            "entries": {
                                "not": {
                                    "contains": {
                                        "type": "object",
                                        "required": ["decision"],
                                        "properties": {"decision": {"const": "PENDING"}},
                                    }
                                }
                            }
                        }
                    },
                }
            ],
        }
    )
    return schema


def _dataset_manifest() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-dataset-manifest/1.0",
        "EOM Local Image Training Dataset Manifest V1",
    )
    sample = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "training_sample_id",
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "source_page_image",
            "bounding_box",
            "rights_policy",
            "representation_kind",
            "rendering_mode",
            "crop_member",
            "caption_en",
            "caption_sha256",
            "perceptual_hash",
        ],
        "properties": {
            "training_sample_id": {
                "type": "string",
                "pattern": "^imgtrainsample_[0-9a-f]{32}$",
            },
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "source_page_image": {"$ref": "#/$defs/artifactPointer"},
            "bounding_box": {"$ref": "#/$defs/boundingBox"},
            "rights_policy": {"$ref": "#/$defs/rightsPolicy"},
            "representation_kind": {"enum": ["COMPOSITE", "PHOTOGRAPH"]},
            "rendering_mode": {"enum": ["MIXED", "RASTER"]},
            "crop_member": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "member_path",
                    "media_type",
                    "width_px",
                    "height_px",
                    "size_bytes",
                    "sha256",
                ],
                "properties": {
                    "member_path": {
                        "type": "string",
                        "pattern": "^samples/imgtrainsample_[0-9a-f]{32}\\.png$",
                    },
                    "media_type": {"const": "image/png"},
                    "width_px": {"const": 768},
                    "height_px": {"const": 512},
                    "size_bytes": {"type": "integer", "minimum": 1, "maximum": 8388608},
                    "sha256": {"$ref": "#/$defs/sha256"},
                },
            },
            "caption_en": {
                "type": "string",
                "minLength": 3,
                "maxLength": 180,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
            },
            "caption_sha256": {"$ref": "#/$defs/sha256"},
            "perceptual_hash": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "dataset_id",
                "dataset_revision_id",
                "revision_number",
                "previous_revision_id",
                "source_snapshot",
                "training_authorization",
                "eligibility_review",
                "candidate_inventory",
                "base_model",
                "eligibility_policy_revision",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "samples",
                "sample_set_sha256",
                "created_at",
                "created_by",
                "dataset_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-dataset-manifest/1.0"},
                "dataset_id": {"type": "string", "pattern": "^imgdataset_[0-9a-f]{32}$"},
                "dataset_revision_id": {
                    "type": "string",
                    "pattern": "^imgdatasetrev_[0-9a-f]{32}$",
                },
                "revision_number": {"type": "integer", "minimum": 1, "maximum": 100000},
                "previous_revision_id": {
                    "anyOf": [
                        {"type": "string", "pattern": "^imgdatasetrev_[0-9a-f]{32}$"},
                        {"type": "null"},
                    ]
                },
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "training_authorization": {"$ref": "#/$defs/artifactPointer"},
                "eligibility_review": {"$ref": "#/$defs/artifactPointer"},
                "candidate_inventory": {"$ref": "#/$defs/artifactPointer"},
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "eligibility_policy_revision": {"const": "local-image-lora-eligibility/1.0"},
                "holdout_evaluation_plan": {"$ref": "#/$defs/artifactPointer"},
                "holdout_sample_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^imgsample_[0-9a-f]{32}$"},
                },
                "holdout_source_anchor_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                    },
                },
                "samples": {"type": "array", "minItems": 100, "maxItems": 200, "items": sample},
                "sample_set_sha256": {"$ref": "#/$defs/sha256"},
                "created_at": DATE_TIME,
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "dataset_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _candidate_inventory() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0",
        "EOM Local Image Training Candidate Inventory V1",
    )
    candidate = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "source_page_image",
            "physical_page",
            "bounding_box",
            "rights_policy",
            "representation_kind",
            "rendering_mode",
            "caption_en",
            "caption_sha256",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": "^imgtraincandidate_[0-9a-f]{32}$",
            },
            "item_revision_id": {"type": "string", "pattern": "^itemrev_[0-9a-f]{32}$"},
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "source_page_image": {"$ref": "#/$defs/artifactPointer"},
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
            "bounding_box": {"$ref": "#/$defs/boundingBox"},
            "rights_policy": {"$ref": "#/$defs/rightsPolicy"},
            "representation_kind": {"enum": ["COMPOSITE", "PHOTOGRAPH"]},
            "rendering_mode": {"enum": ["MIXED", "RASTER"]},
            "caption_en": {
                "type": "string",
                "minLength": 3,
                "maxLength": 180,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
            },
            "caption_sha256": {"$ref": "#/$defs/sha256"},
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "inventory_id",
                "source_snapshot",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "candidates",
                "created_at",
                "created_by",
                "inventory_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-candidate-inventory/1.0"},
                "inventory_id": {
                    "type": "string",
                    "pattern": "^imgtraininventory_[0-9a-f]{32}$",
                },
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "holdout_evaluation_plan": {"$ref": "#/$defs/artifactPointer"},
                "holdout_sample_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^imgsample_[0-9a-f]{32}$"},
                },
                "holdout_source_anchor_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                    },
                },
                "candidates": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4096,
                    "items": candidate,
                },
                "created_at": DATE_TIME,
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


def _eligibility_review() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-training-eligibility-review/1.0",
        "EOM Local Image Training Eligibility Review V1",
    )
    entry = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "source_page_image",
            "physical_page",
            "bounding_box",
            "rights_policy",
            "representation_kind",
            "rendering_mode",
            "decision",
            "exclusion_reasons",
            "caption_en",
            "caption_sha256",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": "^imgtraincandidate_[0-9a-f]{32}$",
            },
            "item_revision_id": {
                "type": "string",
                "pattern": "^itemrev_[0-9a-f]{32}$",
            },
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "source_page_image": {"$ref": "#/$defs/artifactPointer"},
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
            "bounding_box": {"$ref": "#/$defs/boundingBox"},
            "rights_policy": {"$ref": "#/$defs/rightsPolicy"},
            "representation_kind": {"enum": ["COMPOSITE", "PHOTOGRAPH"]},
            "rendering_mode": {"enum": ["MIXED", "RASTER"]},
            "decision": {"enum": ["PENDING", "ELIGIBLE", "EXCLUDED"]},
            "exclusion_reasons": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "enum": [
                        "AMBIGUOUS_CROP",
                        "ANSWER_OR_EXPLANATION_CONTENT",
                        "AUTHORITATIVE_GEOMETRY",
                        "EMBEDDED_LABEL_OR_VALUE",
                        "FULL_PAGE",
                        "HOLDOUT_OR_NEAR_DUPLICATE",
                        "HUMAN_SUBJECT",
                        "ITEM_NUMBER_OR_PUBLISHER_MARK",
                        "TABLE_OR_GRAPH",
                        "UNAUTHORIZED_SOURCE",
                        "UNSUITABLE_OTHER",
                    ]
                },
            },
            "caption_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 180,
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
                    },
                    {"type": "null"},
                ]
            },
            "caption_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
        },
        "allOf": [
            {
                "if": {
                    "required": ["decision"],
                    "properties": {"decision": {"const": "ELIGIBLE"}},
                },
                "then": {
                    "properties": {
                        "exclusion_reasons": {"maxItems": 0},
                        "caption_en": {"type": "string", "minLength": 3},
                        "caption_sha256": {"$ref": "#/$defs/sha256"},
                    }
                },
            },
            {
                "if": {
                    "required": ["decision"],
                    "properties": {"decision": {"const": "EXCLUDED"}},
                },
                "then": {
                    "properties": {
                        "exclusion_reasons": {"minItems": 1},
                        "caption_en": {"type": "null"},
                        "caption_sha256": {"type": "null"},
                    }
                },
            },
            {
                "if": {
                    "required": ["decision"],
                    "properties": {"decision": {"const": "PENDING"}},
                },
                "then": {
                    "properties": {
                        "exclusion_reasons": {"maxItems": 0},
                        "caption_en": {"type": "null"},
                        "caption_sha256": {"type": "null"},
                    }
                },
            },
        ],
    }
    omission = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_revision_id",
            "extraction_result",
            "source_anchor_id",
            "visual_pattern_ids",
            "exclusion_reasons",
        ],
        "properties": {
            "item_revision_id": {
                "type": "string",
                "pattern": "^itemrev_[0-9a-f]{32}$",
            },
            "extraction_result": {"$ref": "#/$defs/artifactPointer"},
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "visual_pattern_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^visualpattern_[0-9a-f]{32}$"},
            },
            "exclusion_reasons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
                "items": {
                    "enum": [
                        "AMBIGUOUS_CROP",
                        "ANSWER_OR_EXPLANATION_CONTENT",
                        "AUTHORITATIVE_GEOMETRY",
                        "EMBEDDED_LABEL_OR_VALUE",
                        "FULL_PAGE",
                        "HOLDOUT_OR_NEAR_DUPLICATE",
                        "HUMAN_SUBJECT",
                        "ITEM_NUMBER_OR_PUBLISHER_MARK",
                        "TABLE_OR_GRAPH",
                        "UNAUTHORIZED_SOURCE",
                        "UNSUITABLE_OTHER",
                    ]
                },
            },
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "review_id",
                "review_state",
                "source_snapshot",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "selection_query_revision",
                "eligibility_policy_revision",
                "entries",
                "projection_omissions",
                "candidate_population_sha256",
                "eligible_candidate_set_sha256",
                "reviewed_at",
                "reviewed_by",
                "review_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-training-eligibility-review/1.0"},
                "review_id": {
                    "type": "string",
                    "pattern": "^imgtrainreview_[0-9a-f]{32}$",
                },
                "review_state": {"enum": ["DRAFT", "FINAL"]},
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "holdout_evaluation_plan": {"$ref": "#/$defs/artifactPointer"},
                "holdout_sample_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "items": {
                        "type": "string",
                        "pattern": "^imgsample_[0-9a-f]{32}$",
                    },
                },
                "holdout_source_anchor_ids": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 12,
                    "items": {
                        "type": "string",
                        "pattern": "^assessmentanchor_[0-9a-f]{32}$",
                    },
                },
                "selection_query_revision": {"const": "local-image-lora-candidate-query/1.0"},
                "eligibility_policy_revision": {"const": "local-image-lora-eligibility/1.0"},
                "entries": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 4096,
                    "items": entry,
                },
                "projection_omissions": {
                    "type": "array",
                    "maxItems": 4096,
                    "items": omission,
                },
                "candidate_population_sha256": {"$ref": "#/$defs/sha256"},
                "eligible_candidate_set_sha256": {"$ref": "#/$defs/sha256"},
                "reviewed_at": DATE_TIME,
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


def _training_plan() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-training-plan/1.0",
        "EOM Local Image LoRA Training Plan V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_plan_id",
                "dataset_manifest",
                "base_model",
                "trainer_contract",
                "dependencies",
                "hyperparameters",
                "seed",
                "created_at",
                "created_by",
                "plan_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-training-plan/1.0"},
                "training_plan_id": {
                    "type": "string",
                    "pattern": "^imgtrainplan_[0-9a-f]{32}$",
                },
                "dataset_manifest": {"$ref": "#/$defs/artifactPointer"},
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "trainer_contract": {"const": "eom-local-image-lora-trainer/1.0"},
                "dependencies": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "python_version",
                        "torch_version",
                        "diffusers_version",
                        "transformers_version",
                        "accelerate_version",
                        "peft_version",
                        "bitsandbytes_version",
                    ],
                    "properties": {
                        name: {"type": "string", "minLength": 1, "maxLength": 64}
                        for name in (
                            "python_version",
                            "torch_version",
                            "diffusers_version",
                            "transformers_version",
                            "accelerate_version",
                            "peft_version",
                            "bitsandbytes_version",
                        )
                    },
                },
                "hyperparameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "adapter_type",
                        "rank",
                        "alpha",
                        "resolution_width",
                        "resolution_height",
                        "train_batch_size",
                        "gradient_accumulation_steps",
                        "gradient_checkpointing",
                        "mixed_precision",
                        "optimizer",
                        "learning_rate",
                        "max_train_steps",
                        "checkpointing_steps",
                        "random_flip",
                        "train_text_encoders",
                        "train_vae",
                    ],
                    "properties": {
                        "adapter_type": {"const": "UNET_LORA"},
                        "rank": {"const": 8},
                        "alpha": {"const": 8},
                        "resolution_width": {"const": 768},
                        "resolution_height": {"const": 512},
                        "train_batch_size": {"const": 1},
                        "gradient_accumulation_steps": {"const": 4},
                        "gradient_checkpointing": {"const": True},
                        "mixed_precision": {"const": "fp16"},
                        "optimizer": {"const": "adamw_8bit"},
                        "learning_rate": {"const": "1e-4"},
                        "max_train_steps": {"type": "integer", "minimum": 200, "maximum": 2000},
                        "checkpointing_steps": {
                            "type": "integer",
                            "minimum": 100,
                            "maximum": 500,
                        },
                        "random_flip": {"const": False},
                        "train_text_encoders": {"const": False},
                        "train_vae": {"const": False},
                    },
                },
                "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                "created_at": DATE_TIME,
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


def _adapter_manifest() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-adapter-manifest/1.0",
        "EOM Local Image LoRA Adapter Manifest V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "adapter_id",
                "adapter_revision_id",
                "state",
                "base_model",
                "dataset_manifest",
                "training_plan",
                "files",
                "created_at",
                "manifest_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-adapter-manifest/1.0"},
                "adapter_id": {"type": "string", "pattern": "^imgadapter_[0-9a-f]{32}$"},
                "adapter_revision_id": {
                    "type": "string",
                    "pattern": "^imgadapterrev_[0-9a-f]{32}$",
                },
                "state": {"const": "CANDIDATE"},
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "dataset_manifest": {"$ref": "#/$defs/artifactPointer"},
                "training_plan": {"$ref": "#/$defs/artifactPointer"},
                "files": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"$ref": "#/$defs/adapterFile"},
                },
                "created_at": DATE_TIME,
                "manifest_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _checkpoint_manifest() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-checkpoint-manifest/1.0",
        "EOM Local Image LoRA Checkpoint Manifest V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "training_plan_sha256",
                "attempt",
                "completed_steps",
                "micro_steps",
                "files",
                "created_at",
                "manifest_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-checkpoint-manifest/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgtrainrun_[0-9a-f]{32}$",
                },
                "training_plan_sha256": {"$ref": "#/$defs/sha256"},
                "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
                "completed_steps": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 2000,
                },
                "micro_steps": {
                    "type": "integer",
                    "minimum": 400,
                    "maximum": 8000,
                },
                "files": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["relative_path", "size_bytes", "sha256"],
                        "properties": {
                            "relative_path": {
                                "type": "string",
                                "enum": [
                                    "adapter_model.safetensors",
                                    "optimizer-rng-state.pt",
                                ],
                            },
                            "size_bytes": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 2147483648,
                            },
                            "sha256": {"$ref": "#/$defs/sha256"},
                        },
                    },
                },
                "created_at": DATE_TIME,
                "manifest_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _training_receipt() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-training-receipt/1.0",
        "EOM Local Image LoRA Training Receipt V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "training_plan",
                "attempt",
                "status",
                "adapter_manifest",
                "error_code",
                "runtime",
                "completed_steps",
                "final_loss",
                "started_at",
                "completed_at",
                "receipt_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-training-receipt/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgtrainrun_[0-9a-f]{32}$",
                },
                "training_plan": {"$ref": "#/$defs/artifactPointer"},
                "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
                "status": {"enum": ["SUCCEEDED", "FAILED", "CANCELLED"]},
                "adapter_manifest": {
                    "anyOf": [{"$ref": "#/$defs/artifactPointer"}, {"type": "null"}]
                },
                "error_code": {
                    "anyOf": [
                        {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,95}$"},
                        {"type": "null"},
                    ]
                },
                "runtime": {"anyOf": [_runtime(), {"type": "null"}]},
                "completed_steps": {"type": "integer", "minimum": 0, "maximum": 2000},
                "final_loss": {
                    "anyOf": [
                        {"type": "number", "minimum": 0, "maximum": 1000000},
                        {"type": "null"},
                    ]
                },
                "started_at": DATE_TIME,
                "completed_at": DATE_TIME,
                "receipt_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "adapter_manifest": {"$ref": "#/$defs/artifactPointer"},
                            "error_code": {"type": "null"},
                            "runtime": _runtime(),
                            "completed_steps": {"minimum": 200},
                            "final_loss": {"type": "number", "minimum": 0, "maximum": 1000000},
                        }
                    },
                    "else": {
                        "properties": {
                            "adapter_manifest": {"type": "null"},
                            "error_code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,95}$"},
                        }
                    },
                }
            ],
        }
    )
    return schema


def _training_command() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-training-command/1.0",
        "EOM Local Image LoRA Training Command V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "training_plan_pointer",
                "training_plan_sha256",
                "training_plan",
                "attempt",
                "staged_plan_member",
                "staged_dataset_root",
                "output_root_member",
                "checkpoint_root_member",
                "timeout_seconds",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-training-command/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgtrainrun_[0-9a-f]{32}$",
                },
                "training_plan_pointer": {"$ref": "#/$defs/artifactPointer"},
                "training_plan_sha256": {"$ref": "#/$defs/sha256"},
                "training_plan": {
                    "$ref": ("eom://schemas/image-provider/local-image-lora-training-plan/1.0")
                },
                "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
                "staged_plan_member": {"const": "inputs/training-plan.json"},
                "staged_dataset_root": {"const": "inputs/dataset"},
                "output_root_member": {"const": "outputs"},
                "checkpoint_root_member": {"const": "checkpoints"},
                "timeout_seconds": {"type": "integer", "minimum": 600, "maximum": 86400},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _training_worker_result() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-training-worker-result/1.0",
        "EOM Local Image LoRA Training Worker Result V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "training_plan_pointer",
                "training_plan_sha256",
                "attempt",
                "status",
                "adapter_manifest",
                "error_code",
                "runtime",
                "completed_steps",
                "final_loss",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-training-worker-result/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgtrainrun_[0-9a-f]{32}$",
                },
                "training_plan_pointer": {"$ref": "#/$defs/artifactPointer"},
                "training_plan_sha256": {"$ref": "#/$defs/sha256"},
                "attempt": {"type": "integer", "minimum": 1, "maximum": 10},
                "status": {"enum": ["SUCCEEDED", "FAILED", "CANCELLED"]},
                "adapter_manifest": {
                    "anyOf": [
                        {
                            "$ref": (
                                "eom://schemas/image-provider/local-image-lora-adapter-manifest/1.0"
                            )
                        },
                        {"type": "null"},
                    ]
                },
                "error_code": {
                    "anyOf": [
                        {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,95}$"},
                        {"type": "null"},
                    ]
                },
                "runtime": {"anyOf": [_runtime(), {"type": "null"}]},
                "completed_steps": {"type": "integer", "minimum": 0, "maximum": 2000},
                "final_loss": {
                    "anyOf": [
                        {"type": "number", "minimum": 0, "maximum": 1000000},
                        {"type": "null"},
                    ]
                },
                "started_at": DATE_TIME,
                "completed_at": DATE_TIME,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {
                        "required": ["status"],
                        "properties": {"status": {"const": "SUCCEEDED"}},
                    },
                    "then": {
                        "properties": {
                            "adapter_manifest": {
                                "$ref": (
                                    "eom://schemas/image-provider/"
                                    "local-image-lora-adapter-manifest/1.0"
                                )
                            },
                            "error_code": {"type": "null"},
                            "runtime": _runtime(),
                            "completed_steps": {"minimum": 200},
                            "final_loss": {"type": "number", "minimum": 0, "maximum": 1000000},
                        }
                    },
                    "else": {
                        "properties": {
                            "adapter_manifest": {"type": "null"},
                            "error_code": {
                                "type": "string",
                                "pattern": "^[A-Z][A-Z0-9_]{2,95}$",
                            },
                        }
                    },
                }
            ],
        }
    )
    return schema


SCHEMAS = {
    "local-image-training-authorization-v1.schema.json": _authorization(),
    "local-image-crop-locator-command-v1.schema.json": _crop_locator_command(),
    "local-image-crop-locator-result-v1.schema.json": _crop_locator_result(),
    "local-image-training-crop-proposal-set-v1.schema.json": _crop_proposal_set(),
    "local-image-training-crop-review-v1.schema.json": _crop_review(),
    "local-image-training-dataset-manifest-v1.schema.json": _dataset_manifest(),
    "local-image-training-candidate-inventory-v1.schema.json": _candidate_inventory(),
    "local-image-training-eligibility-review-v1.schema.json": _eligibility_review(),
    "local-image-lora-training-plan-v1.schema.json": _training_plan(),
    "local-image-lora-adapter-manifest-v1.schema.json": _adapter_manifest(),
    "local-image-lora-checkpoint-manifest-v1.schema.json": _checkpoint_manifest(),
    "local-image-lora-training-receipt-v1.schema.json": _training_receipt(),
    "local-image-lora-training-command-v1.schema.json": _training_command(),
    "local-image-lora-training-worker-result-v1.schema.json": _training_worker_result(),
}


def _payload(schema: dict[str, Any]) -> bytes:
    return (json.dumps(schema, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for root in (CANONICAL_ROOT, PACKAGE_ROOT):
        root.mkdir(parents=True, exist_ok=True)
        for name, schema in SCHEMAS.items():
            path = root / name
            payload = _payload(schema)
            if args.check:
                if not path.is_file() or path.read_bytes() != payload:
                    raise SystemExit(f"LORA_SCHEMA_DRIFT:{path}")
            else:
                path.write_bytes(payload)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate protocol-first schemas for the object-line-art campaign successor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DESTINATIONS = (
    ROOT / "schemas/image-provider",
    ROOT / "packages/image_contracts/eom_image_contracts/schemas",
)
SHA256 = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
UTC = {
    "type": "string",
    "format": "date-time",
    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*Z$",
}
ACTOR = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9._:@-]+$"}


def artifact_member() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "artifact_id",
            "artifact_revision_id",
            "member_path",
            "media_type",
            "schema_ref",
            "sha256",
        ],
        "properties": {
            "artifact_id": {"type": "string", "pattern": "^artifact_[0-9a-f]{32}$"},
            "artifact_revision_id": {"type": "string", "pattern": "^rev_[0-9a-f]{32}$"},
            "member_path": {"type": "string", "minLength": 1, "maxLength": 512},
            "media_type": {"type": "string", "minLength": 1, "maxLength": 128},
            "schema_ref": {"type": "string", "minLength": 1, "maxLength": 512},
            "sha256": SHA256,
        },
    }


def bounding_box() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["bottom", "left", "right", "top"],
        "properties": {
            "bottom": {"type": "integer", "minimum": 1, "maximum": 10000},
            "left": {"type": "integer", "minimum": 0, "maximum": 9999},
            "right": {"type": "integer", "minimum": 1, "maximum": 10000},
            "top": {"type": "integer", "minimum": 0, "maximum": 9999},
        },
    }


OBJECT_FAMILIES = [
    "ANIMAL",
    "HUMAN",
    "LAB_EQUIPMENT",
    "NATURAL_SPECIMEN",
    "PLANT",
    "SAFETY_EQUIPMENT",
    "VEHICLE",
    "OTHER_OBJECT",
]
DECISIONS = [
    "DETERMINISTIC_RENDERER_ONLY",
    "EXCLUDED",
    "OBJECT_LINE_ART_ELIGIBLE",
    "RASTER_STYLE_ONLY",
]
REASONS = [
    "ANSWER_BEARING_CONTENT",
    "AUTHORITATIVE_GEOMETRY",
    "BACKGROUND_CLUTTER",
    "DUPLICATE_CONTENT",
    "INSUFFICIENT_IMAGE_CONTENT",
    "NON_OBJECT_CONTENT",
    "RASTER_TEXTURE_TARGET",
    "REDACTION_OR_MASK",
    "TEXT_OR_LABEL",
]


def review_schema() -> dict[str, Any]:
    entry = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "caption_en",
            "caption_sha256",
            "crop_bounding_box",
            "decision",
            "object_family",
            "reasons",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
            },
            "decision": {"enum": DECISIONS},
            "reasons": {
                "type": "array",
                "maxItems": len(REASONS),
                "uniqueItems": True,
                "items": {"enum": REASONS},
            },
            "object_family": {"anyOf": [{"enum": OBJECT_FAMILIES}, {"type": "null"}]},
            "crop_bounding_box": {"anyOf": [{"$ref": "#/$defs/bounding_box"}, {"type": "null"}]},
            "caption_en": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 240,
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
                    },
                    {"type": "null"},
                ]
            },
            "caption_sha256": {"anyOf": [SHA256, {"type": "null"}]},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/image-provider/local-image-science-object-line-art-suitability-review/1.0",
        "title": "LocalImageScienceObjectLineArtSuitabilityReview",
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "artifact_member": artifact_member(),
            "bounding_box": bounding_box(),
            "entry": entry,
        },
        "required": [
            "campaign_id",
            "created_at",
            "created_by",
            "decision_counts",
            "entries",
            "pattern_inventory",
            "pattern_inventory_semantic_sha256",
            "review_id",
            "review_sha256",
            "schema_version",
        ],
        "properties": {
            "schema_version": {
                "const": "local-image-science-object-line-art-suitability-review/1.0"
            },
            "review_id": {
                "type": "string",
                "pattern": "^imgscivislineartreview_[0-9a-f]{32}$",
            },
            "campaign_id": {"type": "string", "pattern": "^imgsciviscampaign_[0-9a-f]{32}$"},
            "pattern_inventory": {"$ref": "#/$defs/artifact_member"},
            "pattern_inventory_semantic_sha256": SHA256,
            "entries": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2048,
                "items": {"$ref": "#/$defs/entry"},
            },
            "decision_counts": {
                "type": "object",
                "additionalProperties": False,
                "required": DECISIONS,
                "properties": {
                    key: {"type": "integer", "minimum": 0, "maximum": 2048} for key in DECISIONS
                },
            },
            "created_at": UTC,
            "created_by": ACTOR,
            "review_sha256": SHA256,
        },
    }


def crop_set_schema() -> dict[str, Any]:
    member = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "caption_en",
            "caption_sha256",
            "crop_bounding_box",
            "document_id",
            "exam_group_sha256",
            "height_px",
            "media_type",
            "member_path",
            "object_family",
            "parent_candidate_id",
            "parent_candidate_sha256",
            "partition",
            "perceptual_hash",
            "physical_page",
            "sample_id",
            "sha256",
            "size_bytes",
            "width_px",
        ],
        "properties": {
            "sample_id": {"type": "string", "pattern": "^imgscivislineartcrop_[0-9a-f]{32}$"},
            "parent_candidate_id": {
                "type": "string",
                "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
            },
            "parent_candidate_sha256": SHA256,
            "crop_bounding_box": {"$ref": "#/$defs/bounding_box"},
            "document_id": {"type": "string", "pattern": "^sciencedoc_[0-9a-f]{32}$"},
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 512},
            "exam_group_sha256": SHA256,
            "partition": {"enum": ["HOLDOUT", "TRAIN", "VALIDATION"]},
            "object_family": {"enum": OBJECT_FAMILIES},
            "member_path": {
                "type": "string",
                "pattern": "^crops/imgscivislineartcrop_[0-9a-f]{32}\\.png$",
            },
            "media_type": {"const": "image/png"},
            "width_px": {"type": "integer", "minimum": 32, "maximum": 10000},
            "height_px": {"type": "integer", "minimum": 32, "maximum": 10000},
            "size_bytes": {"type": "integer", "minimum": 64, "maximum": 67108864},
            "sha256": SHA256,
            "caption_en": {
                "type": "string",
                "minLength": 3,
                "maxLength": 240,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
            },
            "caption_sha256": SHA256,
            "perceptual_hash": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0",
        "title": "LocalImageScienceObjectLineArtCropSet",
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "artifact_member": artifact_member(),
            "bounding_box": bounding_box(),
            "member": member,
        },
        "required": [
            "campaign_id",
            "created_at",
            "created_by",
            "crop_set_id",
            "crop_set_sha256",
            "line_art_suitability_review",
            "line_art_suitability_review_sha256",
            "member_policy",
            "members",
            "pattern_inventory",
            "pattern_inventory_semantic_sha256",
            "schema_version",
            "training_authorization",
        ],
        "properties": {
            "schema_version": {"const": "local-image-science-object-line-art-crop-set/1.0"},
            "crop_set_id": {"type": "string", "pattern": "^imgscivislineartcropset_[0-9a-f]{32}$"},
            "campaign_id": {"type": "string", "pattern": "^imgsciviscampaign_[0-9a-f]{32}$"},
            "pattern_inventory": {"$ref": "#/$defs/artifact_member"},
            "pattern_inventory_semantic_sha256": SHA256,
            "line_art_suitability_review": {"$ref": "#/$defs/artifact_member"},
            "line_art_suitability_review_sha256": SHA256,
            "training_authorization": {"$ref": "#/$defs/artifact_member"},
            "member_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "max_members_per_document",
                    "max_members_per_exam_group",
                    "partition_policy",
                ],
                "properties": {
                    "partition_policy": {"const": "PINNED_SOURCE_GROUP_V1"},
                    "max_members_per_document": {"const": 3},
                    "max_members_per_exam_group": {"const": 4},
                },
            },
            "members": {
                "type": "array",
                "minItems": 24,
                "maxItems": 96,
                "items": {"$ref": "#/$defs/member"},
            },
            "created_at": UTC,
            "created_by": ACTOR,
            "crop_set_sha256": SHA256,
        },
    }


SCHEMAS = {
    "local-image-science-object-line-art-suitability-review-v1.schema.json": review_schema,
    "local-image-science-object-line-art-crop-set-v1.schema.json": crop_set_schema,
}


def main() -> int:
    for directory in DESTINATIONS:
        directory.mkdir(parents=True, exist_ok=True)
        for filename, factory in SCHEMAS.items():
            payload = json.dumps(factory(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            (directory / filename).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

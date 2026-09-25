#!/usr/bin/env python3
"""Generate additive contracts for the science-corpus visual learning pilot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas" / "image-provider"
PACKAGED = ROOT / "packages" / "image_contracts" / "eom_image_contracts" / "schemas"

SHA256 = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
UTC = {"type": "string", "format": "date-time"}


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
        "$defs": {
            "sha256": SHA256,
            "artifactMember": _artifact_member(),
        },
    }


def _authorization() -> dict[str, Any]:
    schema = _base(
        "EOM Science Corpus Internal Visual Training Authorization V1",
        "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "authorization_id",
                "authorization_revision_id",
                "revision_number",
                "previous_revision_id",
                "corpus_manifest",
                "corpus_id",
                "corpus_manifest_sha256",
                "acquisition_sha256",
                "resolution_sha256",
                "resolution_policy_id",
                "resolution_policy_sha256",
                "authorization_basis",
                "permitted_uses",
                "derivative_output",
                "raw_source_export",
                "state",
                "approved_at",
                "approved_by",
                "authorization_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-corpus-training-authorization/1.0"
                },
                "authorization_id": {
                    "type": "string",
                    "pattern": "^imgscicorpusauth_[0-9a-f]{32}$",
                },
                "authorization_revision_id": {
                    "type": "string",
                    "pattern": "^imgscicorpusauthrev_[0-9a-f]{32}$",
                },
                "revision_number": {"type": "integer", "minimum": 1, "maximum": 100000},
                "previous_revision_id": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^imgscicorpusauthrev_[0-9a-f]{32}$",
                        },
                        {"type": "null"},
                    ]
                },
                "corpus_manifest": {"$ref": "#/$defs/artifactMember"},
                "corpus_id": {
                    "type": "string",
                    "pattern": "^sciencecorpus_[0-9a-f]{32}$",
                },
                "corpus_manifest_sha256": {"$ref": "#/$defs/sha256"},
                "acquisition_sha256": {"$ref": "#/$defs/sha256"},
                "resolution_sha256": {"$ref": "#/$defs/sha256"},
                "resolution_policy_id": {
                    "type": "string",
                    "pattern": "^sciencecorpuspolicy_[0-9a-f]{32}$",
                },
                "resolution_policy_sha256": {"$ref": "#/$defs/sha256"},
                "authorization_basis": {"const": "USER_APPROVED_INTERNAL_EXAM_MATERIALS"},
                "permitted_uses": {
                    "type": "array",
                    "prefixItems": [
                        {"const": "DETERMINISTIC_PATTERN_ANALYSIS"},
                        {"const": "INTERNAL_SSD1B_LORA_TRAINING"},
                    ],
                    "items": False,
                    "minItems": 2,
                    "maxItems": 2,
                },
                "derivative_output": {"const": "LORA_ADAPTER_ONLY"},
                "raw_source_export": {"const": "FORBIDDEN"},
                "state": {"const": "APPROVED"},
                "approved_at": UTC,
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


def _guidance_authority() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["role", "logical_name", "source_commit", "sha256"],
        "properties": {
            "role": {
                "enum": [
                    "AUTHORING_TEAM_LEAD",
                    "HWPX_EDITOR_TEAM_LEAD",
                    "KICE_ILLUSTRATION_GUIDE",
                ]
            },
            "logical_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "pattern": "^[A-Za-z0-9._/-]+$",
            },
            "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _tool_identity(allowed_path: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "sha256", "version"],
        "properties": {
            "path": {"const": allowed_path},
            "sha256": {"$ref": "#/$defs/sha256"},
            "version": {"type": "string", "minLength": 1, "maxLength": 128},
        },
    }


def _pilot_plan() -> dict[str, Any]:
    schema = _base(
        "EOM Science Corpus Visual Pilot Plan V1",
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0",
    )
    schema["$defs"].update(
        {
            "guidanceAuthority": _guidance_authority(),
            "pdfSource": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "document_id",
                    "source_file_id",
                    "pdf",
                    "bytes",
                    "page_count",
                    "subject_family",
                    "issuer_type",
                    "administration_year",
                    "grade",
                    "session_label",
                    "exam_group_sha256",
                    "partition",
                ],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "pattern": "^sciencedoc_[0-9a-f]{32}$",
                    },
                    "source_file_id": {
                        "type": "string",
                        "pattern": "^sourcefile_[0-9a-f]{32}$",
                    },
                    "pdf": {"$ref": "#/$defs/artifactMember"},
                    "bytes": {
                        "type": "integer",
                        "minimum": 1024,
                        "maximum": 104857600,
                    },
                    "page_count": {"type": "integer", "minimum": 1, "maximum": 512},
                    "subject_family": {
                        "enum": [
                            "CHEMISTRY",
                            "EARTH_SCIENCE",
                            "GENERAL_SCIENCE",
                            "INTEGRATED_SCIENCE",
                            "LIFE_SCIENCE",
                            "PHYSICS",
                        ]
                    },
                    "issuer_type": {"enum": ["EDUCATION_AUTHORITY", "KICE"]},
                    "administration_year": {
                        "type": "integer",
                        "minimum": 1994,
                        "maximum": 2200,
                    },
                    "grade": {"type": "integer", "minimum": 1, "maximum": 3},
                    "session_label": {"type": "string", "minLength": 1, "maxLength": 128},
                    "exam_group_sha256": {"$ref": "#/$defs/sha256"},
                    "partition": {"enum": ["HOLDOUT", "TRAIN", "VALIDATION"]},
                },
            },
            "tools": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pdftoppm", "tesseract"],
                "properties": {
                    "pdftoppm": _tool_identity("/usr/bin/pdftoppm"),
                    "tesseract": _tool_identity("/usr/bin/tesseract"),
                },
            },
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "pilot_id",
                "corpus_manifest",
                "corpus_id",
                "corpus_manifest_sha256",
                "acquisition_sha256",
                "resolution_sha256",
                "resolution_policy_id",
                "resolution_policy_sha256",
                "training_authorization",
                "selection_algorithm",
                "selection_seed_sha256",
                "selected_sources",
                "max_page_images",
                "max_visual_candidates",
                "max_lora_training_crops",
                "page_render_dpi",
                "locator_revision",
                "guidance_authorities",
                "tools",
                "created_at",
                "created_by",
                "plan_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-corpus-visual-pilot-plan/1.0"},
                "pilot_id": {
                    "type": "string",
                    "pattern": "^imgscivispilot_[0-9a-f]{32}$",
                },
                "corpus_manifest": {"$ref": "#/$defs/artifactMember"},
                "corpus_id": {
                    "type": "string",
                    "pattern": "^sciencecorpus_[0-9a-f]{32}$",
                },
                "corpus_manifest_sha256": {"$ref": "#/$defs/sha256"},
                "acquisition_sha256": {"$ref": "#/$defs/sha256"},
                "resolution_sha256": {"$ref": "#/$defs/sha256"},
                "resolution_policy_id": {
                    "type": "string",
                    "pattern": "^sciencecorpuspolicy_[0-9a-f]{32}$",
                },
                "resolution_policy_sha256": {"$ref": "#/$defs/sha256"},
                "training_authorization": {"$ref": "#/$defs/artifactMember"},
                "selection_algorithm": {"const": "SCIENCE_VISUAL_STRATIFIED_SHA256_V1"},
                "selection_seed_sha256": {"$ref": "#/$defs/sha256"},
                "selected_sources": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 96,
                    "items": {"$ref": "#/$defs/pdfSource"},
                },
                "max_page_images": {
                    "type": "integer",
                    "minimum": 12,
                    "maximum": 384,
                },
                "max_visual_candidates": {
                    "type": "integer",
                    "minimum": 12,
                    "maximum": 512,
                },
                "max_lora_training_crops": {
                    "type": "integer",
                    "minimum": 12,
                    "maximum": 96,
                },
                "page_render_dpi": {"const": 144},
                "locator_revision": {"const": "science-corpus-visual-locator/1.0"},
                "guidance_authorities": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {"$ref": "#/$defs/guidanceAuthority"},
                },
                "tools": {"$ref": "#/$defs/tools"},
                "created_at": UTC,
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


def _bounding_box() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["left", "top", "right", "bottom"],
        "properties": {
            "left": {"type": "integer", "minimum": 0, "maximum": 9999},
            "top": {"type": "integer", "minimum": 0, "maximum": 9999},
            "right": {"type": "integer", "minimum": 1, "maximum": 10000},
            "bottom": {"type": "integer", "minimum": 1, "maximum": 10000},
        },
    }


REPRESENTATION_KINDS = [
    "APPARATUS",
    "COMPOSITE",
    "CROSS_SECTION",
    "DIAGRAM",
    "MAP",
    "PARTICLE_MODEL",
    "PHOTOGRAPH",
    "PLOT",
    "TABLE",
    "UNKNOWN",
]
VISUAL_FEATURES = [
    "ARROWS",
    "AXES",
    "BOUNDARY",
    "CALLOUT",
    "DATA_POINTS",
    "GRID",
    "HATCHING",
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


def _pilot_result() -> dict[str, Any]:
    schema = _base(
        "EOM Science Corpus Visual Pilot Result V1",
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0",
    )
    schema["$defs"].update(
        {
            "boundingBox": _bounding_box(),
            "pageImage": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "document_id",
                    "physical_page",
                    "member_path",
                    "sha256",
                    "size_bytes",
                    "width_px",
                    "height_px",
                ],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "pattern": "^sciencedoc_[0-9a-f]{32}$",
                    },
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 512},
                    "member_path": {
                        "type": "string",
                        "pattern": "^pages/sciencedoc_[0-9a-f]{32}/page-[0-9]{1,3}\\.png$",
                    },
                    "sha256": {"$ref": "#/$defs/sha256"},
                    "size_bytes": {
                        "type": "integer",
                        "minimum": 64,
                        "maximum": 67108864,
                    },
                    "width_px": {"type": "integer", "minimum": 100, "maximum": 10000},
                    "height_px": {"type": "integer", "minimum": 100, "maximum": 10000},
                },
            },
            "candidate": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "document_id",
                    "physical_page",
                    "page_image_sha256",
                    "bounding_box",
                    "member_path",
                    "sha256",
                    "size_bytes",
                    "representation_kind",
                    "rendering_mode",
                    "visual_features",
                    "authority_class",
                    "review_state",
                    "locator_score_milli",
                ],
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
                    },
                    "document_id": {
                        "type": "string",
                        "pattern": "^sciencedoc_[0-9a-f]{32}$",
                    },
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 512},
                    "page_image_sha256": {"$ref": "#/$defs/sha256"},
                    "bounding_box": {"$ref": "#/$defs/boundingBox"},
                    "member_path": {
                        "type": "string",
                        "pattern": "^crops/imgsciviscandidate_[0-9a-f]{32}\\.png$",
                    },
                    "sha256": {"$ref": "#/$defs/sha256"},
                    "size_bytes": {
                        "type": "integer",
                        "minimum": 64,
                        "maximum": 67108864,
                    },
                    "representation_kind": {"enum": REPRESENTATION_KINDS},
                    "rendering_mode": {"enum": ["MIXED", "RASTER", "VECTOR_LIKE"]},
                    "visual_features": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {"enum": VISUAL_FEATURES},
                    },
                    "authority_class": {
                        "enum": [
                            "AUTHORITATIVE_DETERMINISTIC_GEOMETRY",
                            "NON_AUTHORITATIVE_RASTER_STYLE",
                            "UNKNOWN_REVIEW_REQUIRED",
                        ]
                    },
                    "review_state": {"const": "PENDING"},
                    "locator_score_milli": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
            },
            "omission": {
                "type": "object",
                "additionalProperties": False,
                "required": ["document_id", "physical_page", "reason"],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "pattern": "^sciencedoc_[0-9a-f]{32}$",
                    },
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 512},
                    "reason": {
                        "enum": [
                            "CANDIDATE_LIMIT_REACHED",
                            "NO_VISUAL_REGION",
                            "PAGE_RENDER_FAILED",
                            "PDF_POINTER_INVALID",
                        ]
                    },
                },
            },
            "runtime": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "python_version",
                    "pillow_version",
                    "opencv_version",
                    "tesseract_version",
                    "pdftoppm_version",
                ],
                "properties": {
                    "python_version": {"type": "string", "minLength": 1, "maxLength": 64},
                    "pillow_version": {"type": "string", "minLength": 1, "maxLength": 64},
                    "opencv_version": {"type": "string", "minLength": 1, "maxLength": 64},
                    "tesseract_version": {"type": "string", "minLength": 1, "maxLength": 128},
                    "pdftoppm_version": {"type": "string", "minLength": 1, "maxLength": 128},
                },
            },
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "pilot_id",
                "plan_sha256",
                "status",
                "page_images",
                "visual_candidates",
                "omissions",
                "runtime",
                "error_code",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-corpus-visual-pilot-result/1.0"},
                "pilot_id": {
                    "type": "string",
                    "pattern": "^imgscivispilot_[0-9a-f]{32}$",
                },
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "status": {"enum": ["FAILED", "SUCCEEDED"]},
                "page_images": {
                    "type": "array",
                    "maxItems": 384,
                    "items": {"$ref": "#/$defs/pageImage"},
                },
                "visual_candidates": {
                    "type": "array",
                    "maxItems": 512,
                    "items": {"$ref": "#/$defs/candidate"},
                },
                "omissions": {
                    "type": "array",
                    "maxItems": 384,
                    "items": {"$ref": "#/$defs/omission"},
                },
                "runtime": {"$ref": "#/$defs/runtime"},
                "error_code": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^SCIENCE_VISUAL_PILOT_[A-Z0-9_]{3,80}$",
                        },
                        {"type": "null"},
                    ]
                },
                "started_at": UTC,
                "completed_at": UTC,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _pattern_inventory() -> dict[str, Any]:
    schema = _base(
        "EOM Science Corpus Visual Pattern Inventory V1",
        "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.0",
    )
    schema["$defs"].update(
        {
            "review": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "decision",
                    "pattern_family",
                    "visual_features",
                    "caption_en",
                    "caption_sha256",
                    "reviewed_by",
                    "reviewed_at",
                ],
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
                    },
                    "decision": {
                        "enum": [
                            "DETERMINISTIC_RENDERER_ONLY",
                            "EXCLUDED",
                            "LORA_ELIGIBLE",
                        ]
                    },
                    "pattern_family": {
                        "enum": [
                            "APPARATUS",
                            "ASTRONOMICAL_SCENE",
                            "CELL_CROSS_SECTION",
                            "CIRCUIT",
                            "FOSSIL",
                            "GENERIC_LABELLED_DIAGRAM",
                            "GEOLOGIC_SECTION",
                            "GEOLOGIC_TEXTURE",
                            "MAP_BOUNDARY",
                            "MICROSCOPIC_TEXTURE",
                            "NATURAL_TEXTURE",
                            "ORBITAL_SYSTEM",
                            "ORGANISM",
                            "PARTICLE_SYSTEM",
                            "PLOT",
                            "RAY_DIAGRAM",
                            "TABLE",
                            "VECTOR_FIELD",
                            "OTHER",
                        ]
                    },
                    "visual_features": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {"enum": VISUAL_FEATURES},
                    },
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
                    "caption_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                    "reviewed_by": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "pattern": "^[A-Za-z0-9._:@-]+$",
                    },
                    "reviewed_at": UTC,
                },
            },
            "primitive": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "primitive_key",
                    "support_count",
                    "visual_features",
                    "geometry_authority",
                    "render_route",
                ],
                "properties": {
                    "primitive_key": {
                        "enum": [
                            "APPARATUS",
                            "AXIS_PLOT",
                            "CELL_CROSS_SECTION",
                            "CIRCUIT",
                            "GENERIC_LABELLED_DIAGRAM",
                            "GEOLOGIC_SECTION",
                            "MAP_BOUNDARY",
                            "ORBITAL_SYSTEM",
                            "PARTICLE_SYSTEM",
                            "RAY_DIAGRAM",
                            "VECTOR_FIELD",
                        ]
                    },
                    "support_count": {"type": "integer", "minimum": 2, "maximum": 512},
                    "visual_features": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {"enum": VISUAL_FEATURES},
                    },
                    "geometry_authority": {"const": "AUTHORITATIVE"},
                    "render_route": {"const": "PYTHON_SVG"},
                },
            },
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "inventory_id",
                "pilot_result",
                "pilot_result_sha256",
                "reviews",
                "primitive_recommendations",
                "lora_eligible_count",
                "deterministic_renderer_count",
                "excluded_count",
                "created_at",
                "created_by",
                "inventory_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-visual-pattern-inventory/1.0"},
                "inventory_id": {
                    "type": "string",
                    "pattern": "^imgscivisinventory_[0-9a-f]{32}$",
                },
                "pilot_result": {"$ref": "#/$defs/artifactMember"},
                "pilot_result_sha256": {"$ref": "#/$defs/sha256"},
                "reviews": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 512,
                    "items": {"$ref": "#/$defs/review"},
                },
                "primitive_recommendations": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {"$ref": "#/$defs/primitive"},
                },
                "lora_eligible_count": {"type": "integer", "minimum": 0, "maximum": 512},
                "deterministic_renderer_count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 512,
                },
                "excluded_count": {"type": "integer", "minimum": 0, "maximum": 512},
                "created_at": UTC,
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


SCHEMAS = {
    "local-image-science-corpus-training-authorization-v1.schema.json": _authorization(),
    "local-image-science-corpus-visual-pilot-plan-v1.schema.json": _pilot_plan(),
    "local-image-science-corpus-visual-pilot-result-v1.schema.json": _pilot_result(),
    "local-image-science-visual-pattern-inventory-v1.schema.json": _pattern_inventory(),
}


def main() -> None:
    for root in (CANONICAL, PACKAGED):
        root.mkdir(parents=True, exist_ok=True)
        for filename, schema in SCHEMAS.items():
            root.joinpath(filename).write_text(
                json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()

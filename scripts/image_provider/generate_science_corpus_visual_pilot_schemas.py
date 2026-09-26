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


def _pilot_plan_v2() -> dict[str, Any]:
    schema = _pilot_plan()
    schema["title"] = "EOM Science Corpus Visual Pilot Plan V1.1"
    schema["$id"] = "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.1"
    schema["$defs"]["locatorPolicy"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "max_candidates_per_page",
            "max_candidates_per_source",
            "maximum_redaction_area_milli",
            "minimum_interior_ink_milli",
            "maximum_border_ink_fraction_milli",
            "minimum_aspect_ratio_milli",
            "maximum_aspect_ratio_milli",
        ],
        "properties": {
            "max_candidates_per_page": {"type": "integer", "minimum": 1, "maximum": 8},
            "max_candidates_per_source": {"type": "integer", "minimum": 2, "maximum": 32},
            "maximum_redaction_area_milli": {
                "type": "integer",
                "minimum": 0,
                "maximum": 800,
            },
            "minimum_interior_ink_milli": {
                "type": "integer",
                "minimum": 1,
                "maximum": 250,
            },
            "maximum_border_ink_fraction_milli": {
                "type": "integer",
                "minimum": 250,
                "maximum": 1000,
            },
            "minimum_aspect_ratio_milli": {
                "type": "integer",
                "minimum": 50,
                "maximum": 1000,
            },
            "maximum_aspect_ratio_milli": {
                "type": "integer",
                "minimum": 1000,
                "maximum": 20000,
            },
        },
    }
    required = schema["required"]
    assert isinstance(required, list)
    locator_index = required.index("locator_revision")
    required.insert(locator_index + 1, "locator_policy")
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": "local-image-science-corpus-visual-pilot-plan/1.1"}
    properties["locator_revision"] = {"const": "science-corpus-visual-locator/1.1"}
    properties["locator_policy"] = {"$ref": "#/$defs/locatorPolicy"}
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


def _pilot_command() -> dict[str, Any]:
    schema = _base(
        "EOM Science Corpus Visual Pilot Worker Command V1",
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-command/1.0",
    )
    schema["$defs"].update(
        {
            "stagedSource": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "document_id",
                    "staged_pdf_member",
                    "sha256",
                    "bytes",
                    "page_count",
                ],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "pattern": "^sciencedoc_[0-9a-f]{32}$",
                    },
                    "staged_pdf_member": {
                        "type": "string",
                        "pattern": "^input/pdfs/sciencedoc_[0-9a-f]{32}\\.pdf$",
                    },
                    "sha256": {"$ref": "#/$defs/sha256"},
                    "bytes": {
                        "type": "integer",
                        "minimum": 1024,
                        "maximum": 104857600,
                    },
                    "page_count": {"type": "integer", "minimum": 1, "maximum": 512},
                },
            }
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "attempt_id",
                "plan",
                "plan_sha256",
                "staged_plan_member",
                "staged_sources",
                "result_member",
                "requested_at",
                "requested_by",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-corpus-visual-pilot-command/1.0"},
                "attempt_id": {
                    "type": "string",
                    "pattern": "^imgscivisattempt_[0-9a-f]{32}$",
                },
                "plan": {"$ref": "#/$defs/artifactMember"},
                "plan_sha256": {"$ref": "#/$defs/sha256"},
                "staged_plan_member": {"const": "input/visual-pilot-plan.json"},
                "staged_sources": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 96,
                    "items": {"$ref": "#/$defs/stagedSource"},
                },
                "result_member": {"const": "manifests/visual-pilot-result.json"},
                "requested_at": UTC,
                "requested_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _pilot_command_v2() -> dict[str, Any]:
    schema = _pilot_command()
    schema["title"] = "EOM Science Corpus Visual Pilot Worker Command V1.1"
    schema["$id"] = (
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-command/1.1"
    )
    schema["properties"]["schema_version"] = {
        "const": "local-image-science-corpus-visual-pilot-command/1.1"
    }
    return schema


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


def _pattern_inventory_v2() -> dict[str, Any]:
    """Bind the canonical result file and its semantic self-hash separately."""

    schema = _pattern_inventory()
    schema["title"] = "EOM Science Corpus Visual Pattern Inventory V1.1"
    schema["$id"] = "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.1"
    required = schema["required"]
    assert isinstance(required, list)
    result_hash_index = required.index("pilot_result_sha256")
    required[result_hash_index : result_hash_index + 1] = [
        "pilot_result_file_sha256",
        "pilot_result_semantic_sha256",
    ]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": "local-image-science-visual-pattern-inventory/1.1"}
    properties.pop("pilot_result_sha256")
    properties["pilot_result_file_sha256"] = {"$ref": "#/$defs/sha256"}
    properties["pilot_result_semantic_sha256"] = {"$ref": "#/$defs/sha256"}
    return schema


def _reviewed_crop_set() -> dict[str, Any]:
    """Describe the exact reviewed PNG members committed as one immutable file set."""

    schema = _base(
        "EOM Science Corpus Reviewed Visual Crop Set V1",
        "eom://schemas/image-provider/local-image-science-visual-crop-set/1.0",
    )
    schema["$defs"].update(
        {
            "cropMember": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "document_id",
                    "physical_page",
                    "exam_group_sha256",
                    "partition",
                    "pattern_family",
                    "member_path",
                    "media_type",
                    "width_px",
                    "height_px",
                    "size_bytes",
                    "sha256",
                    "caption_en",
                    "caption_sha256",
                    "perceptual_hash",
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
                    "exam_group_sha256": {"$ref": "#/$defs/sha256"},
                    "partition": {"enum": ["HOLDOUT", "TRAIN", "VALIDATION"]},
                    "pattern_family": {
                        "enum": [
                            "ASTRONOMICAL_SCENE",
                            "FOSSIL",
                            "GEOLOGIC_TEXTURE",
                            "MICROSCOPIC_TEXTURE",
                            "NATURAL_TEXTURE",
                            "ORGANISM",
                        ]
                    },
                    "member_path": {
                        "type": "string",
                        "pattern": "^crops/imgsciviscandidate_[0-9a-f]{32}\\.png$",
                    },
                    "media_type": {"const": "image/png"},
                    "width_px": {"type": "integer", "minimum": 16, "maximum": 10000},
                    "height_px": {"type": "integer", "minimum": 16, "maximum": 10000},
                    "size_bytes": {
                        "type": "integer",
                        "minimum": 64,
                        "maximum": 67108864,
                    },
                    "sha256": {"$ref": "#/$defs/sha256"},
                    "caption_en": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 240,
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
                    },
                    "caption_sha256": {"$ref": "#/$defs/sha256"},
                    "perceptual_hash": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
                },
            }
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "crop_set_id",
                "pattern_inventory",
                "pattern_inventory_semantic_sha256",
                "pilot_plan",
                "pilot_plan_sha256",
                "pilot_result",
                "pilot_result_semantic_sha256",
                "training_authorization",
                "members",
                "created_at",
                "created_by",
                "crop_set_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-visual-crop-set/1.0"},
                "crop_set_id": {
                    "type": "string",
                    "pattern": "^imgsciviscropset_[0-9a-f]{32}$",
                },
                "pattern_inventory": {"$ref": "#/$defs/artifactMember"},
                "pattern_inventory_semantic_sha256": {"$ref": "#/$defs/sha256"},
                "pilot_plan": {"$ref": "#/$defs/artifactMember"},
                "pilot_plan_sha256": {"$ref": "#/$defs/sha256"},
                "pilot_result": {"$ref": "#/$defs/artifactMember"},
                "pilot_result_semantic_sha256": {"$ref": "#/$defs/sha256"},
                "training_authorization": {"$ref": "#/$defs/artifactMember"},
                "members": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 96,
                    "items": {"$ref": "#/$defs/cropMember"},
                },
                "created_at": UTC,
                "created_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "crop_set_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _raster_reviewed_crop_set_v2() -> dict[str, Any]:
    """Add the immutable second-pass raster review to the V1 crop-set shape."""

    schema = _reviewed_crop_set()
    schema["title"] = "EOM Science Corpus Raster-Reviewed Visual Crop Set V1.1"
    schema["$id"] = "eom://schemas/image-provider/local-image-science-visual-crop-set/1.1"
    required = schema["required"]
    assert isinstance(required, list)
    inventory_index = required.index("pattern_inventory_semantic_sha256") + 1
    required[inventory_index:inventory_index] = [
        "raster_suitability_review",
        "raster_suitability_review_sha256",
    ]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["schema_version"] = {"const": "local-image-science-visual-crop-set/1.1"}
    properties["raster_suitability_review"] = {"$ref": "#/$defs/artifactMember"}
    properties["raster_suitability_review_sha256"] = {"$ref": "#/$defs/sha256"}
    return schema


def _raster_suitability_review() -> dict[str, Any]:
    """Second-pass audit that narrows broad LoRA eligibility without rewriting history."""

    schema = _base(
        "EOM Science Corpus Raster Suitability Review V1",
        "eom://schemas/image-provider/local-image-science-raster-suitability-review/1.0",
    )
    schema["$defs"].update(
        {
            "rasterSuitabilityEntry": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "decision",
                    "semantic_alignment",
                    "reasons",
                    "caption_en",
                    "caption_sha256",
                ],
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
                    },
                    "decision": {
                        "enum": [
                            "EXCLUDED",
                            "GPU_RASTER_ELIGIBLE",
                            "PYTHON_SVG_REQUIRED",
                        ]
                    },
                    "semantic_alignment": {"enum": ["MISMATCH", "NOT_APPLICABLE", "VERIFIED"]},
                    "reasons": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "enum": [
                                "AUTHORITATIVE_STRUCTURE",
                                "CAPTION_MISMATCH",
                                "INSUFFICIENT_IMAGE_CONTENT",
                                "NON_RASTER_STYLE",
                                "PANEL_COMPOSITION",
                                "REDACTION_OR_MASK",
                                "TEXT_OR_LABEL",
                            ]
                        },
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
                },
            }
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "review_id",
                "pattern_inventory",
                "pattern_inventory_file_sha256",
                "pattern_inventory_semantic_sha256",
                "entries",
                "gpu_raster_eligible_count",
                "python_svg_required_count",
                "excluded_count",
                "reviewed_at",
                "reviewed_by",
                "review_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-raster-suitability-review/1.0"},
                "review_id": {
                    "type": "string",
                    "pattern": "^imgscivisrasterreview_[0-9a-f]{32}$",
                },
                "pattern_inventory": {"$ref": "#/$defs/artifactMember"},
                "pattern_inventory_file_sha256": {"$ref": "#/$defs/sha256"},
                "pattern_inventory_semantic_sha256": {"$ref": "#/$defs/sha256"},
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 512,
                    "items": {"$ref": "#/$defs/rasterSuitabilityEntry"},
                },
                "gpu_raster_eligible_count": {"type": "integer", "minimum": 0, "maximum": 512},
                "python_svg_required_count": {"type": "integer", "minimum": 0, "maximum": 512},
                "excluded_count": {"type": "integer", "minimum": 0, "maximum": 512},
                "reviewed_at": UTC,
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


def _trainer_dependencies(*, runtime: bool = False) -> dict[str, Any]:
    names = [
        "python_version",
        "torch_version",
        "diffusers_version",
        "transformers_version",
        "accelerate_version",
        "peft_version",
        "bitsandbytes_version",
    ]
    if runtime:
        names.extend(["cuda_version", "gpu_name"])
    required: list[str] = list(names)
    properties: dict[str, Any] = {
        name: {"type": "string", "minLength": 1, "maxLength": 128} for name in names
    }
    if runtime:
        required.extend(["compute_capability", "peak_gpu_memory_bytes"])
        properties.update(
            {
                "compute_capability": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
                "peak_gpu_memory_bytes": {"type": "integer", "minimum": 1},
            }
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _micro_hyperparameters() -> dict[str, Any]:
    return {
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
            "max_train_steps": {"const": 200},
            "checkpointing_steps": {"const": 200},
            "random_flip": {"const": False},
            "train_text_encoders": {"const": False},
            "train_vae": {"const": False},
        },
    }


def _science_micro_plan_object() -> dict[str, Any]:
    member_ids = {
        "type": "array",
        "items": {"type": "string", "pattern": "^imgsciviscandidate_[0-9a-f]{32}$"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "probe_id",
            "crop_set",
            "crop_set_sha256",
            "base_model",
            "training_member_ids",
            "validation_member_ids",
            "holdout_member_ids",
            "preprocessing_revision",
            "trainer_contract",
            "dependencies",
            "hyperparameters",
            "seed",
            "purpose",
            "activation_policy",
            "authorized_at",
            "authorized_by",
            "authorization_reference_sha256",
            "created_at",
            "created_by",
            "source_commit",
            "plan_sha256",
        ],
        "properties": {
            "schema_version": {"const": "local-image-science-lora-micro-probe-plan/1.0"},
            "probe_id": {"type": "string", "pattern": "^imgscimicroprobe_[0-9a-f]{32}$"},
            "crop_set": {"$ref": "#/$defs/artifactMember"},
            "crop_set_sha256": {"$ref": "#/$defs/sha256"},
            "base_model": {"$ref": "#/$defs/modelPointer"},
            "training_member_ids": {**member_ids, "minItems": 12, "maxItems": 12},
            "validation_member_ids": {**member_ids, "minItems": 1, "maxItems": 1},
            "holdout_member_ids": {**member_ids, "minItems": 2, "maxItems": 2},
            "preprocessing_revision": {"const": "local-image-science-crop-preprocess/1.0"},
            "trainer_contract": {"const": "eom-local-image-science-lora-micro-trainer/1.0"},
            "dependencies": {"$ref": "#/$defs/dependencies"},
            "hyperparameters": {"$ref": "#/$defs/hyperparameters"},
            "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
            "purpose": {"const": "EVALUATION_ONLY_SCIENCE_MICRO_PROBE"},
            "activation_policy": {"const": "FORBIDDEN"},
            "authorized_at": UTC,
            "authorized_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9._:@-]+$",
            },
            "authorization_reference_sha256": {"$ref": "#/$defs/sha256"},
            "created_at": UTC,
            "created_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9._:@-]+$",
            },
            "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "plan_sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _science_micro_plan() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro-Probe Plan V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-probe-plan/1.0",
    )
    schema["$defs"].update(
        {
            "modelPointer": _model_pointer(),
            "dependencies": _trainer_dependencies(),
            "hyperparameters": _micro_hyperparameters(),
        }
    )
    schema.update(
        {
            key: value
            for key, value in _science_micro_plan_object().items()
            if key not in {"type", "additionalProperties"}
        }
    )
    return schema


def _science_micro_command() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro-Probe Command V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-probe-command/1.0",
    )
    schema["$defs"].update(
        {
            "modelPointer": _model_pointer(),
            "dependencies": _trainer_dependencies(),
            "hyperparameters": _micro_hyperparameters(),
            "plan": _science_micro_plan_object(),
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "probe_plan_pointer",
                "probe_plan_sha256",
                "probe_plan",
                "attempt",
                "staged_plan_member",
                "staged_crop_set_member",
                "staged_crops_root",
                "runtime_dataset_root",
                "output_root_member",
                "checkpoint_root_member",
                "timeout_seconds",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-lora-micro-probe-command/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgscimicrotrainrun_[0-9a-f]{32}$",
                },
                "probe_plan_pointer": {"$ref": "#/$defs/artifactMember"},
                "probe_plan_sha256": {"$ref": "#/$defs/sha256"},
                "probe_plan": {"$ref": "#/$defs/plan"},
                "attempt": {"const": 1},
                "staged_plan_member": {"const": "inputs/science-micro-probe-plan.json"},
                "staged_crop_set_member": {"const": "inputs/science-visual-crop-set.json"},
                "staged_crops_root": {"const": "inputs/crops"},
                "runtime_dataset_root": {"const": "runtime-dataset"},
                "output_root_member": {"const": "outputs"},
                "checkpoint_root_member": {"const": "checkpoints"},
                "timeout_seconds": {"type": "integer", "minimum": 600, "maximum": 14400},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _adapter_file() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["relative_path", "size_bytes", "sha256"],
        "properties": {
            "relative_path": {"enum": ["adapter_config.json", "adapter_model.safetensors"]},
            "size_bytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
            "sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _science_micro_adapter_object() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "adapter_id",
            "adapter_revision_id",
            "state",
            "activation_policy",
            "base_model",
            "probe_plan",
            "sample_set_sha256",
            "files",
            "created_at",
            "manifest_sha256",
        ],
        "properties": {
            "schema_version": {"const": "local-image-science-lora-micro-adapter-manifest/1.0"},
            "adapter_id": {"type": "string", "pattern": "^imgadapter_[0-9a-f]{32}$"},
            "adapter_revision_id": {
                "type": "string",
                "pattern": "^imgadapterrev_[0-9a-f]{32}$",
            },
            "state": {"const": "EVALUATION_ONLY"},
            "activation_policy": {"const": "FORBIDDEN"},
            "base_model": {"$ref": "#/$defs/modelPointer"},
            "probe_plan": {"$ref": "#/$defs/artifactMember"},
            "sample_set_sha256": {"$ref": "#/$defs/sha256"},
            "files": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"$ref": "#/$defs/adapterFile"},
            },
            "created_at": UTC,
            "manifest_sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _science_micro_adapter() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro Adapter Manifest V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-adapter-manifest/1.0",
    )
    schema["$defs"].update({"modelPointer": _model_pointer(), "adapterFile": _adapter_file()})
    schema.update(
        {
            key: value
            for key, value in _science_micro_adapter_object().items()
            if key not in {"type", "additionalProperties"}
        }
    )
    return schema


def _science_micro_worker_result() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro-Probe Worker Result V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-probe-worker-result/1.0",
    )
    schema["$defs"].update(
        {
            "modelPointer": _model_pointer(),
            "adapterFile": _adapter_file(),
            "adapter": _science_micro_adapter_object(),
            "runtime": _trainer_dependencies(runtime=True),
            "realizedSample": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "document_id",
                    "exam_group_sha256",
                    "training_sample_id",
                    "source_crop_sha256",
                    "realized_crop_sha256",
                    "caption_sha256",
                    "perceptual_hash",
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
                    "exam_group_sha256": {"$ref": "#/$defs/sha256"},
                    "training_sample_id": {
                        "type": "string",
                        "pattern": "^imgtrainsample_[0-9a-f]{32}$",
                    },
                    "source_crop_sha256": {"$ref": "#/$defs/sha256"},
                    "realized_crop_sha256": {"$ref": "#/$defs/sha256"},
                    "caption_sha256": {"$ref": "#/$defs/sha256"},
                    "perceptual_hash": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
                },
            },
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "training_run_id",
                "probe_plan_pointer",
                "probe_plan_sha256",
                "command_sha256",
                "attempt",
                "status",
                "adapter_manifest",
                "realized_samples",
                "sample_set_sha256",
                "error_code",
                "runtime",
                "completed_steps",
                "final_loss",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-lora-micro-probe-worker-result/1.0"
                },
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgscimicrotrainrun_[0-9a-f]{32}$",
                },
                "probe_plan_pointer": {"$ref": "#/$defs/artifactMember"},
                "probe_plan_sha256": {"$ref": "#/$defs/sha256"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "attempt": {"const": 1},
                "status": {"enum": ["SUCCEEDED", "FAILED", "CANCELLED"]},
                "adapter_manifest": {"anyOf": [{"$ref": "#/$defs/adapter"}, {"type": "null"}]},
                "realized_samples": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 12,
                    "items": {"$ref": "#/$defs/realizedSample"},
                },
                "sample_set_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                "error_code": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^IMAGE_TRAINING_[A-Z0-9_]{3,96}$",
                        },
                        {"type": "null"},
                    ]
                },
                "runtime": {"anyOf": [{"$ref": "#/$defs/runtime"}, {"type": "null"}]},
                "completed_steps": {"type": "integer", "minimum": 0, "maximum": 200},
                "final_loss": {
                    "anyOf": [
                        {"type": "number", "minimum": 0, "maximum": 1000000},
                        {"type": "null"},
                    ]
                },
                "started_at": UTC,
                "completed_at": UTC,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "adapter_manifest": {"$ref": "#/$defs/adapter"},
                            "realized_samples": {"minItems": 12, "maxItems": 12},
                            "sample_set_sha256": {"$ref": "#/$defs/sha256"},
                            "error_code": {"type": "null"},
                            "runtime": {"$ref": "#/$defs/runtime"},
                            "completed_steps": {"const": 200},
                            "final_loss": {"type": "number", "minimum": 0},
                        }
                    },
                    "else": {
                        "properties": {
                            "adapter_manifest": {"type": "null"},
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


def _science_micro_evaluation_case() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "document_id",
            "exam_group_sha256",
            "positive_prompt",
            "positive_prompt_sha256",
            "negative_prompt",
            "negative_prompt_sha256",
            "seed",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
            },
            "document_id": {"type": "string", "pattern": "^sciencedoc_[0-9a-f]{32}$"},
            "exam_group_sha256": {"$ref": "#/$defs/sha256"},
            "positive_prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
            "positive_prompt_sha256": {"$ref": "#/$defs/sha256"},
            "negative_prompt": {"type": "string", "minLength": 1, "maxLength": 2000},
            "negative_prompt_sha256": {"$ref": "#/$defs/sha256"},
            "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
        },
    }


def _science_micro_evaluation_command() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro Evaluation Command V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-evaluation-command/1.0",
    )
    schema["$defs"].update(
        {
            "modelPointer": _model_pointer(),
            "adapterFile": _adapter_file(),
            "adapter": _science_micro_adapter_object(),
            "case": _science_micro_evaluation_case(),
        }
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "evaluation_run_id",
                "training_run_id",
                "probe_plan_pointer",
                "probe_plan_sha256",
                "crop_set",
                "crop_set_sha256",
                "training_result_sha256",
                "adapter_manifest",
                "cases",
                "inference_steps",
                "guidance_scale",
                "generation_width",
                "generation_height",
                "delivery_width",
                "delivery_height",
                "staged_adapter_root",
                "output_root_member",
                "source_commit",
                "timeout_seconds",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {
                    "const": "local-image-science-lora-micro-evaluation-command/1.0"
                },
                "evaluation_run_id": {
                    "type": "string",
                    "pattern": "^imgscimicroevalrun_[0-9a-f]{32}$",
                },
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgscimicrotrainrun_[0-9a-f]{32}$",
                },
                "probe_plan_pointer": {"$ref": "#/$defs/artifactMember"},
                "probe_plan_sha256": {"$ref": "#/$defs/sha256"},
                "crop_set": {"$ref": "#/$defs/artifactMember"},
                "crop_set_sha256": {"$ref": "#/$defs/sha256"},
                "training_result_sha256": {"$ref": "#/$defs/sha256"},
                "adapter_manifest": {"$ref": "#/$defs/adapter"},
                "cases": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"$ref": "#/$defs/case"},
                },
                "inference_steps": {"const": 20},
                "guidance_scale": {"const": 7.5},
                "generation_width": {"const": 800},
                "generation_height": {"const": 504},
                "delivery_width": {"const": 800},
                "delivery_height": {"const": 500},
                "staged_adapter_root": {"const": "inputs/adapter"},
                "output_root_member": {"const": "outputs"},
                "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "timeout_seconds": {"type": "integer", "minimum": 600, "maximum": 3600},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _science_micro_evaluation_result() -> dict[str, Any]:
    schema = _base(
        "EOM Science Visual LoRA Micro Evaluation Result V1",
        "eom://schemas/image-provider/local-image-science-lora-micro-evaluation-result/1.0",
    )
    output = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "variant",
            "member_path",
            "sha256",
            "size_bytes",
            "width_px",
            "height_px",
        ],
        "properties": {
            "candidate_id": {
                "type": "string",
                "pattern": "^imgsciviscandidate_[0-9a-f]{32}$",
            },
            "variant": {"enum": ["ADAPTER", "BASE"]},
            "member_path": {
                "type": "string",
                "pattern": ("^outputs/imgsciviscandidate_[0-9a-f]{32}-(adapter|base)\\.png$"),
            },
            "sha256": {"$ref": "#/$defs/sha256"},
            "size_bytes": {"type": "integer", "minimum": 64, "maximum": 67108864},
            "width_px": {"const": 800},
            "height_px": {"const": 500},
        },
    }
    schema.update(
        {
            "required": [
                "schema_version",
                "evaluation_run_id",
                "command_sha256",
                "training_result_sha256",
                "adapter_manifest_sha256",
                "status",
                "outputs",
                "error_code",
                "started_at",
                "completed_at",
                "result_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-science-lora-micro-evaluation-result/1.0"},
                "evaluation_run_id": {
                    "type": "string",
                    "pattern": "^imgscimicroevalrun_[0-9a-f]{32}$",
                },
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "training_result_sha256": {"$ref": "#/$defs/sha256"},
                "adapter_manifest_sha256": {"$ref": "#/$defs/sha256"},
                "status": {"enum": ["SUCCEEDED", "FAILED"]},
                "outputs": {"type": "array", "maxItems": 4, "items": output},
                "error_code": {
                    "anyOf": [
                        {
                            "type": "string",
                            "pattern": "^IMAGE_EVALUATION_[A-Z0-9_]{3,96}$",
                        },
                        {"type": "null"},
                    ]
                },
                "started_at": UTC,
                "completed_at": UTC,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "outputs": {"minItems": 4, "maxItems": 4},
                            "error_code": {"type": "null"},
                        }
                    },
                    "else": {
                        "properties": {
                            "error_code": {
                                "type": "string",
                                "pattern": "^IMAGE_EVALUATION_[A-Z0-9_]{3,96}$",
                            }
                        }
                    },
                }
            ],
        }
    )
    return schema


SCHEMAS = {
    "local-image-science-corpus-training-authorization-v1.schema.json": _authorization(),
    "local-image-science-corpus-visual-pilot-plan-v1.schema.json": _pilot_plan(),
    "local-image-science-corpus-visual-pilot-plan-v2.schema.json": _pilot_plan_v2(),
    "local-image-science-corpus-visual-pilot-command-v1.schema.json": _pilot_command(),
    "local-image-science-corpus-visual-pilot-command-v2.schema.json": _pilot_command_v2(),
    "local-image-science-corpus-visual-pilot-result-v1.schema.json": _pilot_result(),
    "local-image-science-visual-pattern-inventory-v1.schema.json": _pattern_inventory(),
    "local-image-science-visual-pattern-inventory-v2.schema.json": _pattern_inventory_v2(),
    "local-image-science-visual-crop-set-v1.schema.json": _reviewed_crop_set(),
    "local-image-science-visual-crop-set-v2.schema.json": _raster_reviewed_crop_set_v2(),
    "local-image-science-raster-suitability-review-v1.schema.json": _raster_suitability_review(),
    "local-image-science-lora-micro-probe-plan-v1.schema.json": _science_micro_plan(),
    "local-image-science-lora-micro-probe-command-v1.schema.json": _science_micro_command(),
    "local-image-science-lora-micro-adapter-manifest-v1.schema.json": _science_micro_adapter(),
    "local-image-science-lora-micro-probe-worker-result-v1.schema.json": (
        _science_micro_worker_result()
    ),
    "local-image-science-lora-micro-evaluation-command-v1.schema.json": (
        _science_micro_evaluation_command()
    ),
    "local-image-science-lora-micro-evaluation-result-v1.schema.json": (
        _science_micro_evaluation_result()
    ),
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

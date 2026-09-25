#!/usr/bin/env python3
"""Generate canonical and wheel-mirrored local-image LoRA micro-probe contracts."""

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


def _defs() -> dict[str, Any]:
    return {
        "sha256": SHA,
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
                    "minLength": 3,
                    "maxLength": 512,
                    "pattern": (
                        "^(?!/)(?!.*\\\\)[^\\u0000-\\u001f\\u007f]+/[^\\u0000-\\u001f\\u007f]+$"
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
        "runtime": {
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
        },
        "adapterFile": {
            "type": "object",
            "additionalProperties": False,
            "required": ["relative_path", "size_bytes", "sha256"],
            "properties": {
                "relative_path": {"enum": ["adapter_config.json", "adapter_model.safetensors"]},
                "size_bytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
                "sha256": {"$ref": "#/$defs/sha256"},
            },
        },
    }


def _base(identifier: str, title: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": identifier,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "$defs": _defs(),
    }


def _selection() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_anchor_id", "crop_proposal_id", "caption_en", "caption_sha256"],
        "properties": {
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "crop_proposal_id": {
                "type": "string",
                "pattern": "^imgcropproposal_[0-9a-f]{32}$",
            },
            "caption_en": {
                "type": "string",
                "minLength": 3,
                "maxLength": 180,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
            },
            "caption_sha256": {"$ref": "#/$defs/sha256"},
        },
    }


def _hyperparameters() -> dict[str, Any]:
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


def _plan() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-micro-probe-plan/1.0",
        "EOM Local Image LoRA Micro Probe Plan V1",
    )
    schema.update(
        {
            "required": [
                "schema_version",
                "probe_id",
                "source_snapshot",
                "training_authorization",
                "crop_proposal_set",
                "crop_proposal_set_sha256",
                "holdout_evaluation_plan",
                "holdout_sample_ids",
                "holdout_source_anchor_ids",
                "base_model",
                "preprocessing_revision",
                "selections",
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
                "schema_version": {"const": "local-image-lora-micro-probe-plan/1.0"},
                "probe_id": {"type": "string", "pattern": "^imgmicroprobe_[0-9a-f]{32}$"},
                "source_snapshot": {"$ref": "#/$defs/sourceSnapshot"},
                "training_authorization": {"$ref": "#/$defs/artifactPointer"},
                "crop_proposal_set": {"$ref": "#/$defs/artifactPointer"},
                "crop_proposal_set_sha256": {"$ref": "#/$defs/sha256"},
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
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "preprocessing_revision": {"const": "local-image-micro-crop-preprocess/1.0"},
                "selections": {
                    "type": "array",
                    "minItems": 12,
                    "maxItems": 18,
                    "items": _selection(),
                },
                "trainer_contract": {"const": "eom-local-image-lora-micro-trainer/1.0"},
                "dependencies": {"$ref": "#/$defs/dependencies"},
                "hyperparameters": _hyperparameters(),
                "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                "purpose": {"const": "EVALUATION_ONLY_MICRO_PROBE"},
                "activation_policy": {"const": "FORBIDDEN"},
                "authorized_at": DATE_TIME,
                "authorized_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._:@-]+$",
                },
                "authorization_reference_sha256": {"$ref": "#/$defs/sha256"},
                "created_at": DATE_TIME,
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
    )
    return schema


def _command() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-micro-probe-command/1.0",
        "EOM Local Image LoRA Micro Probe Command V1",
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
                "staged_authorization_member",
                "staged_proposal_set_member",
                "staged_pages_root",
                "runtime_dataset_root",
                "output_root_member",
                "checkpoint_root_member",
                "timeout_seconds",
                "command_sha256",
            ],
            "properties": {
                "schema_version": {"const": "local-image-lora-micro-probe-command/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgmicrotrainrun_[0-9a-f]{32}$",
                },
                "probe_plan_pointer": {"$ref": "#/$defs/artifactPointer"},
                "probe_plan_sha256": {"$ref": "#/$defs/sha256"},
                "probe_plan": {
                    "$ref": "eom://schemas/image-provider/local-image-lora-micro-probe-plan/1.0"
                },
                "attempt": {"const": 1},
                "staged_plan_member": {"const": "inputs/micro-probe-plan.json"},
                "staged_authorization_member": {"const": "inputs/training-authorization.json"},
                "staged_proposal_set_member": {"const": "inputs/crop-proposals.json"},
                "staged_pages_root": {"const": "inputs/pages"},
                "runtime_dataset_root": {"const": "runtime-dataset"},
                "output_root_member": {"const": "outputs"},
                "checkpoint_root_member": {"const": "checkpoints"},
                "timeout_seconds": {"type": "integer", "minimum": 600, "maximum": 14400},
                "command_sha256": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    return schema


def _adapter_manifest() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-micro-adapter-manifest/1.0",
        "EOM Local Image LoRA Micro Adapter Manifest V1",
    )
    schema.update(
        {
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
                "schema_version": {"const": "local-image-lora-micro-adapter-manifest/1.0"},
                "adapter_id": {"type": "string", "pattern": "^imgadapter_[0-9a-f]{32}$"},
                "adapter_revision_id": {
                    "type": "string",
                    "pattern": "^imgadapterrev_[0-9a-f]{32}$",
                },
                "state": {"const": "EVALUATION_ONLY"},
                "activation_policy": {"const": "FORBIDDEN"},
                "base_model": {"$ref": "#/$defs/modelPointer"},
                "probe_plan": {"$ref": "#/$defs/artifactPointer"},
                "sample_set_sha256": {"$ref": "#/$defs/sha256"},
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


def _worker_result() -> dict[str, Any]:
    schema = _base(
        "eom://schemas/image-provider/local-image-lora-micro-probe-worker-result/1.0",
        "EOM Local Image LoRA Micro Probe Worker Result V1",
    )
    realized = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_anchor_id",
            "crop_proposal_id",
            "training_sample_id",
            "crop_sha256",
            "caption_sha256",
            "perceptual_hash",
        ],
        "properties": {
            "source_anchor_id": {
                "type": "string",
                "pattern": "^assessmentanchor_[0-9a-f]{32}$",
            },
            "crop_proposal_id": {
                "type": "string",
                "pattern": "^imgcropproposal_[0-9a-f]{32}$",
            },
            "training_sample_id": {
                "type": "string",
                "pattern": "^imgtrainsample_[0-9a-f]{32}$",
            },
            "crop_sha256": {"$ref": "#/$defs/sha256"},
            "caption_sha256": {"$ref": "#/$defs/sha256"},
            "perceptual_hash": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
        },
    }
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
                "schema_version": {"const": "local-image-lora-micro-probe-worker-result/1.0"},
                "training_run_id": {
                    "type": "string",
                    "pattern": "^imgmicrotrainrun_[0-9a-f]{32}$",
                },
                "probe_plan_pointer": {"$ref": "#/$defs/artifactPointer"},
                "probe_plan_sha256": {"$ref": "#/$defs/sha256"},
                "command_sha256": {"$ref": "#/$defs/sha256"},
                "attempt": {"const": 1},
                "status": {"enum": ["SUCCEEDED", "FAILED", "CANCELLED"]},
                "adapter_manifest": {
                    "anyOf": [
                        {
                            "$ref": (
                                "eom://schemas/image-provider/"
                                "local-image-lora-micro-adapter-manifest/1.0"
                            )
                        },
                        {"type": "null"},
                    ]
                },
                "realized_samples": {
                    "type": "array",
                    "maxItems": 18,
                    "items": realized,
                },
                "sample_set_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                "error_code": {
                    "anyOf": [
                        {"type": "string", "pattern": "^IMAGE_TRAINING_[A-Z0-9_]{3,96}$"},
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
                "started_at": DATE_TIME,
                "completed_at": DATE_TIME,
                "result_sha256": {"$ref": "#/$defs/sha256"},
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "adapter_manifest": {
                                "$ref": (
                                    "eom://schemas/image-provider/"
                                    "local-image-lora-micro-adapter-manifest/1.0"
                                )
                            },
                            "realized_samples": {"minItems": 12},
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


SCHEMAS = {
    "local-image-lora-micro-probe-plan-v1.schema.json": _plan(),
    "local-image-lora-micro-probe-command-v1.schema.json": _command(),
    "local-image-lora-micro-adapter-manifest-v1.schema.json": _adapter_manifest(),
    "local-image-lora-micro-probe-worker-result-v1.schema.json": _worker_result(),
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
                    raise SystemExit(f"schema drift: {path}")
            else:
                path.write_bytes(payload)


if __name__ == "__main__":
    main()

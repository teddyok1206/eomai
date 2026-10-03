from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageScienceObjectLineArtCropSet,
    LocalImageSdxlLoraMicroAdapterManifest,
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlLoraMicroResult,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_sdxl_lora_micro_result,
    validate_sdxl_lora_micro_sources,
)
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_science_corpus_visual_contracts import _object_line_art_values
from tests.unit.test_sdxl_lineart_stack_contract import _stack


def _seal_command(value):
    value["training_run_id"] = (
        "imgsdxlmicrotrainrun_"
        + content_sha256(
            {
                name: item
                for name, item in value.items()
                if name not in {"training_run_id", "command_sha256"}
            }
        )[7:39]
    )
    value["command_sha256"] = content_sha256(
        {name: item for name, item in value.items() if name != "command_sha256"}
    )
    return value


def _command_value():
    *_, crops = _object_line_art_values()
    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(crops)
    pointer = {
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "member_path": "manifests/science-object-line-art-crop-set.json",
        "schema_ref": "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0",
        "media_type": "application/json",
        "sha256": content_sha256(crops),
    }
    stack = _stack()
    value = {
        "schema_version": "local-image-sdxl-lora-micro-command/1.0",
        "created_at": "2026-10-03T18:40:00Z",
        "created_by": "fixture.operator",
        "source_commit": "a" * 40,
        "base_model": {
            key: stack[key]
            for key in (
                "model_id",
                "model_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            )
        },
        "crop_set": pointer,
        "crop_set_semantic_sha256": crops["crop_set_sha256"],
        "training_authorization": crops["training_authorization"],
        "experiment_authorization": {
            "approved_at": "2026-10-03T18:35:22Z",
            "approved_by": "fixture.operator",
            "approval_message_sha256": text_sha256("synthetic approval fixture"),
            "permitted_uses": ["INTERNAL_SDXL_COMPARISON", "INTERNAL_SDXL_LORA_TRAINING"],
            "external_export": "FORBIDDEN",
            "automatic_activation": "FORBIDDEN",
        },
        "training_samples": [
            {
                "sample_id": member.sample_id,
                "source_image": {
                    **pointer,
                    "member_path": member.member_path,
                    "schema_ref": "eom://schemas/image-provider/local-image-science-visual-crop/1.0",
                    "media_type": "image/png",
                    "sha256": member.sha256,
                },
                "source_width_px": member.width_px,
                "source_height_px": member.height_px,
                "source_caption_en": member.caption_en,
                "source_caption_sha256": member.caption_sha256,
                "redaction_boxes": [],
            }
            for member in crop_set.members
            if member.partition == "TRAIN"
        ],
        "validation_sample_ids": [
            member.sample_id for member in crop_set.members if member.partition == "VALIDATION"
        ],
        "holdout_sample_ids": [
            member.sample_id for member in crop_set.members if member.partition == "HOLDOUT"
        ],
        "caption_policy": "SOURCE_CAPTION_WITH_EXAM_STYLE_TRIGGER/1.0",
        "preprocessing_policy": "GRAYSCALE_REDACT_FIT_768X512/1.0",
        "dependencies": {
            "python_version": "3.11.13",
            "torch_version": "2.7.1+cu128",
            "diffusers_version": "0.35.2",
            "transformers_version": "4.56.2",
            "accelerate_version": "1.10.1",
            "peft_version": "0.17.1",
            "bitsandbytes_version": "0.47.0",
        },
        "hyperparameters": {
            "adapter_type": "UNET_LORA",
            "rank": 8,
            "alpha": 8,
            "resolution_width": 768,
            "resolution_height": 512,
            "train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "gradient_checkpointing": True,
            "mixed_precision": "fp16",
            "optimizer": "adamw_8bit",
            "learning_rate": "1e-4",
            "max_train_steps": 200,
            "checkpointing_steps": 200,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
        "seed": 17,
        "purpose": "EVALUATION_ONLY_SDXL_OBJECT_LINE_ART_MICRO",
        "activation_policy": "FORBIDDEN",
    }
    return _seal_command(value), crop_set


def _seal_adapter(value):
    value["adapter_id"] = (
        "imgadapter_"
        + content_sha256({"training_command_sha256": value["training_command_sha256"]})[7:39]
    )
    value["adapter_revision_id"] = (
        "imgadapterrev_"
        + content_sha256({key: value[key] for key in ("adapter_id", "base_model", "files")})[7:39]
    )
    value["manifest_sha256"] = content_sha256(
        {name: item for name, item in value.items() if name != "manifest_sha256"}
    )
    return value


def _result_value(command):
    realized = [
        {
            "sample_id": sample.sample_id,
            "source_crop_sha256": sample.source_image.sha256,
            "realized_crop_sha256": text_sha256("realized " + sample.sample_id),
            "training_caption_sha256": text_sha256(sample.training_caption_en),
        }
        for sample in command.training_samples
    ]
    sample_set_sha256 = content_sha256(realized)
    manifest = _seal_adapter(
        {
            "schema_version": "local-image-sdxl-lora-micro-adapter-manifest/1.0",
            "state": "EVALUATION_ONLY",
            "activation_policy": "FORBIDDEN",
            "base_model": command.base_model.model_dump(mode="json"),
            "training_command_sha256": command.command_sha256,
            "sample_set_sha256": sample_set_sha256,
            "files": [
                {"relative_path": name, "size_bytes": 100, "sha256": text_sha256(name)}
                for name in ("adapter_config.json", "adapter_model.safetensors")
            ],
            "created_at": "2026-10-03T18:41:00Z",
        }
    )
    value = {
        "schema_version": "local-image-sdxl-lora-micro-result/1.0",
        "training_run_id": command.training_run_id,
        "command_sha256": command.command_sha256,
        "status": "SUCCEEDED",
        "error_code": None,
        "adapter_manifest": manifest,
        "realized_samples": realized,
        "sample_set_sha256": sample_set_sha256,
        "runtime": {
            **command.dependencies.model_dump(mode="json"),
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 1000,
        },
        "completed_steps": 200,
        "final_loss": 0.5,
        "started_at": "2026-10-03T18:40:00Z",
        "completed_at": "2026-10-03T18:41:01Z",
        "duration_ms": 1000,
    }
    value["result_sha256"] = content_sha256(value)
    return value


def _reseal_result(value):
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


def test_sdxl_micro_contracts_are_additive_pinned_frozen_and_source_complete():
    value, crops = _command_value()
    command = LocalImageSdxlLoraMicroCommand.model_validate(value)
    validate_sdxl_lora_micro_sources(command, crops)
    result = LocalImageSdxlLoraMicroResult.model_validate(_result_value(command))
    validate_sdxl_lora_micro_result(command, result)
    assert command.hyperparameters.max_train_steps == 200
    assert command.base_model.provider_family == "diffusers-sdxl-t2i-lineart"
    assert result.adapter_manifest.state == "EVALUATION_ONLY"
    with pytest.raises(ValidationError, match="frozen"):
        command.seed = 44


def test_canonical_and_wheel_schema_resources_are_complete_identical_and_hash_pinned():
    value, _crops = _command_value()
    command = LocalImageSdxlLoraMicroCommand.model_validate(value)
    result = _result_value(command)
    root = Path(__file__).resolve().parents[2]
    for family, document in (
        ("command", value),
        ("result", result),
        ("adapter-manifest", result["adapter_manifest"]),
    ):
        name = "sdxl-lora-micro-" + family
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        validate_contract(name, document)
        filename = f"local-image-sdxl-lora-micro-{family}-v1.schema.json"
        raw = (root / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert SCHEMA_SHA256[name] == "sha256:" + hashlib.sha256(raw).hexdigest()
        for script in (
            "scripts/image_provider/build_release.sh",
            "scripts/image_trainer/build_release.sh",
            "scripts/api/deploy_release.sh",
        ):
            assert filename in (root / script).read_text()


@pytest.mark.parametrize(
    "fault",
    [
        "ssd",
        "permission",
        "future_approval",
        "activation",
        "overlap",
        "order",
        "revision",
        "source_path",
        "rank",
        "duration",
        "memory",
        "hash",
        "identity",
    ],
)
def test_invalid_micro_commands_cannot_reinterpret_ssd_or_reserved_data(fault):
    value, _crops = _command_value()
    if fault == "ssd":
        value["base_model"]["provider_family"] = "diffusers-ssd-1b"
    elif fault == "permission":
        value["experiment_authorization"]["permitted_uses"] = ["INTERNAL_SDXL_COMPARISON"]
    elif fault == "future_approval":
        value["experiment_authorization"]["approved_at"] = "2026-10-04T18:35:22Z"
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "overlap":
        value["holdout_sample_ids"][0] = value["training_samples"][0]["sample_id"]
        value["holdout_sample_ids"].sort()
    elif fault == "order":
        value["training_samples"].reverse()
    elif fault == "revision":
        value["training_samples"][0]["source_image"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif fault == "source_path":
        value["training_samples"][0]["source_image"]["member_path"] = "../untrusted.png"
    elif fault == "rank":
        value["hyperparameters"]["rank"] = 16
    elif fault == "duration":
        value["budget"]["maximum_duration_ms"] = 3_600_001
    elif fault == "memory":
        value["budget"]["maximum_peak_gpu_memory_bytes"] = 16 * 1024**3 + 1
    _seal_command(value)
    if fault == "hash":
        value["command_sha256"] = "sha256:" + "f" * 64
    if fault == "identity":
        value["training_run_id"] = "imgsdxlmicrotrainrun_" + "f" * 32
    with pytest.raises(ValidationError):
        LocalImageSdxlLoraMicroCommand.model_validate(value)


@pytest.mark.parametrize(
    "fault", ["caption", "width", "image_hash", "partition", "authorization", "semantic"]
)
def test_micro_training_sources_must_match_reviewed_crop_revision(fault):
    value, crops = _command_value()
    if fault == "caption":
        sample = value["training_samples"][0]
        sample["source_caption_en"] = "unreviewed content added to this source caption"
        sample["source_caption_sha256"] = text_sha256(sample["source_caption_en"])
    elif fault == "width":
        value["training_samples"][0]["source_width_px"] += 1
    elif fault == "image_hash":
        value["training_samples"][0]["source_image"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        value["validation_sample_ids"], value["holdout_sample_ids"] = (
            value["holdout_sample_ids"],
            value["validation_sample_ids"],
        )
    elif fault == "authorization":
        value["training_authorization"]["artifact_revision_id"] = "rev_" + "f" * 32
    else:
        value["crop_set_semantic_sha256"] = "sha256:" + "f" * 64
    command = LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value))
    with pytest.raises(ValueError):
        validate_sdxl_lora_micro_sources(command, crops)


@pytest.mark.parametrize(
    "fault",
    [
        "steps",
        "failed_adapter",
        "missing_runtime",
        "wrong_command",
        "source_hash",
        "caption_hash",
        "dependency",
        "duration",
        "memory",
        "base_revision",
    ],
)
def test_micro_success_requires_exact_training_and_resource_evidence(fault):
    value, _crops = _command_value()
    command = LocalImageSdxlLoraMicroCommand.model_validate(value)
    result = _result_value(command)
    if fault == "steps":
        result["completed_steps"] = 199
    elif fault == "failed_adapter":
        result["status"], result["error_code"] = "FAILED", "IMAGE_TRAINING_EXEC_FAILED"
    elif fault == "missing_runtime":
        result["runtime"] = None
    elif fault == "wrong_command":
        result["training_run_id"] = "imgsdxlmicrotrainrun_" + "f" * 32
    elif fault in {"source_hash", "caption_hash"}:
        sample = result["realized_samples"][0]
        sample["source_crop_sha256" if fault == "source_hash" else "training_caption_sha256"] = (
            "sha256:" + "f" * 64
        )
        result["sample_set_sha256"] = content_sha256(result["realized_samples"])
        result["adapter_manifest"]["sample_set_sha256"] = result["sample_set_sha256"]
        _seal_adapter(result["adapter_manifest"])
    elif fault == "dependency":
        result["runtime"]["diffusers_version"] = "unexpected.version"
    elif fault == "duration":
        result["duration_ms"] = command.budget.maximum_duration_ms + 1
    elif fault == "memory":
        result["runtime"]["peak_gpu_memory_bytes"] = (
            command.budget.maximum_peak_gpu_memory_bytes + 1
        )
    elif fault == "base_revision":
        result["adapter_manifest"]["base_model"]["model_revision_id"] = "imgmodelrev_" + "f" * 32
        _seal_adapter(result["adapter_manifest"])
    with pytest.raises(ValueError):
        parsed = LocalImageSdxlLoraMicroResult.model_validate(_reseal_result(result))
        validate_sdxl_lora_micro_result(command, parsed)


def test_adapter_revision_binds_files_independently_of_logical_identity():
    value, _crops = _command_value()
    command = LocalImageSdxlLoraMicroCommand.model_validate(value)
    manifest = _result_value(command)["adapter_manifest"]
    original = LocalImageSdxlLoraMicroAdapterManifest.model_validate(manifest)
    changed = copy.deepcopy(manifest)
    changed["files"][1]["sha256"] = "sha256:" + "f" * 64
    successor = LocalImageSdxlLoraMicroAdapterManifest.model_validate(_seal_adapter(changed))
    assert successor.adapter_id == original.adapter_id
    assert successor.adapter_revision_id != original.adapter_revision_id
    assert successor.manifest_sha256 != original.manifest_sha256

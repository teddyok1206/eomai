"""Closed native training contracts; synthetic acceptance is not image quality."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageSdxlLoraMicroAdapterManifest,
    LocalImageSdxlLoraMicroCommand,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommand,
    LocalImageSdxlNativeLoraResult,
    SdxlNativeLoraConditioning,
    validate_sdxl_native_lora_result,
)
from eom_image_contracts.sdxl_native_training_targets import NATIVE_TARGET_CANVASES
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.test_sdxl_lora_micro_contracts import (
    _command_value as _micro_value,
)
from tests.unit.test_sdxl_lora_micro_contracts import (
    _result_value as _micro_result,
)
from tests.unit.test_sdxl_lora_micro_contracts import (
    _seal_adapter,
)


def _seal_command(value):
    identity = content_sha256(
        {k: v for k, v in value.items() if k not in {"training_run_id", "command_sha256"}}
    )
    value["training_run_id"] = "imgsdxlnativetrainrun_" + identity[7:39]
    value["command_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "command_sha256"}
    )
    return value


def _command_value(count=12, profile="NATIVE_RESOLUTION_PILOT", steps=None):
    legacy, _ = _micro_value()
    prefix = "eom://schemas/image-provider/local-image-"
    batches, samples = [], []
    for index in range((count + 31) // 32):
        result = {
            "artifact_id": "artifact_" + f"{index + 100:032x}",
            "artifact_revision_id": "rev_" + f"{index + 100:032x}",
            "member_path": "manifests/sdxl-training-target-result.json",
            "schema_ref": prefix + "sdxl-training-target-result/1.2",
            "media_type": "application/json",
            "sha256": text_sha256(f"native target result {index}"),
        }
        batches.append(
            {
                "result": result,
                "command": {
                    **result,
                    "artifact_id": "artifact_" + f"{index + 200:032x}",
                    "member_path": "manifests/sdxl-training-target-command.json",
                    "schema_ref": prefix + "sdxl-training-target-command/1.2",
                    "sha256": text_sha256(f"native target command {index}"),
                },
            }
        )
    for index in range(count):
        target_id = "imgsdxltarget_" + f"{index + 1:032x}"
        conditioning = SdxlNativeLoraConditioning(
            literal_subject=f"A complete synthetic scientific object {index}",
            expression=("CLEAN_CONTOUR", "RESTRAINED_TONE", "FINE_HATCHING")[index % 3],
            composition="AUTHORED_SCENE" if index % 2 else "ISOLATED_ON_WHITE",
        )
        samples.append(
            {
                "sample_id": "imgsourcecrop_" + f"{index + 1:032x}",
                "target_id": target_id,
                "target_revision_id": "imgsdxltargetrev_" + f"{index + 1:032x}",
                "source_image": {
                    **batches[index // 32]["result"],
                    "member_path": f"targets/{target_id}.png",
                    "schema_ref": prefix + "sdxl-training-target-png/1.1",
                    "media_type": "image/png",
                    "sha256": text_sha256(f"distinct target pixels {index}"),
                },
                "source_document_id": "sciencedoc_" + f"{index // 2 + 1:032x}",
                "exam_group_sha256": text_sha256(f"exam group {index // 3}"),
                "canvas": tuple(NATIVE_TARGET_CANVASES)[index % 3],
                "conditioning": conditioning.model_dump(mode="json"),
                "training_caption_sha256": text_sha256(conditioning.training_caption_en),
            }
        )
    value = {
        **{
            k: legacy[k]
            for k in (
                "created_at",
                "created_by",
                "source_commit",
                "base_model",
                "training_authorization",
                "experiment_authorization",
                "dependencies",
                "seed",
            )
        },
        "schema_version": "local-image-sdxl-native-lora-command/1.0",
        "target_batches": batches,
        "training_samples": samples,
        "profile": profile,
        "review_scope": "OWN_TRAIN_COHORT_SCREENING_NOT_INDEPENDENT",
        "screening_evidence": {
            **legacy["training_authorization"],
            "member_path": "reports/native-cohort-screening.md",
            "schema_ref": "eom://schemas/operations/plain-text-log/1.0",
            "media_type": "text/plain",
            "sha256": text_sha256("own synthetic cohort screening"),
        },
        "reviewed_at": "2026-10-03T18:39:00Z",
        "reviewed_by": "fixture.operator",
        "caption_policy": "REVIEWED_SUBJECT_EXPRESSION_COMPOSITION/1.0",
        "preprocessing_policy": "EXACT_ADMITTED_PREPARED_NATIVE_RGB/1.0",
        "checkpoint_policy": "TERMINAL_ONLY_NO_RESUME/1.0",
        "hyperparameters": {
            **{
                k: v
                for k, v in legacy["hyperparameters"].items()
                if k not in {"resolution_width", "resolution_height"}
            },
            "max_train_steps": steps
            if steps is not None
            else (20 if profile == "NATIVE_RESOLUTION_PILOT" else 200),
            "checkpointing_steps": 0,
        },
        "budget": {**legacy["budget"], "maximum_input_png_bytes": 128 * 1024**2},
        "purpose": "EVALUATION_ONLY_SDXL_NATIVE_STYLE_TRAINING",
        "activation_policy": "FORBIDDEN",
    }
    return _seal_command(value)


def _seal_result(value):
    if value["adapter_manifest"] is not None:
        _seal_adapter(value["adapter_manifest"])
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    return value


def _result_value(command):
    old, _ = _micro_value()
    base = _micro_result(LocalImageSdxlLoraMicroCommand.model_validate(old))
    realized = [
        {
            "sample_id": s.sample_id,
            "target_png_sha256": s.source_image.sha256,
            "training_caption_sha256": s.training_caption_sha256,
            "canvas": s.canvas,
        }
        for s in command.training_samples
    ]
    sample_set_sha256 = content_sha256(realized)
    manifest = {
        **base["adapter_manifest"],
        "schema_version": "local-image-sdxl-native-lora-adapter-manifest/1.0",
        "profile": command.profile,
        "base_model": command.base_model.model_dump(mode="json"),
        "training_command_sha256": command.command_sha256,
        "sample_set_sha256": sample_set_sha256,
    }
    return _seal_result(
        {
            **base,
            "schema_version": "local-image-sdxl-native-lora-result/1.0",
            "profile": command.profile,
            "training_run_id": command.training_run_id,
            "command_sha256": command.command_sha256,
            "adapter_manifest": manifest,
            "runtime": {**base["runtime"], **command.dependencies.model_dump(mode="json")},
            "realized_samples": realized,
            "sample_set_sha256": sample_set_sha256,
            "requested_steps": command.hyperparameters.max_train_steps,
            "completed_steps": command.hyperparameters.max_train_steps,
        }
    )


@pytest.mark.parametrize(
    "profile,count,steps",
    [
        ("NATIVE_RESOLUTION_PILOT", 12, 20),
        ("NATIVE_RESOLUTION_PILOT", 64, 200),
        ("FULL_STYLE_TRAINING", 100, 200),
        ("FULL_STYLE_TRAINING", 200, 1000),
    ],
)
def test_native_profiles_have_closed_non_alias_geometry_cohort_and_terminal_contracts(
    profile, count, steps
):
    value = _command_value(count, profile, steps)
    command = LocalImageSdxlNativeLoraCommand.model_validate(value)
    validate_contract("sdxl-native-lora-command", value)
    assert command == type(command).model_validate_json(content_json_bytes(value))
    assert {s.width_height for s in command.training_samples} == set(
        NATIVE_TARGET_CANVASES.values()
    )
    assert command.hyperparameters.checkpointing_steps == 0
    result = LocalImageSdxlNativeLoraResult.model_validate(_result_value(command))
    validate_sdxl_native_lora_result(command, result)
    assert result.completed_steps == steps and len(result.realized_samples) == count
    assert result.adapter_manifest.profile == profile
    with pytest.raises(ValidationError, match="frozen"):
        command.seed = 3
    with pytest.raises(ValidationError):
        LocalImageSdxlLoraMicroCommand.model_validate(value)
    with pytest.raises(ValidationError):
        LocalImageSdxlLoraMicroAdapterManifest.model_validate(
            result.adapter_manifest.model_dump(mode="json")
        )


def test_native_schemas_are_202012_resource_identical_and_declared_in_release_gates():
    command = LocalImageSdxlNativeLoraCommand.model_validate(_command_value())
    result = _result_value(command)
    root = Path(__file__).resolve().parents[2]
    for family, value in (
        ("command", command.model_dump(mode="json")),
        ("result", result),
        ("adapter-manifest", result["adapter_manifest"]),
    ):
        name, filename = (
            f"sdxl-native-lora-{family}",
            f"local-image-sdxl-native-lora-{family}-v1.schema.json",
        )
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"].endswith("2020-12/schema")
        validate_contract(name, value)
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


def test_scene_conditioning_is_truthful_and_derivative_without_rewriting_source_caption():
    command = LocalImageSdxlNativeLoraCommand.model_validate(_command_value())
    isolated, scene = command.training_samples[:2]
    assert isolated.training_caption_en.endswith("plain white background")
    assert scene.training_caption_en.endswith("authored scene with its depicted background")
    assert "plain white background" not in scene.training_caption_en
    assert isolated.staged_member_path == f"inputs/targets/{isolated.sample_id}.png"
    assert isolated.training_caption_sha256 == text_sha256(isolated.training_caption_en)


@pytest.mark.parametrize(
    "count,profile,steps",
    [
        (11, "NATIVE_RESOLUTION_PILOT", 20),
        (65, "NATIVE_RESOLUTION_PILOT", 20),
        (12, "NATIVE_RESOLUTION_PILOT", 19),
        (12, "NATIVE_RESOLUTION_PILOT", 201),
        (99, "FULL_STYLE_TRAINING", 200),
        (201, "FULL_STYLE_TRAINING", 200),
        (100, "FULL_STYLE_TRAINING", 199),
        (100, "FULL_STYLE_TRAINING", 1001),
    ],
)
def test_profile_bounds_are_enforced_by_schema_and_pydantic(count, profile, steps):
    value = _command_value(count, profile, steps)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommand.model_validate(value)
    with pytest.raises(SchemaValidationError):
        validate_contract("sdxl-native-lora-command", value)


@pytest.mark.parametrize(
    "fault",
    [
        "sample_duplicate",
        "target_duplicate",
        "pixel_duplicate",
        "order",
        "batch_unused",
        "batch_duplicate",
        "batch_unselected",
        "document_concentration",
        "group_concentration",
        "caption_hash",
        "subject_whitespace",
        "subject_unicode",
        "wrong_canvas",
        "png_schema",
        "png_member",
        "batch_schema",
        "review_pointer",
        "authorization",
        "approval",
        "review_time",
        "timezone",
        "checkpoint",
        "activation",
        "input_budget",
        "hash",
        "identity",
        "extra",
    ],
)
def test_invalid_commands_fail_without_dereferencing_binary_or_model_inputs(fault):
    value = _command_value()
    first, second = value["training_samples"][:2]
    if fault == "sample_duplicate":
        second["sample_id"] = first["sample_id"]
    elif fault == "target_duplicate":
        second["target_id"] = first["target_id"]
        second["source_image"]["member_path"] = first["source_image"]["member_path"]
    elif fault == "pixel_duplicate":
        second["source_image"]["sha256"] = first["source_image"]["sha256"]
    elif fault == "order":
        value["training_samples"].reverse()
    elif fault in {"batch_unused", "batch_duplicate"}:
        batch = copy.deepcopy(value["target_batches"][0])
        if fault == "batch_unused":
            batch["result"]["artifact_id"] = "artifact_" + "f" * 32
        value["target_batches"].append(batch)
    elif fault == "batch_unselected":
        first["source_image"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif fault in {"document_concentration", "group_concentration"}:
        field = "source_document_id" if fault.startswith("document") else "exam_group_sha256"
        for sample in value["training_samples"][:5]:
            sample[field] = first[field]
    elif fault == "caption_hash":
        first["conditioning"]["literal_subject"] = "A different reviewed object"
    elif fault.startswith("subject"):
        first["conditioning"]["literal_subject"] += " " if fault.endswith("whitespace") else "한글"
    elif fault == "wrong_canvas":
        first["canvas"] = "LANDSCAPE_768X512"
    elif fault in {"png_schema", "png_member", "batch_schema"}:
        pointer = (
            value["target_batches"][0]["result"]
            if fault == "batch_schema"
            else first["source_image"]
        )
        if fault == "png_member":
            pointer["member_path"] = "targets/wrong.png"
        else:
            pointer["schema_ref"] = (
                pointer["schema_ref"].replace("/1.2", "/1.1").replace("png/1.1", "png/1.0")
            )
    elif fault == "review_pointer":
        value["screening_evidence"]["media_type"] = "application/json"
    elif fault == "authorization":
        value["training_authorization"]["schema_ref"] = "eom://schemas/unknown/1.0"
    elif fault == "approval":
        value["experiment_authorization"]["permitted_uses"] = ["INTERNAL_SDXL_COMPARISON"]
    elif fault == "review_time":
        value["reviewed_at"] = "2026-10-03T18:41:00Z"
    elif fault == "timezone":
        value["created_at"] = "2026-10-04T03:40:00+09:00"
    elif fault == "checkpoint":
        value["hyperparameters"]["checkpointing_steps"] = 200
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "input_budget":
        value["budget"]["maximum_input_png_bytes"] += 1
    elif fault == "extra":
        value["arbitrary_worker_options"] = {}
    _seal_command(value)
    if fault == "hash":
        value["command_sha256"] = text_sha256("wrong command")
    elif fault == "identity":
        value["training_run_id"] = "imgsdxlnativetrainrun_" + "f" * 32
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommand.model_validate(value)


@pytest.mark.parametrize(
    "fault",
    [
        "partial_steps",
        "unknown_sample",
        "pixels",
        "caption",
        "canvas",
        "cohort_incomplete",
        "command",
        "profile",
        "requested_steps",
        "started_before_command",
        "base",
        "dependency",
        "duration",
        "memory",
        "adapter_profile",
        "adapter_created",
        "failure_adapter",
        "no_loss",
        "result_hash",
        "sample_set_hash",
        "duplicate_sample",
        "cancel_code",
    ],
)
def test_terminal_receipts_are_bound_to_exact_cohort_recipe_and_budget(fault):
    command = LocalImageSdxlNativeLoraCommand.model_validate(_command_value(18))
    value = _result_value(command)
    if fault == "partial_steps":
        value["completed_steps"] -= 1
    elif fault in {"unknown_sample", "pixels", "caption", "canvas"}:
        sample = value["realized_samples"][0]
        key = {
            "unknown_sample": "sample_id",
            "pixels": "target_png_sha256",
            "caption": "training_caption_sha256",
            "canvas": "canvas",
        }[fault]
        sample[key] = (
            "PORTRAIT_768X1024"
            if fault == "canvas"
            else (
                "imgsourcecrop_" + "f" * 32
                if fault == "unknown_sample"
                else text_sha256("wrong " + fault)
            )
        )
        value["realized_samples"].sort(key=lambda s: s["sample_id"])
    elif fault == "cohort_incomplete":
        value["realized_samples"].pop()
    elif fault == "command":
        value["command_sha256"] = text_sha256("another command")
    elif fault == "profile":
        value["profile"] = "FULL_STYLE_TRAINING"
    elif fault == "requested_steps":
        value["requested_steps"] += 1
        value["completed_steps"] += 1
    elif fault == "started_before_command":
        value["started_at"] = "2026-10-03T18:30:00Z"
    elif fault == "base":
        value["adapter_manifest"]["base_model"]["model_revision_id"] = "imgmodelrev_" + "f" * 32
    elif fault == "dependency":
        value["runtime"]["python_version"] = "3.11.14"
    elif fault == "duration":
        value["duration_ms"] = command.budget.maximum_duration_ms + 1
    elif fault == "memory":
        value["runtime"]["peak_gpu_memory_bytes"] = command.budget.maximum_peak_gpu_memory_bytes + 1
    elif fault == "adapter_profile":
        value["adapter_manifest"]["profile"] = "FULL_STYLE_TRAINING"
    elif fault == "adapter_created":
        value["adapter_manifest"]["created_at"] = "2026-10-03T18:42:00Z"
    elif fault == "failure_adapter":
        value["status"] = "FAILED"
        value["error_code"] = "IMAGE_TRAINING_CUDA_OOM"
    elif fault == "no_loss":
        value["final_loss"] = None
    elif fault == "duplicate_sample":
        value["realized_samples"][1] = copy.deepcopy(value["realized_samples"][0])
    elif fault == "cancel_code":
        value["error_code"] = "IMAGE_TRAINING_CANCELLED"
    value["sample_set_sha256"] = content_sha256(value["realized_samples"])
    value["adapter_manifest"]["sample_set_sha256"] = value["sample_set_sha256"]
    _seal_result(value)
    if fault == "result_hash":
        value["result_sha256"] = text_sha256("wrong result")
    elif fault == "sample_set_hash":
        value["sample_set_sha256"] = text_sha256("wrong sample set")
    with pytest.raises((ValidationError, ValueError, SchemaValidationError)):
        result = LocalImageSdxlNativeLoraResult.model_validate(value)
        validate_sdxl_native_lora_result(command, result)


@pytest.mark.parametrize("cancelled", [False, True])
def test_empty_failed_or_cancelled_history_has_no_accepted_adapter(cancelled):
    command = LocalImageSdxlNativeLoraCommand.model_validate(_command_value())
    value = _result_value(command)
    value.update(
        status="CANCELLED" if cancelled else "FAILED",
        error_code="IMAGE_TRAINING_CANCELLED" if cancelled else "IMAGE_TRAINING_INPUT_INVALID",
        adapter_manifest=None,
        realized_samples=[],
        sample_set_sha256=None,
        runtime=None,
        completed_steps=0,
        final_loss=None,
    )
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(value))
    validate_sdxl_native_lora_result(command, result)
    assert result.adapter_manifest is None
    bad = result.model_dump(mode="json")
    bad["error_code"] = None
    with pytest.raises(SchemaValidationError):
        validate_contract("sdxl-native-lora-result", bad)


def test_shared_adapter_identity_preserves_released_micro_bytes_and_hashes():
    value, _ = _micro_value()
    result = _micro_result(LocalImageSdxlLoraMicroCommand.model_validate(value))
    manifest = LocalImageSdxlLoraMicroAdapterManifest.model_validate(result["adapter_manifest"])
    assert manifest.model_dump(mode="json") == result["adapter_manifest"]
    root = Path(__file__).resolve().parents[2]
    for filename in (
        "local-image-sdxl-lora-micro-command-v1.schema.json",
        "local-image-sdxl-lora-micro-result-v1.schema.json",
        "local-image-sdxl-lora-micro-adapter-manifest-v1.schema.json",
    ):
        name = filename.removeprefix("local-image-").removesuffix("-v1.schema.json")
        assert (
            SCHEMA_SHA256[name]
            == "sha256:"
            + hashlib.sha256((root / "schemas/image-provider" / filename).read_bytes()).hexdigest()
        )

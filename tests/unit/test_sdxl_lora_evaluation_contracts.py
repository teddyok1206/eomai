from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlLoraMicroResult,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_sdxl_lora_evaluation_sources,
)
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema
from pydantic import ValidationError

from tests.unit.test_sdxl_lora_micro_contracts import _command_value, _result_value


def _seal(value):
    value["run_id"] = (
        "imgsdxlloraevalrun_"
        + content_sha256({k: v for k, v in value.items() if k not in {"run_id", "command_sha256"}})[
            7:39
        ]
    )
    value["command_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "command_sha256"}
    )
    return value


def _baseline(training, *, invalid_reference=False):
    sample = training.training_samples[0]
    case = {
        "depiction_key": "TEST_RECTANGLE",
        "reference_image": sample.source_image.model_dump(mode="json"),
        "reference_width_px": sample.source_width_px,
        "reference_height_px": sample.source_height_px,
        "prompt_en": "Scientific exam line drawing of one object.",
        "negative_prompt_en": "text, decorative background, color",
        "seeds": [1, 2],
    }
    if invalid_reference:
        case["reference_image"]["sha256"] = "sha256:" + "f" * 64
    case["prompt_sha256"] = text_sha256(case["prompt_en"])
    case["negative_prompt_sha256"] = text_sha256(case["negative_prompt_en"])
    case["case_id"] = (
        "imgsdxlcase_"
        + content_sha256(
            {k: v for k, v in case.items() if k not in {"case_id", "staged_member_path"}}
        )[7:39]
    )
    case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
    baseline = {
        "schema_version": "local-image-sdxl-lineart-probe-command/1.0",
        "run_id": "imgsdxlproberun_" + "a" * 32,
        "created_at": "2026-10-03T18:40:00Z",
        "model": training.base_model.model_dump(mode="json"),
        "prompt_policy": {
            **training.crop_set.model_dump(mode="json"),
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-lineart-prompt-policy/1.0",
            "member_path": "policy.json",
        },
        "style_track": "OBJECT_LINE_ART",
        "conditioning_policy": "FIT_GRAYSCALE_INVERT_832X512/1.0",
        "inference_steps": 20,
        "guidance_scale": 7.0,
        "adapter_conditioning_scale": 0.8,
        "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
        "cases": [case],
    }
    baseline["command_sha256"] = content_sha256(
        {k: v for k, v in baseline.items() if k != "command_sha256"}
    )
    return LocalImageSdxlLineartProbeCommand.model_validate(baseline)


def _fixture():
    training = LocalImageSdxlLoraMicroCommand.model_validate(_command_value()[0])
    result = LocalImageSdxlLoraMicroResult.model_validate(_result_value(training))
    manifest = result.adapter_manifest
    assert manifest is not None
    baseline = _baseline(training)

    def pointer(model, family, identity):
        return {
            "artifact_id": "artifact_" + identity * 32,
            "artifact_revision_id": "rev_" + identity * 32,
            "member_path": "manifests/" + family + ".json",
            "schema_ref": "eom://schemas/image-provider/local-image-" + family + "/1.0",
            "media_type": "application/json",
            "sha256": "sha256:"
            + hashlib.sha256(content_json_bytes(model.model_dump(mode="json"))).hexdigest(),
        }

    value = _seal(
        {
            "schema_version": "local-image-sdxl-lora-evaluation-command/1.0",
            "created_at": "2026-10-03T22:00:00Z",
            "source_commit": "a" * 40,
            "purpose": "EVALUATION_ONLY_MATCHED_SDXL_LORA",
            "activation_policy": "FORBIDDEN",
            "evaluation": {
                "baseline_command": pointer(baseline, "sdxl-lineart-probe-command", "a"),
                "training_command": pointer(training, "sdxl-lora-micro-command", "b"),
                "training_result": pointer(result, "sdxl-lora-micro-result", "c"),
                "adapter_manifest": pointer(manifest, "sdxl-lora-micro-adapter-manifest", "c"),
                "adapter_id": manifest.adapter_id,
                "adapter_revision_id": manifest.adapter_revision_id,
                "adapter_manifest_sha256": manifest.manifest_sha256,
                "adapter_strength": 1.0,
            },
        }
    )
    return value, baseline, training, result, manifest


def test_additive_evaluation_contract_matches_successful_training_and_frozen_baseline():
    value, *sources = _fixture()
    validate_contract("sdxl-lora-evaluation-command", value)
    command = LocalImageSdxlLoraEvaluationCommand.model_validate(value)
    validate_sdxl_lora_evaluation_sources(command, *sources)
    with pytest.raises(ValidationError):
        command.source_commit = "b" * 40


@pytest.mark.parametrize("fault", ["strength", "result_revision", "schema", "hash", "activation"])
def test_invalid_evaluation_cannot_reinterpret_an_unpinned_intervention(fault):
    value, *_ = _fixture()
    if fault == "strength":
        value["evaluation"]["adapter_strength"] = 0
    elif fault == "result_revision":
        value["evaluation"]["adapter_manifest"]["artifact_revision_id"] = "rev_" + "d" * 32
    elif fault == "schema":
        value["evaluation"]["training_result"]["schema_ref"] = (
            "eom://schemas/image-provider/other/1.0"
        )
    elif fault == "hash":
        value["command_sha256"] = "sha256:" + "f" * 64
    else:
        value["activation_policy"] = "ALLOWED"
    if fault != "hash":
        _seal(value)
    with pytest.raises(ValidationError):
        LocalImageSdxlLoraEvaluationCommand.model_validate(value)


@pytest.mark.parametrize("fault", ["adapter", "baseline_stack", "early", "reference", "training"])
def test_source_mismatch_rejected_without_materialization(fault):
    value, baseline, training, result, manifest = _fixture()
    if fault == "adapter":
        value["evaluation"]["adapter_revision_id"] = "imgadapterrev_" + "d" * 32
    elif fault == "early":
        value["created_at"] = "2026-10-03T18:40:00Z"
    elif fault == "reference":
        baseline = _baseline(training, invalid_reference=True)
    elif fault == "baseline_stack":
        altered = copy.deepcopy(baseline.model_dump(mode="json"))
        altered["model"]["model_revision_id"] = "imgmodelrev_" + "d" * 32
        altered["command_sha256"] = content_sha256(
            {k: v for k, v in altered.items() if k != "command_sha256"}
        )
        baseline = LocalImageSdxlLineartProbeCommand.model_validate(altered)
    else:
        altered = result.model_dump(mode="json")
        altered["command_sha256"] = "sha256:" + "d" * 64
        altered["adapter_manifest"] = None
        altered["status"] = "FAILED"
        altered["error_code"] = "IMAGE_TRAINING_EXEC_FAILED"
        altered["result_sha256"] = content_sha256(
            {k: v for k, v in altered.items() if k != "result_sha256"}
        )
        result = LocalImageSdxlLoraMicroResult.model_validate(altered)
    command = LocalImageSdxlLoraEvaluationCommand.model_validate(_seal(value))
    with pytest.raises(ValueError):
        validate_sdxl_lora_evaluation_sources(command, baseline, training, result, manifest)


def test_schema_resources_are_additive_mirrored_and_pinned():
    root = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        name = "sdxl-lora-evaluation-" + family
        filename = "local-image-" + name + "-v1.schema.json"
        raw = (root / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert SCHEMA_SHA256[name] == "sha256:" + hashlib.sha256(raw).hexdigest()
        assert load_schema(name)["$schema"] == "https://json-schema.org/draft/2020-12/schema"

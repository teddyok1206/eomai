"""Explicit exposure admission and scheduling; no GPU or quality acceptance."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import content_json_bytes, text_sha256, validate_contract
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV2,
    LocalImageSdxlNativeLoraCommandV3,
    LocalImageSdxlNativeLoraResult,
    SdxlNativeLoraConditioning,
    native_lora_command_protocol,
    validate_sdxl_native_lora_result,
)
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema
from eom_image_trainer import diffusers_backend as numerical
from eom_image_trainer.sdxl_lora_backend import SdxlNativeLoraBackend
from eom_image_trainer.sdxl_native_lora_runner import load_sdxl_native_lora_command
from eom_image_trainer.style_exposure import native_style_exposure_schedule
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_lora_contracts import _command_value, _result_value, _seal_command


def _balanced_value(*, count=100, steps=800):
    value = _command_value(count, "FULL_STYLE_TRAINING", steps)
    value["schema_version"] = "local-image-sdxl-native-lora-command/1.2"
    value["exposure_policy"] = {
        "policy_version": "ALL_TARGETS_ONCE_THEN_STYLE_STRATIFIED_4_2_4/1.0",
        "clean_contour_weight": 4,
        "fine_hatching_weight": 2,
        "restrained_tone_weight": 4,
    }
    return _seal_command(value)


def _actual_distribution_value():
    value = _balanced_value()
    for index, sample in enumerate(value["training_samples"]):
        conditioning = SdxlNativeLoraConditioning.model_validate(
            {
                **sample["conditioning"],
                "expression": (
                    "CLEAN_CONTOUR"
                    if index < 17
                    else "FINE_HATCHING"
                    if index < 25
                    else "RESTRAINED_TONE"
                ),
            }
        )
        sample["conditioning"] = conditioning.model_dump(mode="json")
        sample["training_caption_sha256"] = text_sha256(conditioning.training_caption_en)
    return _seal_command(value)


def test_closed_successor_has_pinned_canonical_schema_and_command(tmp_path):
    value = _balanced_value()
    protocol = native_lora_command_protocol(value["schema_version"])
    assert protocol.model is LocalImageSdxlNativeLoraCommandV3
    assert protocol.contract == "sdxl-native-lora-command-v3"
    validate_contract(protocol.contract, value)
    command = protocol.model.model_validate(value)
    assert (
        LocalImageSdxlNativeLoraCommandV3.model_validate_json(content_json_bytes(value)) == command
    )
    assert command.activation_policy == "FORBIDDEN"
    with pytest.raises(ValidationError):
        command.seed = 100
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(value))
    assert load_sdxl_native_lora_command(root, root / "command.json") == command
    schema = load_schema(protocol.contract)
    Draft202012Validator.check_schema(schema)
    repo = Path(__file__).resolve().parents[2]
    filename = "local-image-sdxl-native-lora-command-v3.schema.json"
    raw = (repo / "schemas/image-provider" / filename).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[protocol.contract]
    assert (
        raw
        == (repo / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    release = (repo / "scripts/image_trainer/build_release.sh").read_text()
    assert filename in release and "eom_image_trainer/style_exposure.py" in release


@pytest.mark.parametrize(
    "fault",
    ["missing_policy", "unknown_policy", "weight", "missing_style", "pilot", "short_cohort"],
)
def test_schema_and_model_reject_unannounced_or_incomplete_exposure(fault):
    value = _balanced_value()
    if fault == "missing_policy":
        del value["exposure_policy"]
    elif fault == "unknown_policy":
        value["exposure_policy"]["policy_version"] = "ARBITRARY_WEIGHTS/1.0"
    elif fault == "weight":
        value["exposure_policy"]["clean_contour_weight"] = 5
    elif fault == "missing_style":
        for sample in value["training_samples"]:
            conditioning = SdxlNativeLoraConditioning.model_validate(
                {**sample["conditioning"], "expression": "RESTRAINED_TONE"}
            )
            sample["conditioning"] = conditioning.model_dump(mode="json")
            sample["training_caption_sha256"] = text_sha256(conditioning.training_caption_en)
    elif fault == "pilot":
        value["profile"] = "NATIVE_RESOLUTION_PILOT"
    else:
        value = _balanced_value(count=99)
    value = _seal_command(value)
    with pytest.raises(SchemaValidationError):
        validate_contract("sdxl-native-lora-command-v3", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV3.model_validate(value)


@pytest.mark.parametrize("seed", [True, "17", 17.0])
def test_new_policy_does_not_coerce_seed_before_schedule(seed):
    value = _balanced_value()
    value["seed"] = seed
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV3.model_validate(_seal_command(value))


def test_policy_is_identity_bearing_and_cannot_be_a_released_command_alias():
    value = _balanced_value()
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV2.model_validate(value)
    value["schema_version"] = "local-image-sdxl-native-lora-command/1.1"
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV2.model_validate(_seal_command(value))
    with pytest.raises(SchemaValidationError):
        validate_contract("sdxl-native-lora-command-v2", value)
    with pytest.raises(ValueError, match="PROTOCOL_UNSUPPORTED"):
        native_lora_command_protocol("local-image-sdxl-native-lora-command/99.0")


def test_result_pins_exact_balanced_command_without_changing_released_result_semantics():
    command = LocalImageSdxlNativeLoraCommandV3.model_validate(_balanced_value())
    result = LocalImageSdxlNativeLoraResult.model_validate(_result_value(command))
    validate_sdxl_native_lora_result(command, result)
    other = command.model_dump(mode="json")
    other["seed"] += 1
    other = LocalImageSdxlNativeLoraCommandV3.model_validate(_seal_command(other))
    with pytest.raises(ValueError, match="COMMAND_BINDING_INVALID"):
        validate_sdxl_native_lora_result(other, result)


def test_actual_17_8_75_cohort_keeps_all_targets_and_changes_only_exposure():
    command = LocalImageSdxlNativeLoraCommandV3.model_validate(_actual_distribution_value())
    before = content_json_bytes(command.model_dump(mode="json"))
    global_state = random.getstate()
    schedule = native_style_exposure_schedule(command)
    assert random.getstate() == global_state
    assert schedule == native_style_exposure_schedule(command)
    assert before == content_json_bytes(command.model_dump(mode="json"))
    assert len(schedule) == 3200 and set(schedule) == set(range(100))
    assert schedule[:100] == numerical._sample_order(epoch=0, count=100, seed=command.seed)
    counts = Counter(command.training_samples[index].conditioning.expression for index in schedule)
    assert counts == {"CLEAN_CONTOUR": 1257, "FINE_HATCHING": 628, "RESTRAINED_TONE": 1315}
    member_counts = Counter(schedule)
    for expression, _weight in command.exposure_policy.expression_weights:
        within = [
            member_counts[index]
            for index, sample in enumerate(command.training_samples)
            if sample.conditioning.expression == expression
        ]
        assert max(within) - min(within) <= 1
    # Correlated scene/document marginals are measured; not declared unchanged.
    assert (
        sum(Counter(command.training_samples[i].source_document_id for i in schedule).values())
        == 3200
    )
    assert (
        sum(
            Counter(command.training_samples[i].conditioning.composition for i in schedule).values()
        )
        == 3200
    )


@pytest.mark.parametrize("count,steps", [(100, 200), (103, 201), (199, 999), (200, 1000)])
def test_remainder_rounding_and_bounded_schedule_have_no_dropped_or_extra_draws(count, steps):
    command = LocalImageSdxlNativeLoraCommandV3.model_validate(
        _balanced_value(count=count, steps=steps)
    )
    schedule = native_style_exposure_schedule(command)
    assert len(schedule) == steps * 4 and len(set(schedule[:count])) == count
    actual = Counter(command.training_samples[i].conditioning.expression for i in schedule[count:])
    remaining = steps * 4 - count
    total = sum(weight for _, weight in command.exposure_policy.expression_weights)
    for expression, weight in command.exposure_policy.expression_weights:
        assert abs(actual[expression] - remaining * weight / total) < 1


def test_native_wrapper_routes_closed_exposure_into_shared_numerical_recipe(monkeypatch, tmp_path):
    command = LocalImageSdxlNativeLoraCommandV3.model_validate(_balanced_value())
    samples = tuple(
        numerical.LoraTensorSample(
            s.training_caption_en, tmp_path / s.staged_member_path, *s.width_height
        )
        for s in command.training_samples
    )
    stack = SimpleNamespace(
        manifest=command.base_model, component_roots={"BASE": tmp_path, "VAE": tmp_path}
    )
    captured = {}

    def train(_self, **kwargs):
        captured.update(kwargs)
        return "fake numerical result; no weights"

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", train)
    SdxlNativeLoraBackend().train(
        stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
    )
    assert captured["samples"] is samples and captured["checkpoint_policy"] is None
    assert captured["recipe"].sample_schedule == native_style_exposure_schedule(command)
    assert captured["recipe"].seed == command.seed
    assert captured["recipe"].hyperparameters == command.hyperparameters

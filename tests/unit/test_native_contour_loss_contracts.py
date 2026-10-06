"""Closed objective admission/source routing; synthetic tests, not image quality."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import content_json_bytes, validate_contract
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV3,
    LocalImageSdxlNativeLoraCommandV4,
    LocalImageSdxlNativeLoraResult,
    native_lora_command_protocol,
    validate_sdxl_native_lora_result,
)
from eom_image_contracts.sdxl_native_lora_sources import SdxlNativeLoraMetadataAdmission
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema
from eom_image_trainer import diffusers_backend as numerical
from eom_image_trainer.sdxl_lora_backend import SdxlNativeLoraBackend
from eom_image_trainer.sdxl_native_lora_runner import load_sdxl_native_lora_command
from eom_image_trainer.style_exposure import native_style_exposure_schedule
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_native_style_exposure import _actual_distribution_value
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_lora_contracts import _result_value, _seal_command


def _weighted_value():
    value = _actual_distribution_value()
    value["schema_version"] = "local-image-sdxl-native-lora-command/1.3"
    value["loss_policy"] = dict(
        policy_version="SOURCE_DARK_CELL_WEIGHT_2_1/1.0",
        source_cell_size_px=8,
        dark_luminance_threshold=96,
        dark_cell_weight=2,
        other_cell_weight=1,
        normalization="BROADCAST_WEIGHT_SUM",
    )
    value["objective_evidence"] = dict(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id="rev_" + "c" * 32,
        member_path="reports/own-review.json",
        schema_ref="eom://schemas/operations/plain-text-log/1.0",
        media_type="text/plain",
        sha256="sha256:" + hashlib.sha256(b"objective rationale").hexdigest(),
    )
    return _seal_command(value)


def test_schema_model_canonical_reader_and_wheel_package_are_aligned(tmp_path):
    value = _weighted_value()
    protocol = native_lora_command_protocol(value["schema_version"])
    assert protocol.contract == "sdxl-native-lora-command-v4"
    assert protocol.model is LocalImageSdxlNativeLoraCommandV4
    validate_contract(protocol.contract, value)
    command = protocol.model.model_validate(value)
    assert command.activation_policy == "FORBIDDEN"
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(value))
    assert load_sdxl_native_lora_command(root, root / "command.json") == command
    Draft202012Validator.check_schema(load_schema(protocol.contract))
    repo = Path(__file__).resolve().parents[2]
    filename = "local-image-sdxl-native-lora-command-v4.schema.json"
    raw = (repo / "schemas/image-provider" / filename).read_bytes()
    assert (
        raw
        == (repo / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[protocol.contract]
    build = (repo / "scripts/image_trainer/build_release.sh").read_text()
    assert filename in build and "eom_image_trainer/native_contour_loss.py" in build


@pytest.mark.parametrize(
    "field,bad",
    [
        ("policy_version", "UNBOUNDED/1.0"),
        ("source_cell_size_px", 16),
        ("dark_luminance_threshold", 97),
        ("dark_cell_weight", 3),
        ("other_cell_weight", 0),
        ("normalization", "UNNORMALIZED_SUM"),
    ],
)
def test_schema_and_model_reject_changed_recipe(field, bad):
    value = _weighted_value()
    value["loss_policy"][field] = bad
    value = _seal_command(value)
    with pytest.raises(SchemaError):
        validate_contract("sdxl-native-lora-command-v4", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV4.model_validate(value)


@pytest.mark.parametrize(
    "field",
    ["source_cell_size_px", "dark_luminance_threshold", "dark_cell_weight", "other_cell_weight"],
)
@pytest.mark.parametrize("kind", ["float", "string", "bool"])
def test_no_coerced_numeric_policy(field, kind):
    value = _weighted_value()
    original = value["loss_policy"][field]
    value["loss_policy"][field] = (
        float(original) if kind == "float" else str(original) if kind == "string" else True
    )
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV4.model_validate(_seal_command(value))


@pytest.mark.parametrize("field", ["loss_policy", "objective_evidence"])
def test_required_successor_fields_do_not_default(field):
    value = _weighted_value()
    del value[field]
    with pytest.raises(SchemaError):
        validate_contract("sdxl-native-lora-command-v4", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV4.model_validate(_seal_command(value))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("media_type", "application/json"),
        ("member_path", "reports/other.txt"),
        ("schema_ref", "eom://schemas/operations/plain-text-log/2.0"),
    ],
)
def test_objective_evidence_pointer_has_exact_role(field, bad):
    value = _weighted_value()
    value["objective_evidence"][field] = bad
    with pytest.raises(SchemaError):
        validate_contract("sdxl-native-lora-command-v4", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeLoraCommandV4.model_validate(_seal_command(value))


def test_objective_receipt_required_verified_and_not_optional_text():
    command = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    admission = SdxlNativeLoraMetadataAdmission(command)
    assert command.objective_evidence in admission.pending_pointers()
    with pytest.raises(ValueError, match="SCREENING_POINTER_INVALID"):
        admission.admit(command.objective_evidence, b"changed")
    admission.admit(command.objective_evidence, b"objective rationale")
    assert command.objective_evidence not in admission.pending_pointers()
    with pytest.raises(ValueError, match="UNREQUESTED_OR_REPEATED"):
        admission.admit(command.objective_evidence, b"objective rationale")
    with pytest.raises(ValueError, match="CLOSURE_INCOMPLETE"):
        admission.validated_sources()


def test_old_objective_and_same_exposure_remain_immutable():
    old_value = _actual_distribution_value()
    old = LocalImageSdxlNativeLoraCommandV3.model_validate(old_value)
    new = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    assert new.training_samples == old.training_samples
    assert new.exposure_policy == old.exposure_policy
    assert new.hyperparameters == old.hyperparameters
    assert new.seed == old.seed
    assert native_style_exposure_schedule(new) == native_style_exposure_schedule(old)
    assert new.command_sha256 != old.command_sha256 and new.training_run_id != old.training_run_id
    assert content_json_bytes(old.model_dump(mode="json")) == content_json_bytes(old_value)
    with pytest.raises(ValidationError):
        new.loss_policy.dark_cell_weight = 3
    for contract in (
        "sdxl-native-lora-command",
        "sdxl-native-lora-command-v2",
        "sdxl-native-lora-command-v3",
    ):
        with pytest.raises(SchemaError):
            validate_contract(contract, new.model_dump(mode="json"))
        repo = Path(__file__).resolve().parents[2]
        filename = {
            "sdxl-native-lora-command": "local-image-sdxl-native-lora-command-v1.schema.json",
            "sdxl-native-lora-command-v2": "local-image-sdxl-native-lora-command-v2.schema.json",
            "sdxl-native-lora-command-v3": "local-image-sdxl-native-lora-command-v3.schema.json",
        }[contract]
        assert (
            "sha256:"
            + hashlib.sha256((repo / "schemas/image-provider" / filename).read_bytes()).hexdigest()
            == SCHEMA_SHA256[contract]
        )


def test_adapter_result_pins_weighted_command_not_old_mse_alias():
    new = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    old = LocalImageSdxlNativeLoraCommandV3.model_validate(_actual_distribution_value())
    result = LocalImageSdxlNativeLoraResult.model_validate(_result_value(new))
    validate_sdxl_native_lora_result(new, result)
    with pytest.raises(ValueError, match="COMMAND_BINDING_INVALID"):
        validate_sdxl_native_lora_result(old, result)


def test_native_wrapper_routes_weighting_only_to_explicit_successor(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(
        numerical.DiffusersUnetLoraBackend, "train", lambda _self, **kw: captured.append(kw)
    )
    for command in (
        LocalImageSdxlNativeLoraCommandV3.model_validate(_actual_distribution_value()),
        LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value()),
    ):
        samples = tuple(
            numerical.LoraTensorSample(
                s.training_caption_en, tmp_path / s.staged_member_path, *s.width_height
            )
            for s in command.training_samples
        )
        SdxlNativeLoraBackend().train(
            stack=SimpleNamespace(
                manifest=command.base_model, component_roots={"BASE": tmp_path, "VAE": tmp_path}
            ),
            samples=samples,
            command=command,
            output_root=tmp_path / "adapter",
        )
    assert captured[0]["recipe"].loss_policy is None
    assert captured[1]["recipe"].loss_policy == command.loss_policy
    assert captured[0]["recipe"].sample_schedule == captured[1]["recipe"].sample_schedule
    assert all(item["checkpoint_policy"] is None for item in captured)

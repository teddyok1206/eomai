"""Light-environment numeric fakes are not installed CLIP or pretrained quality acceptance."""

from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from eom_image_provider import sdxl_ip_style_encoder_input as inputs
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_pixels import PreparedSdxlIpStylePixels

from tests.unit.test_sdxl_native_lora_contracts import _command_value


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fixture(monkeypatch):
    sample = SdxlNativeLoraSample.model_validate(_command_value()["training_samples"][0])
    rgb = np.full((224, 224, 3), 160, dtype=np.uint8)
    rgb[:5, :5] = (255, 0, 0)
    rgb[-5:, -5:] = (0, 128, 255)
    raw = rgb.tobytes()
    prepared = PreparedSdxlIpStylePixels(
        sample.source_image, SdxlIpStylePreprocessing(), (224, 224), (0, 0), raw, _sha(raw)
    )
    versions = {"Pillow": "11.3.0", "transformers": "4.56.2", "numpy": "2.4.6"}
    monkeypatch.setattr(inputs.metadata, "version", lambda name: versions[name])
    calls = []

    def processor(profile):
        calls.append(("FACTORY", profile))

        def run(**kwargs):
            calls.append(("PROCESS", {k: v for k, v in kwargs.items() if k != "images"}))
            assert kwargs["images"].mode == "RGB" and kwargs["images"].size == (224, 224)
            assert kwargs["images"].tobytes() == raw
            pixels = np.asarray(kwargs["images"]).astype(np.float64)
            pixels = (pixels * profile.rescale_factor).astype(np.float32)
            pixels = (pixels - np.asarray(profile.image_mean, dtype=np.float32)) / np.asarray(
                profile.image_std, dtype=np.float32
            )
            return {"pixel_values": pixels.transpose(2, 0, 1)[None]}

        return run

    monkeypatch.setattr(inputs, "_clip_processor", processor)
    return prepared, sample, calls, versions


def test_normalized_nchw_is_frozen_le_float32_exact_and_preserves_color_gray_corners(monkeypatch):
    prepared, sample, calls, _ = _fixture(monkeypatch)
    value = inputs.prepare_sdxl_ip_style_encoder_input(
        prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
    )
    repeated = inputs.prepare_sdxl_ip_style_encoder_input(
        prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
    )
    assert value == repeated and value.source == sample.source_image
    assert value.source_rgb_sha256 == prepared.rgb_sha256
    assert value.shape == (1, 3, 224, 224)
    assert len(value.float32_le_bytes) == 1 * 3 * 224 * 224 * 4
    assert value.float32_le_sha256 == _sha(value.float32_le_bytes)
    decoded = np.frombuffer(value.float32_le_bytes, dtype="<f4").reshape(value.shape)
    assert not decoded.flags.writeable and np.isfinite(decoded).all()
    for y, x, rgb in ((0, 0, (255, 0, 0)), (223, 223, (0, 128, 255)), (112, 112, (160,) * 3)):
        expected = (np.asarray(rgb, dtype=np.float64) / 255).astype(np.float32)
        expected = (
            expected - np.asarray(prepared.preprocessing.image_mean, dtype=np.float32)
        ) / np.asarray(prepared.preprocessing.image_std, dtype=np.float32)
        assert np.array_equal(decoded[0, :, y, x], expected)
    assert calls[1][1] == dict(
        return_tensors="np", input_data_format="channels_last", data_format="channels_first"
    )
    with pytest.raises(FrozenInstanceError):
        value.shape = (1, 224, 224, 3)


@pytest.mark.parametrize(
    "fault", ["bytes", "declared", "planned", "length", "mutable", "invalid-hash"]
)
def test_rgb_bounds_and_both_trace_hashes_fail_before_processor(monkeypatch, fault):
    prepared, sample, calls, _ = _fixture(monkeypatch)
    expected = prepared.rgb_sha256
    if fault == "bytes":
        prepared = replace(prepared, rgb_bytes=prepared.rgb_bytes[:-1] + b"\0")
    elif fault == "declared":
        prepared = replace(prepared, rgb_sha256="sha256:" + "f" * 64)
    elif fault == "planned":
        expected = "sha256:" + "f" * 64
    elif fault == "length":
        prepared = replace(prepared, rgb_bytes=prepared.rgb_bytes[:-1])
    elif fault == "mutable":
        prepared = replace(prepared, rgb_bytes=bytearray(prepared.rgb_bytes))
    else:
        expected = "not-a-hash"
    with pytest.raises(ProviderError) as error:
        inputs.prepare_sdxl_ip_style_encoder_input(
            prepared, sample=sample, expected_rgb_sha256=expected
        )
    assert error.value.code == (
        "SDXL_PROBE_HASH_MISMATCH"
        if fault in {"bytes", "declared", "planned"}
        else "SDXL_PROBE_INPUT_INVALID"
    )
    assert calls == []


@pytest.mark.parametrize("fault", ["sample", "source", "profile"])
def test_untrusted_small_values_fail_before_numerical_import(monkeypatch, fault):
    prepared, sample, calls, _ = _fixture(monkeypatch)
    if fault == "sample":
        sample = sample.model_copy(
            update={
                "source_image": sample.source_image.model_copy(
                    update={"media_type": "application/pdf"}
                )
            }
        )
    elif fault == "source":
        prepared = replace(
            prepared,
            source=prepared.source.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32}),
        )
    else:
        prepared = replace(
            prepared,
            preprocessing=prepared.preprocessing.model_copy(update={"processor_center_crop": True}),
        )
    with pytest.raises(ProviderError) as error:
        inputs.prepare_sdxl_ip_style_encoder_input(
            prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
        )
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID" and calls == []


@pytest.mark.parametrize("package", ["Pillow", "transformers", "numpy"])
def test_mismatched_or_missing_runtime_is_not_silently_substituted(monkeypatch, package):
    prepared, sample, calls, versions = _fixture(monkeypatch)
    versions[package] = "99.0.0"
    with pytest.raises(ProviderError):
        inputs.prepare_sdxl_ip_style_encoder_input(
            prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
        )
    assert calls == []

    def missing(name):
        raise inputs.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inputs.metadata, "version", missing)
    with pytest.raises(ProviderError):
        inputs.prepare_sdxl_ip_style_encoder_input(
            prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
        )
    assert calls == []


@pytest.mark.parametrize(
    "fault", ["nan", "inf", "float64", "float16", "shape", "empty", "list", "key"]
)
def test_bad_processor_output_cannot_supply_an_encoder_batch(monkeypatch, fault):
    prepared, sample, *_ = _fixture(monkeypatch)
    batch = np.zeros((1, 3, 224, 224), dtype=np.float32)
    if fault in {"nan", "inf"}:
        batch[0, 0, 0, 0] = np.nan if fault == "nan" else np.inf
    elif fault in {"float64", "float16"}:
        batch = batch.astype(fault)
    elif fault == "shape":
        batch = batch.transpose(0, 2, 3, 1)
    elif fault == "empty":
        batch = batch[:0]
    elif fault == "list":
        batch = [batch]
    result = {} if fault == "key" else {"pixel_values": batch}
    monkeypatch.setattr(inputs, "_clip_processor", lambda _p: lambda **_k: result)
    with pytest.raises(ProviderError) as error:
        inputs.prepare_sdxl_ip_style_encoder_input(
            prepared, sample=sample, expected_rgb_sha256=prepared.rgb_sha256
        )
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID"


def test_public_slow_factory_uses_explicit_profile_no_hub_resize_crop_or_conversion(monkeypatch):
    fake = ModuleType("transformers.models.clip.image_processing_clip")
    calls = []
    sentinel = object()
    fake.CLIPImageProcessor = lambda **kwargs: (calls.append(kwargs), sentinel)[1]
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    profile = SdxlIpStylePreprocessing()
    assert inputs._clip_processor(profile) is sentinel
    assert calls == [
        dict(
            do_resize=False,
            do_center_crop=False,
            do_convert_rgb=False,
            do_rescale=True,
            rescale_factor=profile.rescale_factor,
            do_normalize=True,
            image_mean=list(profile.image_mean),
            image_std=list(profile.image_std),
        )
    ]


def test_module_keeps_python311_syntax_and_no_model_or_storage_execution():
    tree = ast.parse(Path(inputs.__file__).read_text(), feature_version=(3, 11))
    roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not roots.intersection(
        {"torch", "diffusers", "sqlalchemy", "eom_orchestrator", "subprocess"}
    )
    forbidden = {"from_pretrained", "load_file", "save_pretrained", "cuda", "to", "connect"}
    assert not {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }.intersection(forbidden)
    import tomllib

    project = tomllib.loads(Path("services/image_provider/pyproject.toml").read_text())
    assert project["project"]["optional-dependencies"]["sdxl-ip-style"] == ["numpy==2.4.6"]
    assert not any(dep.startswith("numpy") for dep in project["project"]["dependencies"])

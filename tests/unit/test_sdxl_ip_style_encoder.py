"""Numerical fakes/real file scopes, not actual pretrained encoder or visual acceptance."""

from __future__ import annotations

import ast
import hashlib
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import numpy as np
import pytest
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from eom_image_provider import sdxl_ip_style_encoder as encoder
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_ip_style_encoder_input import PreparedSdxlIpStyleEncoderInput

from tests.unit.test_sdxl_ip_style_io import _stage
from tests.unit.test_sdxl_native_lora_contracts import _command_value


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path, monkeypatch):
    store, root, manifest, pointer = _stage(tmp_path, monkeypatch)
    sample = SdxlNativeLoraSample.model_validate(_command_value()["training_samples"][0])
    raw = np.full((1, 3, 224, 224), 0.25, dtype="<f4").tobytes()
    prepared = PreparedSdxlIpStyleEncoderInput(
        sample.source_image,
        SdxlIpStylePreprocessing(),
        _sha(b"rgb"),
        (1, 3, 224, 224),
        raw,
        _sha(raw),
    )
    versions = {
        "torch": "2.7.1+cu128",
        "transformers": "4.56.2",
        "safetensors": "0.6.2",
        "numpy": "2.4.6",
    }
    monkeypatch.setattr(encoder.metadata, "version", lambda name: versions[name])
    calls = []
    projected = np.arange(1024, dtype="float32")[None] / 17

    def encode(inputs, pixels):
        calls.append((inputs, pixels))
        assert inputs.manifest == manifest
        assert os.fstat(inputs.encoder_weights_fd).st_size > 0
        assert not pixels.flags.writeable
        return projected

    monkeypatch.setattr(encoder, "_encode_cpu", encode)
    return store, root, pointer, sample, prepared, projected, calls, versions


def _run(values, **changes):
    store, _, pointer, sample, prepared, *_ = values
    kwargs = dict(
        sample=sample,
        expected_input_sha256=prepared.float32_le_sha256,
        expected_owner_uid=os.getuid(),
    )
    kwargs.update(changes)
    return encoder.encode_sdxl_ip_style_embedding(store, pointer, prepared, **kwargs)


def test_exact_frozen_cfg_negative_zero_positive_projected_no_unit_normalization(
    tmp_path, monkeypatch
):
    values = _fixture(tmp_path, monkeypatch)
    output = _run(values)
    repeated = _run(values)
    assert output == repeated
    assert output.model == values[2] and output.source == values[3].source_image
    assert output.policy == "CPU_FLOAT32_EAGER_GLOBAL_CFG/1.0" and output.shape == (2, 1, 1024)
    assert output.encoder_input_sha256 == values[4].float32_le_sha256
    assert output.source_rgb_sha256 == values[4].source_rgb_sha256
    assert output.preprocessing == values[4].preprocessing
    assert len(output.cfg_float32_le_bytes) == 8192
    assert output.cfg_float32_le_sha256 == _sha(output.cfg_float32_le_bytes)
    batch = np.frombuffer(output.cfg_float32_le_bytes, dtype="<f4").reshape(output.shape)
    assert not batch.flags.writeable and np.array_equal(batch[0], np.zeros((1, 1024)))
    assert np.array_equal(batch[1], values[5]) and np.linalg.norm(batch[1]) > 1
    assert len(values[6]) == 2
    for inputs, _ in values[6]:
        for fd in (inputs.encoder_weights_fd, inputs.adapter_weights_fd):
            with pytest.raises(OSError):
                os.fstat(fd)
    with pytest.raises(FrozenInstanceError):
        output.shape = (1, 1024)


@pytest.mark.parametrize(
    "fault",
    [
        "length",
        "mutable",
        "shape",
        "bytes",
        "declared",
        "nan",
        "inf",
        "source",
        "profile",
        "rgb-hash",
    ],
)
def test_bad_input_fails_before_model_open_and_encoding(tmp_path, monkeypatch, fault):
    values = list(_fixture(tmp_path, monkeypatch))
    prepared = values[4]
    expected = prepared.float32_le_sha256
    if fault == "length":
        prepared = replace(prepared, float32_le_bytes=prepared.float32_le_bytes[:-1])
    elif fault == "mutable":
        prepared = replace(prepared, float32_le_bytes=bytearray(prepared.float32_le_bytes))
    elif fault == "shape":
        prepared = replace(prepared, shape=(1, 224, 224, 3))
    elif fault == "bytes":
        prepared = replace(prepared, float32_le_bytes=bytes(len(prepared.float32_le_bytes)))
    elif fault == "declared":
        prepared = replace(prepared, float32_le_sha256="sha256:" + "f" * 64)
    elif fault in {"nan", "inf"}:
        batch = np.frombuffer(prepared.float32_le_bytes, dtype="<f4").copy()
        batch[0] = np.nan if fault == "nan" else np.inf
        raw = batch.tobytes()
        prepared = replace(prepared, float32_le_bytes=raw, float32_le_sha256=_sha(raw))
        expected = _sha(raw)
    elif fault == "source":
        prepared = replace(
            prepared,
            source=prepared.source.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32}),
        )
    elif fault == "profile":
        prepared = replace(
            prepared,
            preprocessing=prepared.preprocessing.model_copy(update={"processor_resize": True}),
        )
    else:
        prepared = replace(prepared, source_rgb_sha256="not-a-hash")
    values[4] = prepared

    def no_open(*_args, **_kwargs):
        pytest.fail("bad input must not open any weights")

    monkeypatch.setattr(encoder, "open_sdxl_ip_style_load_inputs", no_open)
    with pytest.raises(ProviderError) as error:
        _run(values, expected_input_sha256=expected)
    assert error.value.code == (
        "SDXL_PROBE_HASH_MISMATCH" if fault in {"bytes", "declared"} else "SDXL_PROBE_INPUT_INVALID"
    )
    assert values[6] == []


@pytest.mark.parametrize("package", ["torch", "transformers", "safetensors", "numpy"])
def test_runtime_mismatch_or_absence_cannot_open_model(tmp_path, monkeypatch, package):
    values = _fixture(tmp_path, monkeypatch)
    values[7][package] = "99.0.0"
    with pytest.raises(ProviderError) as error:
        _run(values)
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID" and not values[6]
    monkeypatch.setattr(
        encoder.metadata,
        "version",
        lambda _n: (_ for _ in ()).throw(encoder.metadata.PackageNotFoundError(package)),
    )
    with pytest.raises(ProviderError) as error:
        _run(values)
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID" and not values[6]


@pytest.mark.parametrize(
    "fault", ["shape", "hidden-tokens", "float16", "float64", "nan", "inf", "list"]
)
def test_encoder_projection_is_bounded_finite_global_float32(tmp_path, monkeypatch, fault):
    values = _fixture(tmp_path, monkeypatch)
    output = values[5].copy()
    if fault == "shape":
        output = output[:, :512]
    elif fault == "hidden-tokens":
        output = output[:, None, :]
    elif fault in {"float16", "float64"}:
        output = output.astype(fault)
    elif fault in {"nan", "inf"}:
        output[0, 0] = np.nan if fault == "nan" else np.inf
    else:
        output = output.tolist()
    handles = []

    def encode(inputs, _pixels):
        handles.extend((inputs.encoder_weights_fd, inputs.adapter_weights_fd))
        return output

    monkeypatch.setattr(encoder, "_encode_cpu", encode)
    with pytest.raises(ProviderError) as error:
        _run(values)
    assert error.value.code == "SDXL_PROBE_OUTPUT_INVALID"
    for fd in handles:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_changed_weight_after_success_cannot_return_embedding(tmp_path, monkeypatch):
    values = _fixture(tmp_path, monkeypatch)

    def mutate(_inputs, _pixels):
        weight = values[1] / "models/image_encoder/model.safetensors"
        weight.write_bytes(weight.read_bytes())
        return values[5]

    monkeypatch.setattr(encoder, "_encode_cpu", mutate)
    with pytest.raises(ProviderError) as error:
        _run(values)
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID"


@pytest.mark.parametrize(
    "failure,code",
    [
        (RuntimeError, "SDXL_PROBE_MODEL_INVALID"),
        (OSError, "SDXL_PROBE_MODEL_INVALID"),
        (ImportError, "SDXL_PROBE_MODEL_INVALID"),
        (MemoryError, "SDXL_PROBE_OOM"),
    ],
)
def test_loading_failure_closes_scope_and_never_retries(tmp_path, monkeypatch, failure, code):
    values = _fixture(tmp_path, monkeypatch)
    calls = []

    def failed(inputs, _pixels):
        calls.append(inputs)
        raise failure("synthetic load error")

    monkeypatch.setattr(encoder, "_encode_cpu", failed)
    with pytest.raises(ProviderError) as error:
        _run(values)
    assert error.value.code == code and len(calls) == 1
    for fd in (calls[0].encoder_weights_fd, calls[0].adapter_weights_fd):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_optional_module_has_no_hub_pickle_storage_or_seed_mutation():
    tree = ast.parse(Path(encoder.__file__).read_text(), feature_version=(3, 11))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes.intersection(
        {
            "from_pretrained",
            "load_file",
            "load",
            "save_pretrained",
            "manual_seed",
            "cuda",
            "connect",
        }
    )
    roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not roots.intersection({"eom_orchestrator", "sqlalchemy", "subprocess"})

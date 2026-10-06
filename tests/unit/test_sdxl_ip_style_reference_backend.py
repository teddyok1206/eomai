"""Synthetic tensor/GPU fakes prove matching/cleanup, not diffusion or visual quality."""

from __future__ import annotations

import hashlib
import sys
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from eom_image_contracts import (
    LocalImageSdxlIpStyleModelManifest,
    LocalImageSdxlLineartProbeCommand,
    content_sha256,
    sdxl_ip_style_model_pointer,
)
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from eom_image_contracts.sdxl_photo_style import SdxlPhotoStyleInitialization
from eom_image_provider import sdxl_canny_backend as canny
from eom_image_provider import sdxl_ip_style_embedding as embedding
from eom_image_provider import sdxl_ip_style_reference_backend as backend
from eom_image_provider import sdxl_ip_style_routing as routing
from eom_image_provider import sdxl_matched_random_state as random_state
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_reference_backend import SdxlCannyReferencePixels
from eom_image_provider.sdxl_ip_style_encoder import (
    CFG_SHAPE,
    ENCODER_POLICY,
    PreparedSdxlIpStyleEmbedding,
)
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial

from tests.unit.test_sdxl_ip_style_manifest import _value
from tests.unit.test_sdxl_ip_style_routing import _IP, _Pipeline
from tests.unit.test_sdxl_lineart_probe import _command, _png
from tests.unit.test_sdxl_native_lora_contracts import _command_value


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class _Device:
    def __init__(self, kind, index=None):
        self.type, self.index = kind, index

    def __str__(self):
        return self.type if self.index is None else f"{self.type}:{self.index}"


class _Tensor:
    def __init__(self, array, device=None):
        self.array = np.array(array, copy=True)
        self.device = device or _Device("cpu")
        self.requires_grad = False

    @property
    def shape(self):
        return self.array.shape

    @property
    def dtype(self):
        return str(self.array.dtype)

    @property
    def ndim(self):
        return self.array.ndim

    def numel(self):
        return self.array.size

    def to(self, device, dtype):
        with np.errstate(over="ignore"):
            return _Tensor(self.array.astype(dtype), device)

    def __getitem__(self, key):
        return _Tensor(self.array[key], self.device)

    def detach(self):
        return self

    def cpu(self):
        return _Tensor(self.array)

    def contiguous(self):
        return self

    def numpy(self):
        return self.array


class _Generator:
    created = None

    def __init__(self, device):
        self.device = _Device(device, 0 if device == "cuda" else None)
        self.seed = 0
        self.advance = 0
        self.created.append(self)

    def manual_seed(self, seed):
        self.seed = seed
        return self

    def initial_seed(self):
        return self.seed

    def get_state(self):
        return _Tensor(
            np.frombuffer(self.seed.to_bytes(8, "little") + bytes([self.advance]), dtype="uint8")
        )


def _torch(monkeypatch):
    class OOM(RuntimeError):
        pass

    _Generator.created = []
    torch = SimpleNamespace(
        Tensor=_Tensor,
        Generator=_Generator,
        OutOfMemoryError=OOM,
        uint8="uint8",
        float16="float16",
        float32="float32",
        from_numpy=_Tensor,
        isfinite=lambda value: SimpleNamespace(
            all=lambda: SimpleNamespace(item=lambda: bool(np.isfinite(value.array).all()))
        ),
        count_nonzero=lambda value: SimpleNamespace(
            item=lambda: int(np.count_nonzero(value.array))
        ),
        __version__="2.7.1+cu128",
        version=SimpleNamespace(cuda="12.8"),
        cuda=SimpleNamespace(
            OutOfMemoryError=OOM,
            synchronize=lambda _: None,
            get_device_capability=lambda _: (12, 0),
            get_device_name=lambda _: "synthetic GPU",
            max_memory_allocated=lambda _: 1024,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


def _values(monkeypatch):
    torch = _torch(monkeypatch)
    pipeline = _Pipeline()
    pipeline.unet.device, pipeline.unet.dtype = _Device("cuda", 0), "float16"
    pipeline.unet.config = SimpleNamespace(encoder_hid_dim_type="ip_image_proj")
    pipeline.image_encoder = None
    pipeline.num_timesteps = 21
    pointer = sdxl_ip_style_model_pointer(
        LocalImageSdxlIpStyleModelManifest.model_validate(_value())
    )
    source = SdxlNativeLoraSample.model_validate(
        _command_value()["training_samples"][0]
    ).source_image
    cfg = np.zeros(CFG_SHAPE, dtype="<f4")
    cfg[1] = np.arange(1024) / 103
    raw = cfg.tobytes()
    prepared = PreparedSdxlIpStyleEmbedding(
        pointer,
        source,
        SdxlIpStylePreprocessing(),
        _sha(b"rgb"),
        _sha(b"encoder"),
        ENCODER_POLICY,
        CFG_SHAPE,
        raw,
        _sha(raw),
    )
    versions = {"diffusers": "0.35.2", "transformers": "4.56.2"}
    monkeypatch.setattr(routing.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(routing, "_ip_processor_type", lambda: _IP)
    return torch, pipeline, pointer, prepared


def test_materialization_once_exact_source_hash_and_inplace_changes_rejected(monkeypatch):
    _, pipeline, pointer, prepared = _values(monkeypatch)
    bound = embedding.materialize_sdxl_ip_style_embedding(pipeline, prepared, pointer)
    assert bound.cfg_float32_le_sha256 == prepared.cfg_float32_le_sha256
    assert bound.cast_sha256 != bound.cfg_float32_le_sha256
    assert bound.dtype == "float16" and bound.device == "cuda:0"
    for _ in range(2):
        embedding.validate_bound_sdxl_ip_style_embedding(pipeline, pointer, bound)
    bound.tensor.array[1, 0, 0] += 1
    with pytest.raises(ProviderError, match="SDXL_PROBE_HASH_MISMATCH"):
        embedding.validate_bound_sdxl_ip_style_embedding(pipeline, pointer, bound)


@pytest.mark.parametrize(
    "fault",
    ["bytes", "shape", "hash", "zero", "nan", "overflow", "policy", "model", "rgb", "encoder"],
)
def test_bad_cfg_before_or_during_cast(monkeypatch, fault):
    _, pipeline, pointer, prepared = _values(monkeypatch)
    code = "SDXL_PROBE_INPUT_INVALID"
    if fault == "bytes":
        prepared = replace(prepared, cfg_float32_le_bytes=bytearray(prepared.cfg_float32_le_bytes))
    elif fault == "shape":
        prepared = replace(prepared, shape=(1, 2, 1024))
    elif fault == "hash":
        prepared = replace(prepared, cfg_float32_le_sha256=_sha(b"wrong"))
        code = "SDXL_PROBE_HASH_MISMATCH"
    elif fault in {"zero", "nan", "overflow"}:
        array = np.frombuffer(prepared.cfg_float32_le_bytes, dtype="<f4").copy().reshape(CFG_SHAPE)
        array[0 if fault == "zero" else 1, 0, 0] = {"zero": 1, "nan": np.nan, "overflow": 1e30}[
            fault
        ]
        raw = array.tobytes()
        prepared = replace(prepared, cfg_float32_le_bytes=raw, cfg_float32_le_sha256=_sha(raw))
        if fault == "overflow":
            code = "SDXL_PROBE_OUTPUT_INVALID"
    elif fault == "policy":
        prepared = replace(prepared, policy="UNIT_NORMALIZED")
    elif fault == "model":
        prepared = replace(prepared, model=None)
    else:
        prepared = replace(
            prepared, **{f"{'source_rgb' if fault == 'rgb' else 'encoder_input'}_sha256": "invalid"}
        )
        code = "SDXL_PROBE_MODEL_INVALID"
    with pytest.raises(ProviderError, match=code):
        embedding.materialize_sdxl_ip_style_embedding(pipeline, prepared, pointer)


def test_fresh_seeded_generators_actual_state_hash_equal_no_shared_advancing_generator(monkeypatch):
    torch = _torch(monkeypatch)
    first = random_state.prepare_sdxl_generator(torch, 77, device="cuda")
    second = random_state.prepare_sdxl_generator(torch, 77, device="cuda")
    assert (
        first.generator is not second.generator
        and first.initial_state_sha256 == second.initial_state_sha256
    )
    first.generator.advance += 1
    with pytest.raises(ProviderError, match="SDXL_PROBE_HASH_MISMATCH"):
        random_state.validate_sdxl_generator(torch, first, seed=77)
    random_state.validate_sdxl_generator(torch, second, seed=77)
    with pytest.raises(ProviderError, match="SDXL_PROBE_HASH_MISMATCH"):
        random_state.validate_sdxl_generator(torch, second, seed=78)


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.5, "77"])
def test_invalid_seed_no_generator_created(monkeypatch, seed):
    torch = _torch(monkeypatch)
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        random_state.prepare_sdxl_generator(torch, seed, device="cuda")
    assert _Generator.created == []


def _backend(monkeypatch, tmp_path):
    torch, pipeline, pointer, prepared = _values(monkeypatch)
    pixels = _png(size=(832, 512))
    key = _sha(pixels)
    refs = {key: SdxlCannyReferencePixels(bytes([255]) * (832 * 512 * 3), pixels)}
    model_calls, casts, generated, cleanup = [], [], [], []

    @contextmanager
    def open_pipeline(stack, controller, **kwargs):
        model_calls.append(kwargs)
        try:
            yield pipeline, torch
        finally:
            cleanup.append(True)

    monkeypatch.setattr(backend, "open_sdxl_canny_pipeline", open_pipeline)
    monkeypatch.setattr(
        backend,
        "bind_sdxl_ip_style_adapter",
        lambda *args: routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting()),
    )
    original_cast = embedding.materialize_sdxl_ip_style_embedding

    def cast(*args):
        casts.append(True)
        return original_cast(*args)

    monkeypatch.setattr(backend, "materialize_sdxl_ip_style_embedding", cast)
    monkeypatch.setattr(canny, "require_prompt_capacity", lambda *args, **kwargs: None)

    class CallablePipeline(type(pipeline)):
        def __call__(self, **kwargs):
            generated.append(kwargs)
            kwargs["generator"].advance += 1
            return SimpleNamespace(images=np.zeros((1, 512, 832, 3), dtype="float32"))

    pipeline.__class__ = CallablePipeline
    selected = backend.SdxlIpStyleReferenceDiffusersBackend(
        object(),
        SdxlCannyControlParameters(),
        SdxlPhotoStyleInitialization(
            policy="FIT_GRAYSCALE_WHITE_RGB_832X512/1.0",
            denoising_strength=0.7,
            scheduler_steps=30,
            effective_denoising_steps=21,
            pillow_version="11.3.0",
        ),
        refs,
        {key: prepared},
        tmp_path,
        pointer,
        SdxlIpStyleRouting(),
    )
    lora = SdxlLoraAdapterMaterial(None, b"synthetic", 0.7)
    value = _command()
    value["inference_steps"] = 30
    value["command_sha256"] = content_sha256(
        {key: val for key, val in value.items() if key != "command_sha256"}
    )
    command = LocalImageSdxlLineartProbeCommand.model_validate(value)
    return selected, pipeline, pixels, lora, command, casts, generated, cleanup, model_calls


def test_same_lora_tensor_control_initializer_and_fresh_rng_forwarded_cleanup(
    monkeypatch, tmp_path
):
    selected, pipeline, pixels, lora, command, casts, calls, cleanup, model_calls = _backend(
        monkeypatch, tmp_path
    )
    with selected.open(object(), style_adapter=lora) as session:
        values = [
            session.generate(
                arm=arm,
                conditioning=pixels,
                prompt="fixed",
                negative_prompt="fixed negative",
                seed=77,
                command=command,
            )
            for arm in ("OFF", "ON")
        ]
        assert values[0].cfg_float32_le_sha256 == values[1].cfg_float32_le_sha256
        assert values[0].initial_generator_state_sha256 == values[1].initial_generator_state_sha256
        assert calls[0]["ip_adapter_image_embeds"][0] is calls[1]["ip_adapter_image_embeds"][0]
        assert calls[0]["generator"] is not calls[1]["generator"]
        assert calls[0]["image"].tobytes() == calls[1]["image"].tobytes()
        assert calls[0]["control_image"].tobytes() == calls[1]["control_image"].tobytes()
        assert casts == [True] and len(_Generator.created) == 2
    assert cleanup == [True] and session._embeddings == {} and session._scales is None
    assert model_calls[0]["style_adapter"] is lora
    assert all(
        proc.scale == [0.0] for proc in pipeline.unet.attn_processors.values() if type(proc) is _IP
    )
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        session.generate(
            arm="OFF",
            conditioning=pixels,
            prompt="fixed",
            negative_prompt="",
            seed=77,
            command=command,
        )


@pytest.mark.parametrize("fault", ["inference", "timesteps", "tensor"])
def test_inference_failure_resets_zero_poisons_session_no_retry(monkeypatch, tmp_path, fault):
    selected, pipeline, pixels, lora, command, _, calls, cleanup, _ = _backend(
        monkeypatch, tmp_path
    )
    original = backend.generate_sdxl_canny_background

    def fail(*args, **kwargs):
        if fault == "inference":
            raise ProviderError("SDXL_PROBE_EXEC_FAILED")
        value = original(*args, **kwargs)
        if fault == "timesteps":
            pipeline.num_timesteps = 8
        else:
            kwargs["image_arguments"]["ip_adapter_image_embeds"][0].array[1, 0, 0] += 1
        return value

    monkeypatch.setattr(backend, "generate_sdxl_canny_background", fail)
    with selected.open(object(), style_adapter=lora) as session:
        with pytest.raises(ProviderError):
            session.generate(
                arm="ON",
                conditioning=pixels,
                prompt="fixed",
                negative_prompt="",
                seed=77,
                command=command,
            )
        count = len(calls)
        with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
            session.generate(
                arm="OFF",
                conditioning=pixels,
                prompt="fixed",
                negative_prompt="",
                seed=77,
                command=command,
            )
        assert len(calls) == count
    assert cleanup == [True]
    assert all(
        proc.scale == [0.0] for proc in pipeline.unet.attn_processors.values() if type(proc) is _IP
    )


@pytest.mark.parametrize("fault", ["device", "dtype", "encoder", "projection", "grad", "nan"])
def test_bound_tensor_pipeline_drift_rejected(monkeypatch, fault):
    _, pipeline, pointer, prepared = _values(monkeypatch)
    bound = embedding.materialize_sdxl_ip_style_embedding(pipeline, prepared, pointer)
    if fault == "device":
        pipeline.unet.device = _Device("cpu")
    elif fault == "dtype":
        pipeline.unet.dtype = "float32"
    elif fault == "encoder":
        pipeline.image_encoder = object()
    elif fault == "projection":
        pipeline.unet.config.encoder_hid_dim_type = "text_proj"
    elif fault == "grad":
        bound.tensor.requires_grad = True
    else:
        bound.tensor.array[1, 0, 0] = np.nan
    with pytest.raises(ProviderError):
        embedding.validate_bound_sdxl_ip_style_embedding(pipeline, pointer, bound)


@pytest.mark.parametrize("stage", ["attach", "cast", "body"])
def test_pipeline_owner_cleanup_on_prepare_or_body_failure(monkeypatch, tmp_path, stage):
    selected, _, _, lora, _, _, calls, cleanup, _ = _backend(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise ProviderError("SDXL_PROBE_MODEL_INVALID")

    if stage == "attach":
        monkeypatch.setattr(backend, "bind_sdxl_ip_style_adapter", fail)
    elif stage == "cast":
        monkeypatch.setattr(backend, "materialize_sdxl_ip_style_embedding", fail)
    with (
        pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"),
        selected.open(object(), style_adapter=lora),
    ):
        fail()
    assert cleanup == [True] and calls == []


def test_missing_lora_before_open_and_unknown_conditioning_before_inference(monkeypatch, tmp_path):
    selected, _, _, lora, command, _, calls, cleanup, opens = _backend(monkeypatch, tmp_path)
    with (
        pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"),
        selected.open(object(), style_adapter=None),
    ):
        pytest.fail("missing LoRA admitted")
    assert opens == []
    with (
        selected.open(object(), style_adapter=lora) as session,
        pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"),
    ):
        session.generate(
            arm="ON",
            conditioning=b"unknown",
            prompt="fixed",
            negative_prompt="",
            seed=77,
            command=command,
        )
    assert calls == [] and cleanup == [True]


@pytest.mark.parametrize("fault", ["missing", "empty", "hash", "key", "too-many"])
def test_bounded_matching_case_map_before_gpu_open(monkeypatch, tmp_path, fault):
    _, _, pointer, prepared = _values(monkeypatch)
    raw = _png(size=(832, 512))
    inputs = {_sha(raw): SdxlCannyReferencePixels(b"", raw)}
    embeds = {_sha(raw): prepared}
    if fault == "missing":
        embeds = {}
    elif fault == "empty":
        inputs = embeds = {}
    elif fault == "hash":
        inputs = {_sha(b"wrong"): next(iter(inputs.values()))}
        embeds = {_sha(b"wrong"): prepared}
    elif fault == "key":
        inputs = {"invalid": next(iter(inputs.values()))}
        embeds = {"invalid": prepared}
    else:
        inputs = {
            _sha(bytes([index])): SdxlCannyReferencePixels(b"", bytes([index]))
            for index in range(3)
        }
        embeds = {key: prepared for key in inputs}
    with pytest.raises(ProviderError):
        backend.SdxlIpStyleReferenceDiffusersBackend(
            object(),
            SdxlCannyControlParameters(),
            object(),
            inputs,
            embeds,
            tmp_path,
            pointer,
            SdxlIpStyleRouting(),
        )


@pytest.mark.parametrize("fault", ["dtype", "shape", "bound", "cpu", "device", "bool-seed"])
def test_random_state_shape_dtype_device_and_forged_seed(monkeypatch, fault):
    torch = _torch(monkeypatch)
    state = random_state.prepare_sdxl_generator(torch, 1, device="cuda")
    if fault in {"dtype", "shape", "bound", "cpu"}:
        values = {
            "dtype": np.zeros(5, dtype="float32"),
            "shape": np.zeros((2, 3), dtype="uint8"),
            "bound": np.zeros(65537, dtype="uint8"),
            "cpu": np.zeros(5, dtype="uint8"),
        }
        tensor = _Tensor(values[fault], _Device("cuda") if fault == "cpu" else None)
        state.generator.get_state = lambda: tensor
    elif fault == "device":
        state.generator.device = _Device("cuda", 1)
    else:
        state = replace(state, seed=True)
    with pytest.raises(ProviderError):
        random_state.validate_sdxl_generator(torch, state, seed=1)

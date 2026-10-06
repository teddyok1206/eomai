"""Held-file/loader fakes, not real pretrained attachment, diffusion or quality PASS."""

from __future__ import annotations

import ast
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting
from eom_image_provider import sdxl_ip_style_adapter as adapter
from eom_image_provider.provider import ProviderError

from tests.unit.test_sdxl_ip_style_io import _stage

SELF = "up_blocks.0.attentions.1.transformer_blocks.0.attn1.processor"
CROSS = "up_blocks.0.attentions.1.transformer_blocks.0.attn2.processor"
MID = "mid_block.attentions.0.transformer_blocks.0.attn2.processor"


class _Tensor:
    def __init__(self, shape):
        self.shape = shape
        self.dtype = "float32"
        self.device = SimpleNamespace(type="cpu")
        self.finite = True


class _UNet:
    def __init__(self):
        self.config = SimpleNamespace(
            cross_attention_dim=2048,
            block_out_channels=(320, 640, 1280),
            encoder_hid_dim_type=None,
        )
        self.encoder_hid_proj = None
        self.attn_processors = {SELF: object(), CROSS: object(), MID: object()}
        self.parameters = {"base": object(), "lora_A": object(), "lora_B": object()}
        self.modules = {
            name.removesuffix(".processor"): SimpleNamespace(
                to_q=SimpleNamespace(weight=_Tensor((1280, 1280))),
                to_k=SimpleNamespace(weight=_Tensor((1280, 2048))),
                to_v=SimpleNamespace(weight=_Tensor((1280, 2048))),
            )
            for name in (CROSS, MID)
        }

    def get_submodule(self, name):
        return self.modules[name]

    def named_parameters(self):
        return self.parameters.items()


def _fixture(tmp_path, monkeypatch):
    store, root, _manifest, pointer = _stage(tmp_path, monkeypatch)
    pipeline = SimpleNamespace(unet=_UNet(), image_encoder=None)
    events = []
    state = {name: _Tensor(shape) for name, shape in adapter._adapter_shapes(pipeline.unet).items()}

    class Reader:
        def keys(self):
            return list(state)

        def get_tensor(self, name):
            events.append(("tensor", name))
            return state[name]

    @contextmanager
    def safe_open(path, *, framework):
        fd = int(path.removeprefix("/proc/self/fd/"))
        assert framework == "pt" and os.fstat(fd).st_size > 0
        events.append(("read", path))
        yield Reader()
        events.append(("close", path))

    class OOM(RuntimeError):
        pass

    torch = SimpleNamespace(
        float16="float16",
        float32="float32",
        OutOfMemoryError=OOM,
        isfinite=lambda tensor: SimpleNamespace(
            all=lambda: SimpleNamespace(item=lambda: tensor.finite)
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "safetensors", SimpleNamespace(safe_open=safe_open))
    versions = {"torch": "2.7.1+cu128", "diffusers": "0.35.2", "safetensors": "0.6.2"}
    monkeypatch.setattr(adapter.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(adapter, "_validate_pipeline", lambda _pipeline: None)

    def load(value, **kwargs):
        events.append(("load", value, kwargs))
        assert set(value) == {"image_proj", "ip_adapter"}
        assert set(value["image_proj"]) == {"proj.weight", "proj.bias", "norm.weight", "norm.bias"}
        assert set(value["ip_adapter"]) == {
            "1.to_k_ip.weight",
            "1.to_v_ip.weight",
            "3.to_k_ip.weight",
            "3.to_v_ip.weight",
        }
        pipeline.unet.config.encoder_hid_dim_type = "ip_image_proj"

    pipeline.load_ip_adapter = load
    pipeline.set_ip_adapter_scale = lambda scale: events.append(("scale", scale))
    session = object()

    def make_session(current, routing):
        assert current is pipeline and routing == SdxlIpStyleRouting()
        events.append(("session",))
        return session

    monkeypatch.setattr(adapter, "SdxlIpStyleScaleSession", make_session)
    return store, root, pointer, pipeline, events, state, versions, session, torch


def _run(values):
    return adapter.bind_sdxl_ip_style_adapter(
        values[3], values[0], values[2], SdxlIpStyleRouting(), expected_owner_uid=os.getuid()
    )


def test_verified_fd_public_dict_loader_no_encoder_no_hub_and_state_cleanup(tmp_path, monkeypatch):
    values = _fixture(tmp_path, monkeypatch)
    assert _run(values) is values[7]
    events = values[4]
    load = next(event for event in events if event[0] == "load")
    assert load[2] == dict(
        subfolder="",
        weight_name="ip-adapter_sdxl_vit-h.safetensors",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=False,
    )
    assert load[1] == {"image_proj": {}, "ip_adapter": {}}
    assert [event[0] for event in events][-3:] == ["close", "scale", "session"]
    descriptor = int(events[0][1].removeprefix("/proc/self/fd/"))
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize("fault", ["missing", "extra", "plus", "faceid"])
def test_exact_global_keys_before_any_tensor_or_pipeline_mutation(tmp_path, monkeypatch, fault):
    values = _fixture(tmp_path, monkeypatch)
    state = values[5]
    if fault == "missing":
        state.pop("ip_adapter.1.to_v_ip.weight")
    elif fault == "extra":
        state["ip_adapter.2.to_q_lora.down.weight"] = _Tensor((8, 2048))
    elif fault == "plus":
        state["image_proj.latents"] = state.pop("image_proj.proj.weight")
    else:
        state["image_proj.proj.0.weight"] = state.pop("image_proj.proj.weight")
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        _run(values)
    assert not any(event[0] in {"tensor", "load", "scale", "session"} for event in values[4])


@pytest.mark.parametrize("fault", ["shape", "integer", "float64", "gpu", "nonfinite"])
def test_tensor_gate_before_public_loader(tmp_path, monkeypatch, fault):
    values = _fixture(tmp_path, monkeypatch)
    tensor = values[5]["ip_adapter.3.to_v_ip.weight"]
    if fault == "shape":
        tensor.shape = (1281, 2048)
    elif fault in {"integer", "float64"}:
        tensor.dtype = fault
    elif fault == "gpu":
        tensor.device.type = "cuda"
    else:
        tensor.finite = False
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        _run(values)
    assert not any(event[0] in {"load", "scale", "session"} for event in values[4])


def test_float16_cpu_state_allowed(tmp_path, monkeypatch):
    values = _fixture(tmp_path, monkeypatch)
    for tensor in values[5].values():
        tensor.dtype = "float16"
    assert _run(values) is values[7]


@pytest.mark.parametrize(
    "fault", ["base", "lora_A", "lora_B", "encoder", "projection", "loader", "oom"]
)
def test_partial_load_no_repair_retry_or_session_and_state_cleared(tmp_path, monkeypatch, fault):
    values = _fixture(tmp_path, monkeypatch)
    pipeline = values[3]
    original = pipeline.load_ip_adapter

    def failing(value, **kwargs):
        original(value, **kwargs)
        if fault in {"base", "lora_A", "lora_B"}:
            pipeline.unet.parameters[fault] = object()
        elif fault == "encoder":
            pipeline.image_encoder = object()
        elif fault == "projection":
            pipeline.unet.config.encoder_hid_dim_type = "text_proj"
        elif fault == "oom":
            raise values[8].OutOfMemoryError("synthetic allocation failure")
        else:
            raise RuntimeError("synthetic partial load")

    pipeline.load_ip_adapter = failing
    code = "SDXL_PROBE_OOM" if fault == "oom" else "SDXL_PROBE_MODEL_INVALID"
    with pytest.raises(ProviderError, match=code):
        _run(values)
    loads = [event for event in values[4] if event[0] == "load"]
    assert len(loads) == 1 and loads[0][1] == {"image_proj": {}, "ip_adapter": {}}
    assert not any(event[0] in {"scale", "session"} for event in values[4])


@pytest.mark.parametrize(
    "member", ["manifest.json", "sdxl_models/ip-adapter_sdxl_vit-h.safetensors"]
)
def test_final_replacement_never_returns_session(tmp_path, monkeypatch, member):
    values = _fixture(tmp_path, monkeypatch)
    original = adapter.SdxlIpStyleScaleSession

    def mutate(current, routing):
        candidate = values[1] / member
        replacement = candidate.with_suffix(".replacement")
        replacement.write_bytes(candidate.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(candidate)
        return original(current, routing)

    monkeypatch.setattr(adapter, "SdxlIpStyleScaleSession", mutate)
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        _run(values)


@pytest.mark.parametrize("name", ["torch", "diffusers", "safetensors"])
def test_runtime_drift_before_model_read(tmp_path, monkeypatch, name):
    values = _fixture(tmp_path, monkeypatch)
    values[6][name] = "999.0.0"
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        _run(values)
    assert values[4] == []


@pytest.mark.parametrize("fault", ["shape", "name", "none", "cross-dim"])
def test_invalid_public_attention_shape_map(fault):
    unet = _UNet()
    if fault == "shape":
        unet.modules[CROSS.removesuffix(".processor")].to_k.weight.shape = (1, 2)
    elif fault == "name":
        unet.attn_processors["unrecognized"] = object()
    elif fault == "none":
        unet.attn_processors = {SELF: object()}
    else:
        unet.config.cross_attention_dim = False
    with pytest.raises(ValueError):
        adapter._adapter_shapes(unet)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "channels",
        "cross-dim",
        "projection",
        "projection-kind",
        "encoder",
        "loader",
        "scale",
        "empty",
        "processor",
        "subclass",
    ],
)
def test_fresh_closed_pipeline_gate_before_model_loading(monkeypatch, fault):
    class AttnProcessor2_0:
        pass

    monkeypatch.setitem(
        sys.modules,
        "diffusers.models.attention_processor",
        SimpleNamespace(AttnProcessor2_0=AttnProcessor2_0),
    )
    unet = _UNet()
    unet.attn_processors = {name: AttnProcessor2_0() for name in unet.attn_processors}
    pipeline = SimpleNamespace(
        unet=unet,
        image_encoder=None,
        load_ip_adapter=lambda *args, **kwargs: None,
        set_ip_adapter_scale=lambda scale: None,
    )
    if fault == "channels":
        unet.config.block_out_channels = (1, 2, 3)
    elif fault == "cross-dim":
        unet.config.cross_attention_dim = 1024
    elif fault == "projection":
        unet.encoder_hid_proj = object()
    elif fault == "projection-kind":
        unet.config.encoder_hid_dim_type = "text_proj"
    elif fault == "encoder":
        pipeline.image_encoder = object()
    elif fault == "loader":
        pipeline.load_ip_adapter = None
    elif fault == "scale":
        pipeline.set_ip_adapter_scale = None
    elif fault == "empty":
        unet.attn_processors = {}
    elif fault == "processor":
        unet.attn_processors[SELF] = object()
    elif fault == "subclass":

        class Other(AttnProcessor2_0):
            pass

        unet.attn_processors[SELF] = Other()
    if fault is None:
        adapter._validate_pipeline(pipeline)
    else:
        with pytest.raises(ValueError, match="SDXL_IP_STYLE_PIPELINE_NOT_FRESH"):
            adapter._validate_pipeline(pipeline)


def test_adapter_module_no_hub_pickle_private_diffusers_or_inference_calls():
    path = Path(adapter.__file__)
    tree = ast.parse(path.read_text())
    forbidden = {
        "from_pretrained",
        "torch.load",
        "hf_hub_download",
        "snapshot_download",
        "get_tensor_from_file",
        "_load_ip_adapter_weights",
        "_convert_ip_adapter_attn_to_diffusers",
        "unload_ip_adapter",
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes.intersection(forbidden)
    assert "load_ip_adapter" in attributes and "adapter_weights_fd" in attributes

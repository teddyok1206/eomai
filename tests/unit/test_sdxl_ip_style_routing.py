"""Fake scales prove scope isolation, not real diffusion/embedding or quality acceptance."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting
from eom_image_provider import sdxl_ip_style_routing as routing
from eom_image_provider.provider import ProviderError

SELF = "up_blocks.0.attentions.1.transformer_blocks.0.attn1.processor"
STYLE = "up_blocks.0.attentions.1.transformer_blocks.0.attn2.processor"
STYLE2 = "up_blocks.0.attentions.1.transformer_blocks.1.attn2.processor"
LAYOUT = "down_blocks.1.attentions.0.transformer_blocks.0.attn2.processor"
MID = "mid_block.attentions.0.transformer_blocks.0.attn2.processor"


class _IP:
    def __init__(self):
        self.scale = [0.0]


class _Pipeline:
    def __init__(self):
        self.unet = SimpleNamespace(
            attn_processors={SELF: object(), STYLE: _IP(), STYLE2: _IP(), LAYOUT: _IP(), MID: _IP()}
        )
        self.calls = []
        self.fault = None

    def set_ip_adapter_scale(self, scale):
        self.calls.append(scale)
        for name, proc in self.unet.attn_processors.items():
            if type(proc) is _IP:
                proc.scale = [1.0 if isinstance(scale, dict) and name in {STYLE, STYLE2} else 0.0]
        if isinstance(scale, dict):
            if self.fault == "setter":
                raise ValueError("partial scale setter failure")
            if self.fault == "noop":
                self.unet.attn_processors[STYLE].scale = [0.0]
            elif self.fault == "layout":
                self.unet.attn_processors[LAYOUT].scale = [1.0]
            elif self.fault == "replace":
                self.unet.attn_processors[SELF] = object()
        if scale == 0.0 and self.fault == "reset":
            self.unet.attn_processors[STYLE].scale = [1.0]


def _fixture(monkeypatch):
    monkeypatch.setattr(routing.metadata, "version", lambda _name: "0.35.2")
    monkeypatch.setattr(routing, "_ip_processor_type", lambda: _IP)
    return _Pipeline()


def _all_zero(pipeline):
    return all(p.scale == [0.0] for p in pipeline.unet.attn_processors.values() if type(p) is _IP)


def test_public_setter_on_only_style_and_off_reset_zero_no_processor_replacement(monkeypatch):
    pipeline = _fixture(monkeypatch)
    original = dict(pipeline.unet.attn_processors)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    for arm in ("OFF", "ON", "OFF", "ON"):
        with session.arm(arm) as trace:
            assert trace.arm == arm and trace.scales == tuple(sorted(trace.scales))
            assert dict(trace.scales) == {
                STYLE: 1.0 if arm == "ON" else 0.0,
                STYLE2: 1.0 if arm == "ON" else 0.0,
                MID: 0.0,
                LAYOUT: 0.0,
            }
            assert all(pipeline.unet.attn_processors[k] is p for k, p in original.items())
            with pytest.raises(FrozenInstanceError):
                trace.arm = "ON"
        assert _all_zero(pipeline)
    assert pipeline.calls == [
        0.0,
        0.0,
        {"up": {"block_0": [0.0, 1.0, 0.0]}},
        0.0,
        0.0,
        0.0,
        {"up": {"block_0": [0.0, 1.0, 0.0]}},
        0.0,
    ]


@pytest.mark.parametrize(
    "scale", [[1.0], [float("nan")], [float("inf")], [0], [False], [0.0, 0.0], [], (0.0,), None]
)
def test_entry_requires_one_exact_zero_scale_before_any_setter(monkeypatch, scale):
    pipeline = _fixture(monkeypatch)
    pipeline.unet.attn_processors[STYLE].scale = scale
    with pytest.raises(ProviderError) as error:
        routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID" and pipeline.calls == []


@pytest.mark.parametrize(
    "fault", ["missing", "self-ip", "cross-not-ip", "unsupported-subclass", "unknown-key"]
)
def test_unrecognized_or_missing_structure_is_not_silently_noop(monkeypatch, fault):
    pipeline = _fixture(monkeypatch)
    processors = pipeline.unet.attn_processors
    if fault == "missing":
        del processors[STYLE]
        del processors[STYLE2]
    elif fault == "self-ip":
        processors[SELF] = _IP()
    elif fault == "cross-not-ip":
        processors[LAYOUT] = object()
    elif fault == "unsupported-subclass":

        class OtherIP(_IP):
            pass

        processors[STYLE] = OtherIP()
    else:
        processors["up_blocks.0.attentions.10.transformer_blocks.0.attn2.processor-extra"] = _IP()
    with pytest.raises(ProviderError) as error:
        routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID" and pipeline.calls == []


def test_runtime_and_routing_revalidation_before_mutation(monkeypatch):
    pipeline = _fixture(monkeypatch)
    invalid = SdxlIpStyleRouting().model_copy(update={"on_scale": 0.5})
    with pytest.raises(ProviderError):
        routing.SdxlIpStyleScaleSession(pipeline, invalid)
    monkeypatch.setattr(routing.metadata, "version", lambda _name: "0.35.3")
    with pytest.raises(ProviderError):
        routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    assert pipeline.calls == []
    monkeypatch.setattr(routing.metadata, "version", lambda _name: "0.35.2")

    def unavailable():
        raise ImportError("optional numerical runtime unavailable")

    monkeypatch.setattr(routing, "_ip_processor_type", unavailable)
    with pytest.raises(ProviderError):
        routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())


@pytest.mark.parametrize("fault", ["setter", "noop", "layout", "replace", "reset"])
def test_partial_set_wrong_routing_or_reset_fails_and_session_cannot_be_reused(monkeypatch, fault):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    pipeline.fault = fault
    body_calls = []
    with pytest.raises(ProviderError) as error, session.arm("ON"):
        body_calls.append(True)
    assert error.value.code == "SDXL_PROBE_MODEL_INVALID"
    assert body_calls == ([True] if fault == "reset" else [])
    assert pipeline.calls[-1] == 0.0
    assert _all_zero(pipeline) == (fault != "reset")
    count = len(pipeline.calls)
    pipeline.fault = None
    with pytest.raises(ProviderError), session.arm("OFF"):
        pytest.fail("failed scope reused")
    assert len(pipeline.calls) == count


@pytest.mark.parametrize(
    "error", [RuntimeError("body error"), KeyboardInterrupt(), ProviderError("SDXL_PROBE_OOM")]
)
def test_exception_preserved_after_reset_and_no_automatic_retry(monkeypatch, error):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    with pytest.raises(type(error)) as caught, session.arm("ON"):
        raise error
    assert caught.value is error and _all_zero(pipeline)
    with pytest.raises(ProviderError), session.arm("OFF"):
        pytest.fail("failed scope reused")
    assert len(pipeline.calls) == 2


@pytest.mark.parametrize(
    "fault", ["scale", "self-replaced", "ip-replaced", "key-added", "key-removed"]
)
def test_mid_scope_change_fails_after_body_and_still_resets(monkeypatch, fault):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    with pytest.raises(ProviderError), session.arm("ON"):
        processors = pipeline.unet.attn_processors
        if fault == "scale":
            processors[MID].scale = [1.0]
        elif fault == "self-replaced":
            processors[SELF] = object()
        elif fault == "ip-replaced":
            processors[STYLE] = _IP()
        elif fault == "key-added":
            processors["unexpected"] = object()
        else:
            del processors[LAYOUT]
    assert _all_zero(pipeline) and pipeline.calls[-1] == 0.0


def test_between_arm_contamination_and_invalid_arm_fail_before_setter(monkeypatch):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    with pytest.raises(ProviderError) as error, session.arm("AUTO"):
        pytest.fail("invalid arm")
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID"
    pipeline.unet.attn_processors[LAYOUT].scale = [1.0]
    with pytest.raises(ProviderError), session.arm("ON"):
        pytest.fail("contaminated scope")
    assert pipeline.calls == []


def test_same_session_overlap_rejected_without_mutating_active_arm(monkeypatch):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    with session.arm("ON") as trace:
        count = len(pipeline.calls)
        with pytest.raises(ProviderError), session.arm("OFF"):
            pytest.fail("overlap admitted")
        assert len(pipeline.calls) == count
        assert session._validate_scales("ON") == trace
    assert _all_zero(pipeline)
    with session.arm("OFF"):
        pass


def test_module_is_optional_python311_no_model_inference_storage_or_global_registry():
    source = Path(routing.__file__).read_text()
    tree = ast.parse(source, feature_version=(3, 11))
    forbidden = {
        "from_pretrained",
        "load_ip_adapter",
        "unload_ip_adapter",
        "cuda",
        "connect",
        "generate",
        "execute",
        "set_attn_processor",
    }
    assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}.intersection(
        forbidden
    )
    assert "eom_orchestrator" not in source and "sqlalchemy" not in source
    assert not any(
        isinstance(n.value, (ast.Dict, ast.List, ast.Set))
        for n in tree.body
        if isinstance(n, ast.Assign)
    )


def test_concurrent_call_rejected_without_waiting_or_changing_active_scale(monkeypatch):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())

    def other_arm():
        try:
            with session.arm("OFF"):
                return "ACCEPTED"
        except ProviderError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as pool, session.arm("ON") as trace:
        count = len(pipeline.calls)
        assert pool.submit(other_arm).result(timeout=2) == "SDXL_PROBE_MODEL_INVALID"
        assert len(pipeline.calls) == count
        assert session._validate_scales("ON") == trace
    assert _all_zero(pipeline)


@pytest.mark.parametrize("arm", [None, False, [], {}, "AUTO"])
def test_invalid_arm_value_fails_before_lock_or_mutation(monkeypatch, arm):
    pipeline = _fixture(monkeypatch)
    session = routing.SdxlIpStyleScaleSession(pipeline, SdxlIpStyleRouting())
    with pytest.raises(ProviderError) as caught, session.arm(arm):
        pytest.fail("invalid arm admitted")
    assert caught.value.code == "SDXL_PROBE_INPUT_INVALID" and pipeline.calls == []
    with session.arm("OFF"):
        pass

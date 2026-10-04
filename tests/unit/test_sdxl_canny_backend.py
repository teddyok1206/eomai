"""Offline calls and resource failures; fake tensors do not certify CUDA/image quality."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from eom_image_contracts import LocalImageSdxlLineartProbeCommand, LocalImageSdxlLineartStack
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_provider import sdxl_canny_backend as backend
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_controller_io import ResolvedSdxlCannyController
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack
from PIL import Image

from tests.unit.test_sdxl_canny_controller import _manifest
from tests.unit.test_sdxl_lineart_backend import _Tokenizer
from tests.unit.test_sdxl_lineart_probe import _command, _png
from tests.unit.test_sdxl_lineart_stack_contract import _stack


@pytest.mark.parametrize(
    "fault", [None, "tokens", "shape", "nan", "range", "architecture", "gpu", "oom", "unexpected"]
)
@pytest.mark.parametrize("use_lora", [False, True])
def test_exact_control_offline_loading_no_t2i_offload_and_cleanup(
    monkeypatch, tmp_path, fault, use_lora
):
    calls = []
    array = np.ones((1, 512, 832, 3), dtype=np.float32)
    if fault == "nan":
        array[0, 0, 0, 0] = np.nan
    elif fault == "range":
        array[0, 0, 0, 0] = 1.01
    elif fault == "shape":
        array = array[:, :, :800]
    controller = SimpleNamespace(
        config=SimpleNamespace(
            addition_embed_type="text_time",
            conditioning_channels=3,
            cross_attention_dim=2048 if fault != "architecture" else 768,
        ),
        dtype="fp16",
    )

    class Oom(RuntimeError):
        pass

    class Pipeline:
        def __init__(self):
            self.unet = SimpleNamespace(
                config=SimpleNamespace(
                    block_out_channels=(320, 640, 1280), cross_attention_dim=2048
                ),
                dtype="fp16",
            )
            self.controlnet = controller
            self.vae = SimpleNamespace(dtype="fp16")
            self.tokenizer = _Tokenizer(78 if fault == "tokens" else 25)
            self.tokenizer_2 = _Tokenizer(25)

        def set_progress_bar_config(self, **kwargs):
            pass

        def to(self, device):
            calls.append(("to", device))

        def __call__(self, **kwargs):
            calls.append(("inference", kwargs))
            assert kwargs["controlnet_conditioning_scale"] == 1.0
            assert kwargs["control_guidance_start"] == 0.0 and kwargs["control_guidance_end"] == 1.0
            assert kwargs["width"] == 832 and kwargs["height"] == 512
            assert "adapter_conditioning_scale" not in kwargs and kwargs["output_type"] == "np"
            assert kwargs["num_inference_steps"] == command.inference_steps
            assert kwargs["guidance_scale"] == command.guidance_scale
            if fault == "oom":
                raise Oom()
            if fault == "unexpected":
                raise RuntimeError("synthetic")
            return SimpleNamespace(images=array)

    pipelines = []

    def load(component, root, **kwargs):
        assert Path(root).is_relative_to(tmp_path)
        assert "LINEART_ADAPTER" not in root and kwargs["local_files_only"] is True
        assert "add_watermarker" not in kwargs
        if component != "scheduler":
            assert kwargs["use_safetensors"] is True and kwargs["torch_dtype"] == "fp16"
        if component in {"controller", "pipeline"}:
            assert kwargs["variant"] == "fp16"
        calls.append(("load", component))
        if component == "controller":
            return controller
        if component == "pipeline":
            assert kwargs["controlnet"] is controller
            pipe = Pipeline()
            pipelines.append(pipe)
            return pipe
        return object()

    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: fault != "gpu",
            get_device_capability=lambda i: (12, 0),
            reset_peak_memory_stats=lambda i: None,
            synchronize=lambda i: None,
            get_device_name=lambda i: "fixture GPU",
            max_memory_allocated=lambda i: 1024,
            empty_cache=lambda: calls.append(("cleanup", None)),
            OutOfMemoryError=Oom,
        ),
        float16="fp16",
        __version__="2.7.1+cu128",
        version=SimpleNamespace(cuda="12.8"),
        Generator=lambda **k: SimpleNamespace(manual_seed=lambda s: s),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(
            AutoencoderKL=SimpleNamespace(from_pretrained=lambda p, **k: load("vae", p, **k)),
            ControlNetModel=SimpleNamespace(
                from_pretrained=lambda p, **k: load("controller", p, **k)
            ),
            EulerAncestralDiscreteScheduler=SimpleNamespace(
                from_pretrained=lambda p, **k: load("scheduler", p, **k)
            ),
            StableDiffusionXLControlNetPipeline=SimpleNamespace(
                from_pretrained=lambda p, **k: load("pipeline", p, **k)
            ),
        ),
    )
    monkeypatch.setattr(
        backend.metadata, "version", lambda p: "0.35.2" if p == "diffusers" else "4.56.2"
    )
    monkeypatch.setattr(
        backend, "apply_sdxl_lora", lambda unet, material: calls.append(("lora", material))
    )
    stack = ResolvedSdxlStack(
        manifest=LocalImageSdxlLineartStack.model_validate(_stack()),
        component_roots={role: tmp_path / role for role in ("BASE", "LINEART_ADAPTER", "VAE")},
    )
    resolved = ResolvedSdxlCannyController(manifest=_manifest(), root=tmp_path / "controller")
    style = (
        SimpleNamespace(manifest=SimpleNamespace(base_model=stack.manifest)) if use_lora else None
    )
    command = LocalImageSdxlLineartProbeCommand.model_validate(_command())

    def execute():
        with backend.SdxlCannyDiffusersBackend(resolved, SdxlCannyControlParameters()).open(
            stack, style_adapter=style
        ) as session:
            result = session.generate(
                conditioning=_png(size=(832, 512)),
                prompt="scientific line art",
                negative_prompt="text, color",
                seed=1,
                command=command,
            )
            with Image.open(io.BytesIO(result.png_bytes)) as image:
                assert image.size == (832, 512) and image.mode == "RGB"
            assert result.runtime.peak_gpu_memory_bytes == 1024
        assert session.pipeline is None

    if fault:
        code = {
            "tokens": "PROMPT_TRUNCATED",
            "shape": "OUTPUT_INVALID",
            "nan": "OUTPUT_INVALID",
            "range": "OUTPUT_INVALID",
            "architecture": "MODEL_INVALID",
            "gpu": "GPU_UNAVAILABLE",
            "oom": "OOM",
            "unexpected": "EXEC_FAILED",
        }[fault]
        with pytest.raises(ProviderError, match="SDXL_PROBE_" + code):
            execute()
        if fault in {"tokens", "architecture", "gpu"}:
            assert not any(name == "inference" for name, _ in calls)
    else:
        execute()
        assert [value for name, value in calls if name == "load"] == [
            "controller",
            "vae",
            "scheduler",
            "pipeline",
        ]
    if fault != "gpu":
        assert calls[-1][0] == "cleanup"
    assert sum(name == "lora" for name, _ in calls) == int(
        use_lora and fault not in {"gpu", "architecture"}
    )
    assert not any("offload" in name for name, _ in calls)

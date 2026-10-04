from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from eom_image_contracts import (
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartStack,
    content_sha256,
)
from eom_image_provider import sdxl_lineart_backend as backend
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack
from PIL import Image

from tests.unit.test_sdxl_lineart_probe import _command, _png
from tests.unit.test_sdxl_lineart_stack_contract import _stack


class _Tokenizer:
    model_max_length = 77

    def __init__(self, count: int) -> None:
        self.count = count

    def __call__(self, _prompt: str, **kwargs: object) -> dict[str, list[int]]:
        assert kwargs["truncation"] is False
        return {"input_ids": list(range(self.count))}


@pytest.mark.parametrize("fault", [None, "tokens", "shape", "nan", "architecture", "gpu", "oom"])
@pytest.mark.parametrize("conditioning_scale", [0.0, 0.8])
def test_offline_load_architecture_prompt_capacity_numerics_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str | None,
    conditioning_scale: float,
) -> None:
    calls = []
    array = np.ones((1, 512, 832, 3), dtype=np.float32)
    if fault == "nan":
        array[0, 0, 0, 0] = np.nan
    if fault == "shape":
        array = array[:, :, :800]
    pipeline = SimpleNamespace(
        unet=SimpleNamespace(
            config=SimpleNamespace(block_out_channels=(320, 640, 1280)), dtype="fp16"
        ),
        adapter=SimpleNamespace(
            config=SimpleNamespace(
                channels=(320, 640, 1280, 1280),
                adapter_type="full_adapter_xl",
                in_channels=3,
                downscale_factor=16 if fault != "architecture" else 8,
            )
        ),
        vae=SimpleNamespace(dtype="fp16"),
        tokenizer=_Tokenizer(78 if fault == "tokens" else 25),
        tokenizer_2=_Tokenizer(25),
        set_progress_bar_config=lambda **k: None,
        to=lambda device: calls.append(("to", device)),
    )

    class Oom(RuntimeError):
        pass

    class Pipeline:
        def __init__(self) -> None:
            self.__dict__.update(pipeline.__dict__)

        def __call__(self, **kwargs: object) -> SimpleNamespace:
            calls.append(("inference", kwargs))
            if fault == "oom":
                raise Oom()
            assert kwargs["width"] == 832 and kwargs["height"] == 512
            assert kwargs["adapter_conditioning_scale"] == conditioning_scale
            assert kwargs["output_type"] == "np"
            return SimpleNamespace(images=array)

    def load(component: str, root: str, **kwargs: object) -> object:
        assert "add_watermarker" not in kwargs
        assert Path(root).is_relative_to(tmp_path)
        assert kwargs["local_files_only"] is True
        if component != "scheduler":
            assert kwargs["use_safetensors"] is True and kwargs["torch_dtype"] == "fp16"
        calls.append(("load", component))
        return Pipeline() if component == "pipeline" else object()

    cuda = SimpleNamespace(
        is_available=lambda: fault != "gpu",
        get_device_capability=lambda i: (12, 0),
        reset_peak_memory_stats=lambda i: None,
        synchronize=lambda i: None,
        get_device_name=lambda i: "fixture GPU",
        max_memory_allocated=lambda i: 1024,
        empty_cache=lambda: calls.append(("cleanup", None)),
        OutOfMemoryError=Oom,
    )
    torch = SimpleNamespace(
        cuda=cuda,
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
            T2IAdapter=SimpleNamespace(from_pretrained=lambda p, **k: load("adapter", p, **k)),
            EulerAncestralDiscreteScheduler=SimpleNamespace(
                from_pretrained=lambda p, **k: load("scheduler", p, **k)
            ),
            StableDiffusionXLAdapterPipeline=SimpleNamespace(
                from_pretrained=lambda p, **k: load("pipeline", p, **k)
            ),
        ),
    )
    monkeypatch.setattr(
        backend.metadata, "version", lambda p: "0.35.2" if p == "diffusers" else "4.56.2"
    )
    stack = ResolvedSdxlStack(
        manifest=LocalImageSdxlLineartStack.model_validate(_stack()),
        component_roots={role: tmp_path / role for role in ("BASE", "LINEART_ADAPTER", "VAE")},
    )

    def execute() -> None:
        command_value = _command()
        command_value["adapter_conditioning_scale"] = conditioning_scale
        command_value["command_sha256"] = content_sha256(
            {key: value for key, value in command_value.items() if key != "command_sha256"}
        )
        with backend.SdxlLineartDiffusersBackend().open(stack) as session:
            result = session.generate(
                conditioning=_png(size=(832, 512)),
                prompt="scientific line art",
                negative_prompt="text, color",
                seed=1,
                command=LocalImageSdxlLineartProbeCommand.model_validate(command_value),
            )
            with Image.open(io.BytesIO(result.png_bytes)) as image:
                assert image.size == (832, 512) and image.mode == "RGB"
            assert result.runtime.peak_gpu_memory_bytes == 1024
        assert session.pipeline is None

    if fault:
        expected = {
            "tokens": "SDXL_PROBE_PROMPT_TRUNCATED",
            "shape": "SDXL_PROBE_OUTPUT_INVALID",
            "nan": "SDXL_PROBE_OUTPUT_INVALID",
            "architecture": "SDXL_PROBE_MODEL_INVALID",
            "gpu": "SDXL_PROBE_GPU_UNAVAILABLE",
            "oom": "SDXL_PROBE_OOM",
        }[fault]
        with pytest.raises(ProviderError, match=expected):
            execute()
        if fault in {"tokens", "architecture", "gpu"}:
            assert not any(name == "inference" for name, _ in calls)
    else:
        execute()
        assert sum(name == "load" for name, _ in calls) == 4
    if fault != "gpu":
        assert calls[-1][0] == "cleanup"


def test_probe_systemd_preserves_existing_isolation_and_bounds() -> None:
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-image-sdxl-lineart-probe@.service").read_text()
    for expected in (
        "User=eom-image",
        "Group=eom-image",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/root/.codex",
        "ProtectSystem=strict",
        "DevicePolicy=closed",
        "Restart=no",
        "TimeoutStartSec=1830",
        "Environment=HF_HUB_OFFLINE=1",
        "Environment=TRANSFORMERS_OFFLINE=1",
        "--gpu-lock /var/lib/eom-image/gpu0.lock",
    ):
        assert expected in unit
    assert "PYTHONPATH" not in unit and "sudo" not in unit

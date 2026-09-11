from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_image_contracts import LocalImageGenerationRequest, content_sha256, text_sha256
from eom_image_provider.diffusers_backend import Ssd1bDiffusersBackend
from eom_image_provider.provider import ProviderError


class _Tokenizer:
    model_max_length = 77

    def __init__(self, *, token_count: int) -> None:
        self.token_count = token_count

    def __call__(self, _prompt: str, **_kwargs: object) -> dict[str, list[int]]:
        return {"input_ids": list(range(self.token_count))}


class EulerDiscreteScheduler:
    pass


class _Pipeline:
    def __init__(self, *, token_count: int, dtype: object) -> None:
        self.scheduler = EulerDiscreteScheduler()
        self.tokenizer = _Tokenizer(token_count=token_count)
        self.tokenizer_2 = _Tokenizer(token_count=token_count)
        self.unet = SimpleNamespace(dtype=dtype)
        self.transferred_to: str | None = None

    def set_progress_bar_config(self, *, disable: bool) -> None:
        assert disable is True

    def to(self, device: str) -> None:
        self.transferred_to = device

    def __call__(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(images=[_Image()])


class _Image:
    def convert(self, mode: str) -> _Image:
        assert mode == "RGB"
        return self

    def crop(self, box: tuple[int, int, int, int]) -> _Image:
        assert box == (0, 2, 800, 502)
        return self

    def save(self, output: Any, **kwargs: object) -> None:
        assert kwargs == {"format": "PNG", "optimize": False, "compress_level": 9}
        output.write(b"\x89PNG\r\n\x1a\nprovider-test")


class _Generator:
    def __init__(self, *, device: str) -> None:
        assert device == "cuda"

    def manual_seed(self, _seed: int) -> _Generator:
        return self


class _Cuda:
    OutOfMemoryError = RuntimeError

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def get_device_capability(_index: int) -> tuple[int, int]:
        return (12, 0)

    @staticmethod
    def reset_peak_memory_stats(_index: int) -> None:
        return None

    @staticmethod
    def synchronize(_index: int) -> None:
        return None

    @staticmethod
    def get_device_name(_index: int) -> str:
        return "NVIDIA GeForce RTX 5080"

    @staticmethod
    def max_memory_allocated(_index: int) -> int:
        return 1

    @staticmethod
    def empty_cache() -> None:
        return None


def _request() -> LocalImageGenerationRequest:
    body: dict[str, Any] = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": "imgreq_" + "1" * 32,
        "idempotency_key": "local-image:" + "2" * 64,
        "model": {
            "model_id": "imgmodel_" + "3" * 32,
            "model_revision_id": "imgmodelrev_" + "4" * 32,
            "manifest_sha256": "sha256:" + "5" * 64,
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "prompt": "one fox in grass",
        "prompt_sha256": text_sha256("one fox in grass"),
        "negative_prompt": "text, watermark",
        "negative_prompt_sha256": text_sha256("text, watermark"),
        "seed": 7,
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": 900,
    }
    return LocalImageGenerationRequest.model_validate(
        {**body, "request_sha256": content_sha256(body)}
    )


def _runtime_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_count: int,
    loaded_dtype_matches: bool = True,
) -> tuple[SimpleNamespace, type[Any]]:
    float16 = object()
    pipeline = _Pipeline(
        token_count=token_count,
        dtype=float16 if loaded_dtype_matches else object(),
    )

    class DiffusionPipeline:
        call: tuple[str, dict[str, object]] | None = None

        @classmethod
        def from_pretrained(cls, path: str, **kwargs: object) -> _Pipeline:
            cls.call = (path, kwargs)
            return pipeline

    torch = SimpleNamespace(
        cuda=_Cuda(),
        float16=float16,
        Generator=_Generator,
        version=SimpleNamespace(cuda="12.8"),
        __version__="2.7.1+cu128",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(DiffusionPipeline=DiffusionPipeline),
    )
    monkeypatch.setattr(
        "eom_image_provider.diffusers_backend.metadata.version",
        lambda name: {"diffusers": "0.35.2", "transformers": "4.56.2"}[name],
    )
    return torch, DiffusionPipeline


def test_ssd1b_uses_supported_and_verified_float16_loader_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    torch, pipeline_class = _runtime_modules(monkeypatch, token_count=20)

    generated = Ssd1bDiffusersBackend().generate(
        model_directory=tmp_path,
        request=_request(),
    )

    assert generated.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert pipeline_class.call == (
        str(tmp_path),
        {
            "dtype": torch.float16,
            "variant": "fp16",
            "local_files_only": True,
            "use_safetensors": True,
        },
    )


def test_ssd1b_rejects_prompt_truncation_before_cuda_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _torch, pipeline_class = _runtime_modules(monkeypatch, token_count=78)

    with pytest.raises(ProviderError, match="LOCAL_IMAGE_INPUT_INVALID"):
        Ssd1bDiffusersBackend().generate(
            model_directory=tmp_path,
            request=_request(),
        )

    assert pipeline_class.call is not None


def test_ssd1b_rejects_a_loader_that_did_not_apply_float16(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime_modules(monkeypatch, token_count=20, loaded_dtype_matches=False)

    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL_UNAVAILABLE"):
        Ssd1bDiffusersBackend().generate(
            model_directory=tmp_path,
            request=_request(),
        )

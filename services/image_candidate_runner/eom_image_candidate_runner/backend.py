"""Diffusers adapter for the isolated FLUX.2 Klein candidate runtime."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any, cast

from eom_image_contracts import Flux2ReferenceProbeRuntime
from PIL import Image  # type: ignore[import-not-found]


class Flux2BackendError(RuntimeError):
    """Stable inference-adapter failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Flux2KleinBackend:
    """Load one pinned local model and evaluate cases sequentially."""

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._torch: Any | None = None

    def prepare(self, model_root: Path) -> Flux2ReferenceProbeRuntime:
        try:
            import torch  # type: ignore[import-not-found]
            from diffusers import Flux2KleinPipeline  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised in the isolated runtime
            raise Flux2BackendError("FLUX2_PROBE_MODEL_INVALID") from exc
        if not torch.cuda.is_available():
            raise Flux2BackendError("FLUX2_PROBE_GPU_UNAVAILABLE")
        properties = torch.cuda.get_device_properties(0)
        capability = torch.cuda.get_device_capability(0)
        if properties.name != "NVIDIA GeForce RTX 5080" or capability != (12, 0):
            raise Flux2BackendError("FLUX2_PROBE_GPU_UNAVAILABLE")
        try:
            pipeline = Flux2KleinPipeline.from_pretrained(
                model_root,
                torch_dtype=torch.bfloat16,
                local_files_only=True,
                low_cpu_mem_usage=True,
            )
            pipeline.enable_model_cpu_offload()
            pipeline.set_progress_bar_config(disable=True)
        except Exception as exc:  # pragma: no cover - real checkpoint boundary
            raise Flux2BackendError("FLUX2_PROBE_MODEL_INVALID") from exc
        self._pipeline = pipeline
        self._torch = torch
        return Flux2ReferenceProbeRuntime(
            python_version=".".join(map(str, __import__("sys").version_info[:3])),
            torch_version=cast(str, torch.__version__).split("+")[0],
            diffusers_version=metadata.version("diffusers"),
            transformers_version=metadata.version("transformers"),
            cuda_version=cast(str | None, torch.version.cuda) or "unknown",
            gpu_name=properties.name,
            compute_capability="12.0",
        )

    def generate(
        self,
        *,
        conditioning: Image.Image,
        prompt: str,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> tuple[Image.Image, int]:
        if self._pipeline is None or self._torch is None:
            raise Flux2BackendError("FLUX2_PROBE_MODEL_INVALID")
        torch = self._torch
        try:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(0)
            generator = torch.Generator(device="cuda").manual_seed(seed)
            output = self._pipeline(
                image=conditioning,
                prompt=prompt,
                height=height,
                width=width,
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
                num_images_per_prompt=1,
                output_type="pil",
            )
            image = output.images[0]
            peak = int(torch.cuda.max_memory_allocated(0))
        except torch.cuda.OutOfMemoryError as exc:  # pragma: no cover - hardware dependent
            raise Flux2BackendError("FLUX2_PROBE_OOM") from exc
        except Exception as exc:  # pragma: no cover - real inference boundary
            raise Flux2BackendError("FLUX2_PROBE_EXEC_FAILED") from exc
        if not isinstance(image, Image.Image):
            raise Flux2BackendError("FLUX2_PROBE_OUTPUT_INVALID")
        return image, peak

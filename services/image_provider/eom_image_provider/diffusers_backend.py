"""SSD-1B Diffusers adapter; imported only inside the isolated eom-image runtime."""

from __future__ import annotations

import io
import platform
from importlib import metadata
from pathlib import Path
from typing import Any

from eom_image_contracts import LocalImageGenerationRequest, LocalImageRuntime

from eom_image_provider.provider import GeneratedBackground, ProviderError


class Ssd1bDiffusersBackend:
    def generate(
        self,
        *,
        model_directory: Path,
        request: LocalImageGenerationRequest,
    ) -> GeneratedBackground:
        try:
            import torch  # type: ignore[import-not-found]
            from diffusers import DiffusionPipeline  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
        if not torch.cuda.is_available():
            raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE")
        capability = torch.cuda.get_device_capability(0)
        if capability != (12, 0):
            raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE")
        torch.cuda.reset_peak_memory_stats(0)
        pipeline: Any | None = None
        try:
            pipeline = DiffusionPipeline.from_pretrained(
                str(model_directory),
                torch_dtype=torch.float16,
                variant="fp16",
                local_files_only=True,
                use_safetensors=True,
            )
            if pipeline.scheduler.__class__.__name__ != "EulerDiscreteScheduler":
                raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
            _require_untruncated_prompts(pipeline, request)
            pipeline.set_progress_bar_config(disable=True)
            pipeline.to("cuda")
            generator = torch.Generator(device="cuda").manual_seed(request.seed)
            response = pipeline(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                width=request.generation_canvas.width_px,
                height=request.generation_canvas.height_px,
                num_inference_steps=request.sampler.inference_steps,
                guidance_scale=request.sampler.guidance_scale,
                generator=generator,
            )
            torch.cuda.synchronize(0)
            image = response.images[0].convert("RGB")
            image = image.crop((0, 2, 800, 502))
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=False, compress_level=9)
            cuda_version = torch.version.cuda
            if not isinstance(cuda_version, str) or not cuda_version:
                raise ProviderError("LOCAL_IMAGE_GPU_UNAVAILABLE")
            runtime = LocalImageRuntime(
                python_version=platform.python_version(),
                torch_version=torch.__version__,
                diffusers_version=metadata.version("diffusers"),
                transformers_version=metadata.version("transformers"),
                cuda_version=cuda_version,
                gpu_name=torch.cuda.get_device_name(0),
                compute_capability=f"{capability[0]}.{capability[1]}",
                peak_gpu_memory_bytes=torch.cuda.max_memory_allocated(0),
            )
            return GeneratedBackground(png_bytes=output.getvalue(), runtime=runtime)
        except ProviderError:
            raise
        except torch.cuda.OutOfMemoryError as exc:
            raise ProviderError("LOCAL_IMAGE_PROVIDER_OOM") from exc
        except Exception as exc:
            raise ProviderError("LOCAL_IMAGE_PROVIDER_FAILED") from exc
        finally:
            if pipeline is not None:
                del pipeline
            torch.cuda.empty_cache()


def _require_untruncated_prompts(
    pipeline: Any,
    request: LocalImageGenerationRequest,
) -> None:
    """Reject an SSD-1B request before CUDA transfer if either CLIP encoder would truncate it."""

    prompts = tuple(
        value for value in (request.prompt, request.negative_prompt) if value is not None
    )
    for name in ("tokenizer", "tokenizer_2"):
        tokenizer = getattr(pipeline, name, None)
        maximum = getattr(tokenizer, "model_max_length", None)
        if tokenizer is None or not isinstance(maximum, int) or not 1 <= maximum <= 512:
            raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")
        for prompt in prompts:
            try:
                encoded = tokenizer(
                    prompt,
                    add_special_tokens=True,
                    padding=False,
                    truncation=False,
                    return_attention_mask=False,
                )
                input_ids = encoded["input_ids"]
            except Exception as exc:
                raise ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE") from exc
            if (
                not isinstance(input_ids, list)
                or not input_ids
                or isinstance(input_ids[0], list)
                or len(input_ids) > maximum
            ):
                raise ProviderError("LOCAL_IMAGE_INPUT_INVALID")

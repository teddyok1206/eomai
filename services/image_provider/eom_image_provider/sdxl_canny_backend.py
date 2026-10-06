"""One offline ControlNet factor with the existing pinned SDXL base/VAE/LoRA."""

from __future__ import annotations

import io
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from typing import Any, Literal

from eom_image_contracts.models import LocalImageRuntime
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from PIL import Image

from eom_image_provider.prompt_capacity import require_prompt_capacity
from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_canny_controller_io import ResolvedSdxlCannyController
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial, apply_sdxl_lora
from eom_image_provider.sdxl_matched_random_state import (
    PreparedSdxlGenerator,
    validate_sdxl_generator,
)
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack


class SdxlCannySession:
    def __init__(self, pipeline: Any, torch: Any, control: SdxlCannyControlParameters) -> None:
        self.pipeline = pipeline
        self.torch = torch
        self.control = control

    def generate(
        self,
        *,
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        command: LocalImageSdxlLineartProbeCommand,
    ) -> GeneratedBackground:
        with Image.open(io.BytesIO(conditioning)) as source:
            if (
                source.format != "PNG"
                or source.mode != "RGB"
                or source.size != (832, 512)
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            image = source.copy()
        return generate_sdxl_canny_background(
            self.pipeline,
            self.torch,
            self.control,
            image_arguments={"image": image},
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            command=command,
        )


def generate_sdxl_canny_background(
    pipeline: Any,
    torch: Any,
    control: SdxlCannyControlParameters,
    *,
    image_arguments: dict[str, Any],
    prompt: str,
    negative_prompt: str,
    seed: int,
    command: LocalImageSdxlLineartProbeCommand,
    random_state: PreparedSdxlGenerator | None = None,
) -> GeneratedBackground:
    """Shared finite RGB serialization/runtime evidence for two explicit numerical modes."""
    import numpy as np

    require_prompt_capacity(
        pipeline,
        (prompt, negative_prompt),
        model_error="SDXL_PROBE_MODEL_INVALID",
        overflow_error="SDXL_PROBE_PROMPT_TRUNCATED",
    )
    try:
        if random_state is not None:
            validate_sdxl_generator(torch, random_state, seed=seed)
            if random_state.generator.device.type != "cuda":
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        generator = (
            random_state.generator
            if random_state is not None
            else torch.Generator(device="cuda").manual_seed(seed)
        )
        response = pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            **image_arguments,
            width=832,
            height=512,
            generator=generator,
            num_inference_steps=command.inference_steps,
            guidance_scale=command.guidance_scale,
            controlnet_conditioning_scale=control.conditioning_scale,
            control_guidance_start=control.guidance_start,
            control_guidance_end=control.guidance_end,
            output_type="np",
        )
        torch.cuda.synchronize(0)
        raster = np.asarray(response.images)
        if (
            raster.shape != (1, 512, 832, 3)
            or not np.isfinite(raster).all()
            or raster.min() < 0
            or raster.max() > 1
        ):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        output = io.BytesIO()
        Image.fromarray(np.rint(raster[0] * 255).astype("uint8")).save(
            output, format="PNG", compress_level=9
        )
        capability = torch.cuda.get_device_capability(0)
        runtime = LocalImageRuntime(
            python_version=platform.python_version(),
            torch_version=torch.__version__,
            diffusers_version=metadata.version("diffusers"),
            transformers_version=metadata.version("transformers"),
            cuda_version=torch.version.cuda,
            gpu_name=torch.cuda.get_device_name(0),
            compute_capability=f"{capability[0]}.{capability[1]}",
            peak_gpu_memory_bytes=torch.cuda.max_memory_allocated(0),
        )
        return GeneratedBackground(png_bytes=output.getvalue(), runtime=runtime)
    except ProviderError:
        raise
    except torch.cuda.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except Exception as exc:
        raise ProviderError("SDXL_PROBE_EXEC_FAILED") from exc


class SdxlCannyDiffusersBackend:
    def __init__(
        self, controller: ResolvedSdxlCannyController, control: SdxlCannyControlParameters
    ) -> None:
        self.controller = controller
        self.control = control

    @contextmanager
    def open(
        self, stack: ResolvedSdxlStack, *, style_adapter: SdxlLoraAdapterMaterial | None = None
    ) -> Iterator[SdxlCannySession]:
        with open_sdxl_canny_pipeline(
            stack,
            self.controller,
            pipeline_class_name="StableDiffusionXLControlNetPipeline",
            style_adapter=style_adapter,
        ) as (pipeline, torch):
            session = SdxlCannySession(pipeline, torch, self.control)
            try:
                yield session
            finally:
                session.pipeline = None
                pipeline = None


@contextmanager
def open_sdxl_canny_pipeline(
    stack: ResolvedSdxlStack,
    resolved: ResolvedSdxlCannyController,
    *,
    pipeline_class_name: Literal[
        "StableDiffusionXLControlNetPipeline", "StableDiffusionXLControlNetImg2ImgPipeline"
    ],
    style_adapter: SdxlLoraAdapterMaterial | None = None,
) -> Iterator[tuple[Any, Any]]:
    """Common offline load/LoRA isolation, not an adaptive model or offload selector."""
    try:
        import diffusers  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
        from diffusers import (
            AutoencoderKL,
            ControlNetModel,
            EulerAncestralDiscreteScheduler,
        )

        pipeline_type = getattr(diffusers, pipeline_class_name)
    except (ImportError, AttributeError) as exc:
        raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
    if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) != (12, 0):
        raise ProviderError("SDXL_PROBE_GPU_UNAVAILABLE")
    pipeline: Any | None = None
    controller: Any | None = None
    vae: Any | None = None
    try:
        torch.cuda.reset_peak_memory_stats(0)
        controller = ControlNetModel.from_pretrained(
            str(resolved.root),
            torch_dtype=torch.float16,
            variant="fp16",
            local_files_only=True,
            use_safetensors=True,
        )
        roots = stack.component_roots
        vae = AutoencoderKL.from_pretrained(
            str(roots["VAE"]),
            torch_dtype=torch.float16,
            local_files_only=True,
            use_safetensors=True,
        )
        scheduler = EulerAncestralDiscreteScheduler.from_pretrained(
            str(roots["BASE"]),
            subfolder="scheduler",
            local_files_only=True,
        )
        pipeline = pipeline_type.from_pretrained(
            str(roots["BASE"]),
            controlnet=controller,
            vae=vae,
            scheduler=scheduler,
            torch_dtype=torch.float16,
            variant="fp16",
            local_files_only=True,
            use_safetensors=True,
        )
        if (
            tuple(pipeline.unet.config.block_out_channels) != (320, 640, 1280)
            or pipeline.unet.config.cross_attention_dim != 2048
            or pipeline.controlnet.config.addition_embed_type != "text_time"
            or pipeline.controlnet.config.conditioning_channels != 3
            or pipeline.controlnet.config.cross_attention_dim != 2048
            or pipeline.controlnet.dtype != torch.float16
            or pipeline.unet.dtype != torch.float16
            or pipeline.vae.dtype != torch.float16
        ):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        if style_adapter is not None:
            if any(
                getattr(style_adapter.manifest.base_model, name) != getattr(stack.manifest, name)
                for name in (
                    "model_id",
                    "model_revision_id",
                    "manifest_sha256",
                    "provider_family",
                    "runtime_contract_version",
                )
            ):
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            apply_sdxl_lora(pipeline.unet, style_adapter)
        pipeline.set_progress_bar_config(disable=True)
        pipeline.to("cuda")
        yield pipeline, torch
    except ProviderError:
        raise
    except torch.cuda.OutOfMemoryError as exc:
        raise ProviderError("SDXL_PROBE_OOM") from exc
    except Exception as exc:
        raise ProviderError("SDXL_PROBE_EXEC_FAILED") from exc
    finally:
        controller = None
        vae = None
        if pipeline is not None:
            del pipeline
        torch.cuda.empty_cache()

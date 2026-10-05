"""Offline SDXL adapter inference; one model load per bounded diagnostic command."""

from __future__ import annotations

import io
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from typing import Any

from eom_image_contracts import LocalImageRuntime, LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_native_geometry import (
    GeometryCanvas,
    SdxlNativeGeometryNumerics,
    geometry_dimensions,
)
from PIL import Image

from eom_image_provider.prompt_capacity import require_prompt_capacity
from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial, apply_sdxl_lora
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack


class SdxlLineartSession:
    def __init__(self, pipeline: Any, torch: Any) -> None:
        self.pipeline = pipeline
        self.torch = torch

    def generate(
        self,
        *,
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        command: LocalImageSdxlLineartProbeCommand,
    ) -> GeneratedBackground:
        return self._generate(
            conditioning=conditioning,
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            dimensions=(832, 512),
            inference_steps=command.inference_steps,
            guidance_scale=command.guidance_scale,
            adapter_conditioning_scale=command.adapter_conditioning_scale,
        )

    def generate_geometry(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        canvas: GeometryCanvas,
        numerics: SdxlNativeGeometryNumerics,
    ) -> GeneratedBackground:
        dimensions = geometry_dimensions(canvas)
        control = io.BytesIO()
        Image.new("RGB", dimensions, (0, 0, 0)).save(control, format="PNG")
        return self._generate(
            conditioning=control.getvalue(),
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=numerics.seed,
            dimensions=dimensions,
            inference_steps=numerics.inference_steps,
            guidance_scale=numerics.guidance_scale,
            adapter_conditioning_scale=numerics.adapter_conditioning_scale,
        )

    def _generate(
        self,
        *,
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        dimensions: tuple[int, int],
        inference_steps: int,
        guidance_scale: float,
        adapter_conditioning_scale: float,
    ) -> GeneratedBackground:
        import numpy as np

        require_prompt_capacity(
            self.pipeline,
            (prompt, negative_prompt),
            model_error="SDXL_PROBE_MODEL_INVALID",
            overflow_error="SDXL_PROBE_PROMPT_TRUNCATED",
        )
        with Image.open(io.BytesIO(conditioning)) as source:
            if source.format != "PNG" or source.mode != "RGB" or source.size != dimensions:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            image = source.copy()
        try:
            width, height = dimensions
            response = self.pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=image,
                width=width,
                height=height,
                generator=self.torch.Generator(device="cuda").manual_seed(seed),
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                adapter_conditioning_scale=adapter_conditioning_scale,
                output_type="np",
            )
            self.torch.cuda.synchronize(0)
            raster = np.asarray(response.images)
            if (
                raster.shape != (1, height, width, 3)
                or not np.isfinite(raster).all()
                or raster.min() < 0
                or raster.max() > 1
            ):
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            output = io.BytesIO()
            Image.fromarray(np.rint(raster[0] * 255).astype("uint8")).save(
                output, format="PNG", compress_level=9
            )
            capability = self.torch.cuda.get_device_capability(0)
            runtime = LocalImageRuntime(
                python_version=platform.python_version(),
                torch_version=self.torch.__version__,
                diffusers_version=metadata.version("diffusers"),
                transformers_version=metadata.version("transformers"),
                cuda_version=self.torch.version.cuda,
                gpu_name=self.torch.cuda.get_device_name(0),
                compute_capability=f"{capability[0]}.{capability[1]}",
                peak_gpu_memory_bytes=self.torch.cuda.max_memory_allocated(0),
            )
            return GeneratedBackground(png_bytes=output.getvalue(), runtime=runtime)
        except ProviderError:
            raise
        except self.torch.cuda.OutOfMemoryError as exc:
            raise ProviderError("SDXL_PROBE_OOM") from exc
        except Exception as exc:
            raise ProviderError("SDXL_PROBE_EXEC_FAILED") from exc


class SdxlLineartDiffusersBackend:
    @contextmanager
    def open(
        self, stack: ResolvedSdxlStack, *, style_adapter: SdxlLoraAdapterMaterial | None = None
    ) -> Iterator[SdxlLineartSession]:
        try:
            import torch  # type: ignore[import-not-found]
            from diffusers import (  # type: ignore[import-not-found]
                AutoencoderKL,
                EulerAncestralDiscreteScheduler,
                StableDiffusionXLAdapterPipeline,
                T2IAdapter,
            )
        except ImportError as exc:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
        if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) != (12, 0):
            raise ProviderError("SDXL_PROBE_GPU_UNAVAILABLE")
        pipeline: Any | None = None
        adapter: Any | None = None
        vae: Any | None = None
        session: SdxlLineartSession | None = None
        try:
            torch.cuda.reset_peak_memory_stats(0)
            roots = stack.component_roots
            adapter = T2IAdapter.from_pretrained(
                str(roots["LINEART_ADAPTER"]),
                torch_dtype=torch.float16,
                variant="fp16",
                local_files_only=True,
                use_safetensors=True,
            )
            vae = AutoencoderKL.from_pretrained(
                str(roots["VAE"]),
                torch_dtype=torch.float16,
                local_files_only=True,
                use_safetensors=True,
            )
            scheduler = EulerAncestralDiscreteScheduler.from_pretrained(
                str(roots["BASE"]), subfolder="scheduler", local_files_only=True
            )
            pipeline = StableDiffusionXLAdapterPipeline.from_pretrained(
                str(roots["BASE"]),
                adapter=adapter,
                vae=vae,
                scheduler=scheduler,
                torch_dtype=torch.float16,
                variant="fp16",
                local_files_only=True,
                use_safetensors=True,
            )
            if (
                tuple(pipeline.unet.config.block_out_channels) != (320, 640, 1280)
                or tuple(pipeline.adapter.config.channels) != (320, 640, 1280, 1280)
                or pipeline.adapter.config.adapter_type != "full_adapter_xl"
                or pipeline.adapter.config.in_channels != 3
                or pipeline.adapter.config.downscale_factor != 16
                or pipeline.vae.dtype != torch.float16
                or pipeline.unet.dtype != torch.float16
            ):
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            if style_adapter is not None:
                if any(
                    getattr(style_adapter.manifest.base_model, name)
                    != getattr(stack.manifest, name)
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
            session = SdxlLineartSession(pipeline, torch)
            yield session
        except ProviderError:
            raise
        except torch.cuda.OutOfMemoryError as exc:
            raise ProviderError("SDXL_PROBE_OOM") from exc
        except Exception as exc:
            raise ProviderError("SDXL_PROBE_EXEC_FAILED") from exc
        finally:
            if session is not None:
                session.pipeline = None
            adapter = None
            vae = None
            if pipeline is not None:
                del pipeline
            torch.cuda.empty_cache()

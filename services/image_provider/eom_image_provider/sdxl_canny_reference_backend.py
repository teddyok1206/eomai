"""Offline source initialization and Canny are distinct inputs, not a background filter."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_canny_reference import SdxlCannyReferenceInitialization
from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_photo_style import SdxlPhotoStyleInitialization
from PIL import Image

from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_canny_backend import (
    generate_sdxl_canny_background,
    open_sdxl_canny_pipeline,
)
from eom_image_provider.sdxl_canny_controller_io import ResolvedSdxlCannyController
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack


@dataclass(frozen=True, slots=True)
class SdxlCannyReferencePixels:
    canvas_rgb: bytes
    conditioning_png: bytes


class SdxlCannyReferenceSession:
    def __init__(
        self,
        pipeline: Any,
        torch: Any,
        control: SdxlCannyControlParameters,
        initialization: SdxlCannyReferenceInitialization | SdxlPhotoStyleInitialization,
        inputs: Mapping[str, SdxlCannyReferencePixels],
    ) -> None:
        self.pipeline, self.torch = pipeline, torch
        self.control, self.initialization, self.inputs = control, initialization, inputs

    def generate(
        self,
        *,
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        command: LocalImageSdxlLineartProbeCommand,
    ) -> GeneratedBackground:
        key = "sha256:" + hashlib.sha256(conditioning).hexdigest()
        if key not in self.inputs or command.inference_steps != self.initialization.scheduler_steps:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        pixels = self.inputs[key]
        if len(pixels.canvas_rgb) != 832 * 512 * 3:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        with Image.open(io.BytesIO(pixels.conditioning_png)) as source:
            if (
                source.format != "PNG"
                or source.mode != "RGB"
                or source.size != (832, 512)
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            control_image = source.copy()
        generated = generate_sdxl_canny_background(
            self.pipeline,
            self.torch,
            self.control,
            image_arguments=dict(
                image=Image.frombytes("RGB", (832, 512), pixels.canvas_rgb),
                control_image=control_image,
                strength=self.initialization.denoising_strength,
            ),
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            command=command,
        )
        if self.pipeline.num_timesteps != self.initialization.effective_denoising_steps:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        return generated


class SdxlCannyReferenceDiffusersBackend:
    def __init__(
        self,
        controller: ResolvedSdxlCannyController,
        control: SdxlCannyControlParameters,
        initialization: SdxlCannyReferenceInitialization | SdxlPhotoStyleInitialization,
        inputs: Mapping[str, SdxlCannyReferencePixels],
    ) -> None:
        self.controller, self.control, self.initialization = controller, control, initialization
        self.inputs = MappingProxyType(dict(inputs))

    @contextmanager
    def open(
        self, stack: ResolvedSdxlStack, *, style_adapter: SdxlLoraAdapterMaterial | None = None
    ) -> Iterator[SdxlCannyReferenceSession]:
        with open_sdxl_canny_pipeline(
            stack,
            self.controller,
            pipeline_class_name="StableDiffusionXLControlNetImg2ImgPipeline",
            style_adapter=style_adapter,
        ) as (pipeline, torch):
            session = SdxlCannyReferenceSession(
                pipeline, torch, self.control, self.initialization, self.inputs
            )
            try:
                yield session
            finally:
                session.pipeline = None
                pipeline = None

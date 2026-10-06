"""Matched style-only arms on the existing owned LoRA/ControlNet/reference pipeline."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from eom_image_contracts.models import Sha256
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer
from eom_image_contracts.sdxl_ip_style_comparison import SdxlIpStyleRouting
from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_photo_style import SdxlPhotoStyleInitialization
from pydantic import TypeAdapter

from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_canny_backend import (
    generate_sdxl_canny_background,
    open_sdxl_canny_pipeline,
)
from eom_image_provider.sdxl_canny_controller_io import ResolvedSdxlCannyController
from eom_image_provider.sdxl_canny_reference_backend import (
    SdxlCannyReferencePixels,
    sdxl_canny_reference_image_arguments,
)
from eom_image_provider.sdxl_ip_style_adapter import bind_sdxl_ip_style_adapter
from eom_image_provider.sdxl_ip_style_embedding import (
    BoundSdxlIpStyleEmbedding,
    materialize_sdxl_ip_style_embedding,
    validate_bound_sdxl_ip_style_embedding,
)
from eom_image_provider.sdxl_ip_style_encoder import PreparedSdxlIpStyleEmbedding
from eom_image_provider.sdxl_ip_style_routing import (
    SdxlIpStyleScaleSession,
    SdxlIpStyleScaleTrace,
)
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial
from eom_image_provider.sdxl_matched_random_state import prepare_sdxl_generator
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack


@dataclass(frozen=True, slots=True)
class SdxlIpStyleGeneratedBackground:
    generated: GeneratedBackground
    cfg_float32_le_sha256: str
    initial_generator_state_sha256: str
    scale_trace: SdxlIpStyleScaleTrace


class SdxlIpStyleReferenceSession:
    def __init__(
        self,
        pipeline: Any,
        torch: Any,
        control: SdxlCannyControlParameters,
        initialization: SdxlPhotoStyleInitialization,
        pointer: SdxlIpStyleModelPointer,
        inputs: Mapping[str, SdxlCannyReferencePixels],
        embeddings: dict[str, BoundSdxlIpStyleEmbedding],
        scales: SdxlIpStyleScaleSession,
    ) -> None:
        self._pipeline, self._torch = pipeline, torch
        self._control, self._initialization, self._pointer = control, initialization, pointer
        self._inputs, self._embeddings = inputs, embeddings
        self._scales: SdxlIpStyleScaleSession | None = scales

    def close(self) -> None:
        self._pipeline = self._torch = self._scales = None
        self._embeddings.clear()

    def generate(
        self,
        *,
        arm: Literal["OFF", "ON"],
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        command: LocalImageSdxlLineartProbeCommand,
    ) -> SdxlIpStyleGeneratedBackground:
        if self._pipeline is None or self._scales is None:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        key = "sha256:" + hashlib.sha256(conditioning).hexdigest()
        if (
            key not in self._inputs
            or command.inference_steps != self._initialization.scheduler_steps
        ):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        with self._scales.arm(arm) as trace:
            bound = self._embeddings[key]
            validate_bound_sdxl_ip_style_embedding(self._pipeline, self._pointer, bound)
            random_state = prepare_sdxl_generator(self._torch, seed, device="cuda")
            arguments = sdxl_canny_reference_image_arguments(self._inputs[key])
            arguments["strength"] = self._initialization.denoising_strength
            arguments["ip_adapter_image_embeds"] = [bound.tensor]
            generated = generate_sdxl_canny_background(
                self._pipeline,
                self._torch,
                self._control,
                image_arguments=arguments,
                prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                command=command,
                random_state=random_state,
            )
            if self._pipeline.num_timesteps != self._initialization.effective_denoising_steps:
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            validate_bound_sdxl_ip_style_embedding(self._pipeline, self._pointer, bound)
            return SdxlIpStyleGeneratedBackground(
                generated, bound.cfg_float32_le_sha256, random_state.initial_state_sha256, trace
            )


class SdxlIpStyleReferenceDiffusersBackend:
    def __init__(
        self,
        controller: ResolvedSdxlCannyController,
        control: SdxlCannyControlParameters,
        initialization: SdxlPhotoStyleInitialization,
        inputs: Mapping[str, SdxlCannyReferencePixels],
        embeddings: Mapping[str, PreparedSdxlIpStyleEmbedding],
        model_store_root: Path,
        style_model: SdxlIpStyleModelPointer,
        routing: SdxlIpStyleRouting,
    ) -> None:
        if not 1 <= len(inputs) <= 2 or set(inputs) != set(embeddings):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        try:
            for key in inputs:
                TypeAdapter(Sha256).validate_python(key)
                if "sha256:" + hashlib.sha256(inputs[key].conditioning_png).hexdigest() != key:
                    raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
            self._style_model = SdxlIpStyleModelPointer.model_validate(
                style_model.model_dump(mode="json")
            )
            self._routing = SdxlIpStyleRouting.model_validate(routing.model_dump(mode="json"))
        except ValueError as exc:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
        self._controller, self._control, self._initialization = controller, control, initialization
        self._inputs = MappingProxyType(dict(inputs))
        self._embeddings = MappingProxyType(dict(embeddings))
        self._model_store_root = model_store_root

    @contextmanager
    def open(
        self, stack: ResolvedSdxlStack, *, style_adapter: SdxlLoraAdapterMaterial
    ) -> Iterator[SdxlIpStyleReferenceSession]:
        if not isinstance(style_adapter, SdxlLoraAdapterMaterial):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        with open_sdxl_canny_pipeline(
            stack,
            self._controller,
            pipeline_class_name="StableDiffusionXLControlNetImg2ImgPipeline",
            style_adapter=style_adapter,
        ) as (pipeline, torch):
            bound: dict[str, BoundSdxlIpStyleEmbedding] = {}
            session: SdxlIpStyleReferenceSession | None = None
            scales: SdxlIpStyleScaleSession | None = None
            try:
                scales = bind_sdxl_ip_style_adapter(
                    pipeline, self._model_store_root, self._style_model, self._routing
                )
                for key, prepared in self._embeddings.items():
                    bound[key] = materialize_sdxl_ip_style_embedding(
                        pipeline, prepared, self._style_model
                    )
                session = SdxlIpStyleReferenceSession(
                    pipeline,
                    torch,
                    self._control,
                    self._initialization,
                    self._style_model,
                    self._inputs,
                    bound,
                    scales,
                )
                yield session
            finally:
                if session is not None:
                    session.close()
                bound.clear()
                scales = pipeline = None

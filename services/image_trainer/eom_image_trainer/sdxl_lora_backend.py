"""Explicit SDXL numerical adapters share tensor work, never command reinterpretation."""

from __future__ import annotations

from pathlib import Path

from eom_image_contracts import LocalImageSdxlLoraMicroCommand
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartStackPointer
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommandV3,
    NativeLoraCommand,
)
from eom_image_contracts.sdxl_reviewed_micro import LocalImageSdxlReviewedMicroCommand
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack

from eom_image_trainer.diffusers_backend import (
    DiffusersUnetLoraBackend,
    LoraTensorSample,
    LoraTrainingBudget,
    LoraTrainingRecipe,
    VaeWeightLocation,
)
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult
from eom_image_trainer.style_exposure import native_style_exposure_schedule


def _require_sdxl_stack(stack: ResolvedSdxlStack, pointer: SdxlLineartStackPointer) -> None:
    if (
        stack.manifest.model_id != pointer.model_id
        or stack.manifest.model_revision_id != pointer.model_revision_id
        or stack.manifest.manifest_sha256 != pointer.manifest_sha256
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_MODEL_INVALID")


class SdxlMicroLoraBackend:
    """Use the admitted SDXL base and separately pinned fp16-fixed VAE."""

    def train(
        self,
        *,
        stack: ResolvedSdxlStack,
        samples: tuple[LoraTensorSample, ...],
        command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
        output_root: Path,
    ) -> TrainingBackendResult:
        if len(samples) != len(command.training_samples) or tuple(
            sample.caption_en for sample in samples
        ) != tuple(source.training_caption_en for source in command.training_samples):
            raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
        if any((s.width_px, s.height_px) != (768, 512) for s in samples):
            raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
        _require_sdxl_stack(stack, command.base_model)
        return DiffusersUnetLoraBackend().train(
            model_directory=stack.component_roots["BASE"],
            vae_source=VaeWeightLocation(stack.component_roots["VAE"], None, None),
            samples=samples,
            recipe=LoraTrainingRecipe(command.dependencies, command.hyperparameters, command.seed),
            output_root=output_root,
            checkpoint_policy=None,
            budget=LoraTrainingBudget(
                command.budget.maximum_duration_ms, command.budget.maximum_peak_gpu_memory_bytes
            ),
        )


class SdxlNativeLoraBackend:
    """Exact admitted native geometry and reviewed conditioning, with no resume."""

    def train(
        self,
        *,
        stack: ResolvedSdxlStack,
        samples: tuple[LoraTensorSample, ...],
        command: NativeLoraCommand,
        output_root: Path,
    ) -> TrainingBackendResult:
        actual = tuple((s.caption_en, (s.width_px, s.height_px)) for s in samples)
        expected = tuple((s.training_caption_en, s.width_height) for s in command.training_samples)
        if actual != expected:
            raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
        _require_sdxl_stack(stack, command.base_model)
        schedule = (
            native_style_exposure_schedule(command)
            if isinstance(command, LocalImageSdxlNativeLoraCommandV3)
            else None
        )
        return DiffusersUnetLoraBackend().train(
            model_directory=stack.component_roots["BASE"],
            vae_source=VaeWeightLocation(stack.component_roots["VAE"], None, None),
            samples=samples,
            recipe=LoraTrainingRecipe(
                command.dependencies, command.hyperparameters, command.seed, schedule
            ),
            output_root=output_root,
            checkpoint_policy=None,
            budget=LoraTrainingBudget(
                command.budget.maximum_duration_ms, command.budget.maximum_peak_gpu_memory_bytes
            ),
        )

"""SDXL micro numerical adapter; no SSD command conversion or checkpoint relabeling."""

from __future__ import annotations

from pathlib import Path

from eom_image_contracts import LocalImageSdxlLoraMicroCommand
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack

from eom_image_trainer.diffusers_backend import (
    DiffusersUnetLoraBackend,
    LoraTensorSample,
    LoraTrainingBudget,
    LoraTrainingRecipe,
    VaeWeightLocation,
)
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult


class SdxlMicroLoraBackend:
    """Use the admitted SDXL base and separately pinned fp16-fixed VAE."""

    def train(
        self,
        *,
        stack: ResolvedSdxlStack,
        samples: tuple[LoraTensorSample, ...],
        command: LocalImageSdxlLoraMicroCommand,
        output_root: Path,
    ) -> TrainingBackendResult:
        if len(samples) != 16 or tuple(sample.caption_en for sample in samples) != tuple(
            source.training_caption_en for source in command.training_samples
        ):
            raise TrainingBackendFailure("IMAGE_TRAINING_SAMPLE_INVALID")
        if (
            stack.manifest.model_id != command.base_model.model_id
            or stack.manifest.model_revision_id != command.base_model.model_revision_id
            or stack.manifest.manifest_sha256 != command.base_model.manifest_sha256
        ):
            raise TrainingBackendFailure("IMAGE_TRAINING_MODEL_INVALID")
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

"""Closed source-cell weighting and normalized tensor loss; never source editing."""

from __future__ import annotations

from typing import Any

from eom_image_contracts.sdxl_native_lora import SdxlNativeContourLossPolicy

from eom_image_trainer.runner import TrainingBackendFailure


def source_cell_weights(
    *, luminance: bytes, width: int, height: int, policy: SdxlNativeContourLossPolicy, torch: Any
) -> Any:
    """One CPU pass over decoded native pixels; O(pixels) time, O(cells) result.

    Luminance is decoded once alongside the existing VAE RGB input. No pixel,
    caption or expression label changes; nearwhite and gray remain positive.
    """
    cell = policy.source_cell_size_px
    if (
        width < cell
        or height < cell
        or width % cell
        or height % cell
        or (len(luminance) != width * height)
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_CONTOUR_GEOMETRY_INVALID")
    pixels = torch.frombuffer(bytearray(luminance), dtype=torch.uint8)
    darkest = pixels.reshape(height // cell, cell, width // cell, cell).amin(dim=(1, 3))
    weights = torch.where(
        darkest < policy.dark_luminance_threshold,
        policy.dark_cell_weight,
        policy.other_cell_weight,
    ).to(dtype=torch.float32)
    return weights.reshape(1, 1, height // cell, width // cell)


def native_contour_weighted_mse(*, prediction: Any, target: Any, weights: Any, torch: Any) -> Any:
    """Float32 normalized broadcast loss, preserving batch1/channel accounting."""
    if (
        prediction.shape != target.shape
        or len(prediction.shape) != 4
        or prediction.shape[0] != 1
        or prediction.shape[1] != 4
        or weights.shape != (1, 1, *prediction.shape[-2:])
        or weights.dtype != torch.float32
        or prediction.device != target.device
        or prediction.device != weights.device
        or weights.requires_grad
        or not bool(((weights == 1) | (weights == 2)).all())
    ):
        raise TrainingBackendFailure("IMAGE_TRAINING_CONTOUR_WEIGHTS_INVALID")
    squared = (prediction.float() - target.float()).square()
    return (squared * weights).sum() / (weights.sum() * prediction.shape[1])

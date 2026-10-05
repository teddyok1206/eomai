"""Closed CPU-only transform verification for initialized paired comparisons."""

from __future__ import annotations

from pathlib import Path

from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleCommand,
    LocalImageSdxlPhotoStyleResult,
)
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    LocalImageSdxlValidationComparisonResult,
)

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_photo_style import verify_sdxl_photo_style_transforms
from eom_image_provider.sdxl_validation_comparison import verify_sdxl_validation_transforms


def verify_sdxl_initialized_reference_transforms(
    workspace: Path,
) -> LocalImageSdxlPhotoStyleResult | LocalImageSdxlValidationComparisonResult:
    command = load_sdxl_comparison_command(workspace, workspace / "command.json")
    if isinstance(command, LocalImageSdxlPhotoStyleCommand):
        return verify_sdxl_photo_style_transforms(workspace)
    if isinstance(command, LocalImageSdxlValidationComparisonCommand):
        return verify_sdxl_validation_transforms(workspace)
    raise ProviderError("SDXL_PROBE_INPUT_INVALID")

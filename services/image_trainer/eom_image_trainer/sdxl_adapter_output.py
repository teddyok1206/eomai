"""The exact local adapter output boundary shared by SDXL training protocols."""

from __future__ import annotations

import os
from pathlib import Path

from eom_image_provider.staged_file_io import verified_directory

from eom_image_trainer.runner import TrainingRunnerError, validate_adapter_files


def validate_sdxl_adapter_files(workspace: Path) -> tuple[dict[str, object], ...]:
    """Reject extra files before the existing bounded config/weight validation."""
    with verified_directory(workspace / "adapter", expected_owner_uid=os.geteuid()) as root:
        if tuple(sorted(os.listdir(root))) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise TrainingRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    return validate_adapter_files(workspace / "adapter")

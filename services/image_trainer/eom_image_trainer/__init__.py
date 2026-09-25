"""Isolated local-image training adapters."""

from eom_image_trainer.dataset_builder import (
    DatasetBuildError,
    StagedPageImage,
    build_training_dataset,
)

__all__ = ["DatasetBuildError", "StagedPageImage", "build_training_dataset"]

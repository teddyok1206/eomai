"""Legacy TRAIN diagnostic for a literal-target SDXL adapter; never holdout PASS."""

from __future__ import annotations

from typing import Literal

from eom_image_contracts.sdxl_lora_evaluation import (
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraEvaluationResult,
    SdxlLoraEvaluationPin,
)


class SdxlReviewedLoraEvaluationPin(SdxlLoraEvaluationPin):
    def training_contract_version(self) -> str:
        return "1.1"


class LocalImageSdxlReviewedEvaluationCommand(LocalImageSdxlLoraEvaluationCommand):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.1"]  # type: ignore[assignment]
    evaluation: SdxlReviewedLoraEvaluationPin
    case_relation: Literal["LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"]


class LocalImageSdxlReviewedEvaluationResult(LocalImageSdxlLoraEvaluationResult):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.1"]  # type: ignore[assignment]
    evaluation: SdxlReviewedLoraEvaluationPin
    case_relation: Literal["LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"]

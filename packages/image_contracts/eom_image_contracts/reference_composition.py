"""Immutable contract for reference composition-preservation evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eom_image_contracts.models import content_sha256
from eom_image_contracts.visual_reference import LocalImageVisualReferencePointer

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FailureReason = Literal[
    "CENTER_SHIFT_HIGH",
    "COLOR_REMAINS",
    "EDGE_OCCUPANCY_DRIFT",
    "EDGE_RECALL_LOW",
    "FOREGROUND_BBOX_IOU_LOW",
    "HEIGHT_SCALE_DRIFT",
    "WIDTH_SCALE_DRIFT",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceCompositionImageMember(FrozenModel):
    member_path: Literal[
        "inputs/reference-conditioning.png",
        "outputs/candidate.png",
    ]
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    width_px: Literal[800] = 800
    height_px: Literal[504] = 504


class ReferenceCompositionMetrics(FrozenModel):
    edge_precision: float = Field(ge=0, le=1)
    edge_recall: float = Field(ge=0, le=1)
    edge_f1: float = Field(ge=0, le=1)
    foreground_bbox_iou: float = Field(ge=0, le=1)
    center_shift_ratio: float = Field(ge=0, le=1.5)
    width_scale_ratio: float = Field(ge=0.25, le=4)
    height_scale_ratio: float = Field(ge=0.25, le=4)
    edge_occupancy_delta_ratio: float = Field(ge=0, le=1)
    mean_chroma_ratio: float = Field(ge=0, le=1)


class ReferenceCompositionThresholds(FrozenModel):
    edge_recall_min: float = Field(default=0.8, ge=0.8, le=0.8)
    foreground_bbox_iou_min: float = Field(default=0.7, ge=0.7, le=0.7)
    center_shift_ratio_max: float = Field(default=0.08, ge=0.08, le=0.08)
    width_scale_ratio_min: float = Field(default=0.75, ge=0.75, le=0.75)
    width_scale_ratio_max: float = Field(default=1.25, ge=1.25, le=1.25)
    height_scale_ratio_min: float = Field(default=0.75, ge=0.75, le=0.75)
    height_scale_ratio_max: float = Field(default=1.25, ge=1.25, le=1.25)
    edge_occupancy_delta_ratio_max: float = Field(default=0.2, ge=0.2, le=0.2)
    mean_chroma_ratio_max: float = Field(default=0.04, ge=0.04, le=0.04)


class ReferenceCompositionEvaluator(FrozenModel):
    contract: Literal["local-image-reference-composition-evaluator/1.0"] = (
        "local-image-reference-composition-evaluator/1.0"
    )
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    pillow_version: str = Field(min_length=1, max_length=64)
    numpy_version: str = Field(min_length=1, max_length=64)


def composition_failure_reasons(
    metrics: ReferenceCompositionMetrics,
    thresholds: ReferenceCompositionThresholds,
) -> tuple[FailureReason, ...]:
    """Return stable, sorted failures for one fixed-threshold comparison."""

    failures: set[FailureReason] = set()
    if metrics.edge_recall < thresholds.edge_recall_min:
        failures.add("EDGE_RECALL_LOW")
    if metrics.foreground_bbox_iou < thresholds.foreground_bbox_iou_min:
        failures.add("FOREGROUND_BBOX_IOU_LOW")
    if metrics.center_shift_ratio > thresholds.center_shift_ratio_max:
        failures.add("CENTER_SHIFT_HIGH")
    if not (
        thresholds.width_scale_ratio_min
        <= metrics.width_scale_ratio
        <= thresholds.width_scale_ratio_max
    ):
        failures.add("WIDTH_SCALE_DRIFT")
    if not (
        thresholds.height_scale_ratio_min
        <= metrics.height_scale_ratio
        <= thresholds.height_scale_ratio_max
    ):
        failures.add("HEIGHT_SCALE_DRIFT")
    if metrics.edge_occupancy_delta_ratio > thresholds.edge_occupancy_delta_ratio_max:
        failures.add("EDGE_OCCUPANCY_DRIFT")
    if metrics.mean_chroma_ratio > thresholds.mean_chroma_ratio_max:
        failures.add("COLOR_REMAINS")
    return tuple(sorted(failures))


class LocalImageReferenceCompositionEvaluation(FrozenModel):
    schema_version: Literal["local-image-reference-composition-evaluation/1.0"] = (
        "local-image-reference-composition-evaluation/1.0"
    )
    evaluation_id: str = Field(pattern=r"^imgcompositioneval_[0-9a-f]{32}$")
    policy: Literal["COMPOSITION_PRESERVING_LINE_ART"] = "COMPOSITION_PRESERVING_LINE_ART"
    visual_reference: LocalImageVisualReferencePointer
    reference_conditioning: ReferenceCompositionImageMember
    candidate_output: ReferenceCompositionImageMember
    metrics: ReferenceCompositionMetrics
    thresholds: ReferenceCompositionThresholds
    failure_reasons: tuple[FailureReason, ...] = Field(max_length=8)
    outcome: Literal["PASS", "FAIL"]
    evaluator: ReferenceCompositionEvaluator
    evaluated_at: datetime
    evaluation_sha256: Sha256

    @field_validator("evaluated_at")
    @classmethod
    def utc_evaluation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("composition evaluation timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_identity_and_outcome(self) -> LocalImageReferenceCompositionEvaluation:
        if self.reference_conditioning.member_path != "inputs/reference-conditioning.png":
            raise ValueError("composition reference member path is invalid")
        if self.candidate_output.member_path != "outputs/candidate.png":
            raise ValueError("composition candidate member path is invalid")
        failures = composition_failure_reasons(self.metrics, self.thresholds)
        if self.failure_reasons != failures:
            raise ValueError("composition failure reasons differ from measured metrics")
        if self.outcome != ("PASS" if not failures else "FAIL"):
            raise ValueError("composition outcome differs from measured metrics")
        identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"evaluation_id", "evaluation_sha256"},
            )
        ).removeprefix("sha256:")
        if self.evaluation_id != "imgcompositioneval_" + identity[:32]:
            raise ValueError("composition evaluation ID does not bind its inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"evaluation_sha256"}))
        if self.evaluation_sha256 != expected:
            raise ValueError("composition evaluation hash mismatch")
        return self

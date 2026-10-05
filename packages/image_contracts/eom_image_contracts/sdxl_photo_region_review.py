"""Frozen source-space morphology reviews, not automatic object segmentation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, ImageEvaluationBoundingBox, Sha256
from eom_image_contracts.sdxl_canny_conditioning import (
    SdxlCannyPolicy,
    validate_canny_retained_region,
)


class SdxlPhotoSourceRegionBox(ImageEvaluationBoundingBox):
    left: int = Field(ge=0, le=799, strict=True)
    top: int = Field(ge=0, le=503, strict=True)
    right: int = Field(ge=1, le=800, strict=True)
    bottom: int = Field(ge=1, le=504, strict=True)


def photo_source_box_to_canvas(box: SdxlPhotoSourceRegionBox) -> ImageEvaluationBoundingBox:
    """Exact fixed800x504 Pillow fit794x500/offset19,6, conservative floor/ceil."""
    return ImageEvaluationBoundingBox(
        left=19 + box.left * 794 // 800,
        top=6 + box.top * 500 // 504,
        right=19 + (box.right * 794 + 799) // 800,
        bottom=6 + (box.bottom * 500 + 503) // 504,
    )


class SdxlPhotoRetainedRegionReview(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    reference_sha256: Sha256
    coordinate_system: Literal["NORMALIZED_PHOTO_SOURCE_PIXELS_800X504/1.0"]
    source_width_px: Literal[800]
    source_height_px: Literal[504]
    retained_box: SdxlPhotoSourceRegionBox
    protected_boxes: tuple[SdxlPhotoSourceRegionBox, ...] = Field(min_length=1, max_length=8)
    context_policy: Literal["SUBJECT_MORPHOLOGY_ONLY_IRRELEVANT_BACKDROP"]
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    observation: str = Field(min_length=10, max_length=1000, pattern=r"^[ -~]+$")

    @field_validator("reviewed_at")
    @classmethod
    def utc_review(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("photo region review must use UTC")
        return value

    @model_validator(mode="after")
    def protected_source_geometry(self) -> Self:
        box = self.retained_box
        if len(set(self.protected_boxes)) != len(self.protected_boxes) or any(
            not (
                box.left <= p.left < p.right <= box.right
                and box.top <= p.top < p.bottom <= box.bottom
            )
            for p in self.protected_boxes
        ):
            raise ValueError("photo retained region lacks unique contained source protection")
        validate_canny_retained_region(
            policy=SdxlCannyPolicy(),
            retained_box=photo_source_box_to_canvas(box),
            protected_boxes=tuple(photo_source_box_to_canvas(p) for p in self.protected_boxes),
        )
        return self

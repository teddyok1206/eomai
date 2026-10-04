"""Native PDF source preparation; no renderer, filesystem, database or model behavior."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.science_corpus_visual import ScienceVisualToolIdentity
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
    ScienceSourcePageCropMember,
    ScienceSourcePageCropRegion,
    SourcePageCropReview,
    source_page_crop_protocol,
)
from eom_image_contracts.validation import validate_contract

SOURCE_PDF_CROP_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-source-pdf-crop-command/1.0"
)
SOURCE_PDF_CROP_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-source-pdf-crop-set/1.0"
)
NATIVE_SOURCE_RENDER_DPI = 576
MAX_NATIVE_CROP_DIMENSION = 4096
MAX_NATIVE_BATCH_PIXELS = 32_000_000


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("native PDF crop timestamp must be UTC")
    return value


class LocalImageScienceSourcePdfCropCommand(FrozenModel):
    schema_version: Literal["local-image-science-source-pdf-crop-command/1.0"]
    command_id: str = Field(pattern=r"^imgpdfcropcommand_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_review: ImageEvaluationArtifactMember
    selection_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    render_dpi: Literal[576]
    renderer: ScienceVisualToolIdentity
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    policy: Literal["PINNED_TRAIN_REVIEW_144_DPI_FRAME_RENDERED_AT_576_DPI/1.0"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if (
            self.source_review.schema_ref
            not in {
                SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
                SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
                SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
            }
            or self.source_review.media_type != "application/json"
            or self.source_review.member_path != "manifests/science-source-page-crop-review.json"
            or self.renderer.path != "/usr/bin/pdftoppm"
        ):
            raise ValueError("native PDF crop source/renderer contract mismatch")
        if self.selection_ids != tuple(sorted(set(self.selection_ids))) or any(
            re.fullmatch(r"imgsourcecrop_[0-9a-f]{32}", identifier) is None
            for identifier in self.selection_ids
        ):
            raise ValueError("native PDF crop IDs must be valid, uniquely sorted")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"command_id", "command_sha256"})
        )
        if self.command_id != "imgpdfcropcommand_" + identity[7:39] or (
            self.command_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        ):
            raise ValueError("native PDF crop command identity/hash mismatch")
        return self


def select_native_source_pdf_regions(
    command: LocalImageScienceSourcePdfCropCommand, review: SourcePageCropReview
) -> tuple[ScienceSourcePageCropRegion, ...]:
    """Choose literal TRAIN frames; dpi is a derivative, not an independent drawing."""
    if (
        source_page_crop_protocol(review).review_schema_ref != command.source_review.schema_ref
        or review.created_at > command.created_at
        or review.pillow_version != command.pillow_version
    ):
        raise ValueError("NATIVE_PDF_CROP_REVIEW_MISMATCH")
    review_raw = content_json_bytes(review.model_dump(mode="json"))
    if command.source_review.sha256 not in {
        "sha256:" + hashlib.sha256(review_raw).hexdigest(),
        "sha256:" + hashlib.sha256(review_raw + b"\n").hexdigest(),
    }:
        raise ValueError("NATIVE_PDF_CROP_REVIEW_HASH_MISMATCH")
    by_id = {selection.selection_id: selection for selection in review.selections}
    if not set(command.selection_ids) <= by_id.keys():
        raise ValueError("NATIVE_PDF_CROP_SELECTION_MISSING")
    selected = tuple(by_id[identifier] for identifier in command.selection_ids)
    total_pixels = 0
    for selection in selected:
        if selection.partition != "TRAIN":
            raise ValueError("NATIVE_PDF_CROP_RESERVED_SOURCE_FORBIDDEN")
        _left, _top, right, bottom = selection.pixel_box
        width, height = native_source_pdf_crop_dimensions(selection)
        # A one-reference-pixel margin protects Poppler's fractional page-extent rounding.
        if right >= selection.page_width_px or bottom >= selection.page_height_px:
            raise ValueError("NATIVE_PDF_CROP_PAGE_EDGE_UNSUPPORTED")
        total_pixels += width * height
    if total_pixels > MAX_NATIVE_BATCH_PIXELS:
        raise ValueError("NATIVE_PDF_CROP_PIXEL_BUDGET_EXCEEDED")
    return selected


def native_source_pdf_crop_dimensions(selection: ScienceSourcePageCropRegion) -> tuple[int, int]:
    left, top, right, bottom = selection.pixel_box
    factor = NATIVE_SOURCE_RENDER_DPI // selection.page_render_dpi
    width, height = (right - left) * factor, (bottom - top) * factor
    if not (
        128 <= width <= MAX_NATIVE_CROP_DIMENSION and 128 <= height <= MAX_NATIVE_CROP_DIMENSION
    ):
        raise ValueError("NATIVE_PDF_CROP_DIMENSIONS_INVALID")
    return width, height


class LocalImageScienceSourcePdfCropSet(FrozenModel):
    schema_version: Literal["local-image-science-source-pdf-crop-set/1.0"]
    crop_set_id: str = Field(pattern=r"^imgpdfcropset_[0-9a-f]{32}$")
    crop_set_revision_id: str = Field(pattern=r"^imgpdfcropsetrev_[0-9a-f]{32}$")
    created_at: datetime
    command: ImageEvaluationArtifactMember
    command_sha256: Sha256
    members: tuple[ScienceSourcePageCropMember, ...] = Field(min_length=1, max_length=32)
    state: Literal["RENDERED_SOURCE_DERIVATIVES_PENDING_TARGET_REVIEW"]
    activation_policy: Literal["FORBIDDEN"]
    crop_set_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_set(self) -> Self:
        if (
            self.command.schema_ref != SOURCE_PDF_CROP_COMMAND_SCHEMA_REF
            or self.command.media_type != "application/json"
            or self.command.member_path != "manifests/science-source-pdf-crop-command.json"
        ):
            raise ValueError("native PDF crop command pointer mismatch")
        ids = tuple(member.selection_id for member in self.members)
        if ids != tuple(sorted(set(ids))) or len({member.sha256 for member in self.members}) != len(
            ids
        ):
            raise ValueError("native PDF crop set repeats identities/pixels")
        if (
            any(
                member.width_px > MAX_NATIVE_CROP_DIMENSION
                or member.height_px > MAX_NATIVE_CROP_DIMENSION
                or member.width_px < 128
                or member.height_px < 128
                for member in self.members
            )
            or sum(member.width_px * member.height_px for member in self.members)
            > MAX_NATIVE_BATCH_PIXELS
        ):
            raise ValueError("native PDF crop set pixel budget exceeded")
        if sum(member.size_bytes for member in self.members) > 128 * 1024**2:
            raise ValueError("native PDF crop set byte budget exceeded")
        if self.crop_set_id != "imgpdfcropset_" + content_sha256({"selection_ids": ids})[7:39]:
            raise ValueError("native PDF crop set logical identity mismatch")
        revision = content_sha256(
            self.model_dump(mode="json", exclude={"crop_set_revision_id", "crop_set_sha256"})
        )
        if self.crop_set_revision_id != "imgpdfcropsetrev_" + revision[7:39] or (
            self.crop_set_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"crop_set_sha256"}))
        ):
            raise ValueError("native PDF crop set revision/hash mismatch")
        return self


def validate_native_source_pdf_crop_set(
    command: LocalImageScienceSourcePdfCropCommand,
    review: SourcePageCropReview,
    crop_set: LocalImageScienceSourcePdfCropSet,
    *,
    command_pointer: ImageEvaluationArtifactMember,
) -> None:
    validate_contract("science-source-pdf-crop-command", command.model_dump(mode="json"))
    validate_contract("science-source-pdf-crop-set", crop_set.model_dump(mode="json"))
    selected = select_native_source_pdf_regions(command, review)
    expected_raw = (
        "sha256:" + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest()
    )
    if (
        crop_set.command != command_pointer
        or crop_set.command.sha256 != expected_raw
        or crop_set.command_sha256 != command.command_sha256
        or (
            crop_set.created_at < command.created_at
            or tuple(member.selection_id for member in crop_set.members) != command.selection_ids
        )
    ):
        raise ValueError("NATIVE_PDF_CROP_SET_COMMAND_MISMATCH")
    for selection, member in zip(selected, crop_set.members, strict=True):
        if (member.width_px, member.height_px) != native_source_pdf_crop_dimensions(selection):
            raise ValueError("NATIVE_PDF_CROP_SET_DIMENSIONS_MISMATCH")

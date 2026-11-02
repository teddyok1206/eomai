"""Explicit original-bitmap regions; no PDF raster or reference-question substitution."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, StrictInt, model_validator

from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_CONTENT_MEMBER,
    VISUAL_PRESENTATION_SCHEMA_REF,
    CreativeVisualPresentationManifest,
    EmbeddedSourceImageProof,
    validate_visual_presentation_references,
)
from eom_catalog_contracts.legacy_assessment import NormalizedBoundingBox
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

BITMAP_PRESENTATION_SCHEMA_REF = "eom://schemas/external-item/creative-visual-presentation/1.1"


class SelectedSourceBitmap(EmbeddedSourceImageProof):
    pixel_box: tuple[StrictInt, StrictInt, StrictInt, StrictInt]
    selection: Literal["WHOLE_IMAGE", "MAIN_BODY_VIEWPORT", "MAIN_PANEL", "EMPTY_MARGIN_ONLY"]

    @model_validator(mode="after")
    def exact_source_region(self) -> Self:
        left, top, right, bottom = self.pixel_box
        whole = self.pixel_box == (0, 0, self.width_px, self.height_px)
        if (
            any(type(value) is not int for value in self.pixel_box)
            or not (0 <= left < right <= self.width_px and 0 <= top < bottom <= self.height_px)
            or whole != (self.selection == "WHOLE_IMAGE")
        ):
            raise ValueError("CREATIVE_SOURCE_BITMAP_REGION_INVALID")
        return self


class RecoveredBitmapVisual(FrozenModel):
    canonical_block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    display_block_id: str = Field(pattern=r"^block_restored_[0-9a-f]{24}$")
    source_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    target_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    physical_page: int = Field(strict=True, ge=1, le=32)
    target_box: NormalizedBoundingBox
    source_images: tuple[SelectedSourceBitmap, ...] = Field(min_length=1, max_length=64)
    member_path: str = Field(pattern=r"^images/[0-9a-f]{64}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    content_length: int = Field(strict=True, ge=24, le=16 * 1024 * 1024)
    source_image_crops: int = Field(strict=True, ge=0, le=64)
    page_captures: Literal[0] = 0
    reference_original_used: Literal[False] = False

    @model_validator(mode="after")
    def exact_group(self) -> Self:
        keys = tuple(
            (v.source_member, v.source_object_number, v.pixel_box) for v in self.source_images
        )
        if (
            len(keys) != len(set(keys))
            or self.source_image_crops
            != sum(v.selection != "WHOLE_IMAGE" for v in self.source_images)
            or self.member_path != f"images/{self.sha256[7:]}.png"
            or self.width_px * self.height_px > 20_000_000
        ):
            raise ValueError("CREATIVE_RECOVERED_BITMAP_VISUAL_INVALID")
        return self


class CreativeBitmapPresentationManifest(FrozenModel):
    schema_version: Literal["creative-visual-presentation/1.1"] = "creative-visual-presentation/1.1"
    profile: Literal["HANCOM_SOURCE_BITMAP_REGIONS_V1"] = "HANCOM_SOURCE_BITMAP_REGIONS_V1"
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    canonical_content: ArtifactMemberPointer
    source_document: ArtifactMemberPointer
    source_pdf: ArtifactMemberPointer
    role_result: ArtifactMemberPointer
    role_work_sha256: Sha256
    content_member: Literal["assessment-item-content.json"] = VISUAL_PRESENTATION_CONTENT_MEMBER
    content_sha256: Sha256
    nonvisual_content_sha256: Sha256
    visuals: tuple[RecoveredBitmapVisual, ...] = Field(min_length=1, max_length=64)
    authorized_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    verification: Literal["CODEX_OPERATOR_ASSISTED_SOURCE_COMPARISON"] = (
        "CODEX_OPERATOR_ASSISTED_SOURCE_COMPARISON"
    )
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_derivation(self) -> Self:
        value = self.model_dump(mode="json")
        validate_visual_presentation_references(
            tuple(v.canonical_block_id for v in self.visuals),
            tuple(v.display_block_id for v in self.visuals),
            self.canonical_content,
            self.source_document,
            self.source_pdf,
            self.role_result,
            self.manifest_sha256,
            content_sha256({k: v for k, v in value.items() if k != "manifest_sha256"}),
        )
        return self


VisualPresentationManifest = CreativeVisualPresentationManifest | CreativeBitmapPresentationManifest


def visual_presentation_schema_ref(manifest: VisualPresentationManifest) -> str:
    return (
        BITMAP_PRESENTATION_SCHEMA_REF
        if isinstance(manifest, CreativeBitmapPresentationManifest)
        else VISUAL_PRESENTATION_SCHEMA_REF
    )


def read_visual_presentation_manifest(value: object, schema_ref: str) -> VisualPresentationManifest:
    """Select only an installed released contract; never infer a profile from unknown bytes."""
    if not isinstance(value, dict):
        raise ValueError("CREATIVE_VISUAL_PRESENTATION_MANIFEST_INVALID")
    if schema_ref == VISUAL_PRESENTATION_SCHEMA_REF:
        validate_contract("creative-visual-presentation-v1", value)
        return CreativeVisualPresentationManifest.model_validate(value)
    if schema_ref == BITMAP_PRESENTATION_SCHEMA_REF:
        validate_contract("creative-visual-presentation-v1-1", value)
        return CreativeBitmapPresentationManifest.model_validate(value)
    raise ValueError("CREATIVE_VISUAL_PRESENTATION_SCHEMA_UNSUPPORTED")

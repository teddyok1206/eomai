"""Pinned, render-only page images for one creative archive learning input.

The PDF remains canonical. These PNGs are bounded worker materializations and
cannot by themselves prove a source occurrence, Item approval, or Graph entry.
"""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.models import FrozenModel, Sha256

EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA = "external-item-learning-page-set-v1"
EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA_REF = "eom://schemas/external-item/learning-page-set/1.0"
EXTERNAL_ITEM_LEARNING_PAGE_IMAGE_SCHEMA_REF = "eom://schemas/external-item/learning-page-image/1.0"


class ExternalItemLearningPageRenderer(FrozenModel):
    profile: Literal["PDFTOPPM_PNG_SCALE_2400_V1"] = "PDFTOPPM_PNG_SCALE_2400_V1"
    pdfinfo_sha256: Sha256
    pdftoppm_sha256: Sha256


class ExternalItemLearningPage(FrozenModel):
    physical_page: int = Field(strict=True, ge=1, le=32)
    member_path: str = Field(pattern=r"^pages/page-[0-9]{4}\.png$")
    sha256: Sha256
    content_length: int = Field(strict=True, ge=24, le=16 * 1024 * 1024)
    width_px: int = Field(strict=True, ge=64, le=2400)
    height_px: int = Field(strict=True, ge=64, le=2400)

    @model_validator(mode="after")
    def exact_path(self) -> Self:
        if self.member_path != f"pages/page-{self.physical_page:04d}.png":
            raise ValueError("learning page member path differs from its physical page")
        return self


class ExternalItemLearningPageSet(FrozenModel):
    """Immutable manifest committed with PNGs; no duplicate PDF member."""

    schema_version: Literal["external-item-learning-page-set/1.0"] = (
        "external-item-learning-page-set/1.0"
    )
    source_input_sha256: Sha256
    preview_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    preview_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    preview_pdf_sha256: Sha256
    renderer: ExternalItemLearningPageRenderer
    pages: tuple[ExternalItemLearningPage, ...] = Field(min_length=1, max_length=32)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_order_and_hash(self) -> Self:
        if tuple(page.physical_page for page in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("learning page set must cover ordered, contiguous pages")
        if sum(page.content_length for page in self.pages) > 256 * 1024 * 1024:
            raise ValueError("learning page set exceeds its total byte bound")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("learning page set manifest hash differs")
        return self


def validate_external_item_learning_page_set_for_source(
    pages: ExternalItemLearningPageSet,
    source: ExternalItemLearningSource,
) -> None:
    """Close page derivatives over the exact selected Office→PDF projection."""

    if (
        pages.source_input_sha256 != source.input_sha256
        or pages.preview_artifact_id != source.preview_artifact_id
        or pages.preview_artifact_revision_id != source.preview_artifact_revision_id
        or pages.preview_pdf_sha256 != source.preview_manifest.pdf_sha256
    ):
        raise ValueError("learning pages differ from their pinned source PDF")

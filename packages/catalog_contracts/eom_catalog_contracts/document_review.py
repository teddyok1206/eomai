"""Immutable Catalog contracts for PDF document-review intake."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DocumentId = Annotated[str, Field(pattern=r"^document_[0-9a-f]{32}$")]
DocumentRevisionId = Annotated[str, Field(pattern=r"^documentrev_[0-9a-f]{32}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class PdfDocumentReviewRendererIdentity(FrozenModel):
    renderer_key: Literal["poppler-pdftoppm"] = "poppler-pdftoppm"
    pdfinfo_sha256: Sha256
    pdftoppm_sha256: Sha256
    scale_to_px: Literal[2400] = 2400
    output_format: Literal["PNG"] = "PNG"


class PdfDocumentReviewPageMember(FrozenModel):
    page_number: int = Field(ge=1, le=2000)
    member_path: str = Field(pattern=r"^pages/page-[0-9]{4}\.png$")
    sha256: Sha256
    content_length: int = Field(ge=1, le=64 * 1024 * 1024)
    width_px: int = Field(ge=64, le=2400)
    height_px: int = Field(ge=64, le=2400)
    rotation_degrees: Literal[0] = 0

    @model_validator(mode="after")
    def require_page_path(self) -> PdfDocumentReviewPageMember:
        if self.member_path != f"pages/page-{self.page_number:04d}.png":
            raise ValueError("PDF document-review page path differs from its page number")
        return self


class PdfDocumentReviewIntakeManifest(FrozenModel):
    schema_version: Literal["pdf-document-review-intake-manifest/1.0"] = (
        "pdf-document-review-intake-manifest/1.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    source_pdf_sha256: Sha256
    source_pdf_bytes: int = Field(ge=8, le=256 * 1024 * 1024)
    renderer: PdfDocumentReviewRendererIdentity
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfDocumentReviewPageMember, ...] = Field(min_length=1, max_length=2000)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_pages_and_hash(self) -> PdfDocumentReviewIntakeManifest:
        if len(self.pages) != self.page_count:
            raise ValueError("PDF document-review manifest page count differs")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF document-review manifest pages must be complete and ordered")
        paths = tuple(page.member_path for page in self.pages)
        if len(paths) != len(set(paths)):
            raise ValueError("PDF document-review manifest page paths must be unique")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("PDF document-review intake manifest hash differs")
        return self

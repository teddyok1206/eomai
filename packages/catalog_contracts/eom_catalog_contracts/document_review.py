"""Immutable Catalog contracts for PDF document-review intake."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DocumentId = Annotated[str, Field(pattern=r"^document_[0-9a-f]{32}$")]
DocumentRevisionId = Annotated[str, Field(pattern=r"^documentrev_[0-9a-f]{32}$")]
ArtifactId = Annotated[str, Field(pattern=r"^artifact_[0-9a-f]{32}$")]
ArtifactRevisionId = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{32}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class PdfReviewArtifactMemberPointer(FrozenModel):
    """One exact member of the immutable Catalog-owned review source Artifact."""

    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    member_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    sha256: Sha256
    schema_ref: str = Field(pattern=r"^eom://schemas/document-review/[a-z0-9-]+/1\.0$")
    media_type: Literal["application/pdf", "image/png", "application/json"]
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)

    @field_validator("member_path")
    @classmethod
    def require_safe_relative_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.startswith("/"):
            raise ValueError("PDF review Artifact member path is unsafe")
        return value


class PdfReviewPagePointer(FrozenModel):
    """One ordered page render used for worker and browser materialization."""

    page_number: int = Field(ge=1, le=2000)
    width_px: int = Field(ge=64, le=16384)
    height_px: int = Field(ge=64, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270]
    page_image: PdfReviewArtifactMemberPointer
    text_layer: PdfReviewArtifactMemberPointer | None

    @model_validator(mode="after")
    def require_exact_member_contracts(self) -> PdfReviewPagePointer:
        expected_prefix = f"pages/page-{self.page_number:04d}"
        if (
            self.page_image.media_type != "image/png"
            or self.page_image.schema_ref != "eom://schemas/document-review/pdf-page-render/1.0"
            or self.page_image.member_path != f"{expected_prefix}.png"
        ):
            raise ValueError("PDF review page image pointer differs from its exact page contract")
        if self.text_layer is not None and (
            self.text_layer.media_type != "application/json"
            or self.text_layer.schema_ref != "eom://schemas/document-review/pdf-page-text/1.0"
            or self.text_layer.member_path != f"{expected_prefix}.text.json"
        ):
            raise ValueError("PDF review text pointer differs from its exact page contract")
        return self


class PdfReviewDocumentPointer(FrozenModel):
    """Immutable source and ordered derived pages for one PDF document revision."""

    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    source_pdf: PdfReviewArtifactMemberPointer
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfReviewPagePointer, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_document_members(self) -> PdfReviewDocumentPointer:
        if (
            self.source_pdf.media_type != "application/pdf"
            or self.source_pdf.schema_ref != "eom://schemas/document-review/pdf-source/1.0"
            or self.source_pdf.member_path != "source/original.pdf"
        ):
            raise ValueError("PDF source pointer differs from its exact source contract")
        if len(self.pages) != self.page_count:
            raise ValueError("PDF page count differs from the ordered page pointer count")
        page_numbers = tuple(page.page_number for page in self.pages)
        if page_numbers != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF page pointers must be complete and ordered from one")
        source_identity = (
            self.source_pdf.artifact_id,
            self.source_pdf.artifact_revision_id,
        )
        if any(
            (member.artifact_id, member.artifact_revision_id) != source_identity
            for page in self.pages
            for member in (page.page_image, page.text_layer)
            if member is not None
        ):
            raise ValueError("PDF review members must belong to the exact source Artifact revision")
        member_keys = [
            (page.page_image.artifact_revision_id, page.page_image.member_path)
            for page in self.pages
        ]
        member_keys.extend(
            (page.text_layer.artifact_revision_id, page.text_layer.member_path)
            for page in self.pages
            if page.text_layer is not None
        )
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("PDF review page members must be unique")
        return self


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

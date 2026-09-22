"""Private streaming application contracts for immutable PDF review intake."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.document_review import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
)

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES = 16 * 1024 * 1024


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class PdfDocumentReviewIntakeCommand(FrozenModel):
    """Header sent before exactly ``content_length`` raw PDF bytes."""

    schema_version: Literal["pdf-document-review-intake-request/1.0"] = (
        "pdf-document-review-intake-request/1.0"
    )
    operation: Literal["INGEST_PDF_DOCUMENT_REVIEW_SOURCE"] = "INGEST_PDF_DOCUMENT_REVIEW_SOURCE"
    actor_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,255}$",
    )
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    sha256: Sha256


class PdfDocumentReviewIntakeResponse(FrozenModel):
    """Bounded response carrying either one exact document pointer or one stable error."""

    schema_version: Literal["pdf-document-review-intake-response/1.0"] = (
        "pdf-document-review-intake-response/1.0"
    )
    operation: Literal["INGEST_PDF_DOCUMENT_REVIEW_SOURCE"] = "INGEST_PDF_DOCUMENT_REVIEW_SOURCE"
    status: Literal["OK", "ERROR"]
    document: PdfReviewDocumentPointer | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> PdfDocumentReviewIntakeResponse:
        if self.status == "OK":
            if self.document is None or self.error_code is not None:
                raise ValueError("successful PDF intake requires only a document pointer")
        elif self.document is not None or self.error_code is None:
            raise ValueError("failed PDF intake requires only one stable error code")
        return self


class PdfDocumentReviewPageMediaQuery(FrozenModel):
    """Resolve one exact rendered page from an immutable PDF review source."""

    schema_version: Literal["pdf-document-review-page-media-request/1.0"] = (
        "pdf-document-review-page-media-request/1.0"
    )
    operation: Literal["GET_PDF_DOCUMENT_REVIEW_PAGE_IMAGE"] = "GET_PDF_DOCUMENT_REVIEW_PAGE_IMAGE"
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    page_number: int = Field(ge=1, le=2000)
    page_image: PdfReviewArtifactMemberPointer

    @model_validator(mode="after")
    def require_exact_page_pointer(self) -> PdfDocumentReviewPageMediaQuery:
        if (
            self.page_image.member_path != f"pages/page-{self.page_number:04d}.png"
            or self.page_image.media_type != "image/png"
            or self.page_image.schema_ref != "eom://schemas/document-review/pdf-page-render/1.0"
            or self.page_image.content_length > PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES
        ):
            raise ValueError("PDF review page-media pointer differs from its page contract")
        return self


class PdfDocumentReviewPageMediaResponse(FrozenModel):
    """Bounded streaming header for one verified PDF review page image."""

    schema_version: Literal["pdf-document-review-page-media-response/1.0"] = (
        "pdf-document-review-page-media-response/1.0"
    )
    operation: Literal["GET_PDF_DOCUMENT_REVIEW_PAGE_IMAGE"] = "GET_PDF_DOCUMENT_REVIEW_PAGE_IMAGE"
    status: Literal["OK", "ERROR"]
    media_type: Literal["image/png"] | None = None
    content_length: int | None = Field(
        default=None,
        ge=1,
        le=PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES,
    )
    sha256: Sha256 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> PdfDocumentReviewPageMediaResponse:
        success = (self.media_type, self.content_length, self.sha256)
        if self.status == "OK":
            if any(value is None for value in success) or self.error_code is not None:
                raise ValueError("successful PDF page media requires only stream metadata")
        elif any(value is not None for value in success) or self.error_code is None:
            raise ValueError("failed PDF page media requires only one stable error code")
        return self

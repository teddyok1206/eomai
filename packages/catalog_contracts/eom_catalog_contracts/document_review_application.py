"""Private streaming application contracts for immutable PDF review intake."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.document_review import (
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewMemberPointer,
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


class OfficeDocumentReviewIntakeCommand(FrozenModel):
    """Header sent before exactly ``content_length`` raw PDF, HWP, or HWPX bytes."""

    schema_version: Literal["document-review-intake-request/2.0"] = (
        "document-review-intake-request/2.0"
    )
    operation: Literal["INGEST_DOCUMENT_REVIEW_SOURCE"] = "INGEST_DOCUMENT_REVIEW_SOURCE"
    actor_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["PDF", "HWP", "HWPX"]
    media_type: Literal[
        "application/pdf",
        "application/vnd.hancom.hwp",
        "application/vnd.hancom.hwpx",
    ]
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,255}$",
    )
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    sha256: Sha256

    @model_validator(mode="after")
    def require_format_media_and_suffix(self) -> OfficeDocumentReviewIntakeCommand:
        expected = {
            "PDF": (".pdf", "application/pdf"),
            "HWP": (".hwp", "application/vnd.hancom.hwp"),
            "HWPX": (".hwpx", "application/vnd.hancom.hwpx"),
        }[self.source_format]
        if (
            not self.original_filename.lower().endswith(expected[0])
            or self.media_type != expected[1]
        ):
            raise ValueError("Office review filename, format, and media type differ")
        return self


class OfficeDocumentReviewSourcePointer(FrozenModel):
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["PDF", "HWP", "HWPX"]
    original_source: OfficeDocumentReviewMemberPointer
    review_document: PdfReviewDocumentPointer
    editable_hwpx: OfficeDocumentReviewMemberPointer | None
    intake_manifest: OfficeDocumentReviewMemberPointer
    conversion: OfficeDocumentReviewConversionIdentity

    @model_validator(mode="after")
    def require_exact_source_document(self) -> OfficeDocumentReviewSourcePointer:
        identity = (self.original_source.artifact_id, self.original_source.artifact_revision_id)
        members: list[OfficeDocumentReviewMemberPointer | PdfReviewArtifactMemberPointer] = [
            self.intake_manifest,
            self.review_document.source_pdf,
        ]
        members.extend(page.page_image for page in self.review_document.pages)
        members.extend(
            page.text_layer for page in self.review_document.pages if page.text_layer is not None
        )
        if self.editable_hwpx is not None:
            members.append(self.editable_hwpx)
        if any((member.artifact_id, member.artifact_revision_id) != identity for member in members):
            raise ValueError("Office review pointers must share one immutable Artifact revision")
        if (
            self.document_id != self.review_document.document_id
            or self.document_revision_id != self.review_document.document_revision_id
        ):
            raise ValueError("Office review projection identity differs from its source document")
        if (
            self.review_document.source_pdf.sha256 != self.conversion.review_pdf_sha256
            or self.review_document.source_pdf.member_path != "source/original.pdf"
        ):
            raise ValueError("Office review PDF projection differs from conversion identity")
        if (
            self.intake_manifest.member_path != "manifest.json"
            or self.intake_manifest.media_type != "application/json"
            or self.intake_manifest.schema_ref
            != "eom://schemas/document-review/document-review-intake-manifest/2.0"
        ):
            raise ValueError("Office review intake manifest pointer differs")
        expected_source = {
            "PDF": (
                ".pdf",
                "application/pdf",
                "eom://schemas/document-review/pdf-source/1.0",
                None,
                "IDENTITY_PDF",
            ),
            "HWP": (
                ".hwp",
                "application/vnd.hancom.hwp",
                "eom://schemas/document-review/hwp-source/2.0",
                None,
                "LIBREOFFICE_H2ORESTART_PDF",
            ),
            "HWPX": (
                ".hwpx",
                "application/vnd.hancom.hwpx",
                "eom://schemas/document-review/editable-hwpx/1.0",
                self.original_source,
                "LIBREOFFICE_H2ORESTART_PDF",
            ),
        }[self.source_format]
        if (
            not self.original_filename.lower().endswith(expected_source[0])
            or self.original_source.member_path != f"source/original{expected_source[0]}"
            or self.original_source.media_type != expected_source[1]
            or self.original_source.schema_ref != expected_source[2]
            or self.editable_hwpx != expected_source[3]
            or self.conversion.conversion_kind != expected_source[4]
        ):
            raise ValueError("Office review source pointer differs from its declared format")
        return self


class OfficeDocumentReviewIntakeResponse(FrozenModel):
    schema_version: Literal["document-review-intake-response/2.0"] = (
        "document-review-intake-response/2.0"
    )
    operation: Literal["INGEST_DOCUMENT_REVIEW_SOURCE"] = "INGEST_DOCUMENT_REVIEW_SOURCE"
    status: Literal["OK", "ERROR"]
    document: OfficeDocumentReviewSourcePointer | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> OfficeDocumentReviewIntakeResponse:
        if self.status == "OK":
            if self.document is None or self.error_code is not None:
                raise ValueError("successful Office intake requires only a document pointer")
        elif self.document is not None or self.error_code is None:
            raise ValueError("failed Office intake requires only one stable error code")
        return self


class ApplyDocumentReviewHwpxCorrections(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-request/1.0"] = (
        "document-review-hwpx-correction-request/1.0"
    )
    operation: Literal["APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"] = (
        "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"
    )
    actor_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,255}$",
    )
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    review_result: OfficeDocumentReviewMemberPointer
    base_hwpx: OfficeDocumentReviewMemberPointer
    finding_ids: tuple[Annotated[str, Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")], ...] = Field(
        min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def require_exact_correction_request(self) -> ApplyDocumentReviewHwpxCorrections:
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("HWPX correction finding IDs must be unique")
        if (
            self.review_result.member_path != "result.json"
            or self.review_result.media_type != "application/json"
            or self.review_result.schema_ref != "eom://schemas/document-review/review-result/1.0"
        ):
            raise ValueError("HWPX correction review pointer differs")
        if (
            self.base_hwpx.member_path != "source/original.hwpx"
            or self.base_hwpx.media_type != "application/vnd.hancom.hwpx"
            or self.base_hwpx.schema_ref != "eom://schemas/document-review/editable-hwpx/1.0"
        ):
            raise ValueError("HWPX correction base pointer differs")
        return self

"""Private streaming application contracts for immutable PDF review intake."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.document_review import (
    DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER,
    DocumentReviewAnnotatedPdfPointer,
    DocumentReviewAnnotationSource,
    DocumentReviewHwpxCorrectionResult,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationResult,
    DocumentReviewPdfAnnotationResultV2,
    DocumentReviewResultMemberPointer,
    GraphGroundedDocumentReviewResultMemberPointer,
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewMemberPointer,
    OfficeDocumentReviewMemberPointerV2,
    PdfDocumentReviewResultMemberPointer,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
)

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES = 16 * 1024 * 1024
OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER = "document-manifest.json"
_OFFICE_DOCUMENT_REVIEW_COMPATIBLE_INTAKE_MANIFEST_MEMBERS = (
    "manifest.json",
    OFFICE_DOCUMENT_REVIEW_INTAKE_MANIFEST_MEMBER,
)


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


class OfficeDocumentReviewIntakeCommandV3(FrozenModel):
    """Successor intake header that requires durable source admission."""

    schema_version: Literal["document-review-intake-request/3.0"] = (
        "document-review-intake-request/3.0"
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
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["HWP", "HWPX"]
    media_type: Literal[
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
    def require_format_media_and_suffix(self) -> OfficeDocumentReviewIntakeCommandV3:
        suffix, media_type = {
            "HWP": (".hwp", "application/vnd.hancom.hwp"),
            "HWPX": (".hwpx", "application/vnd.hancom.hwpx"),
        }[self.source_format]
        if not self.original_filename.lower().endswith(suffix) or self.media_type != media_type:
            raise ValueError("Office V3 review filename, format, and media type differ")
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
            self.intake_manifest.member_path
            not in _OFFICE_DOCUMENT_REVIEW_COMPATIBLE_INTAKE_MANIFEST_MEMBERS
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


class OfficeDocumentReviewSourcePointerV2(FrozenModel):
    """Office source and a separately committed immutable PDF projection."""

    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["HWP", "HWPX"]
    original_source: OfficeDocumentReviewMemberPointerV2
    review_document: PdfReviewDocumentPointer
    editable_hwpx: OfficeDocumentReviewMemberPointerV2 | None
    intake_manifest: OfficeDocumentReviewMemberPointerV2
    conversion: OfficeDocumentReviewConversionIdentity

    @model_validator(mode="after")
    def require_exact_split_source_document(self) -> OfficeDocumentReviewSourcePointerV2:
        projection_identity = (
            self.review_document.source_pdf.artifact_id,
            self.review_document.source_pdf.artifact_revision_id,
        )
        projection_members: list[
            OfficeDocumentReviewMemberPointerV2 | PdfReviewArtifactMemberPointer
        ] = [
            self.intake_manifest,
        ]
        projection_members.extend(page.page_image for page in self.review_document.pages)
        projection_members.extend(
            page.text_layer for page in self.review_document.pages if page.text_layer is not None
        )
        if any(
            (member.artifact_id, member.artifact_revision_id) != projection_identity
            for member in projection_members
        ):
            raise ValueError("Office review V3 projection pointers must share one revision")
        source_identity = (
            self.original_source.artifact_id,
            self.original_source.artifact_revision_id,
        )
        if source_identity == projection_identity:
            raise ValueError("Office review V3 source and projection revisions must be distinct")
        if (
            self.document_id != self.review_document.document_id
            or self.document_revision_id != self.review_document.document_revision_id
            or self.review_document.source_pdf.sha256 != self.conversion.review_pdf_sha256
            or self.review_document.source_pdf.member_path != "source/original.pdf"
            or self.intake_manifest.member_path
            not in _OFFICE_DOCUMENT_REVIEW_COMPATIBLE_INTAKE_MANIFEST_MEMBERS
            or self.intake_manifest.media_type != "application/json"
            or self.intake_manifest.schema_ref
            != "eom://schemas/document-review/document-review-intake-manifest/3.0"
            or self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF"
        ):
            raise ValueError("Office review V3 projection identity differs")
        suffix, media_type, schema_ref = {
            "HWP": (
                ".hwp",
                "application/vnd.hancom.hwp",
                "eom://schemas/document-review/hwp-source/2.0",
            ),
            "HWPX": (
                ".hwpx",
                "application/vnd.hancom.hwpx",
                "eom://schemas/document-review/editable-hwpx/1.0",
            ),
        }[self.source_format]
        expected_editable = self.original_source if self.source_format == "HWPX" else None
        if (
            not self.original_filename.lower().endswith(suffix)
            or self.original_source.member_path != f"source/original{suffix}"
            or self.original_source.media_type != media_type
            or self.original_source.schema_ref != schema_ref
            or self.editable_hwpx != expected_editable
        ):
            raise ValueError("Office review V3 source pointer differs from its format")
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


class OfficeDocumentReviewIntakeResponseV3(FrozenModel):
    schema_version: Literal["document-review-intake-response/3.0"] = (
        "document-review-intake-response/3.0"
    )
    operation: Literal["INGEST_DOCUMENT_REVIEW_SOURCE"] = "INGEST_DOCUMENT_REVIEW_SOURCE"
    status: Literal["OK", "ERROR"]
    document: OfficeDocumentReviewSourcePointerV2 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    retained_source: OfficeDocumentReviewMemberPointerV2 | None = None

    @model_validator(mode="after")
    def require_one_response_variant(self) -> OfficeDocumentReviewIntakeResponseV3:
        if self.status == "OK":
            if (
                self.document is None
                or self.error_code is not None
                or self.retained_source is not None
                or "error_code" in self.model_fields_set
                or "retained_source" in self.model_fields_set
            ):
                raise ValueError("successful Office V3 intake requires only a document pointer")
        elif (
            self.document is not None
            or "document" in self.model_fields_set
            or self.error_code is None
            or "retained_source" not in self.model_fields_set
        ):
            raise ValueError("failed Office V3 intake requires one stable error code")
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
    review_result: PdfDocumentReviewResultMemberPointer
    base_hwpx: OfficeDocumentReviewMemberPointer
    finding_ids: tuple[Annotated[str, Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")], ...] = Field(
        min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def require_exact_correction_request(self) -> ApplyDocumentReviewHwpxCorrections:
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("HWPX correction finding IDs must be unique")
        if (
            self.base_hwpx.member_path != "source/original.hwpx"
            or self.base_hwpx.media_type != "application/vnd.hancom.hwpx"
            or self.base_hwpx.schema_ref != "eom://schemas/document-review/editable-hwpx/1.0"
        ):
            raise ValueError("HWPX correction base pointer differs")
        return self


class DocumentReviewHwpxCorrectionResponse(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-response/1.0"] = (
        "document-review-hwpx-correction-response/1.0"
    )
    operation: Literal["APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"] = (
        "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS"
    )
    status: Literal["OK", "ERROR"]
    output: OfficeDocumentReviewMemberPointer | None = None
    result: DocumentReviewHwpxCorrectionResult | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_exact_response(self) -> DocumentReviewHwpxCorrectionResponse:
        if self.status == "OK":
            if self.output is None or self.result is None or self.error_code is not None:
                raise ValueError("successful HWPX correction requires output and result")
            expected = self.result.output_member
            if (
                self.output.member_path != expected.member_path
                or self.output.sha256 != expected.sha256
                or self.output.content_length != expected.content_length
                or self.output.media_type != expected.media_type
                or self.output.schema_ref != "eom://schemas/document-review/corrected-hwpx/1.0"
            ):
                raise ValueError("HWPX correction output pointer differs from its result")
        elif self.output is not None or self.result is not None or self.error_code is None:
            raise ValueError("failed HWPX correction requires only one stable error code")
        return self


class DocumentReviewHwpxCorrectionMediaQuery(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-media-request/1.0"] = (
        "document-review-hwpx-correction-media-request/1.0"
    )
    operation: Literal["GET_DOCUMENT_REVIEW_CORRECTED_HWPX"] = "GET_DOCUMENT_REVIEW_CORRECTED_HWPX"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    correction_id: str = Field(pattern=r"^doccorrection_[0-9a-f]{32}$")
    output: OfficeDocumentReviewMemberPointer

    @model_validator(mode="after")
    def require_exact_output(self) -> DocumentReviewHwpxCorrectionMediaQuery:
        if (
            self.output.member_path != "corrected/document-review-redline.hwpx"
            or self.output.media_type != "application/vnd.hancom.hwpx"
            or self.output.schema_ref != "eom://schemas/document-review/corrected-hwpx/1.0"
        ):
            raise ValueError("HWPX correction media pointer differs")
        return self


class DocumentReviewHwpxCorrectionMediaResponse(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-media-response/1.0"] = (
        "document-review-hwpx-correction-media-response/1.0"
    )
    operation: Literal["GET_DOCUMENT_REVIEW_CORRECTED_HWPX"] = "GET_DOCUMENT_REVIEW_CORRECTED_HWPX"
    status: Literal["OK", "ERROR"]
    media_type: Literal["application/vnd.hancom.hwpx"] | None = None
    content_length: int | None = Field(default=None, ge=1, le=256 * 1024 * 1024)
    sha256: Sha256 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> DocumentReviewHwpxCorrectionMediaResponse:
        success = (self.media_type, self.content_length, self.sha256)
        if self.status == "OK":
            if any(value is None for value in success) or self.error_code is not None:
                raise ValueError("successful HWPX media response requires stream metadata")
        elif any(value is not None for value in success) or self.error_code is None:
            raise ValueError("failed HWPX media response requires only one stable error code")
        return self


class CreateDocumentReviewAnnotatedPdfs(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-request/1.0"] = (
        "document-review-pdf-annotation-request/1.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"] = (
        "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"
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
    review_result: DocumentReviewResultMemberPointer
    sources: tuple[DocumentReviewAnnotationSource, ...] = Field(min_length=1, max_length=2)
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...] = Field(
        min_length=1,
        max_length=4096,
    )
    annotation_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_request(self) -> CreateDocumentReviewAnnotatedPdfs:
        source_roles = tuple(value.role for value in self.sources)
        if source_roles not in {("DOCUMENT",), ("QUESTION", "SOLUTION")}:
            raise ValueError("annotation request source roles are invalid")
        source_pages = {
            (source.role, page.page_number): page.page_image.sha256
            for source in self.sources
            for page in source.pages
        }
        annotation_keys = tuple(
            (
                value.document_role,
                value.page_number,
                value.ordinal,
                value.anchor_id,
            )
            for value in self.annotations
        )
        if annotation_keys != tuple(sorted(set(annotation_keys))):
            raise ValueError("annotation marks must be sorted and unique")
        if any(
            source_pages.get((value.document_role, value.page_number)) != value.page_image_sha256
            for value in self.annotations
        ):
            raise ValueError("annotation mark differs from its pinned page")
        dumped_annotations = [value.model_dump(mode="json") for value in self.annotations]
        if content_sha256(dumped_annotations) != self.annotation_set_sha256:
            raise ValueError("annotation set hash differs")
        if (
            content_sha256(
                self.model_dump(
                    mode="json",
                    exclude={"idempotency_key", "request_sha256"},
                )
            )
            != self.request_sha256
        ):
            raise ValueError("annotation request self-hash differs")
        return self


class DocumentReviewPdfAnnotationResponse(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-response/1.0"] = (
        "document-review-pdf-annotation-response/1.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"] = (
        "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS"
    )
    status: Literal["OK", "ERROR"]
    outputs: tuple[DocumentReviewAnnotatedPdfPointer, ...] | None = None
    manifest: OfficeDocumentReviewMemberPointer | None = None
    result: DocumentReviewPdfAnnotationResult | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> DocumentReviewPdfAnnotationResponse:
        if self.status == "OK":
            if (
                self.outputs is None
                or self.manifest is None
                or self.result is None
                or self.error_code is not None
            ):
                raise ValueError("successful annotation response requires immutable outputs")
            if tuple(value.document_role for value in self.outputs) != tuple(
                value.document_role for value in self.result.outputs
            ):
                raise ValueError("annotation response output roles differ from its result")
            if any(
                pointer.member_path != descriptor.member_path
                or pointer.sha256 != descriptor.sha256
                or pointer.content_length != descriptor.content_length
                for pointer, descriptor in zip(self.outputs, self.result.outputs, strict=True)
            ):
                raise ValueError("annotation response output pointers differ from its result")
            if (
                self.manifest.member_path
                not in ("manifest.json", DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER)
                or self.manifest.media_type != "application/json"
                or self.manifest.schema_ref
                != "eom://schemas/document-review/document-review-pdf-annotation-manifest/1.0"
            ):
                raise ValueError("annotation response manifest pointer differs")
        elif any(value is not None for value in (self.outputs, self.manifest, self.result)) or (
            self.error_code is None
        ):
            raise ValueError("failed annotation response requires only one stable error code")
        return self


class CreateDocumentReviewAnnotatedPdfsV2(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-request/2.0"] = (
        "document-review-pdf-annotation-request/2.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"] = (
        "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"
    )
    annotation_profile: Literal["NUMBERED_BOXES_WITH_NATIVE_COMMENTS"] = (
        "NUMBERED_BOXES_WITH_NATIVE_COMMENTS"
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
    review_result: DocumentReviewResultMemberPointer
    sources: tuple[DocumentReviewAnnotationSource, ...] = Field(min_length=1, max_length=2)
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...] = Field(
        min_length=1,
        max_length=4096,
    )
    annotation_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_request(self) -> CreateDocumentReviewAnnotatedPdfsV2:
        source_roles = tuple(value.role for value in self.sources)
        if source_roles not in {("DOCUMENT",), ("QUESTION", "SOLUTION")}:
            raise ValueError("annotation request source roles are invalid")
        source_pages = {
            (source.role, page.page_number): page.page_image.sha256
            for source in self.sources
            for page in source.pages
        }
        annotation_keys = tuple(
            (
                value.document_role,
                value.page_number,
                value.ordinal,
                value.anchor_id,
            )
            for value in self.annotations
        )
        if annotation_keys != tuple(sorted(set(annotation_keys))):
            raise ValueError("annotation marks must be sorted and unique")
        if any(
            source_pages.get((value.document_role, value.page_number)) != value.page_image_sha256
            for value in self.annotations
        ):
            raise ValueError("annotation mark differs from its pinned page")
        dumped_annotations = [value.model_dump(mode="json") for value in self.annotations]
        if content_sha256(dumped_annotations) != self.annotation_set_sha256:
            raise ValueError("annotation set hash differs")
        if (
            content_sha256(
                self.model_dump(
                    mode="json",
                    exclude={"idempotency_key", "request_sha256"},
                )
            )
            != self.request_sha256
        ):
            raise ValueError("annotation request self-hash differs")
        return self


class CreateDocumentReviewAnnotatedPdfsV3(CreateDocumentReviewAnnotatedPdfsV2):
    """Native-panel annotation request for a Graph-grounded V3 review result."""

    schema_version: Literal["document-review-pdf-annotation-request/3.0"] = (
        "document-review-pdf-annotation-request/3.0"  # type: ignore[assignment]
    )
    review_result: GraphGroundedDocumentReviewResultMemberPointer  # type: ignore[assignment]


class DocumentReviewPdfAnnotationResponseV2(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-response/2.0"] = (
        "document-review-pdf-annotation-response/2.0"
    )
    operation: Literal["CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"] = (
        "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS_V2"
    )
    status: Literal["OK", "ERROR"]
    outputs: tuple[DocumentReviewAnnotatedPdfPointer, ...] | None = None
    manifest: OfficeDocumentReviewMemberPointer | None = None
    result: DocumentReviewPdfAnnotationResultV2 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> DocumentReviewPdfAnnotationResponseV2:
        if self.status == "OK":
            if (
                self.outputs is None
                or self.manifest is None
                or self.result is None
                or self.error_code is not None
            ):
                raise ValueError("successful annotation response requires immutable outputs")
            if tuple(value.document_role for value in self.outputs) != tuple(
                value.document_role for value in self.result.outputs
            ):
                raise ValueError("annotation response output roles differ from its result")
            if any(
                pointer.member_path != descriptor.member_path
                or pointer.sha256 != descriptor.sha256
                or pointer.content_length != descriptor.content_length
                for pointer, descriptor in zip(self.outputs, self.result.outputs, strict=True)
            ):
                raise ValueError("annotation response output pointers differ from its result")
            if (
                self.manifest.member_path
                not in ("manifest.json", DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER)
                or self.manifest.media_type != "application/json"
                or self.manifest.schema_ref
                != "eom://schemas/document-review/document-review-pdf-annotation-manifest/2.0"
            ):
                raise ValueError("annotation response manifest pointer differs")
        elif any(value is not None for value in (self.outputs, self.manifest, self.result)) or (
            self.error_code is None
        ):
            raise ValueError("failed annotation response requires only one stable error code")
        return self


class DocumentReviewPdfAnnotationMediaQuery(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-media-request/1.0"] = (
        "document-review-pdf-annotation-media-request/1.0"
    )
    operation: Literal["GET_DOCUMENT_REVIEW_ANNOTATED_PDF"] = "GET_DOCUMENT_REVIEW_ANNOTATED_PDF"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    annotation_id: str = Field(pattern=r"^docannotation_[0-9a-f]{32}$")
    document_role: Literal["DOCUMENT", "QUESTION", "SOLUTION"]
    output: DocumentReviewAnnotatedPdfPointer

    @model_validator(mode="after")
    def require_exact_output(self) -> DocumentReviewPdfAnnotationMediaQuery:
        if self.output.document_role != self.document_role:
            raise ValueError("annotation media role differs from its output pointer")
        return self


class DocumentReviewPdfAnnotationMediaResponse(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-media-response/1.0"] = (
        "document-review-pdf-annotation-media-response/1.0"
    )
    operation: Literal["GET_DOCUMENT_REVIEW_ANNOTATED_PDF"] = "GET_DOCUMENT_REVIEW_ANNOTATED_PDF"
    status: Literal["OK", "ERROR"]
    media_type: Literal["application/pdf"] | None = None
    content_length: int | None = Field(default=None, ge=1, le=512 * 1024 * 1024)
    sha256: Sha256 | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def require_one_response_variant(self) -> DocumentReviewPdfAnnotationMediaResponse:
        success = (self.media_type, self.content_length, self.sha256)
        if self.status == "OK":
            if any(value is None for value in success) or self.error_code is not None:
                raise ValueError("successful annotation media response requires stream metadata")
        elif any(value is not None for value in success) or self.error_code is None:
            raise ValueError("failed annotation media response requires only one stable error code")
        return self

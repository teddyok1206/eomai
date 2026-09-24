"""Public API DTOs for immutable PDF document-review uploads."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_workflow import PairedDocumentReviewOutput, PdfDocumentReviewOutput
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, UtcDatetime

PdfReviewPresetKey = Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]
PdfReviewUploadState = Literal[
    "AWAITING_UPLOAD",
    "PROCESSING",
    "STARTED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
]
PdfDocumentReviewState = Literal["SUBMITTED", "REVIEWING", "COMPLETED", "FAILED"]
DocumentReviewSourceFormat = Literal["PDF", "HWP", "HWPX"]
DocumentReviewSourceMediaType = Literal[
    "application/pdf",
    "application/vnd.hancom.hwp",
    "application/vnd.hancom.hwpx",
]
DocumentReviewFindingId = Annotated[
    str,
    Field(pattern=r"^reviewfinding_[0-9a-f]{32}$"),
]
DocumentReviewRole = Literal["QUESTION", "SOLUTION"]
DocumentReviewSetState = Literal[
    "AWAITING_UPLOADS",
    "STARTING",
    "STARTED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
]
DocumentReviewSetMemberState = Literal[
    "AWAITING_UPLOAD",
    "PROCESSING",
    "COMMITTED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
]


class CreatePdfDocumentReviewUploadIntentRequest(ApiModel):
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    preset_key: PdfReviewPresetKey
    additional_guidance: str | None = Field(
        default=None,
        min_length=1,
        max_length=8000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    locale: Literal["ko-KR"] = "ko-KR"


class PdfDocumentReviewUploadIntentView(ApiModel):
    upload_intent_id: str = Field(pattern=r"^pdfreviewintent_[0-9a-f]{32}$")
    state: PdfReviewUploadState
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    preset_key: PdfReviewPresetKey
    additional_guidance_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    upload_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[0-9a-f]{32}$")
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    upload_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/upload-intents/"
            r"pdfreviewintent_[0-9a-f]{32}/content$"
        )
    )
    review_url: str | None = Field(
        default=None,
        pattern=r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}$",
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    expires_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_state_payload(self) -> PdfDocumentReviewUploadIntentView:
        expected_upload_url = (
            f"/api/v1/pdf-document-reviews/upload-intents/{self.upload_intent_id}/content"
        )
        if self.upload_url != expected_upload_url:
            raise ValueError("PDF review upload URL differs from its upload intent")
        if self.state == "AWAITING_UPLOAD":
            if any(
                value is not None
                for value in (
                    self.upload_sha256,
                    self.workflow_id,
                    self.failure_code,
                    self.review_url,
                )
            ):
                raise ValueError("awaiting PDF review upload exposes completed state")
        elif self.state == "PROCESSING":
            if (
                self.upload_sha256 is None
                or self.workflow_id is not None
                or self.failure_code is not None
                or self.review_url is not None
            ):
                raise ValueError("processing PDF review upload has inconsistent state")
        elif self.state == "STARTED":
            if (
                self.upload_sha256 is None
                or self.workflow_id is None
                or self.failure_code is not None
                or self.review_url != f"/api/v1/pdf-document-reviews/{self.workflow_id}"
            ):
                raise ValueError("started PDF review upload has inconsistent state")
        elif (
            self.upload_sha256 is None
            or self.workflow_id is not None
            or self.failure_code is None
            or self.review_url is not None
        ):
            raise ValueError("failed PDF review upload has inconsistent state")
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("PDF review upload intent timestamps are inconsistent")
        return self


class CreateDocumentReviewUploadIntentRequestV2(ApiModel):
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: DocumentReviewSourceFormat
    media_type: DocumentReviewSourceMediaType
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    preset_key: PdfReviewPresetKey
    additional_guidance: str | None = Field(
        default=None,
        min_length=1,
        max_length=8000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    locale: Literal["ko-KR"] = "ko-KR"

    @model_validator(mode="after")
    def require_source_identity(self) -> CreateDocumentReviewUploadIntentRequestV2:
        suffix, media_type = {
            "PDF": (".pdf", "application/pdf"),
            "HWP": (".hwp", "application/vnd.hancom.hwp"),
            "HWPX": (".hwpx", "application/vnd.hancom.hwpx"),
        }[self.source_format]
        if not self.original_filename.lower().endswith(suffix) or self.media_type != media_type:
            raise ValueError("document-review filename, format, and media type differ")
        return self


class DocumentReviewUploadIntentViewV2(ApiModel):
    upload_intent_id: str = Field(pattern=r"^pdfreviewintent_[0-9a-f]{32}$")
    state: PdfReviewUploadState
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: DocumentReviewSourceFormat
    media_type: DocumentReviewSourceMediaType
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    preset_key: PdfReviewPresetKey
    additional_guidance_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    upload_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[0-9a-f]{32}$")
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    upload_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/upload-intents/"
            r"pdfreviewintent_[0-9a-f]{32}/content$"
        )
    )
    review_url: str | None = Field(
        default=None,
        pattern=r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}$",
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    expires_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_intent(self) -> DocumentReviewUploadIntentViewV2:
        CreateDocumentReviewUploadIntentRequestV2(
            original_filename=self.original_filename,
            source_format=self.source_format,
            media_type=self.media_type,
            content_length=self.content_length,
            preset_key=self.preset_key,
        )
        expected_upload_url = (
            f"/api/v1/pdf-document-reviews/upload-intents/{self.upload_intent_id}/content"
        )
        if self.upload_url != expected_upload_url:
            raise ValueError("document-review upload URL differs from its intent")
        if self.state == "AWAITING_UPLOAD":
            if any(
                value is not None
                for value in (
                    self.upload_sha256,
                    self.workflow_id,
                    self.failure_code,
                    self.review_url,
                )
            ):
                raise ValueError("awaiting document upload exposes completed state")
        elif self.state == "PROCESSING":
            if (
                self.upload_sha256 is None
                or self.workflow_id is not None
                or self.failure_code is not None
                or self.review_url is not None
            ):
                raise ValueError("processing document upload has inconsistent state")
        elif self.state == "STARTED":
            if (
                self.upload_sha256 is None
                or self.workflow_id is None
                or self.failure_code is not None
                or self.review_url != f"/api/v1/pdf-document-reviews/{self.workflow_id}"
            ):
                raise ValueError("started document upload has inconsistent state")
        elif (
            self.upload_sha256 is None
            or self.workflow_id is not None
            or self.failure_code is None
            or self.review_url is not None
        ):
            raise ValueError("failed document upload has inconsistent state")
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("document-review upload timestamps are inconsistent")
        return self


class DocumentReviewSetSourceRequest(ApiModel):
    role: DocumentReviewRole
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: DocumentReviewSourceFormat
    media_type: DocumentReviewSourceMediaType
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)

    @model_validator(mode="after")
    def require_source_identity(self) -> DocumentReviewSetSourceRequest:
        suffix, media_type = {
            "PDF": (".pdf", "application/pdf"),
            "HWP": (".hwp", "application/vnd.hancom.hwp"),
            "HWPX": (".hwpx", "application/vnd.hancom.hwpx"),
        }[self.source_format]
        if not self.original_filename.lower().endswith(suffix) or self.media_type != media_type:
            raise ValueError("paired review filename, format, and media type differ")
        return self


class CreateDocumentReviewSetRequest(ApiModel):
    documents: tuple[DocumentReviewSetSourceRequest, DocumentReviewSetSourceRequest] = Field(
        min_length=2, max_length=2
    )
    preset_key: PdfReviewPresetKey
    additional_guidance: str | None = Field(
        default=None,
        min_length=1,
        max_length=8000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    locale: Literal["ko-KR"] = "ko-KR"

    @model_validator(mode="after")
    def require_question_then_solution(self) -> CreateDocumentReviewSetRequest:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review request requires QUESTION then SOLUTION")
        return self


class DocumentReviewSetMemberView(DocumentReviewSetSourceRequest):
    state: DocumentReviewSetMemberState
    upload_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    document_id: str | None = Field(default=None, pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str | None = Field(default=None, pattern=r"^documentrev_[0-9a-f]{32}$")
    source_pdf_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    page_count: int | None = Field(default=None, ge=1, le=2000)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    upload_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/sets/docreviewset_[0-9a-f]{32}/"
            r"documents/(?:QUESTION|SOLUTION)/content$"
        )
    )

    @model_validator(mode="after")
    def require_member_state_payload(self) -> DocumentReviewSetMemberView:
        pointers = (
            self.document_id,
            self.document_revision_id,
            self.source_pdf_sha256,
            self.page_count,
        )
        if self.state == "AWAITING_UPLOAD":
            if (
                self.upload_sha256 is not None
                or any(value is not None for value in pointers)
                or (self.failure_code is not None)
            ):
                raise ValueError("awaiting paired review member exposes processed state")
        elif self.state == "PROCESSING":
            if (
                self.upload_sha256 is None
                or any(value is not None for value in pointers)
                or (self.failure_code is not None)
            ):
                raise ValueError("processing paired review member has inconsistent state")
        elif self.state == "COMMITTED":
            if (
                self.upload_sha256 is None
                or any(value is None for value in pointers)
                or (self.failure_code is not None)
            ):
                raise ValueError("committed paired review member lacks immutable pointers")
        elif self.upload_sha256 is None or self.failure_code is None:
            raise ValueError("failed paired review member lacks its hash or failure code")
        return self


class DocumentReviewSetView(ApiModel):
    review_set_id: str = Field(pattern=r"^docreviewset_[0-9a-f]{32}$")
    state: DocumentReviewSetState
    documents: tuple[DocumentReviewSetMemberView, DocumentReviewSetMemberView] = Field(
        min_length=2, max_length=2
    )
    preset_key: PdfReviewPresetKey
    additional_guidance_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[0-9a-f]{32}$")
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    review_url: str | None = Field(
        default=None,
        pattern=r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}$",
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    expires_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_set_state(self) -> DocumentReviewSetView:
        if tuple(value.role for value in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review set requires QUESTION then SOLUTION")
        expected_urls = tuple(
            f"/api/v1/pdf-document-reviews/sets/{self.review_set_id}/documents/{value.role}/content"
            for value in self.documents
        )
        if tuple(value.upload_url for value in self.documents) != expected_urls:
            raise ValueError("paired review member URL differs from set identity")
        if self.state == "STARTED":
            if (
                self.workflow_id is None
                or self.failure_code is not None
                or self.review_url != f"/api/v1/pdf-document-reviews/{self.workflow_id}"
                or any(value.state != "COMMITTED" for value in self.documents)
            ):
                raise ValueError("started paired review set has inconsistent state")
        elif self.state == "STARTING":
            if (
                self.workflow_id is not None
                or self.failure_code is not None
                or (self.review_url is not None)
            ):
                raise ValueError("starting paired review set has inconsistent state")
        elif self.state == "AWAITING_UPLOADS":
            if (
                self.workflow_id is not None
                or self.failure_code is not None
                or (self.review_url is not None)
            ):
                raise ValueError("awaiting paired review set exposes terminal state")
        elif (
            self.workflow_id is not None or self.failure_code is None or self.review_url is not None
        ):
            raise ValueError("failed paired review set has inconsistent state")
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("paired review set timestamps are inconsistent")
        return self


class ApplyDocumentReviewCorrectionRequest(ApiModel):
    finding_ids: tuple[DocumentReviewFindingId, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_findings(self) -> ApplyDocumentReviewCorrectionRequest:
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("document-review correction finding IDs are invalid")
        return self


class DocumentReviewCorrectionEligibilityView(ApiModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    source_format: DocumentReviewSourceFormat
    correction_available: bool
    eligible_finding_ids: tuple[DocumentReviewFindingId, ...] = Field(max_length=32)
    unavailable_reason: (
        Literal[
            "SOURCE_NOT_HWPX",
            "REVIEW_NOT_COMPLETED",
            "NO_SAFE_REPLACEMENTS",
        ]
        | None
    )

    @model_validator(mode="after")
    def require_availability(self) -> DocumentReviewCorrectionEligibilityView:
        if len(self.eligible_finding_ids) != len(set(self.eligible_finding_ids)):
            raise ValueError("eligible document-review findings must be unique")
        if self.correction_available != (
            self.source_format == "HWPX"
            and bool(self.eligible_finding_ids)
            and self.unavailable_reason is None
        ):
            raise ValueError("document-review correction availability is inconsistent")
        if not self.correction_available and self.unavailable_reason is None:
            raise ValueError("unavailable document-review correction requires a reason")
        return self


class DocumentReviewCorrectionView(ApiModel):
    correction_id: str = Field(pattern=r"^doccorrection_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    state: Literal["COMPLETED"] = "COMPLETED"
    applied_finding_ids: tuple[DocumentReviewFindingId, ...] = Field(
        min_length=1,
        max_length=32,
    )
    text_color: Literal["#FF0000"] = "#FF0000"
    output_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_content_length: int = Field(ge=1, le=256 * 1024 * 1024)
    download_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/corrections/"
            r"doccorrection_[0-9a-f]{32}/download$"
        )
    )
    created_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_url_and_findings(self) -> DocumentReviewCorrectionView:
        if len(self.applied_finding_ids) != len(set(self.applied_finding_ids)):
            raise ValueError("applied document-review findings must be unique")
        expected = (
            f"/api/v1/pdf-document-reviews/{self.workflow_id}/corrections/"
            f"{self.correction_id}/download"
        )
        if self.download_url != expected:
            raise ValueError("document-review correction download URL differs")
        return self


class PdfDocumentReviewPageView(ApiModel):
    page_number: int = Field(ge=1, le=32)
    width_px: int = Field(ge=64, le=16384)
    height_px: int = Field(ge=64, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270]
    image_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_content_length: int = Field(ge=1, le=16 * 1024 * 1024)
    image_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/pages/"
            r"(?:[1-9]|[12][0-9]|3[0-2])/image$"
        )
    )


class PdfDocumentReviewResultArtifactView(ApiModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PairedDocumentReviewPageView(ApiModel):
    document_role: DocumentReviewRole
    page_number: int = Field(ge=1, le=64)
    width_px: int = Field(ge=64, le=16384)
    height_px: int = Field(ge=64, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270]
    image_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_content_length: int = Field(ge=1, le=16 * 1024 * 1024)
    image_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/documents/"
            r"(?:QUESTION|SOLUTION)/pages/(?:[1-9]|[1-5][0-9]|6[0-4])/image$"
        )
    )


class PairedDocumentReviewDocumentView(ApiModel):
    role: DocumentReviewRole
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: DocumentReviewSourceFormat
    source_pdf_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    page_count: int = Field(ge=1, le=64)
    pages: tuple[PairedDocumentReviewPageView, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_exact_document_view(self) -> PairedDocumentReviewDocumentView:
        expected_suffix = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}[self.source_format]
        if not self.original_filename.lower().endswith(expected_suffix):
            raise ValueError("paired review filename differs from its source format")
        if len(self.pages) != self.page_count:
            raise ValueError("paired review page count differs from its pages")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("paired review pages must be complete and ordered")
        if any(page.document_role != self.role for page in self.pages):
            raise ValueError("paired review page role differs from its document")
        return self


class PairedDocumentReviewView(ApiModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    state: PdfDocumentReviewState
    documents: tuple[
        PairedDocumentReviewDocumentView,
        PairedDocumentReviewDocumentView,
    ] = Field(min_length=2, max_length=2)
    preset_key: PdfReviewPresetKey
    preset_display_name: Literal["N제", "주간지", "모의고사"]
    additional_guidance_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    result_artifact: PdfDocumentReviewResultArtifactView | None = None
    result: PairedDocumentReviewOutput | None = None
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_paired_projection(self) -> PairedDocumentReviewView:
        if tuple(document.role for document in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review view requires QUESTION then SOLUTION")
        if len({document.document_revision_id for document in self.documents}) != 2:
            raise ValueError("paired review view requires distinct document revisions")
        for document in self.documents:
            for page in document.pages:
                expected_url = (
                    f"/api/v1/pdf-document-reviews/{self.workflow_id}/documents/"
                    f"{document.role}/pages/{page.page_number}/image"
                )
                if page.image_url != expected_url:
                    raise ValueError("paired review page URL differs from its exact role")
        display_names = {
            "PROBLEM_SET": "N제",
            "WEEKLY_WORKBOOK": "주간지",
            "MOCK_EXAM": "모의고사",
        }
        if self.preset_display_name != display_names[self.preset_key]:
            raise ValueError("paired review preset display name differs from its key")
        if self.state == "COMPLETED":
            identities = tuple(
                (document.role, document.document_id, document.document_revision_id)
                for document in self.documents
            )
            result_identities = (
                tuple(
                    (document.role, document.document_id, document.document_revision_id)
                    for document in self.result.documents
                )
                if self.result is not None
                else ()
            )
            if (
                self.result_artifact is None
                or self.result is None
                or self.failure_code is not None
                or identities != result_identities
                or self.result.preset_key != self.preset_key
                or self.result.additional_guidance_sha256 != self.additional_guidance_sha256
            ):
                raise ValueError("completed paired review has an inconsistent result")
        elif self.result_artifact is not None or self.result is not None:
            raise ValueError("non-completed paired review cannot expose a result")
        if self.state == "FAILED" and self.failure_code is None:
            raise ValueError("failed paired review requires a stable failure code")
        if self.state != "FAILED" and self.failure_code is not None:
            raise ValueError("non-failed paired review cannot expose a failure code")
        if self.updated_at < self.created_at:
            raise ValueError("paired review timestamps are inconsistent")
        return self


class PdfDocumentReviewView(ApiModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    state: PdfDocumentReviewState
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: DocumentReviewSourceFormat = "PDF"
    source_pdf_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    page_count: int = Field(ge=1, le=32)
    pages: tuple[PdfDocumentReviewPageView, ...] = Field(min_length=1, max_length=32)
    preset_key: PdfReviewPresetKey
    preset_display_name: Literal["N제", "주간지", "모의고사"]
    additional_guidance_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    result_artifact: PdfDocumentReviewResultArtifactView | None = None
    result: PdfDocumentReviewOutput | None = None
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_review_projection(self) -> PdfDocumentReviewView:
        expected_suffix = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}[self.source_format]
        if not self.original_filename.lower().endswith(expected_suffix):
            raise ValueError("document-review filename differs from its source format")
        if len(self.pages) != self.page_count:
            raise ValueError("PDF review page count differs from its view pages")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF review pages must be complete and ordered")
        for page in self.pages:
            expected_url = (
                f"/api/v1/pdf-document-reviews/{self.workflow_id}/pages/{page.page_number}/image"
            )
            if page.image_url != expected_url:
                raise ValueError("PDF review page URL differs from its Workflow and page")
        display_names = {
            "PROBLEM_SET": "N제",
            "WEEKLY_WORKBOOK": "주간지",
            "MOCK_EXAM": "모의고사",
        }
        if self.preset_display_name != display_names[self.preset_key]:
            raise ValueError("PDF review preset display name differs from its key")
        if self.state == "COMPLETED":
            if (
                self.result_artifact is None
                or self.result is None
                or self.failure_code is not None
                or self.result.document_id != self.document_id
                or self.result.document_revision_id != self.document_revision_id
                or self.result.source_pdf_sha256 != self.source_pdf_sha256
                or self.result.preset_key != self.preset_key
                or self.result.additional_guidance_sha256 != self.additional_guidance_sha256
            ):
                raise ValueError("completed PDF review has an inconsistent result projection")
        elif self.result_artifact is not None or self.result is not None:
            raise ValueError("non-completed PDF review cannot expose a result")
        if self.state == "FAILED" and self.failure_code is None:
            raise ValueError("failed PDF review requires a stable failure code")
        if self.state != "FAILED" and self.failure_code is not None:
            raise ValueError("non-failed PDF review cannot expose a failure code")
        if self.updated_at < self.created_at:
            raise ValueError("PDF review timestamps are inconsistent")
        return self


class CreateDocumentReviewAnnotationRequest(ApiModel):
    include_all_findings: Literal[True] = True


class CreateDocumentReviewAnnotationRequestV2(ApiModel):
    include_all_findings: Literal[True] = True
    annotation_profile: Literal["NUMBERED_BOXES_WITH_NATIVE_COMMENTS"]


class DocumentReviewAnnotationOutputView(ApiModel):
    document_role: Literal["DOCUMENT", "QUESTION", "SOLUTION"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_length: int = Field(ge=1, le=512 * 1024 * 1024)
    download_url: str = Field(
        pattern=(
            r"^/api/v1/pdf-document-reviews/workflow_[0-9a-f]{32}/annotations/"
            r"docannotation_[0-9a-f]{32}/documents/(?:DOCUMENT|QUESTION|SOLUTION)/download$"
        )
    )


class DocumentReviewAnnotationView(ApiModel):
    annotation_id: str = Field(pattern=r"^docannotation_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    outputs: tuple[DocumentReviewAnnotationOutputView, ...] = Field(
        min_length=1,
        max_length=2,
    )
    created_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exact_outputs(self) -> DocumentReviewAnnotationView:
        roles = tuple(value.document_role for value in self.outputs)
        if roles not in {("DOCUMENT",), ("QUESTION", "SOLUTION")}:
            raise ValueError("document review annotation output roles are invalid")
        for output in self.outputs:
            expected = (
                f"/api/v1/pdf-document-reviews/{self.workflow_id}/annotations/"
                f"{self.annotation_id}/documents/{output.document_role}/download"
            )
            if output.download_url != expected:
                raise ValueError("document review annotation download URL differs")
        return self

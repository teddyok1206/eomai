"""Public API DTOs for immutable PDF document-review uploads."""

from __future__ import annotations

from typing import Literal

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

"""Immutable BFF contracts paired with JSON Schema 2020-12 documents."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from eom_web_gui.draft_integrity import (
    REQUEST_DRAFT_EDITABLE_FIELDS,
    authoring_guidance_sha256,
    draft_spec_sha256,
    normalize_authoring_guidance,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
AnalysisRangeId = Annotated[str, Field(pattern=r"^analysisrange_[0-9a-f]{32}$")]
CurriculumUnitKey = Annotated[
    str,
    Field(
        pattern=(
            r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|"
            r"5-\([1-7]\)|6-\([1-4]\))$"
        )
    ),
]


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StudioProblem(WebModel):
    error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    message: str = Field(min_length=1, max_length=160)
    request_id: str = Field(pattern=r"^webreq_[0-9a-f]{24}$")


class CustomerSupportSubmission(WebModel):
    category: Literal["HOW_TO", "TECHNICAL_ERROR", "CONTENT_QUALITY", "FEATURE_REQUEST"]
    subject: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    question: str = Field(
        min_length=10,
        max_length=4000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    browser_route: str | None = Field(
        default=None,
        max_length=512,
        pattern=r"^/[^\x00-\x1f?#]*$",
    )
    stable_error_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{2,63}$",
    )
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class CustomerSupportAction(WebModel):
    title: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[^\x00-\x1f]+$",
    )
    instruction: str = Field(
        min_length=1,
        max_length=1000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )


class CustomerSupportCaseView(WebModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    category: Literal["HOW_TO", "TECHNICAL_ERROR", "CONTENT_QUALITY", "FEATURE_REQUEST"]
    subject: str = Field(min_length=3, max_length=120)
    question: str = Field(min_length=10, max_length=4000)
    state: Literal["SUBMITTED", "DIAGNOSING", "ANSWERED", "FAILED"]
    classification: (
        Literal[
            "USAGE_GUIDANCE",
            "TRANSIENT_RUNTIME",
            "VALIDATION_ERROR",
            "PERMISSION_OR_SESSION",
            "CONTENT_QUALITY",
            "FEATURE_REQUEST",
            "UNKNOWN",
        ]
        | None
    ) = None
    answer_text: str | None = Field(default=None, min_length=1, max_length=6000)
    recommended_actions: tuple[CustomerSupportAction, ...] = Field(default=(), max_length=5)
    needs_operator: bool = False
    failure_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{2,63}$",
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def answer_matches_state(self) -> CustomerSupportCaseView:
        if self.state == "ANSWERED":
            if self.classification is None or self.answer_text is None:
                raise ValueError("answered customer-support case requires a classified answer")
        elif (
            self.classification is not None
            or self.answer_text is not None
            or self.recommended_actions
            or self.needs_operator
        ):
            raise ValueError("non-answered customer-support case cannot expose answer output")
        return self


PdfReviewPresetKey = Literal["PROBLEM_SET", "WEEKLY_WORKBOOK", "MOCK_EXAM"]


class PdfDocumentReviewSubmission(WebModel):
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
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class PdfDocumentReviewUploadIntentView(WebModel):
    upload_intent_id: str = Field(pattern=r"^pdfreviewintent_[0-9a-f]{32}$")
    state: Literal["AWAITING_UPLOAD", "PROCESSING", "STARTED", "FAILED_RETRYABLE", "FAILED_FINAL"]
    original_filename: str = Field(min_length=5, max_length=240)
    content_length: int = Field(ge=8, le=256 * 1024 * 1024)
    preset_key: PdfReviewPresetKey
    additional_guidance_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    upload_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[0-9a-f]{32}$")
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    upload_url: str = Field(pattern=r"^/api/v1/pdf-document-reviews/upload-intents/.+/content$")
    review_url: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    expires_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_upload_intent(self) -> PdfDocumentReviewUploadIntentView:
        expected_upload_url = (
            f"/api/v1/pdf-document-reviews/upload-intents/{self.upload_intent_id}/content"
        )
        if self.upload_url != expected_upload_url:
            raise ValueError("PDF review upload URL differs from its intent")
        started = self.state == "STARTED"
        failed = self.state in {"FAILED_RETRYABLE", "FAILED_FINAL"}
        if started:
            if (
                self.upload_sha256 is None
                or self.workflow_id is None
                or self.failure_code is not None
                or self.review_url != f"/api/v1/pdf-document-reviews/{self.workflow_id}"
            ):
                raise ValueError("started PDF review upload is inconsistent")
        elif failed:
            if (
                self.upload_sha256 is None
                or self.workflow_id is not None
                or self.failure_code is None
            ):
                raise ValueError("failed PDF review upload is inconsistent")
        elif self.state == "PROCESSING":
            if self.upload_sha256 is None or any(
                value is not None
                for value in (self.workflow_id, self.failure_code, self.review_url)
            ):
                raise ValueError("processing PDF review upload is inconsistent")
        elif any(
            value is not None
            for value in (self.upload_sha256, self.workflow_id, self.failure_code, self.review_url)
        ):
            raise ValueError("awaiting PDF review upload exposes completed state")
        return self


class PdfReviewRegion(WebModel):
    x_ppm: int = Field(ge=0, le=999999)
    y_ppm: int = Field(ge=0, le=999999)
    width_ppm: int = Field(ge=1, le=1000000)
    height_ppm: int = Field(ge=1, le=1000000)

    @model_validator(mode="after")
    def bounded_region(self) -> PdfReviewRegion:
        if self.x_ppm + self.width_ppm > 1_000_000 or self.y_ppm + self.height_ppm > 1_000_000:
            raise ValueError("PDF review region exceeds its page")
        return self


class PdfReviewAnchor(WebModel):
    anchor_id: str = Field(pattern=r"^reviewanchor_[0-9a-f]{32}$")
    page_number: int = Field(ge=1, le=32)
    page_image_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    region: PdfReviewRegion
    quote: str | None = Field(default=None, min_length=1, max_length=1000)
    quote_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def quote_hash_matches_quote(self) -> PdfReviewAnchor:
        if (self.quote is None) != (self.quote_sha256 is None):
            raise ValueError("PDF review quote and hash must be present together")
        return self


class PdfReviewVerificationTarget(WebModel):
    target_id: str = Field(pattern=r"^reviewtarget_[0-9a-f]{32}$")
    axis: str = Field(min_length=1, max_length=64)
    page_numbers: tuple[int, ...] = Field(min_length=1, max_length=32)
    anchors: tuple[PdfReviewAnchor, ...] = Field(max_length=16)
    status: Literal["VERIFIED", "FAILED", "INSUFFICIENT"]
    conclusion: str = Field(min_length=1, max_length=4000)


class PdfReviewCandidate(WebModel):
    candidate_id: str = Field(pattern=r"^reviewcandidate_[0-9a-f]{32}$")
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    category: str = Field(min_length=1, max_length=64)
    severity: Literal["BLOCKER", "HIGH", "MEDIUM", "LOW", "NOTE"]
    title: str = Field(min_length=1, max_length=160)
    anchors: tuple[PdfReviewAnchor, ...] = Field(min_length=1, max_length=8)
    disposition: Literal["CONFIRMED", "DEMOTED", "UNCERTAIN"]
    rationale: str = Field(min_length=1, max_length=4000)


class PdfReviewRecommendation(WebModel):
    operation: Literal["REPLACE", "INSERT", "DELETE", "MOVE", "REDRAW", "VERIFY", "NONE"]
    instruction: str = Field(min_length=1, max_length=4000)
    before_text: str | None = Field(default=None, max_length=2000)
    after_text: str | None = Field(default=None, max_length=2000)


class PdfReviewFinding(WebModel):
    finding_id: str = Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")
    candidate_id: str = Field(pattern=r"^reviewcandidate_[0-9a-f]{32}$")
    ordinal: int = Field(ge=1, le=512)
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    category: str = Field(min_length=1, max_length=64)
    severity: Literal["BLOCKER", "HIGH", "MEDIUM", "LOW", "NOTE"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    anchors: tuple[PdfReviewAnchor, ...] = Field(min_length=1, max_length=8)
    recommendation: PdfReviewRecommendation


class PdfDocumentReviewOutputView(WebModel):
    review_request_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    source_pdf_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    preset_key: PdfReviewPresetKey
    preset_revision_id: str = Field(pattern=r"^reviewpresetrev_[0-9a-f]{32}$")
    preset_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    additional_guidance_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    review_status: Literal["COMPLETE", "NEEDS_HUMAN_DECISION"]
    summary: str = Field(min_length=1, max_length=4000)
    verification_targets: tuple[PdfReviewVerificationTarget, ...] = Field(
        min_length=1, max_length=256
    )
    candidate_findings: tuple[PdfReviewCandidate, ...] = Field(max_length=512)
    findings: tuple[PdfReviewFinding, ...] = Field(max_length=512)
    mutation_performed: Literal[False] = False


class PdfDocumentReviewPageView(WebModel):
    page_number: int = Field(ge=1, le=32)
    width_px: int = Field(ge=64, le=16384)
    height_px: int = Field(ge=64, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270]
    image_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_content_length: int = Field(ge=1, le=16 * 1024 * 1024)
    image_url: str = Field(pattern=r"^/api/v1/pdf-document-reviews/.+/pages/[0-9]+/image$")


class PdfDocumentReviewArtifactView(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PdfDocumentReviewView(WebModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    state: Literal["SUBMITTED", "REVIEWING", "COMPLETED", "FAILED"]
    document_id: str = Field(pattern=r"^document_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^documentrev_[0-9a-f]{32}$")
    original_filename: str = Field(min_length=5, max_length=240)
    source_pdf_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    page_count: int = Field(ge=1, le=32)
    pages: tuple[PdfDocumentReviewPageView, ...] = Field(min_length=1, max_length=32)
    preset_key: PdfReviewPresetKey
    preset_display_name: Literal["N제", "주간지", "모의고사"]
    additional_guidance_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    result_artifact: PdfDocumentReviewArtifactView | None = None
    result: PdfDocumentReviewOutputView | None = None
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_review(self) -> PdfDocumentReviewView:
        if len(self.pages) != self.page_count:
            raise ValueError("PDF review page count differs from its page projection")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF review pages must be complete and ordered")
        for page in self.pages:
            if page.image_url != (
                f"/api/v1/pdf-document-reviews/{self.workflow_id}/pages/{page.page_number}/image"
            ):
                raise ValueError("PDF review page URL differs from its Workflow")
        expected_display = {
            "PROBLEM_SET": "N제",
            "WEEKLY_WORKBOOK": "주간지",
            "MOCK_EXAM": "모의고사",
        }[self.preset_key]
        if self.preset_display_name != expected_display:
            raise ValueError("PDF review preset display differs from its key")
        if self.state == "COMPLETED":
            if self.result is None or self.result_artifact is None or self.failure_code is not None:
                raise ValueError("completed PDF review requires its immutable result")
            if (
                self.result.document_id != self.document_id
                or self.result.document_revision_id != self.document_revision_id
                or self.result.source_pdf_sha256 != self.source_pdf_sha256
                or self.result.preset_key != self.preset_key
                or self.result.additional_guidance_sha256 != self.additional_guidance_sha256
            ):
                raise ValueError("PDF review result differs from its immutable request")
        elif self.result is not None or self.result_artifact is not None:
            raise ValueError("non-completed PDF review cannot expose result bytes")
        if (self.state == "FAILED") != (self.failure_code is not None):
            raise ValueError("PDF review failure state is inconsistent")
        return self


class QualityProfile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class ContentTeamMaterialRequirement(WebModel):
    """Presentation DTO mirroring the canonical reviewed material requirement."""

    schema_version: Literal["content-team-material-requirement/1.0"] = (
        "content-team-material-requirement/1.0"
    )
    form: Literal["AUTO", "TEXT", "DATA", "TABLE", "IMAGE", "MIXED", "INQUIRY"]
    panel_count: int | None

    @model_validator(mode="after")
    def coherent_panel_count(self) -> ContentTeamMaterialRequirement:
        if self.form in {"AUTO", "TEXT", "DATA", "INQUIRY"}:
            if self.panel_count is not None:
                raise ValueError(f"{self.form} material cannot declare a panel count")
        elif self.form in {"TABLE", "IMAGE"}:
            if self.panel_count not in {1, 2}:
                raise ValueError(f"{self.form} material requires one or two panels")
        elif self.panel_count != 2:
            raise ValueError("MIXED material requires exactly two panels")
        return self


class ContentIntakeOption(WebModel):
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    batch_name: str = Field(min_length=1, max_length=256)
    state: Literal["ACCEPTED"] = "ACCEPTED"
    purpose: str = Field(max_length=2000)
    updated_at: UtcDatetime


class ContentIntakeSourcePointer(WebModel):
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    filename: str = Field(min_length=1, max_length=255)
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_member: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: Literal["image/png", "image/jpeg"]


class KnowledgeAnalysisBatchStatus(WebModel):
    """Bounded read-only projection for the long-running analysis lane."""

    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    state: Literal["QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "CANCELLED"]
    total_range_count: int = Field(ge=1, le=1000)
    accepted_range_count: int = Field(ge=0, le=1000)
    failed_range_count: int = Field(ge=0, le=1000)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_progress(self) -> KnowledgeAnalysisBatchStatus:
        if self.accepted_range_count + self.failed_range_count > self.total_range_count:
            raise ValueError("analysis batch terminal counts exceed total ranges")
        if self.state == "SUCCEEDED" and (
            self.accepted_range_count != self.total_range_count or self.failed_range_count != 0
        ):
            raise ValueError("succeeded analysis batch must accept every range")
        return self


class AssessmentLearningWorkUnitCounts(WebModel):
    pending: int = Field(ge=0, le=10_000)
    claimed: int = Field(ge=0, le=10_000)
    submitted: int = Field(ge=0, le=10_000)
    awaiting_review: int = Field(ge=0, le=10_000)
    accepted: int = Field(ge=0, le=10_000)
    failed: int = Field(ge=0, le=10_000)
    cancelled: int = Field(ge=0, le=10_000)

    @property
    def total(self) -> int:
        return sum(
            (
                self.pending,
                self.claimed,
                self.submitted,
                self.awaiting_review,
                self.accepted,
                self.failed,
                self.cancelled,
            )
        )


class AssessmentLearningItemCounts(WebModel):
    expected: int = Field(ge=0, le=100_000)
    accepted: int = Field(ge=0, le=100_000)
    promoted: int = Field(ge=0, le=100_000)
    analysis_active: int = Field(ge=0, le=100_000)
    analysis_accepted: int = Field(ge=0, le=100_000)
    analysis_failed: int = Field(ge=0, le=100_000)
    graph_published: int = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def coherent_pipeline(self) -> AssessmentLearningItemCounts:
        if not (
            self.graph_published
            <= self.analysis_accepted
            <= self.promoted
            <= self.accepted
            <= self.expected
        ):
            raise ValueError("assessment learning item counts are not monotonic")
        if self.analysis_active + self.analysis_accepted + self.analysis_failed > self.promoted:
            raise ValueError("assessment learning analysis counts exceed promoted Items")
        return self


class AssessmentLearningBatchStatus(WebModel):
    schema_version: Literal["assessment-learning-batch-view/1.0"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state: Literal[
        "QUEUED",
        "RUNNING",
        "AWAITING_REVIEW",
        "SUCCEEDED",
        "COMPLETED_WITH_GAPS",
        "CANCELLED",
    ]
    exam_count: int = Field(ge=1, le=10_000)
    total_work_unit_count: int = Field(ge=1, le=10_000)
    image_required_work_unit_count: int = Field(ge=1, le=10_000)
    image_observation_mode: Literal["REQUIRED"]
    text_evidence_mode: Literal["AUXILIARY_WHEN_AVAILABLE"]
    work_units: AssessmentLearningWorkUnitCounts
    items: AssessmentLearningItemCounts
    current_graph_snapshot_revision_id: str | None = Field(
        default=None, pattern=r"^graphrev_[0-9a-f]{32}$"
    )
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_batch(self) -> AssessmentLearningBatchStatus:
        if (
            self.work_units.total != self.total_work_unit_count
            or self.image_required_work_unit_count != self.total_work_unit_count
        ):
            raise ValueError("assessment learning work-unit totals differ")
        return self


class AssessmentLearningCorpusStatus(WebModel):
    schema_version: Literal["assessment-learning-corpus-view/1.0"]
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    corpus_revision_id: str = Field(pattern=r"^corpusrev_[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=128)
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_revision_number: int = Field(ge=1)
    source_pdf_count: int = Field(ge=2, le=20_000)
    exam_count: int = Field(ge=1, le=10_000)
    approved_item_count: int = Field(ge=1, le=100_000)
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_corpus(self) -> AssessmentLearningCorpusStatus:
        if self.source_pdf_count != self.exam_count * 2:
            raise ValueError("assessment learning source PDF count differs from exam corpus")
        if self.approved_item_count < self.exam_count:
            raise ValueError("assessment learning Item count is smaller than exam count")
        return self


class AssessmentLearningCorpusStatusV2(WebModel):
    schema_version: Literal["assessment-learning-corpus-view/2.0"]
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    corpus_revision_id: str = Field(pattern=r"^corpusrev_[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=128)
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_revision_number: int = Field(ge=1)
    source_pdf_count: int = Field(ge=2, le=20_000)
    exam_count: int = Field(ge=1, le=10_000)
    approved_item_count: int = Field(ge=1, le=100_000)
    solution_report_total_count: int = Field(ge=1, le=100_000)
    solution_report_completed_count: int = Field(ge=0, le=100_000)
    solution_report_active_count: int = Field(ge=0, le=100_000)
    solution_report_failed_count: int = Field(ge=0, le=100_000)
    solution_report_pending_count: int = Field(ge=0, le=100_000)
    solution_report_status: Literal["NOT_STARTED", "RUNNING", "COMPLETED", "BLOCKED"]
    solution_report_updated_at: UtcDatetime | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_corpus(self) -> AssessmentLearningCorpusStatusV2:
        if self.source_pdf_count != self.exam_count * 2:
            raise ValueError("assessment learning source PDF count differs from exam corpus")
        if self.approved_item_count < self.exam_count:
            raise ValueError("assessment learning Item count is smaller than exam count")
        return self

    @model_validator(mode="after")
    def coherent_solution_reports(self) -> AssessmentLearningCorpusStatusV2:
        if self.solution_report_total_count != self.approved_item_count:
            raise ValueError("solution report denominator differs from Graph Item count")
        if (
            self.solution_report_completed_count
            + self.solution_report_active_count
            + self.solution_report_failed_count
            + self.solution_report_pending_count
            != self.solution_report_total_count
        ):
            raise ValueError("solution report state counts differ from total")
        expected = (
            "BLOCKED"
            if self.solution_report_failed_count
            else (
                "COMPLETED"
                if self.solution_report_completed_count == self.solution_report_total_count
                else (
                    "NOT_STARTED"
                    if self.solution_report_pending_count == self.solution_report_total_count
                    else "RUNNING"
                )
            )
        )
        if self.solution_report_status != expected:
            raise ValueError("solution report status differs from state counts")
        if (self.solution_report_updated_at is None) != (
            self.solution_report_pending_count == self.solution_report_total_count
        ):
            raise ValueError("solution report update timestamp differs from progress")
        return self


class AssessmentLearningExamStatusV2(WebModel):
    schema_version: Literal["assessment-learning-exam-view/2.0"]
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    source_pdf_count: Literal[2]
    approved_item_count: int = Field(ge=1, le=200)

    @model_validator(mode="after")
    def coherent_exam(self) -> AssessmentLearningExamStatusV2:
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


class AssessmentLearningExamStatus(WebModel):
    schema_version: Literal["assessment-learning-exam-view/1.0"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    total_work_unit_count: int = Field(ge=1, le=10_000)
    image_required_work_unit_count: int = Field(ge=1, le=10_000)
    work_units: AssessmentLearningWorkUnitCounts
    items: AssessmentLearningItemCounts

    @model_validator(mode="after")
    def coherent_exam(self) -> AssessmentLearningExamStatus:
        if (
            self.work_units.total != self.total_work_unit_count
            or self.image_required_work_unit_count != self.total_work_unit_count
        ):
            raise ValueError("assessment learning exam work-unit totals differ")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


class AssessmentLearningPageStatus(WebModel):
    schema_version: Literal["assessment-learning-page-view/1.0"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    source_role: Literal["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"]
    physical_page: int = Field(ge=1, le=100000)
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_member: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: Literal["image/png"]
    content_length: int = Field(ge=1, le=32 * 1024 * 1024)
    width_px: int = Field(ge=1, le=20000)
    height_px: int = Field(ge=1, le=20000)


class AssessmentLearningPageStatusV2(WebModel):
    schema_version: Literal["assessment-learning-page-view/2.0"]
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    source_role: Literal["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"]
    physical_page: int = Field(ge=1, le=100000)
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_member: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: Literal["image/png"]
    content_length: int = Field(ge=1, le=32 * 1024 * 1024)
    width_px: int = Field(ge=1, le=20000)
    height_px: int = Field(ge=1, le=20000)


class AssessmentLearningItemStatus(WebModel):
    """One Graph-published Item placement bound to its immutable parent exam."""

    schema_version: Literal["assessment-item-occurrence-view/2.0"]
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    occurrence_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    item_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    curriculum_unit_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    placement_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent_item(self) -> AssessmentLearningItemStatus:
        if tuple(sorted(set(self.curriculum_unit_ids))) != self.curriculum_unit_ids or any(
            re.fullmatch(r"currunit_[0-9a-f]{32}", value) is None
            for value in self.curriculum_unit_ids
        ):
            raise ValueError("assessment learning curriculum unit IDs are invalid")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


class ItemBankCurriculumUnit(WebModel):
    curriculum_unit_id: str = Field(pattern=r"^currunit_[0-9a-f]{32}$")
    unit_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    unit_code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=200)
    unit_level: Literal["MAJOR", "MIDDLE", "MINOR", "ACHIEVEMENT_STANDARD"]
    parent_unit_id: str | None = Field(default=None, pattern=r"^currunit_[0-9a-f]{32}$")


class ItemBankEntry(WebModel):
    schema_version: Literal["item-bank-entry-view/1.0"]
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_state: Literal["APPROVED", "SUPERSEDED"]
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    curriculum_units: tuple[ItemBankCurriculumUnit, ...] = Field(min_length=1, max_length=8)
    placement_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent_graph_pointer(self) -> ItemBankEntry:
        keys = tuple(unit.unit_key for unit in self.curriculum_units)
        ids = tuple(unit.curriculum_unit_id for unit in self.curriculum_units)
        if keys != tuple(sorted(set(keys))) or len(ids) != len(set(ids)):
            raise ValueError("item-bank curriculum pointers must be sorted and unique")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


class MockExamAssemblyPlacementInput(WebModel):
    position: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    curriculum_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=16)
    points_milli: int = Field(ge=1, le=1_000_000)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = None
    is_inquiry: bool
    material_type: str = Field(min_length=1, max_length=64)


class MockExamAssemblySubmission(WebModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
    deliverable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    title: str = Field(min_length=1, max_length=256)
    edition: str = Field(min_length=1, max_length=64)
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    placements: tuple[MockExamAssemblyPlacementInput, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_unique_placements(self) -> MockExamAssemblySubmission:
        positions = tuple(row.position for row in self.placements)
        if positions != tuple(range(1, len(self.placements) + 1)):
            raise ValueError("mock-exam positions must be contiguous and ordered")
        revision_ids = tuple(row.item_revision_id for row in self.placements)
        if len(revision_ids) != len(set(revision_ids)):
            raise ValueError("mock-exam Item revisions must be unique")
        return self


class PlannedMockExamAssemblySubmission(WebModel):
    """Presentation values plus an opaque server-issued plan token; no authored placements."""

    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
    deliverable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    title: str = Field(min_length=1, max_length=256)
    edition: str = Field(min_length=1, max_length=64)
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_plan_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    planned_at: UtcDatetime


class MockExamHwpxBuildRequest(WebModel):
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")


class MockExamHwpxBuildView(WebModel):
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    item_set_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    renderer: Literal["content-team-exam"]
    renderer_version: Literal["1.0.0", "2.0.0", "3.0.0"]
    state: Literal["REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"]
    validation_state: Literal["PENDING", "PASS", "FAIL"]
    item_count: int = Field(ge=1, le=200)
    section_count: int | None = Field(default=None, ge=0, le=200)
    native_equation_count: int | None = Field(default=None, ge=0, le=25600)
    native_table_count: int | None = Field(default=None, ge=0, le=4000)
    visual_count: int | None = Field(default=None, ge=0, le=400)
    output_artifact_id: str | None = Field(default=None, pattern=r"^artifact_[0-9a-f]{32}$")
    output_artifact_revision_id: str | None = Field(default=None, pattern=r"^rev_[0-9a-f]{32}$")
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    download_available: bool
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    failure_detail_sanitized: str | None = Field(default=None, max_length=500)
    created_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    resource_version: int = Field(ge=1)


class KnowledgeAnalysisBatchRangeStatus(WebModel):
    """Minimum immutable range projection needed by the quality observer."""

    range_id: str = Field(pattern=r"^analysisrange_[0-9a-f]{32}$")
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    ordinal: int = Field(ge=0, le=999)
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    curriculum_unit_keys: tuple[CurriculumUnitKey, ...] = Field(max_length=32)
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    analysis_schema_ref: Literal[
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0",
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0",
    ]
    analysis_run_id: str | None = Field(default=None, pattern=r"^analysisrun_[0-9a-f]{32}$")
    state: Literal["PENDING", "CLAIMED", "SUBMITTED", "ACCEPTED", "FAILED", "CANCELLED"]
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def ordered_page_interval(self) -> KnowledgeAnalysisBatchRangeStatus:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("analysis range page interval is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("analysis range page interval exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("analysis range curriculum unit keys must be sorted and unique")
        return self


class KnowledgeQualityFindingCode(StrEnum):
    ANALYSIS_REVISION_REUSED = "ANALYSIS_REVISION_REUSED"
    ANALYSIS_RUN_REUSED = "ANALYSIS_RUN_REUSED"
    BATCH_RANGE_COUNT_MISMATCH = "BATCH_RANGE_COUNT_MISMATCH"
    PAGE_COVERAGE_GAP = "PAGE_COVERAGE_GAP"
    PAGE_COVERAGE_OVERLAP = "PAGE_COVERAGE_OVERLAP"
    RANGE_BATCH_POINTER_MISMATCH = "RANGE_BATCH_POINTER_MISMATCH"
    RANGE_ORDINAL_SEQUENCE_INVALID = "RANGE_ORDINAL_SEQUENCE_INVALID"
    SOURCE_POINTER_DRIFT = "SOURCE_POINTER_DRIFT"


class KnowledgeQualityFinding(WebModel):
    code: KnowledgeQualityFindingCode
    severity: Literal["WARNING", "ERROR"]
    document_revision_id: str | None = Field(default=None, pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int | None = Field(default=None, ge=1, le=10000)
    last_physical_page: int | None = Field(default=None, ge=1, le=10000)
    range_ids: tuple[AnalysisRangeId, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def coherent_page_interval(self) -> KnowledgeQualityFinding:
        if (self.first_physical_page is None) != (self.last_physical_page is None):
            raise ValueError("quality finding page interval must be complete")
        if (
            self.first_physical_page is not None
            and self.last_physical_page is not None
            and self.last_physical_page < self.first_physical_page
        ):
            raise ValueError("quality finding page interval is reversed")
        if len(self.range_ids) != len(set(self.range_ids)):
            raise ValueError("quality finding range IDs must be unique")
        return self


class KnowledgeDocumentCoverage(WebModel):
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    range_count: int = Field(ge=1, le=1000)
    unique_page_count: int = Field(ge=1, le=32000)
    accepted_page_count: int = Field(ge=0, le=32000)
    cancelled_page_count: int = Field(ge=0, le=32000)
    failed_page_count: int = Field(ge=0, le=32000)
    in_progress_page_count: int = Field(ge=0, le=32000)
    gap_page_count: int = Field(ge=0, le=32000)
    overlap_page_count: int = Field(ge=0, le=32000)
    curriculum_unit_keys: tuple[CurriculumUnitKey, ...] = Field(max_length=32)


class KnowledgeAnalysisQualityReport(WebModel):
    """Derived, non-persisted quality observation over one batch projection."""

    schema_version: Literal["knowledge-analysis-quality-report/1.0"] = (
        "knowledge-analysis-quality-report/1.0"
    )
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    resource_version: int = Field(ge=1)
    quality_state: Literal["PASS", "WARN", "FAIL"]
    total_range_count: int = Field(ge=1, le=1000)
    observed_range_count: int = Field(ge=0, le=1000)
    selected_page_count: int = Field(ge=0, le=32000)
    unique_page_count: int = Field(ge=0, le=32000)
    accepted_page_count: int = Field(ge=0, le=32000)
    cancelled_page_count: int = Field(ge=0, le=32000)
    failed_page_count: int = Field(ge=0, le=32000)
    in_progress_page_count: int = Field(ge=0, le=32000)
    visual_input_range_count: int = Field(ge=0, le=1000)
    visual_input_page_count: int = Field(ge=0, le=32000)
    gap_page_count: int = Field(ge=0, le=32000)
    overlap_page_count: int = Field(ge=0, le=32000)
    duplicate_analysis_revision_count: int = Field(ge=0, le=1000)
    duplicate_analysis_run_count: int = Field(ge=0, le=1000)
    document_count: int = Field(ge=0, le=1000)
    curriculum_unit_count: int = Field(ge=0, le=32000)
    documents: tuple[KnowledgeDocumentCoverage, ...] = Field(max_length=1000)
    findings: tuple[KnowledgeQualityFinding, ...] = Field(max_length=5008)
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def coherent_report(self) -> KnowledgeAnalysisQualityReport:
        if self.document_count != len(self.documents):
            raise ValueError("quality report document count is inconsistent")
        if self.selected_page_count != (
            self.accepted_page_count
            + self.failed_page_count
            + self.cancelled_page_count
            + self.in_progress_page_count
        ):
            raise ValueError("quality report state page counts are inconsistent")
        if self.unique_page_count > self.selected_page_count:
            raise ValueError("quality report unique pages exceed selected pages")
        if self.visual_input_range_count > self.observed_range_count:
            raise ValueError("quality report visual ranges exceed observed ranges")
        if self.visual_input_page_count > self.selected_page_count:
            raise ValueError("quality report visual pages exceed selected pages")
        severities = {finding.severity for finding in self.findings}
        expected = "FAIL" if "ERROR" in severities else "WARN" if severities else "PASS"
        if self.quality_state != expected:
            raise ValueError("quality report state does not match its findings")
        return self


class RequestDraftInput(WebModel):
    original_request_text: str = Field(min_length=10, max_length=2000)

    @field_validator("original_request_text")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("request text must contain at least 10 non-whitespace characters")
        return value


class CurriculumEditorialUnitOption(WebModel):
    key: str = Field(pattern=r"^eom\.is\.(large\.[1-6]|middle\.[1-6]-[1-7])$")
    level: Literal["LARGE", "MIDDLE"]
    code: str = Field(pattern=r"^[1-6](?:-\([1-7]\))?$")
    label: str = Field(min_length=1, max_length=80)
    parent_key: str = Field(pattern=r"^eom\.is\.(volume\.(i|ii)|large\.[1-6])$")
    ordinal: int = Field(ge=1, le=7)


class CurriculumEditorialOutline(WebModel):
    schema_version: Literal["integrated-science-editorial-outline/1.0"]
    outline_key: Literal["eom-integrated-science-editorial-outline"]
    outline_revision: Literal["1.0"]
    subject_key: Literal["integrated-science"]
    subject_label: Literal["통합과학"]
    graph_mapping_status: Literal[
        "RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF",
        "PUBLISHED_CURRICULUM_GRAPH_VERIFIED",
    ]
    graph_grounding_available: bool = False
    supported_product_levels: tuple[Literal["LARGE", "MIDDLE"], Literal["LARGE", "MIDDLE"]]
    unsupported_product_levels: tuple[Literal["SMALL"]]
    units: tuple[CurriculumEditorialUnitOption, ...] = Field(min_length=41, max_length=41)

    @model_validator(mode="after")
    def coherent_hierarchy(self) -> CurriculumEditorialOutline:
        if self.graph_grounding_available != (
            self.graph_mapping_status == "PUBLISHED_CURRICULUM_GRAPH_VERIFIED"
        ):
            raise ValueError("curriculum Graph capability projection is inconsistent")
        if self.supported_product_levels != ("LARGE", "MIDDLE"):
            raise ValueError("curriculum supported product levels must remain ordered")
        by_key = {unit.key: unit for unit in self.units}
        if len(by_key) != len(self.units):
            raise ValueError("curriculum outline unit keys must be unique")
        large = tuple(unit for unit in self.units if unit.level == "LARGE")
        middle = tuple(unit for unit in self.units if unit.level == "MIDDLE")
        if len(large) != 6 or len(middle) != 35:
            raise ValueError("curriculum outline must contain 6 large and 35 middle units")
        if any(unit.parent_key not in by_key for unit in middle):
            raise ValueError("curriculum middle unit parent is missing")
        middle_counts = (4, 6, 7, 7, 7, 4)
        expected_order: list[str] = []
        for large_number, middle_count in enumerate(middle_counts, start=1):
            large_key = f"eom.is.large.{large_number}"
            expected_order.append(large_key)
            large_unit = by_key.get(large_key)
            volume = "i" if large_number <= 3 else "ii"
            expected_ordinal = large_number if large_number <= 3 else large_number - 3
            if (
                large_unit is None
                or large_unit.level != "LARGE"
                or large_unit.code != str(large_number)
                or large_unit.parent_key != f"eom.is.volume.{volume}"
                or large_unit.ordinal != expected_ordinal
            ):
                raise ValueError("curriculum large unit identity contract is invalid")
            for middle_number in range(1, middle_count + 1):
                middle_key = f"eom.is.middle.{large_number}-{middle_number}"
                expected_order.append(middle_key)
                middle_unit = by_key.get(middle_key)
                if (
                    middle_unit is None
                    or middle_unit.level != "MIDDLE"
                    or middle_unit.code != f"{large_number}-({middle_number})"
                    or middle_unit.parent_key != large_key
                    or middle_unit.ordinal != middle_number
                ):
                    raise ValueError("curriculum middle unit identity contract is invalid")
        if tuple(expected_order) != tuple(unit.key for unit in self.units):
            raise ValueError("curriculum outline preorder is invalid")
        return self


class RequestDraftEditable(WebModel):
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    item_format: Literal["multiple_choice"] = "multiple_choice"
    task_type: Literal["calculation", "conceptual", "data_interpretation"]
    difficulty: Literal["easy", "medium", "hard"]
    choice_count: Literal[5] = 5
    equation_required: Literal[True] = True
    material_requirement: ContentTeamMaterialRequirement
    quality_profile: QualityProfile
    source_intake_batch_id: str | None = Field(default=None, pattern=r"^intake_[0-9a-f]{32}$")
    authoring_guidance: str = Field(min_length=10, max_length=2000)
    knowledge_grounding: bool = False
    curriculum_selected_unit_key: str | None = Field(
        default=None,
        pattern=r"^eom\.is\.(large\.[1-6]|middle\.[1-6]-[1-7])$",
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_image_request(cls, value: object) -> object:
        """Keep the former boolean write API while storing only the typed V4 contract."""

        if not isinstance(value, dict) or "material_requirement" in value:
            return value
        if value.get("image_required") is not True:
            return value
        migrated = dict(value)
        migrated.pop("image_required")
        migrated["material_requirement"] = {
            "schema_version": "content-team-material-requirement/1.0",
            "form": "IMAGE",
            "panel_count": 1,
        }
        return migrated

    @field_validator("authoring_guidance")
    @classmethod
    def normalized_authoring_guidance(cls, value: str) -> str:
        normalized = normalize_authoring_guidance(value)
        if normalized != value:
            raise ValueError("authoring guidance must be NFC-normalized compact text")
        return value


class RequestDraftUpdate(RequestDraftEditable):
    @model_validator(mode="after")
    def exact_knowledge_grounding_scope(self) -> RequestDraftUpdate:
        if self.knowledge_grounding and self.curriculum_selected_unit_key is None:
            raise ValueError("knowledge grounding requires a selected curriculum unit")
        return self


class RequestDraft(RequestDraftEditable):
    schema_version: Literal["4.0"] = "4.0"
    request_draft_id: str = Field(pattern=r"^requestdraft_[0-9a-f]{32}$")
    status: Literal["DRAFT"] = "DRAFT"
    language: Literal["ko"] = "ko"
    original_request_text: str = Field(min_length=10, max_length=2000)
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoring_guidance_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    draft_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def exact_knowledge_grounding_scope(self) -> RequestDraft:
        if self.knowledge_grounding and self.curriculum_selected_unit_key is None:
            raise ValueError("knowledge grounding requires a selected curriculum unit")
        actual = authoring_guidance_sha256(self.authoring_guidance)
        if actual != self.authoring_guidance_sha256:
            raise ValueError("authoring guidance SHA-256 does not match normalized text")
        wire = self.model_dump(mode="json")
        editable = {name: wire[name] for name in REQUEST_DRAFT_EDITABLE_FIELDS}
        expected_spec = draft_spec_sha256(
            editable=editable,
            original_request_sha256=self.original_request_sha256,
        )
        if expected_spec != self.draft_spec_sha256:
            raise ValueError("draft spec SHA-256 does not match reviewed request fields")
        return self


class DraftSubmission(WebModel):
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class CodexAccountAdminCommand(WebModel):
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    resource_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def coherent_reason(self) -> CodexAccountAdminCommand:
        requires_reason = self.command_type in {"DRAIN", "DISABLE"}
        if requires_reason != (self.reason_code is not None):
            raise ValueError("drain/disable require a reason and observe/enable forbid one")
        return self


class CodexCapabilityStatusView(WebModel):
    model: str = Field(min_length=1, max_length=128)
    reasoning_effort: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)


class CodexUsageWindowStatusView(WebModel):
    limit_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    limit_name: str | None = Field(default=None, min_length=1, max_length=128)
    window_kind: Literal["PRIMARY", "SECONDARY"]
    used_percent: int = Field(ge=0, le=100)
    window_duration_minutes: int | None = Field(default=None, ge=1, le=525_600)
    resets_at: UtcDatetime | None


class CodexUsageStatusView(WebModel):
    plan_type: str = Field(min_length=1, max_length=64)
    windows: tuple[CodexUsageWindowStatusView, ...] = Field(min_length=1, max_length=32)
    observed_at: UtcDatetime


class CodexAccountStatusView(WebModel):
    """Credential-free account projection accepted from the Application API."""

    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-6]$")
    account_label: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    codex_cli_version: str | None = Field(default=None, min_length=1, max_length=64)
    observed_at: UtcDatetime | None
    valid_until: UtcDatetime | None
    resource_version: int = Field(ge=1)
    capabilities: tuple[CodexCapabilityStatusView, ...] = Field(max_length=128)
    active_lease_count: int = Field(ge=0)
    last_successful_job_id: str | None = Field(default=None, pattern=r"^job_[0-9a-f]{32}$")
    active_auth_enrollment_id: str | None = Field(default=None, pattern=r"^authflow_[0-9a-f]{32}$")
    active_auth_enrollment_state: str | None = Field(default=None, min_length=1, max_length=64)
    usage_observation: CodexUsageStatusView | None = None

    @model_validator(mode="after")
    def coherent_active_enrollment(self) -> CodexAccountStatusView:
        if (self.active_auth_enrollment_id is None) != (self.active_auth_enrollment_state is None):
            raise ValueError("active auth enrollment identity and state must be paired")
        return self


class CodexControlCommandStatusView(WebModel):
    command_id: str = Field(pattern=r"^codexcmd_[0-9a-f]{32}$")
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"]
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    state: str = Field(min_length=1, max_length=64)
    attempts: int = Field(ge=0, le=3)
    result_resource_version: int | None = Field(default=None, ge=1)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    requested_at: UtcDatetime
    processed_at: UtcDatetime | None
    usage_observation: CodexUsageStatusView | None = None


class CodexAuthEnrollmentStart(WebModel):
    requested_account_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    acknowledge_drain: Literal[True]
    resource_version: int = Field(ge=1)
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class CodexAuthChallengeReveal(WebModel):
    confirm: Literal[True]


class CodexAuthEnrollmentStatusView(WebModel):
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-6]$")
    requested_account_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    state: Literal[
        "REQUESTED",
        "DRAINING",
        "READY_FOR_LOGIN",
        "WAITING_FOR_USER",
        "VERIFYING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "EXPIRED",
    ]
    challenge_available: bool
    challenge_revealed_at: UtcDatetime | None
    assignment_revision_id: str | None = Field(
        default=None, pattern=r"^authassignrev_[0-9a-f]{32}$"
    )
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    requested_at: UtcDatetime
    started_at: UtcDatetime | None
    expires_at: UtcDatetime
    completed_at: UtcDatetime | None
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_lifecycle(self) -> CodexAuthEnrollmentStatusView:
        terminal = self.state in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
        failed = self.state in {"FAILED", "CANCELLED", "EXPIRED"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal enrollment state must match completion timestamp")
        if failed != (self.error_code is not None):
            raise ValueError("failed enrollment state must match stable error code")
        if (self.state == "SUCCEEDED") != (self.assignment_revision_id is not None):
            raise ValueError("only successful enrollment may identify an assignment revision")
        if self.challenge_available and (
            self.state != "WAITING_FOR_USER" or self.challenge_revealed_at is not None
        ):
            raise ValueError("challenge availability does not match enrollment state")
        return self


class CodexDeviceChallengeView(WebModel):
    enrollment_id: str = Field(pattern=r"^authflow_[0-9a-f]{32}$")
    slot_key: str = Field(pattern=r"^slot0[1-6]$")
    verification_uri: str = Field(max_length=512)
    user_code: str = Field(pattern=r"^[A-Z0-9]{3,12}(?:-[A-Z0-9]{3,12})?$")
    expires_at: UtcDatetime

    @field_validator("verification_uri")
    @classmethod
    def exact_openai_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "auth.openai.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
        ):
            raise ValueError("device verification URI must use the reviewed OpenAI origin")
        return value


class ControlArtifactPointerDraft(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class BundleRevisionPointerDraft(WebModel):
    bundle_id: str = Field(pattern=r"^(?:instrbundle|refbundle)_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^(?:instrrev|refrev)_[0-9a-f]{32}$")
    manifest_artifact: ControlArtifactPointerDraft
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PresetModelCandidateDraft(WebModel):
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"]


class PresetRolePolicyDraft(WebModel):
    role: Literal["authoring", "image", "review", "item_management", "support"]
    model_candidates: tuple[PresetModelCandidateDraft, ...] = Field(min_length=1, max_length=4)
    instruction_bundle: BundleRevisionPointerDraft
    reference_bundle: BundleRevisionPointerDraft | None
    worker_pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    timeout_seconds: int = Field(ge=30, le=7200)
    sandbox: Literal["read-only"] = "read-only"
    network: Literal["disabled"] = "disabled"


class ExecutionPresetDraftSubmission(WebModel):
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    role_policies: tuple[PresetRolePolicyDraft, ...] = Field(min_length=1, max_length=5)
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    general_knowledge_policy: Literal["DENY", "ALLOW_WITH_PROVENANCE"]
    compatible_workflow_protocols: tuple[str, ...] = Field(min_length=1, max_length=16)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class ExecutionPresetLifecycleCommand(WebModel):
    resource_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class WorkflowApproval(WebModel):
    etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reason: str | None = Field(default=None, max_length=2000)


class TimelineEvent(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=128)
    timestamp: UtcDatetime
    label: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=40)
    step: str | None = None
    worker_slot: str | None = None
    job_id: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    artifact_id: str | None = None
    validation_result: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")


class PreviewChoice(WebModel):
    choice_id: str = Field(pattern=r"^choice_[a-z0-9][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=20_000)


class PreviewParagraphBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["paragraph"] = "paragraph"
    purpose: Literal["stem", "prompt", "context"]
    text: str = Field(min_length=1, max_length=20_000)


class PreviewEquationBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["equation"] = "equation"
    purpose: Literal["stimulus", "stem"]
    notation: Literal["latex", "hancom-equation-script"]
    source: str = Field(min_length=1, max_length=4000)


class PreviewTableBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["table"] = "table"
    purpose: Literal["stimulus", "data", "reference"]
    caption: str | None = Field(default=None, max_length=500)
    headers: tuple[str, ...] = Field(min_length=1, max_length=20)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def rectangular(self) -> PreviewTableBlock:
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("preview table rows must match header width")
        return self


class PreviewImageBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["image"] = "image"
    purpose: Literal["stimulus", "reference"]
    media_url: str = Field(
        pattern=(
            r"^/studio/api/v1/items/item_[a-z0-9]{8,55}/revisions/"
            r"itemrev_[a-z0-9]{8,55}/media/block_[a-z][a-z0-9_]{0,63}$"
        )
    )
    media_type: Literal["image/png", "image/jpeg"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    alt_text: str = Field(min_length=1, max_length=1000)
    width_px: int = Field(ge=1, le=10_000)
    height_px: int = Field(ge=1, le=10_000)


class PreviewStatement(WebModel):
    statement_id: str = Field(pattern=r"^statement_[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=20_000)


class PreviewStatementSetBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["statement_set"] = "statement_set"
    purpose: Literal["claims"] = "claims"
    statements: tuple[PreviewStatement, ...] = Field(min_length=2, max_length=10)


PreviewBlock = Annotated[
    PreviewParagraphBlock
    | PreviewEquationBlock
    | PreviewTableBlock
    | PreviewImageBlock
    | PreviewStatementSetBlock,
    Field(discriminator="type"),
]


class PreviewStatementExplanation(WebModel):
    statement_id: str = Field(pattern=r"^statement_[a-z][a-z0-9_]{0,31}$")
    text: str = Field(min_length=1, max_length=20_000)


class ItemPreviewV2(WebModel):
    """Historical block-oriented preview contract retained for byte-stable validation."""

    schema_version: Literal["2.0"] = "2.0"
    preview_state: Literal["AVAILABLE", "METADATA_ONLY"]
    workflow_id: str
    item_id: str
    item_revision_id: str
    revision_etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    revision_state: str
    content_pack_release_id: str
    template_delivery_available: bool = False
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}$")
    title: str | None = Field(default=None, min_length=1, max_length=20_000)
    score_points: int | None = Field(default=None, ge=0, le=100)
    blocks: tuple[PreviewBlock, ...] = Field(default=(), max_length=100)
    choices: tuple[PreviewChoice, ...] = Field(default=(), max_length=10)
    answer: str | None = Field(default=None, min_length=1, max_length=4000)
    explanation: str | None = Field(default=None, min_length=1, max_length=20000)
    authoring_intent: str | None = Field(default=None, min_length=1, max_length=20_000)
    statement_explanations: tuple[PreviewStatementExplanation, ...] = Field(
        default=(), max_length=10
    )

    @model_validator(mode="after")
    def available_preview_is_complete(self) -> ItemPreviewV2:
        if self.preview_state == "AVAILABLE" and (
            self.locale is None
            or self.title is None
            or self.score_points is None
            or not self.blocks
            or not self.choices
            or self.answer is None
            or self.explanation is None
        ):
            raise ValueError("available Item Preview is incomplete")
        if self.preview_state == "METADATA_ONLY" and any(
            (
                self.locale is not None,
                self.title is not None,
                self.score_points is not None,
                bool(self.blocks),
                bool(self.choices),
                self.answer is not None,
                self.explanation is not None,
                self.authoring_intent is not None,
                bool(self.statement_explanations),
            )
        ):
            raise ValueError("metadata-only Item Preview cannot contain rendered content")
        block_ids = tuple(block.block_id for block in self.blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Item Preview block identifiers must be unique")
        choice_ids = tuple(choice.choice_id for choice in self.choices)
        choice_labels = tuple(choice.label for choice in self.choices)
        if len(choice_ids) != len(set(choice_ids)) or len(choice_labels) != len(set(choice_labels)):
            raise ValueError("Item Preview choice identifiers and labels must be unique")
        if self.preview_state == "AVAILABLE" and self.answer not in set(choice_labels):
            raise ValueError("Item Preview answer must resolve to one choice label")
        statement_ids = tuple(
            statement.statement_id
            for block in self.blocks
            if isinstance(block, PreviewStatementSetBlock)
            for statement in block.statements
        )
        explanation_ids = tuple(value.statement_id for value in self.statement_explanations)
        if len(statement_ids) != len(set(statement_ids)) or len(explanation_ids) != len(
            set(explanation_ids)
        ):
            raise ValueError("Item Preview statement identifiers must be unique")
        if set(statement_ids) != set(explanation_ids):
            raise ValueError("Item Preview statement explanations must cover the statement set")
        return self


class PreviewParagraphBlockV3(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["paragraph"] = "paragraph"
    purpose: Literal["stem", "prompt", "context"]
    text: str = Field(min_length=1, max_length=24_000)


class PreviewLabeledTextBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["labeled_text"] = "labeled_text"
    kind: Literal["DATA", "CONDITION"]
    label: Literal["<자료>", "<조건>"]
    text: str = Field(min_length=1, max_length=12_000)

    @model_validator(mode="after")
    def label_matches_kind(self) -> PreviewLabeledTextBlock:
        if self.label != {"DATA": "<자료>", "CONDITION": "<조건>"}[self.kind]:
            raise ValueError("preview labeled-text kind and label differ")
        return self


class PreviewInquiryBlock(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["inquiry"] = "inquiry"
    kind: Literal["탐구", "실험"]
    goal: str | None = Field(default=None, min_length=1, max_length=4000)
    procedure: str = Field(min_length=1, max_length=12_000)
    result: str = Field(min_length=1, max_length=12_000)


class PreviewTableBlockV3(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["table"] = "table"
    purpose: Literal["stimulus", "data", "reference"]
    caption: str | None = Field(default=None, max_length=500)
    headers: tuple[str, ...] = Field(min_length=1, max_length=20)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def rectangular(self) -> PreviewTableBlockV3:
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("preview table rows must match header width")
        if any(len(value) > 2000 for value in self.headers):
            raise ValueError("preview table header is invalid")
        if any(len(value) > 2000 for value in (cell for row in self.rows for cell in row)):
            raise ValueError("preview table cell is invalid")
        return self


class PreviewImageBlockV3(WebModel):
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["image"] = "image"
    purpose: Literal["stimulus", "reference"]
    label: Literal["", "(가)", "(나)"] = ""
    media_url: str = Field(
        pattern=(
            r"^/studio/api/v1/items/item_[a-z0-9]{8,55}/revisions/"
            r"itemrev_[a-z0-9]{8,55}/(?:media/block_[a-z][a-z0-9_]{0,63}|visuals/[01])$"
        )
    )
    media_type: Literal["image/png", "image/jpeg"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    alt_text: str = Field(min_length=1, max_length=1000)
    width_px: int = Field(ge=1, le=10_000)
    height_px: int = Field(ge=1, le=10_000)


PreviewBlockV3 = Annotated[
    PreviewParagraphBlockV3
    | PreviewLabeledTextBlock
    | PreviewInquiryBlock
    | PreviewEquationBlock
    | PreviewTableBlockV3
    | PreviewImageBlockV3
    | PreviewStatementSetBlock,
    Field(discriminator="type"),
]


class ItemPreview(WebModel):
    """Current presentation contract for every supported immutable Item content revision."""

    schema_version: Literal["3.0"] = "3.0"
    preview_state: Literal["AVAILABLE", "UNSUPPORTED"]
    unavailable_reason: Literal["UNSUPPORTED_CONTENT_SCHEMA"] | None = None
    workflow_id: str = Field(pattern=r"^workflow_[a-z0-9]{8,55}$")
    item_id: str = Field(pattern=r"^item_[a-z0-9]{8,55}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    revision_etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    revision_state: Literal["APPROVED"]
    content_pack_release_id: str = Field(pattern=r"^packrel_[a-z0-9]{8,55}$")
    content_schema_ref: str = Field(min_length=1, max_length=256)
    content_profile: Literal["BLOCKS_V1", "CONTENT_TEAM_V2", "CONTENT_TEAM_V3"] | None = None
    template_delivery_available: bool = False
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}$")
    title: str | None = Field(default=None, min_length=1, max_length=20_000)
    item_number: int | None = Field(default=None, ge=1, le=999)
    score_display: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]?|100|[1-9][0-9]?\.5)$",
    )
    blocks: tuple[PreviewBlockV3, ...] = Field(default=(), max_length=100)
    choices: tuple[PreviewChoice, ...] = Field(default=(), max_length=10)
    answer: str | None = Field(default=None, min_length=1, max_length=4000)
    explanation: str | None = Field(default=None, min_length=1, max_length=48_000)
    concept_source: str | None = Field(default=None, min_length=1, max_length=12_000)
    authoring_intent: str | None = Field(default=None, min_length=1, max_length=20_000)
    statement_explanations: tuple[PreviewStatementExplanation, ...] = Field(
        default=(), max_length=10
    )

    @model_validator(mode="after")
    def exact_preview_variant(self) -> ItemPreview:
        content_values = (
            self.locale,
            self.title,
            self.item_number,
            self.score_display,
            self.blocks,
            self.choices,
            self.answer,
            self.explanation,
            self.concept_source,
            self.authoring_intent,
            self.statement_explanations,
        )
        if self.preview_state == "UNSUPPORTED":
            if self.unavailable_reason != "UNSUPPORTED_CONTENT_SCHEMA":
                raise ValueError("unsupported Item Preview requires an exact reason")
            if self.content_profile is not None or any(bool(value) for value in content_values):
                raise ValueError("unsupported Item Preview cannot contain rendered content")
            return self
        if self.unavailable_reason is not None or self.content_profile is None:
            raise ValueError("available Item Preview has invalid capability metadata")
        if (
            self.locale is None
            or self.score_display is None
            or not self.blocks
            or not self.choices
            or self.answer is None
            or self.explanation is None
        ):
            raise ValueError("available Item Preview is incomplete")
        if self.content_profile == "BLOCKS_V1":
            if (
                self.title is None
                or self.item_number is not None
                or self.concept_source is not None
            ):
                raise ValueError("V1 Item Preview has invalid profile fields")
        elif self.item_number is None or self.concept_source is None or self.title is not None:
            raise ValueError("content-team Item Preview has invalid profile fields")
        block_ids = tuple(block.block_id for block in self.blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Item Preview block identifiers must be unique")
        choice_ids = tuple(choice.choice_id for choice in self.choices)
        choice_labels = tuple(choice.label for choice in self.choices)
        if len(choice_ids) != len(set(choice_ids)) or len(choice_labels) != len(set(choice_labels)):
            raise ValueError("Item Preview choice identifiers and labels must be unique")
        if self.answer not in set(choice_labels):
            raise ValueError("Item Preview answer must resolve to one choice label")
        statement_ids = tuple(
            statement.statement_id
            for block in self.blocks
            if isinstance(block, PreviewStatementSetBlock)
            for statement in block.statements
        )
        explanation_ids = tuple(value.statement_id for value in self.statement_explanations)
        if len(statement_ids) != len(set(statement_ids)) or len(explanation_ids) != len(
            set(explanation_ids)
        ):
            raise ValueError("Item Preview statement identifiers must be unique")
        if set(statement_ids) != set(explanation_ids):
            raise ValueError("Item Preview statement explanations must cover the statement set")
        return self


class RecentItemOption(WebModel):
    """Bounded pointer projection for selecting a current immutable Item Revision."""

    item_id: str = Field(pattern=r"^item_[a-z0-9]{8,55}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    lifecycle_state: Literal["ACTIVE"] = "ACTIVE"
    human_reference_code: str | None = Field(default=None, max_length=128)
    created_at: UtcDatetime


class StructuredItemImportRequest(WebModel):
    base_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    revision_etag: str = Field(pattern=r'^"v[1-9][0-9]*"$')
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    reviewed: Literal[True]
    review_reason: str = Field(min_length=10, max_length=2000)
    content: dict[str, Any]

    @model_validator(mode="after")
    def canonical_api_contract(self) -> StructuredItemImportRequest:
        required = {"schema_version", "locale", "title", "body", "interaction", "solution", "score"}
        if self.content.get("schema_version") != "1.0" or not required.issubset(self.content):
            raise ValueError("structured content envelope is incomplete")
        return self


class ExplorerEntity(StrEnum):
    WORKFLOWS = "workflows"
    WORKFLOW_COMMANDS = "workflow_commands"
    WORKFLOW_EVENTS = "workflow_events"
    STEP_RUNS = "step_runs"
    JOBS = "jobs"
    ARTIFACTS = "artifacts"
    ARTIFACT_REVISIONS = "artifact_revisions"
    ITEMS = "items"
    ITEM_REVISIONS = "item_revisions"
    CONTENT_PACK_RELEASES = "content_pack_releases"
    USAGE_PLANS = "usage_plans"
    USAGE_RECORDS = "usage_records"
    HWPX_BUILDS = "hwpx_builds"


class ExplorerQuery(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    entity: ExplorerEntity
    exact_id: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    date_from: UtcDatetime | None = None
    date_to: UtcDatetime | None = None
    sort: Literal["created_desc", "created_asc", "updated_desc", "updated_asc"] = "created_desc"
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_range(self) -> ExplorerQuery:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be later than date_to")
        return self


class ExplorerResult(WebModel):
    entity: ExplorerEntity
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    next_cursor: str | None = None
    has_more: bool = False
    capability: Literal["READY", "EXACT_ID_REQUIRED", "PREPARED_NOT_DEPLOYED"] = "READY"


class HwpxCapability(WebModel):
    state: Literal["READY", "PREPARED_NOT_DEPLOYED", "UNAVAILABLE", "DEGRADED"]
    renderer_key: str
    renderer_version: str
    document_profile: Literal[
        "item-revision-auto",
        "eom-question-template-v1",
        "content-team-hwp-question-editor-v1",
        "content-team-hwp-question-editor-v2",
    ]
    boundary: Literal["APPLICATION_API_ONLY"] = "APPLICATION_API_ONLY"
    build_available: bool
    native_equations: bool
    native_tables: bool
    detail_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    message: str


class HwpxBuildRequest(WebModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    require_native_equations: bool = False
    require_native_tables: bool = False
    item_number: int = Field(default=1, ge=1, le=999)


class HwpxBuildView(WebModel):
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    item_id: str
    item_revision_id: str
    source_artifact_revision_id: str = Field(pattern=r"^rev_[a-f0-9]{32}$")
    source_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    renderer: Literal["kordoc", "eom-template", "content-team"]
    renderer_version: Literal["4.9.0", "1.0.0", "2.0.0", "3.0.0"]
    state: Literal["REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"]
    validation_state: Literal["PENDING", "PASS", "FAIL"]
    native_equation_count: int | None = Field(default=None, ge=0, le=128)
    native_table_count: int | None = Field(default=None, ge=0, le=20)
    output_artifact_id: str | None = None
    output_artifact_revision_id: str | None = None
    output_sha256: str | None = None
    download_available: bool
    failure_code: str | None = None
    failure_detail_sanitized: str | None = None
    created_by_operator_id: str = Field(pattern=r"^operator_[a-f0-9]{32}$")
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    resource_version: int = Field(ge=1)

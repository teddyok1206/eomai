"""Read-only assessment archive learning progress projections."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime


class AssessmentLearningWorkUnitCounts(ApiModel):
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


class AssessmentLearningItemCounts(ApiModel):
    expected: int = Field(ge=0, le=100_000)
    accepted: int = Field(ge=0, le=100_000)
    promoted: int = Field(ge=0, le=100_000)
    analysis_active: int = Field(ge=0, le=100_000)
    analysis_accepted: int = Field(ge=0, le=100_000)
    analysis_failed: int = Field(ge=0, le=100_000)
    graph_published: int = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def coherent_pipeline(self) -> Self:
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


class AssessmentLearningBatchView(ApiModel):
    schema_version: Literal["assessment-learning-batch-view/1.0"] = (
        "assessment-learning-batch-view/1.0"
    )
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
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
    image_observation_mode: Literal["REQUIRED"] = "REQUIRED"
    text_evidence_mode: Literal["AUXILIARY_WHEN_AVAILABLE"] = "AUXILIARY_WHEN_AVAILABLE"
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
    def coherent_batch(self) -> Self:
        if (
            self.work_units.total != self.total_work_unit_count
            or self.image_required_work_unit_count != self.total_work_unit_count
        ):
            raise ValueError("assessment learning work-unit totals differ")
        return self


class AssessmentLearningExamView(ApiModel):
    schema_version: Literal["assessment-learning-exam-view/1.0"] = (
        "assessment-learning-exam-view/1.0"
    )
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: Sha256
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
    def coherent_exam(self) -> Self:
        if (
            self.work_units.total != self.total_work_unit_count
            or self.image_required_work_unit_count != self.total_work_unit_count
        ):
            raise ValueError("assessment exam work-unit totals differ")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self

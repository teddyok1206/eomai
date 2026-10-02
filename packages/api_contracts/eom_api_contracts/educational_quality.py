"""Human educational-quality review contracts for immutable assessment Assemblies."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime

QualityReviewerRole = Literal["PRIMARY", "SECONDARY"]
QualitySessionState = Literal["DRAFT", "FINALIZED"]
QualityUniqueAnswer = Literal["PASS", "FAIL", "AMBIGUOUS"]
QualityDisposition = Literal["NO_EDIT", "MINOR_EDIT", "MAJOR_EDIT", "DISCARD"]


class EducationalQualityObservationInput(ApiModel):
    position: int = Field(ge=1, le=200)
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    preview_checked: bool
    hwpx_checked: bool
    evidence_checked: bool
    science_score: int = Field(ge=1, le=5)
    critical_error: bool
    unique_answer: QualityUniqueAnswer
    evidence_score: int = Field(ge=1, le=5)
    authoring_value_score: int = Field(ge=1, le=5)
    visual_score: int | None = Field(default=None, ge=1, le=5)
    visual_not_applicable_reason: str | None = Field(default=None, min_length=1, max_length=240)
    explanation_quality_score: int = Field(ge=1, le=5)
    disposition: QualityDisposition
    edit_minutes: int = Field(ge=0, le=1440)
    short_reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def visual_score_matches_reason(self) -> Self:
        if (self.visual_score is None) != (self.visual_not_applicable_reason is not None):
            raise ValueError(
                "visual_not_applicable_reason is required exactly when visual_score is null"
            )
        return self


class CreateEducationalQualityPlanCommand(ApiModel):
    operation: Literal["CREATE_PLAN"]
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    secondary_positions: tuple[int, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_unique_positions(self) -> Self:
        if self.secondary_positions != tuple(sorted(set(self.secondary_positions))):
            raise ValueError("secondary_positions must be sorted and unique")
        if any(value < 1 or value > 200 for value in self.secondary_positions):
            raise ValueError("secondary_positions must be between 1 and 200")
        return self


class StartEducationalQualitySessionCommand(ApiModel):
    operation: Literal["START_SESSION"]
    plan_id: str = Field(pattern=r"^qualityplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    reviewer_role: QualityReviewerRole


class UpsertEducationalQualityObservationCommand(ApiModel):
    operation: Literal["UPSERT_OBSERVATION"]
    session_id: str = Field(pattern=r"^qualitysession_[0-9a-f]{32}$")
    expected_lock_version: int = Field(ge=1)
    observation: EducationalQualityObservationInput


class FinalizeEducationalQualitySessionCommand(ApiModel):
    operation: Literal["FINALIZE_SESSION"]
    session_id: str = Field(pattern=r"^qualitysession_[0-9a-f]{32}$")
    expected_lock_version: int = Field(ge=1)


class ResolveEducationalQualityDisagreementCommand(ApiModel):
    operation: Literal["RESOLVE_DISAGREEMENT"]
    plan_id: str = Field(pattern=r"^qualityplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    position: int = Field(ge=1, le=200)
    chosen_session_id: str = Field(pattern=r"^qualitysession_[0-9a-f]{32}$")
    notes: str = Field(min_length=1, max_length=1000)


EducationalQualityReviewCommand = Annotated[
    CreateEducationalQualityPlanCommand
    | StartEducationalQualitySessionCommand
    | UpsertEducationalQualityObservationCommand
    | FinalizeEducationalQualitySessionCommand
    | ResolveEducationalQualityDisagreementCommand,
    Field(discriminator="operation"),
]


class EducationalQualityAssemblyCandidateView(ApiModel):
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    revision_state: Literal["RELEASED", "SUPERSEDED", "WITHDRAWN"]
    item_count: int = Field(ge=1, le=200)
    created_at: UtcDatetime
    existing_plan_id: str | None = Field(default=None, pattern=r"^qualityplan_[0-9a-f]{32}$")


class EducationalQualityPlanSummaryView(ApiModel):
    plan_id: str = Field(pattern=r"^qualityplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    item_count: int = Field(ge=1, le=200)
    primary_finalized: bool
    secondary_finalized: bool
    resolved_count: int = Field(ge=0, le=200)
    created_at: UtcDatetime


class EducationalQualityPlanItemView(ApiModel):
    position: int = Field(ge=1, le=200)
    display_number: str = Field(min_length=1, max_length=32)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    material_type: str = Field(min_length=1, max_length=64)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)


class EducationalQualityObservationView(EducationalQualityObservationInput):
    updated_at: UtcDatetime


class EducationalQualitySessionView(ApiModel):
    session_id: str = Field(pattern=r"^qualitysession_[0-9a-f]{32}$")
    reviewer_id: str = Field(min_length=1, max_length=128)
    reviewer_role: QualityReviewerRole
    state: QualitySessionState
    lock_version: int = Field(ge=1)
    required_positions: tuple[int, ...] = Field(min_length=1, max_length=200)
    observations: tuple[EducationalQualityObservationView, ...] = Field(max_length=200)
    created_at: UtcDatetime
    finalized_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def lifecycle_and_coverage_are_coherent(self) -> Self:
        required = self.required_positions
        observed = tuple(value.position for value in self.observations)
        if required != tuple(sorted(set(required))):
            raise ValueError("required_positions must be sorted and unique")
        if observed != tuple(sorted(set(observed))) or not set(observed).issubset(required):
            raise ValueError("session observations must be sorted, unique, and assigned")
        if (self.state == "FINALIZED") != (self.finalized_at is not None):
            raise ValueError("session lifecycle timestamp does not match state")
        if self.state == "FINALIZED" and (
            observed != required
            or any(
                not value.preview_checked or not value.hwpx_checked or not value.evidence_checked
                for value in self.observations
            )
        ):
            raise ValueError("finalized session must cover every assigned quality check")
        return self


class EducationalQualityResolutionView(ApiModel):
    position: int = Field(ge=1, le=200)
    chosen_session_id: str = Field(pattern=r"^qualitysession_[0-9a-f]{32}$")
    resolved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=1000)
    resolved_at: UtcDatetime


class EducationalQualityScoreMetricsView(ApiModel):
    item_count: int = Field(ge=1, le=200)
    no_edit_count: int = Field(ge=0, le=200)
    minor_edit_count: int = Field(ge=0, le=200)
    major_edit_count: int = Field(ge=0, le=200)
    discard_count: int = Field(ge=0, le=200)
    adoptable_count: int = Field(ge=0, le=200)
    critical_error_count: int = Field(ge=0, le=200)
    unique_answer_pass_count: int = Field(ge=0, le=200)
    unique_answer_ambiguous_count: int = Field(ge=0, le=200)
    unique_answer_fail_count: int = Field(ge=0, le=200)
    total_edit_minutes: int = Field(ge=0, le=288_000)
    mean_edit_minutes_milli: int = Field(ge=0, le=1_440_000)
    science_score_milli: int = Field(ge=1000, le=5000)
    evidence_score_milli: int = Field(ge=1000, le=5000)
    authoring_value_score_milli: int = Field(ge=1000, le=5000)
    explanation_quality_score_milli: int = Field(ge=1000, le=5000)
    visual_scored_item_count: int = Field(ge=0, le=200)
    visual_score_milli: int | None = Field(default=None, ge=1000, le=5000)

    @model_validator(mode="after")
    def counts_are_coherent(self) -> Self:
        if (
            self.no_edit_count + self.minor_edit_count + self.major_edit_count + self.discard_count
            != self.item_count
            or self.adoptable_count != self.no_edit_count + self.minor_edit_count
            or self.unique_answer_pass_count
            + self.unique_answer_ambiguous_count
            + self.unique_answer_fail_count
            != self.item_count
            or self.critical_error_count > self.item_count
            or self.visual_scored_item_count > self.item_count
            or (self.visual_scored_item_count == 0) != (self.visual_score_milli is None)
            or self.mean_edit_minutes_milli
            != (self.total_edit_minutes * 1000 + self.item_count // 2) // self.item_count
        ):
            raise ValueError("educational quality score metrics are incoherent")
        return self


class EducationalQualityScorecardView(ApiModel):
    state: Literal["IN_PROGRESS", "READY"]
    primary_observation_count: int = Field(ge=0, le=200)
    secondary_observation_count: int = Field(ge=0, le=200)
    unresolved_disagreement_count: int = Field(ge=0, le=200)
    metrics: EducationalQualityScoreMetricsView | None = None

    @model_validator(mode="after")
    def ready_state_matches_metrics(self) -> Self:
        if (self.state == "READY") != (self.metrics is not None):
            raise ValueError("ready scorecard state requires exact canonical metrics")
        if self.state == "READY" and (
            self.unresolved_disagreement_count != 0
            or self.metrics is None
            or self.primary_observation_count != self.metrics.item_count
        ):
            raise ValueError("ready scorecard counts do not match canonical metrics")
        return self


class EducationalQualityPlanDetailView(ApiModel):
    summary: EducationalQualityPlanSummaryView
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    secondary_positions: tuple[int, ...] = Field(min_length=1, max_length=200)
    items: tuple[EducationalQualityPlanItemView, ...] = Field(min_length=1, max_length=200)
    sessions: tuple[EducationalQualitySessionView, ...] = Field(max_length=32)
    resolutions: tuple[EducationalQualityResolutionView, ...] = Field(max_length=200)
    scorecard: EducationalQualityScorecardView

    @model_validator(mode="after")
    def pinned_plan_shape_is_coherent(self) -> Self:
        positions = tuple(value.position for value in self.items)
        expected = tuple(range(1, self.summary.item_count + 1))
        secondary = self.secondary_positions
        resolution_positions = tuple(value.position for value in self.resolutions)
        if positions != expected:
            raise ValueError("plan Items must be the exact contiguous pinned sequence")
        if len({value.item_revision_id for value in self.items}) != len(self.items):
            raise ValueError("plan Item revisions must be unique")
        if secondary != tuple(sorted(set(secondary))) or not set(secondary).issubset(expected):
            raise ValueError("secondary_positions must be sorted, unique, and assigned")
        if resolution_positions != tuple(sorted(set(resolution_positions))) or not set(
            resolution_positions
        ).issubset(secondary):
            raise ValueError("resolutions must be sorted, unique, and secondary-assigned")
        if self.summary.resolved_count != len(self.resolutions):
            raise ValueError("summary resolved_count does not match immutable resolutions")
        session_roles = tuple(value.reviewer_role for value in self.sessions)
        if len(set(session_roles)) != len(session_roles):
            raise ValueError("plan can contain at most one session per reviewer role")
        item_by_position = {value.position: value for value in self.items}
        for session in self.sessions:
            required = expected if session.reviewer_role == "PRIMARY" else secondary
            if session.required_positions != required:
                raise ValueError("session assignment does not match the pinned plan")
            if any(
                observation.item_revision_id
                != item_by_position[observation.position].item_revision_id
                for observation in session.observations
            ):
                raise ValueError("session observation points to a different Item revision")
        return self


class EducationalQualityReviewWorkbenchView(ApiModel):
    schema_version: Literal["educational-quality-review-workbench/1.0"]
    candidate_assemblies: tuple[EducationalQualityAssemblyCandidateView, ...] = Field(max_length=50)
    plans: tuple[EducationalQualityPlanSummaryView, ...] = Field(max_length=100)
    selected_plan: EducationalQualityPlanDetailView | None = None

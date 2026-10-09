"""Bounded, self-hashed corrections of reviewer-authored routing metadata only."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_workflow.models import (
    ArtifactPointer,
    FrozenModel,
    ReviewEscalationReason,
    Sha256,
    WorkflowId,
)
from eom_workflow.schemas import load_review_correction_directive_schema, validate_schema_message

ReviewCorrectionCode = Literal[
    "REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH",
    "REVIEW_ESCALATION_REASONS_MISMATCH",
    "REVIEW_ESCALATION_DECISION_MISMATCH",
]
ReviewPass = Literal["PRIMARY", "ESCALATED"]
MAX_REVIEW_CORRECTION_PASSES = 3


class ReviewRoutingPolicyValues(FrozenModel):
    """Small routing values; never an Artifact identity or arbitrary worker payload."""

    structural_complexity_score: int = Field(ge=0, le=10)
    reason_codes: tuple[ReviewEscalationReason, ...] = Field(max_length=5)
    decision: Literal["REQUIRED", "NOT_REQUIRED", "COMPLETED"]

    @model_validator(mode="after")
    def ordered_unique_reasons(self) -> ReviewRoutingPolicyValues:
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("review correction reasons must be sorted and unique")
        return self


class ReviewPolicyCorrection(FrozenModel):
    """One enumerated correction with complete expected and observed routing values."""

    code: ReviewCorrectionCode
    expected: ReviewRoutingPolicyValues
    observed: ReviewRoutingPolicyValues

    @model_validator(mode="after")
    def named_value_differs(self) -> ReviewPolicyCorrection:
        fields = {
            "REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH": "structural_complexity_score",
            "REVIEW_ESCALATION_REASONS_MISMATCH": "reason_codes",
            "REVIEW_ESCALATION_DECISION_MISMATCH": "decision",
        }
        field = fields[self.code]
        if getattr(self.expected, field) == getattr(self.observed, field):
            raise ValueError("review correction code does not identify a differing value")
        return self


class ReviewPolicyCorrectionRequired(ValueError):
    """Recoverable domain error; callers route by its typed issue, never its message."""

    def __init__(self, issue: ReviewPolicyCorrection) -> None:
        self.issue = issue
        super().__init__(issue.code)


class WorkflowReviewCorrectionDirective(FrozenModel):
    """Exact submitted review and draft pins for the second or third proof."""

    schema_version: Literal["workflow-review-correction-directive/1.0"] = (
        "workflow-review-correction-directive/1.0"
    )
    workflow_id: WorkflowId
    reviewed_authoring: ArtifactPointer
    source_review: ArtifactPointer
    review_pass: ReviewPass
    pass_number: Literal[2, 3]
    source_attempt: int = Field(ge=1, le=9)
    next_attempt: int = Field(ge=2, le=10)
    issue: ReviewPolicyCorrection
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_sources_pass_and_hash(self) -> WorkflowReviewCorrectionDirective:
        if (
            self.reviewed_authoring.step_key != "authoring"
            or self.reviewed_authoring.result_schema != "authoring-result@12.0"
            or self.source_review.step_key != "review"
            or self.source_review.result_schema != "review-result@12.0"
            or self.source_review.attempt != self.source_attempt
            or self.next_attempt != self.source_attempt + 1
        ):
            raise ValueError("review correction source pointers or attempts differ")
        if (
            self.reviewed_authoring.job_id == self.source_review.job_id
            or self.reviewed_authoring.logical_artifact_id == self.source_review.logical_artifact_id
            or self.reviewed_authoring.revision_id == self.source_review.revision_id
        ):
            raise ValueError("review correction source identities must be distinct")
        expected = self.issue.expected
        if self.review_pass == "PRIMARY":
            if expected.decision != ("REQUIRED" if expected.reason_codes else "NOT_REQUIRED"):
                raise ValueError("primary review correction expected decision differs")
        elif expected.decision != "COMPLETED" or not expected.reason_codes:
            raise ValueError("escalated review correction requires completion and reasons")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
            != self.decision_sha256
        ):
            raise ValueError("review correction directive hash differs")
        return self


def build_review_correction_directive(
    *,
    workflow_id: str,
    reviewed_authoring: ArtifactPointer,
    source_review: ArtifactPointer,
    review_pass: ReviewPass,
    pass_number: Literal[2, 3],
    issue: ReviewPolicyCorrection,
) -> WorkflowReviewCorrectionDirective:
    """Bind one exact correction; caller owns source resolution and the bounded chain."""

    unsigned = {
        "schema_version": "workflow-review-correction-directive/1.0",
        "workflow_id": workflow_id,
        "reviewed_authoring": reviewed_authoring.model_dump(mode="json"),
        "source_review": source_review.model_dump(mode="json"),
        "review_pass": review_pass,
        "pass_number": pass_number,
        "source_attempt": source_review.attempt,
        "next_attempt": source_review.attempt + 1,
        "issue": issue.model_dump(mode="json"),
    }
    document = {**unsigned, "decision_sha256": content_sha256(unsigned)}
    validate_schema_message(
        load_review_correction_directive_schema(),
        document,
        "workflow-review-correction-directive/1.0",
    )
    return WorkflowReviewCorrectionDirective.model_validate(document)

"""Typed contracts for immutable mock-exam Item review publication."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

MOCK_EXAM_ITEM_REVIEW_PUBLICATION_COMMAND_SCHEMA: Final = (
    "mock-exam-item-review-publication-command"
)
MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_SCHEMA: Final = "mock-exam-item-review-publication-result"
MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_V2_SCHEMA: Final = (
    "mock-exam-item-review-publication-result-v2"
)
MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_V3_SCHEMA: Final = (
    "mock-exam-item-review-publication-result-v3"
)
MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA: Final = "mock-exam-review-eligibility-query"
MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA: Final = "mock-exam-review-eligibility-result"
MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V2_SCHEMA: Final = "mock-exam-review-eligibility-result-v2"
MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA: Final = "mock-exam-review-eligibility-result-v3"
MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA: Final = "mock-exam-item-review-decision"
MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA: Final = "mock-exam-item-review-decision-v2"
MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA: Final = "mock-exam-item-review-decision-v3"
MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME: Final = "mock-exam-item-review-decision.json"
MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF: Final = (
    "eom://schemas/assessment-assembly/mock-exam-item-review-decision/1.0"
)
MOCK_EXAM_ITEM_REVIEW_DECISION_V2_SCHEMA_REF: Final = (
    "eom://schemas/assessment-assembly/mock-exam-item-review-decision/2.0"
)
MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA_REF: Final = (
    "eom://schemas/assessment-assembly/mock-exam-item-review-decision/3.0"
)


class PublishMockExamItemReviewCommand(FrozenModel):
    """Publish one human-approved rating for one exact current V2 Item revision."""

    schema_version: Literal["mock-exam-item-review-publication-command/1.0"] = (
        "mock-exam-item-review-publication-command/1.0"
    )
    operation: Literal["PUBLISH_MOCK_EXAM_ITEM_REVIEW"] = "PUBLISH_MOCK_EXAM_ITEM_REVIEW"
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    expected_workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    final_rating: Literal["A", "B", "C"]
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def printable_idempotency_key(cls, value: str) -> str:
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError("idempotency key contains a control character")
        return value


class MockExamReviewFindingCounts(FrozenModel):
    info: int = Field(ge=0, le=20)
    warning: int = Field(ge=0, le=20)
    blocking: Literal[0] = 0


class MockExamReviewFindingCountsV3(MockExamReviewFindingCounts):
    """V3 wire form keeps the zero-blocking field explicit rather than defaulted."""

    blocking: Literal[0]


class MockExamEligibilityFindingCounts(FrozenModel):
    info: int = Field(ge=0, le=20)
    warning: int = Field(ge=0, le=20)
    blocking: int = Field(ge=0, le=20)


class MockExamEligibilityFinding(FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: Literal["info", "warning", "blocking"]
    message: str = Field(min_length=1, max_length=2000)


class MockExamEvidenceUsageResultPointerV1(FrozenModel):
    """Small exact result/receipt pointer; the complete receipt remains canonical upstream."""

    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    attempt: int = Field(ge=1, le=10)
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    receipt_sha256: Sha256


class MockExamAuthoringEvidenceUsageReceiptPointerV1(MockExamEvidenceUsageResultPointerV1):
    step_key: Literal["authoring"]
    result_schema: Literal["authoring-result@10.0"]


class MockExamReviewEvidenceUsageReceiptPointerV1(MockExamEvidenceUsageResultPointerV1):
    step_key: Literal["review"]
    result_schema: Literal["review-result@10.0"]


class MockExamTrustedEvidenceUsageReceiptPairV1(FrozenModel):
    """Resolvable authoring/review receipt identities for one trusted RAG Workflow."""

    schema_version: Literal["mock-exam-trusted-evidence-usage-receipt-pair/1.0"]
    role_protocol_version: Literal["workflow-role/1.20.0"]
    receipt_schema_version: Literal["evidence-usage-validation-receipt/1.0"]
    authoring: MockExamAuthoringEvidenceUsageReceiptPointerV1
    review: MockExamReviewEvidenceUsageReceiptPointerV1

    @model_validator(mode="after")
    def one_exact_workflow_chain(self) -> Self:
        if self.authoring.workflow_id != self.review.workflow_id:
            raise ValueError("trusted evidence receipts must belong to one Workflow")
        authoring_identity = (
            self.authoring.step_run_id,
            self.authoring.job_id,
            self.authoring.artifact_id,
            self.authoring.artifact_revision_id,
            self.authoring.receipt_sha256,
        )
        review_identity = (
            self.review.step_run_id,
            self.review.job_id,
            self.review.artifact_id,
            self.review.artifact_revision_id,
            self.review.receipt_sha256,
        )
        if any(
            left == right for left, right in zip(authoring_identity, review_identity, strict=True)
        ):
            raise ValueError("authoring and review receipt identities must be distinct")
        return self

    def matches_review_result(
        self,
        *,
        step_run_id: str,
        artifact_id: str,
        artifact_revision_id: str,
        sha256: str,
    ) -> bool:
        """Compare one materialized review projection with the pinned receipt in O(1)."""

        return (
            self.review.step_run_id == step_run_id
            and self.review.artifact_id == artifact_id
            and self.review.artifact_revision_id == artifact_revision_id
            and self.review.sha256 == sha256
        )


class InspectMockExamReviewEligibilityQuery(FrozenModel):
    """Resolve the exact pre-approval review evidence for one workflow."""

    schema_version: Literal["mock-exam-review-eligibility-query/1.0"] = (
        "mock-exam-review-eligibility-query/1.0"
    )
    operation: Literal["INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"] = (
        "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"
    )
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")


class MockExamReviewEligibilityResult(FrozenModel):
    """Human-readable, pointer-pinned review snapshot safe to use before approval."""

    schema_version: Literal["mock-exam-review-eligibility-result/1.0"] = (
        "mock-exam-review-eligibility-result/1.0"
    )
    operation: Literal["INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"] = (
        "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"
    )
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_lock_version: int = Field(ge=1)
    approval_state: Literal["PENDING", "APPROVED"]
    approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    approval_lock_version: int = Field(ge=1)
    reviewer_operator_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    approved_at: UtcDatetime | None
    review_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    review_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    review_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    review_sha256: Sha256
    review_result_schema: Literal["review-result@7.0", "review-result@8.0"]
    decision: Literal["ready_for_human"] = "ready_for_human"
    review_summary: str = Field(min_length=1, max_length=4000)
    findings: tuple[MockExamEligibilityFinding, ...] = Field(max_length=20)
    finding_counts: MockExamEligibilityFindingCounts
    eligible: bool
    eligibility_reason: Literal["ELIGIBLE", "REVIEW_BLOCKING_FINDINGS"]

    @model_validator(mode="after")
    def exact_counts_and_reason(self) -> MockExamReviewEligibilityResult:
        has_reviewer = self.reviewer_operator_id is not None
        has_approval_time = self.approved_at is not None
        if has_reviewer != has_approval_time or (self.approval_state == "APPROVED") != has_reviewer:
            raise ValueError(
                "review eligibility approval state, reviewer, and approval time must be atomic"
            )
        counts = {
            "info": sum(row.severity == "info" for row in self.findings),
            "warning": sum(row.severity == "warning" for row in self.findings),
            "blocking": sum(row.severity == "blocking" for row in self.findings),
        }
        if self.finding_counts.model_dump(mode="json") != counts:
            raise ValueError("review eligibility finding counts do not match findings")
        expected_eligible = self.finding_counts.blocking == 0
        expected_reason = "ELIGIBLE" if expected_eligible else "REVIEW_BLOCKING_FINDINGS"
        if self.eligible != expected_eligible or self.eligibility_reason != expected_reason:
            raise ValueError("review eligibility reason differs from blocking findings")
        return self


class MockExamReviewEligibilityResultV2(MockExamReviewEligibilityResult):
    """V2 eligibility projection for the content-team V3/review-result@9 family."""

    schema_version: Literal["mock-exam-review-eligibility-result/2.0"] = (
        "mock-exam-review-eligibility-result/2.0"  # type: ignore[assignment]
    )
    review_result_schema: Literal["review-result@9.0"]  # type: ignore[assignment]


class MockExamReviewEligibilityResultV3(MockExamReviewEligibilityResult):
    """Eligibility projection whose @10 review is backed by trusted RAG receipts."""

    schema_version: Literal["mock-exam-review-eligibility-result/3.0"]  # type: ignore[assignment]
    operation: Literal["INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"]
    review_result_schema: Literal["review-result@10.0"]  # type: ignore[assignment]
    decision: Literal["ready_for_human"]
    trusted_evidence_usage_receipts: MockExamTrustedEvidenceUsageReceiptPairV1

    @model_validator(mode="after")
    def trusted_receipts_bind_review(self) -> Self:
        receipts = self.trusted_evidence_usage_receipts
        if receipts.review.workflow_id != self.workflow_id or not receipts.matches_review_result(
            step_run_id=self.review_step_run_id,
            artifact_id=self.review_artifact_id,
            artifact_revision_id=self.review_artifact_revision_id,
            sha256=self.review_sha256,
        ):
            raise ValueError("trusted evidence receipt pair differs from eligibility review")
        return self


class MockExamSourceReviewPointer(FrozenModel):
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    result_schema: Literal["review-result@7.0", "review-result@8.0"]
    worker_decision: Literal["ready_for_human"] = "ready_for_human"
    finding_counts: MockExamReviewFindingCounts


class MockExamSourceReviewPointerV2(MockExamSourceReviewPointer):
    """V2 source pointer admitting the content-team V3 review result."""

    result_schema: Literal["review-result@9.0"]  # type: ignore[assignment]


class MockExamSourceReviewPointerV3(MockExamSourceReviewPointer):
    """Exact @10 review result plus the trusted authoring/review receipt pair."""

    result_schema: Literal["review-result@10.0"]  # type: ignore[assignment]
    worker_decision: Literal["ready_for_human"]
    finding_counts: MockExamReviewFindingCountsV3
    trusted_evidence_usage_receipts: MockExamTrustedEvidenceUsageReceiptPairV1

    @model_validator(mode="after")
    def trusted_receipts_bind_source_review(self) -> Self:
        if not self.trusted_evidence_usage_receipts.matches_review_result(
            step_run_id=self.step_run_id,
            artifact_id=self.artifact_id,
            artifact_revision_id=self.artifact_revision_id,
            sha256=self.sha256,
        ):
            raise ValueError("trusted evidence receipt pair differs from source review")
        return self


class MockExamHumanApprovalPointer(FrozenModel):
    approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    approved_at: UtcDatetime


class MockExamItemReviewDecisionV1(FrozenModel):
    """Canonical rating decision; its self-hash excludes only ``decision_sha256``."""

    schema_version: Literal["mock-exam-item-review-decision/1.0"] = (
        "mock-exam-item-review-decision/1.0"
    )
    item_review_record_id: str = Field(pattern=r"^itemreview_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    source_review: MockExamSourceReviewPointer
    human_approval: MockExamHumanApprovalPointer
    decision: Literal["APPROVE"] = "APPROVE"
    final_rating: Literal["A", "B", "C"]
    rating_policy_key: Literal["integrated-science-item-rating"] = "integrated-science-item-rating"
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256
    idempotency_key_sha256: Sha256
    decided_at: UtcDatetime
    decision_sha256: Sha256

    @model_validator(mode="after")
    def exact_self_hash_and_approval_time(self) -> MockExamItemReviewDecisionV1:
        if self.decided_at != self.human_approval.approved_at:
            raise ValueError("Item review decision time must be the human approval time")
        if self.decision_sha256 != mock_exam_item_review_decision_sha256(
            self.model_dump(mode="json")
        ):
            raise ValueError("Item review decision self-hash mismatch")
        return self


class MockExamItemReviewDecisionV2(MockExamItemReviewDecisionV1):
    """V2 immutable decision for the content-team V3/review-result@9 family."""

    schema_version: Literal["mock-exam-item-review-decision/2.0"] = (
        "mock-exam-item-review-decision/2.0"  # type: ignore[assignment]
    )
    source_review: MockExamSourceReviewPointerV2


class MockExamItemReviewDecisionV3(MockExamItemReviewDecisionV1):
    """Immutable operator decision closed over the exact trusted RAG evidence chain."""

    schema_version: Literal["mock-exam-item-review-decision/3.0"]  # type: ignore[assignment]
    source_review: MockExamSourceReviewPointerV3
    decision: Literal["APPROVE"]
    rating_policy_key: Literal["integrated-science-item-rating"]

    @model_validator(mode="after")
    def trusted_receipts_bind_workflow(self) -> Self:
        if (
            self.source_review.trusted_evidence_usage_receipts.review.workflow_id
            != self.workflow_id
        ):
            raise ValueError("trusted evidence receipts differ from decision Workflow")
        return self


def mock_exam_item_review_decision_sha256(value: dict[str, Any]) -> str:
    """Hash the canonical decision payload without its self-hash field."""

    unsigned = dict(value)
    unsigned.pop("decision_sha256", None)
    return content_sha256(unsigned)


class MockExamItemReviewPublicationResult(FrozenModel):
    """Stable receipt for an append or an exact idempotent replay."""

    schema_version: Literal["mock-exam-item-review-publication-result/1.0"] = (
        "mock-exam-item-review-publication-result/1.0"
    )
    operation: Literal["PUBLISH_MOCK_EXAM_ITEM_REVIEW"] = "PUBLISH_MOCK_EXAM_ITEM_REVIEW"
    item_review_record_id: str = Field(pattern=r"^itemreview_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    review_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    human_approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    review_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    review_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    review_sha256: Sha256
    decision_sha256: Sha256
    review_result_schema: Literal["review-result@7.0", "review-result@8.0"]
    decision: Literal["APPROVE"] = "APPROVE"
    final_rating: Literal["A", "B", "C"]
    finding_counts: MockExamReviewFindingCounts
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256
    created: bool


class MockExamItemReviewPublicationResultV2(MockExamItemReviewPublicationResult):
    """V2 publication receipt for the content-team V3/review-result@9 family."""

    schema_version: Literal["mock-exam-item-review-publication-result/2.0"] = (
        "mock-exam-item-review-publication-result/2.0"  # type: ignore[assignment]
    )
    review_result_schema: Literal["review-result@9.0"]  # type: ignore[assignment]


class MockExamItemReviewPublicationResultV3(MockExamItemReviewPublicationResult):
    """Publication receipt preserving both decision Artifact and trusted source review."""

    schema_version: Literal[  # type: ignore[assignment]
        "mock-exam-item-review-publication-result/3.0"
    ]
    operation: Literal["PUBLISH_MOCK_EXAM_ITEM_REVIEW"]
    review_result_schema: Literal["review-result@10.0"]  # type: ignore[assignment]
    decision: Literal["APPROVE"]
    finding_counts: MockExamReviewFindingCountsV3
    source_review_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    source_review_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_review_sha256: Sha256
    trusted_evidence_usage_receipts: MockExamTrustedEvidenceUsageReceiptPairV1

    @model_validator(mode="after")
    def trusted_receipts_bind_publication(self) -> Self:
        receipts = self.trusted_evidence_usage_receipts
        if receipts.review.workflow_id != self.workflow_id or not receipts.matches_review_result(
            step_run_id=self.review_step_run_id,
            artifact_id=self.source_review_artifact_id,
            artifact_revision_id=self.source_review_artifact_revision_id,
            sha256=self.source_review_sha256,
        ):
            raise ValueError("trusted evidence receipt pair differs from publication review")
        return self


MockExamReviewEligibilityResultContract = Annotated[
    MockExamReviewEligibilityResult
    | MockExamReviewEligibilityResultV2
    | MockExamReviewEligibilityResultV3,
    Field(discriminator="schema_version"),
]
MockExamItemReviewDecisionContract = Annotated[
    MockExamItemReviewDecisionV1 | MockExamItemReviewDecisionV2 | MockExamItemReviewDecisionV3,
    Field(discriminator="schema_version"),
]
MockExamItemReviewPublicationResultContract = Annotated[
    MockExamItemReviewPublicationResult
    | MockExamItemReviewPublicationResultV2
    | MockExamItemReviewPublicationResultV3,
    Field(discriminator="schema_version"),
]

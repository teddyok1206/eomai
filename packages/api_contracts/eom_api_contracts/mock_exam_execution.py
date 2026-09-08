"""Pointer-only application contracts for one 25-Item mock-exam production run."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime

ProductionExecutionState = Literal[
    "ITEM_PRODUCTION",
    "ANALYSIS",
    "GRAPH_PUBLICATION",
    "RATING",
    "ASSEMBLY",
    "HWPX",
    "COMPLETED",
    "BLOCKED",
]
ProductionItemState = Literal[
    "PLANNED",
    "START_UNCONFIRMED",
    "WORKFLOW_UNCONFIRMED",
    "WORKFLOW_ACTIVE",
    "REVIEW_BLOCKED",
    "APPROVAL_UNCONFIRMED",
    "APPROVAL_SUBMITTED",
    "REGISTERED",
    "ANALYSIS_UNCONFIRMED",
    "ANALYSIS_ACTIVE",
    "ANALYSIS_REVIEW_REQUIRED",
    "ANALYSIS_ACCEPTED",
    "GRAPH_PUBLISHED",
    "RATING_UNCONFIRMED",
    "RATED",
    "FAILED",
]


class MockExamProductionFailureV1(ApiModel):
    """Sanitized failure evidence; it never contains prompts, content, or logs."""

    stage: Literal[
        "PREFLIGHT",
        "WORKFLOW_START",
        "WORKFLOW_EXECUTION",
        "REVIEW_GATE",
        "HUMAN_APPROVAL",
        "REGISTRATION",
        "ANALYSIS",
        "GRAPH_PUBLICATION",
        "RATING",
        "ASSEMBLY_PLAN",
        "ASSEMBLY",
        "HWPX",
    ]
    category: Literal[
        "REQUEST_CONTRACT_FAILED",
        "PIN_RESOLUTION_FAILED",
        "WORKFLOW_EXECUTION_FAILED",
        "QUALITY_GATE_FAILED",
        "HUMAN_REJECTED",
        "REGISTRATION_FAILED",
        "ANALYSIS_FAILED",
        "GRAPH_PUBLICATION_FAILED",
        "RATING_FAILED",
        "ASSEMBLY_FAILED",
        "DELIVERY_FAILED",
        "ARTIFACT_INTEGRITY_FAILED",
        "RUNTIME_NOT_READY",
        "OPERATION_OUTCOME_UNKNOWN",
    ]
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    retryable: bool
    observed_at: UtcDatetime


class MockExamGenerationBlockResolutionV1(ApiModel):
    """Exact runtime resolution of the source-pinned one-Item block."""

    generation_block_key: Literal["content-team-one-item-generation"]
    generation_block_revision: Literal["1.0"]
    generation_block_sha256: Sha256
    workflow_definition_key: Literal["generic-item-development"]
    workflow_definition_version: Literal["1.8.0"]
    workflow_definition_sha256: Sha256
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    content_pack_key: Literal["generated-knowledge-item"]
    content_pack_version: Literal["1.13.0"]
    content_pack_release_sha256: Sha256
    content_pack_source_tree_sha256: Sha256
    execution_preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    execution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    execution_preset_key: Literal["knowledge-grounded-item"]
    execution_preset_sha256: Sha256
    resolved_at: UtcDatetime


class MockExamReviewPointerV1(ApiModel):
    """Exact validated review artifact with a zero-blocking quality gate."""

    approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    approval_resource_version: int = Field(ge=1)
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    result_schema: Literal["review-result@7.0", "review-result@8.0"]
    finding_info_count: int = Field(ge=0, le=20)
    finding_warning_count: int = Field(ge=0, le=20)
    finding_blocking_count: Literal[0] = 0


class MockExamReviewEligibilityObservationV1(ApiModel):
    """Official read-only observation used before issuing human approval."""

    schema_version: Literal["mock-exam-review-eligibility/1.0"]
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_resource_version: int = Field(ge=1)
    approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    approval_resource_version: int = Field(ge=1)
    approval_state: Literal["PENDING", "APPROVED"]
    reviewer_operator_id: str | None = Field(default=None, pattern=r"^operator_[0-9a-f]{32}$")
    approved_at: UtcDatetime | None = None
    eligibility: Literal["ELIGIBLE", "BLOCKED"]
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    result_schema: Literal["review-result@7.0", "review-result@8.0"]
    worker_decision: Literal["ready_for_human"] = "ready_for_human"
    finding_info_count: int = Field(ge=0, le=20)
    finding_warning_count: int = Field(ge=0, le=20)
    finding_blocking_count: int = Field(ge=0, le=20)

    @model_validator(mode="after")
    def eligibility_matches_findings(self) -> Self:
        if (self.eligibility == "ELIGIBLE") != (self.finding_blocking_count == 0):
            raise ValueError("review eligibility must be derived from blocking findings")
        approved = self.approval_state == "APPROVED"
        if approved != (self.reviewer_operator_id is not None and self.approved_at is not None):
            raise ValueError("approval state and human decision evidence must be atomic")
        if not approved and (self.reviewer_operator_id is not None or self.approved_at is not None):
            raise ValueError("pending approval cannot expose human decision evidence")
        return self

    def approved_pointer(self) -> MockExamReviewPointerV1:
        if self.eligibility != "ELIGIBLE" or self.finding_blocking_count != 0:
            raise ValueError("blocked review cannot be used for approval")
        return MockExamReviewPointerV1(
            approval_request_id=self.approval_request_id,
            approval_resource_version=self.approval_resource_version,
            step_run_id=self.step_run_id,
            artifact_id=self.artifact_id,
            artifact_revision_id=self.artifact_revision_id,
            sha256=self.sha256,
            result_schema=self.result_schema,
            finding_info_count=self.finding_info_count,
            finding_warning_count=self.finding_warning_count,
            finding_blocking_count=0,
        )

    def human_approval_pointer(self) -> MockExamHumanApprovalPointerV1:
        if (
            self.approval_state != "APPROVED"
            or self.reviewer_operator_id is None
            or self.approved_at is None
        ):
            raise ValueError("pending approval has no human approval pointer")
        return MockExamHumanApprovalPointerV1(
            approval_request_id=self.approval_request_id,
            reviewer_operator_id=self.reviewer_operator_id,
            approved_at=self.approved_at,
        )


class MockExamItemRegistrationPointerV1(ApiModel):
    """New V2 Item Revision produced by the exact workflow occurrence."""

    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    revision_number: Literal[1]
    manifest_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    manifest_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    manifest_sha256: Sha256


class MockExamHumanApprovalPointerV1(ApiModel):
    approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    approved_at: UtcDatetime


class MockExamAnalysisPointerV1(ApiModel):
    """Current read projection for analysis of one exact generated Item Revision."""

    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    request_sha256: Sha256
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    risk_policy_sha256: Sha256
    state: Literal[
        "REQUESTED",
        "RESOLVED",
        "QUEUED",
        "RUNNING",
        "VALIDATING",
        "NEEDS_REVIEW",
        "ACCEPTED",
        "REJECTED",
        "FAILED",
        "CANCELLED",
    ]
    resource_version: int = Field(ge=1)
    accepted_result_artifact_id: str | None = Field(
        default=None, pattern=r"^artifact_[0-9a-f]{32}$"
    )
    accepted_result_artifact_revision_id: str | None = Field(
        default=None, pattern=r"^rev_[0-9a-f]{32}$"
    )
    accepted_result_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def accepted_pointer_is_atomic(self) -> Self:
        pointers = (
            self.accepted_result_artifact_id,
            self.accepted_result_artifact_revision_id,
            self.accepted_result_sha256,
        )
        if (self.state == "ACCEPTED") != all(value is not None for value in pointers):
            raise ValueError("accepted analysis requires one complete immutable result pointer")
        if self.state != "ACCEPTED" and any(value is not None for value in pointers):
            raise ValueError("non-accepted analysis cannot expose an accepted result pointer")
        return self


class MockExamRatingPointerV1(ApiModel):
    """Published human rating decision used by the assembly planner."""

    item_review_record_id: str = Field(pattern=r"^itemreview_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    human_approval_request_id: str = Field(pattern=r"^approval_[0-9a-f]{32}$")
    decision_sha256: Sha256
    final_rating: Literal["A", "B", "C"]
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256


class MockExamRatingAuthorizationPointerV1(ApiModel):
    """Exact operator rating-set authorization pinned before publication."""

    decision_set_sha256: Sha256
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    authorized_at: UtcDatetime
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256


class MockExamWorkflowKnowledgeProvenancePointerV1(ApiModel):
    """Exact Graph/Evidence pointers accepted by one generated-Item Workflow."""

    schema_version: Literal["workflow-knowledge-provenance/1.0"]
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    corpus_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    query_kind: Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]
    curriculum_root_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    required_item_elements: tuple[
        Literal["paragraph", "table", "image", "equation", "statement_set", "choice"], ...
    ] = Field(min_length=1, max_length=8)
    source_classes: tuple[
        Literal["CURRICULUM", "TEXTBOOK", "APPROVED_ITEM", "PAST_EXAM", "INTERNAL_GUIDE"],
        ...,
    ] = Field(min_length=1, max_length=5)
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    retrieval_request_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    evidence_manifest_sha256: Sha256
    resolved_at: UtcDatetime

    @model_validator(mode="after")
    def filters_are_canonical(self) -> Self:
        for values, label in (
            (self.required_item_elements, "required Item elements"),
            (self.source_classes, "source classes"),
        ):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise ValueError(f"knowledge provenance {label} must be sorted and unique")
        return self


class MockExamProductionItemRunV1(ApiModel):
    """Pointer chain for exactly one production-plan workflow call."""

    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    position: int = Field(ge=1, le=25)
    state: ProductionItemState
    start_command_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_id: str | None = Field(default=None, pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_resource_version: int | None = Field(default=None, ge=1)
    knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV1 | None = None
    review: MockExamReviewPointerV1 | None = None
    approval_command_id: str | None = Field(default=None, min_length=1, max_length=128)
    human_approval: MockExamHumanApprovalPointerV1 | None = None
    registration: MockExamItemRegistrationPointerV1 | None = None
    analysis: MockExamAnalysisPointerV1 | None = None
    graph_publication_id: str | None = Field(default=None, pattern=r"^graphpub_[0-9a-f]{32}$")
    rating: MockExamRatingPointerV1 | None = None
    failure: MockExamProductionFailureV1 | None = None

    @model_validator(mode="after")
    def pointer_chain_is_monotonic(self) -> Self:
        workflow_fields = (
            self.start_command_id,
            self.workflow_id,
            self.workflow_resource_version,
        )
        if self.state in {"PLANNED", "START_UNCONFIRMED"}:
            if any(value is not None for value in workflow_fields):
                raise ValueError("unconfirmed workflow start cannot invent a child pointer")
        elif not all(value is not None for value in workflow_fields):
            raise ValueError("started production call requires the exact Workflow pointer")
        if self.knowledge_provenance is not None and self.workflow_id is None:
            raise ValueError("knowledge provenance requires its Workflow occurrence")
        if self.review is not None and (
            self.workflow_id is None or self.knowledge_provenance is None
        ):
            raise ValueError("review pointer requires its knowledge-backed Workflow occurrence")
        if self.approval_command_id is not None and self.review is None:
            raise ValueError("human approval must bind a zero-blocking review pointer")
        if self.human_approval is not None and (self.review is None or self.workflow_id is None):
            raise ValueError("human approval pointer requires its Workflow review")
        if (
            self.human_approval is not None
            and self.review is not None
            and (self.human_approval.approval_request_id != self.review.approval_request_id)
        ):
            raise ValueError("human approval must close the observed approval request")
        if self.registration is not None and self.human_approval is None:
            raise ValueError("registered Item must follow the same Workflow approval")
        if self.analysis is not None and (
            self.registration is None
            or self.analysis.source_item_revision_id != self.registration.item_revision_id
        ):
            raise ValueError("analysis source must be the generated Item Revision")
        if self.graph_publication_id is not None and (
            self.analysis is None or self.analysis.state != "ACCEPTED"
        ):
            raise ValueError("Graph publication requires an accepted analysis")
        if self.rating is not None and (
            self.graph_publication_id is None
            or self.registration is None
            or self.workflow_id is None
            or self.rating.item_revision_id != self.registration.item_revision_id
            or self.rating.workflow_id != self.workflow_id
            or self.human_approval is None
            or self.rating.human_approval_request_id != self.human_approval.approval_request_id
            or self.rating.reviewer_operator_id != self.human_approval.reviewer_operator_id
        ):
            raise ValueError("rating pointer does not close over the generated Item chain")
        failure_states = {
            "START_UNCONFIRMED",
            "WORKFLOW_UNCONFIRMED",
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "ANALYSIS_UNCONFIRMED",
            "ANALYSIS_REVIEW_REQUIRED",
            "RATING_UNCONFIRMED",
            "FAILED",
        }
        if (self.state in failure_states) != (self.failure is not None):
            raise ValueError("blocked or unknown Item state requires one sanitized failure")
        if self.failure is not None:
            structurally_valid_failure = {
                "START_UNCONFIRMED": self.workflow_id is None,
                "WORKFLOW_UNCONFIRMED": self.workflow_id is not None and self.review is None,
                "REVIEW_BLOCKED": self.workflow_id is not None
                and self.knowledge_provenance is not None
                and self.human_approval is None,
                "APPROVAL_UNCONFIRMED": self.review is not None and self.human_approval is None,
                "ANALYSIS_UNCONFIRMED": self.registration is not None and self.rating is None,
                "ANALYSIS_REVIEW_REQUIRED": self.analysis is not None
                and self.analysis.state == "NEEDS_REVIEW",
                "RATING_UNCONFIRMED": self.graph_publication_id is not None and self.rating is None,
                "FAILED": True,
            }.get(self.state, False)
            if not structurally_valid_failure:
                raise ValueError("Item failure state does not match its preserved pointer chain")
        if self.failure is None:
            expected_state: ProductionItemState
            if self.rating is not None:
                expected_state = "RATED"
            elif self.graph_publication_id is not None:
                expected_state = "GRAPH_PUBLISHED"
            elif self.analysis is not None:
                expected_state = (
                    "ANALYSIS_ACCEPTED" if self.analysis.state == "ACCEPTED" else "ANALYSIS_ACTIVE"
                )
            elif self.registration is not None:
                expected_state = "REGISTERED"
            elif self.human_approval is not None:
                expected_state = "WORKFLOW_ACTIVE"
            elif self.approval_command_id is not None:
                expected_state = "APPROVAL_SUBMITTED"
            elif self.review is not None:
                raise ValueError(
                    "submitted review requires approval evidence or an explicit failure"
                )
            elif self.workflow_id is not None:
                expected_state = "WORKFLOW_ACTIVE"
            else:
                expected_state = "PLANNED"
            if self.state != expected_state:
                raise ValueError("Item state does not match its immutable pointer chain")
        return self


class MockExamGraphPublicationPointerV1(ApiModel):
    batch_number: Literal[1] = 1
    publication_id: str = Field(pattern=r"^graphpub_[0-9a-f]{32}$")
    previous_graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    previous_graph_snapshot_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    analysis_run_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    workflow_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    item_revision_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    authorized_at: UtcDatetime
    outcome: Literal["CREATED", "REPLAYED"]
    result_sha256: Sha256
    published_at: UtcDatetime

    @model_validator(mode="after")
    def batch_is_one_to_one(self) -> Self:
        expected_count = 25
        if (
            len(self.analysis_run_ids) != expected_count
            or len(self.workflow_ids) != expected_count
            or len(self.item_revision_ids) != expected_count
            or len(set(self.analysis_run_ids)) != expected_count
            or len(set(self.workflow_ids)) != expected_count
            or len(set(self.item_revision_ids)) != expected_count
        ):
            raise ValueError("Graph publication must contain exactly 25 aligned pointers")
        for value in self.analysis_run_ids:
            if not _opaque_hex_id(value, "analysisrun_", 32):
                raise ValueError("Graph publication analysis identity is invalid")
        for value in self.item_revision_ids:
            if not _opaque_hex_id(value, "itemrev_", 32):
                raise ValueError("Graph publication Item Revision identity is invalid")
        for value in self.workflow_ids:
            if not _opaque_hex_id(value, "workflow_", 32):
                raise ValueError("Graph publication Workflow identity is invalid")
        if self.authorized_at > self.published_at:
            raise ValueError("Graph publication authorization cannot follow publication")
        return self


class MockExamAssemblyPlanPointerV1(ApiModel):
    plan_sha256: Sha256
    cohort_id: str = Field(pattern=r"^assemblycohort_[0-9a-f]{32}$")
    cohort_sha256: Sha256
    assembly_idempotency_key_sha256: Sha256
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    item_revision_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    planned_at: UtcDatetime

    @model_validator(mode="after")
    def exact_new_item_set(self) -> Self:
        if len(set(self.item_revision_ids)) != 25:
            raise ValueError("assembly plan must contain 25 unique generated Item Revisions")
        return self


class MockExamAssemblyPointerV1(ApiModel):
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    item_set_sha256: Sha256
    item_revision_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    created_at: UtcDatetime

    @model_validator(mode="after")
    def exact_new_item_set(self) -> Self:
        if len(set(self.item_revision_ids)) != 25:
            raise ValueError("assembly must contain 25 unique generated Item Revisions")
        return self


class MockExamHwpxBuildPointerV1(ApiModel):
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    item_set_sha256: Sha256
    item_revision_ids: tuple[str, ...] = Field(min_length=25, max_length=25)
    renderer: Literal["content-team-exam"]
    renderer_version: Literal["1.0.0"]
    state: Literal["REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"]
    validation_state: Literal["PENDING", "PASS", "FAIL"]
    item_count: Literal[25]
    section_count: int | None = Field(default=None, ge=0, le=25)
    output_artifact_id: str | None = Field(default=None, pattern=r"^artifact_[0-9a-f]{32}$")
    output_artifact_revision_id: str | None = Field(default=None, pattern=r"^rev_[0-9a-f]{32}$")
    output_sha256: Sha256 | None = None
    download_available: bool
    resource_version: int = Field(ge=1)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    created_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def terminal_result_is_atomic(self) -> Self:
        if len(set(self.item_revision_ids)) != 25:
            raise ValueError("HWPX build must pin 25 unique ordered Item Revisions")
        output = (
            self.output_artifact_id,
            self.output_artifact_revision_id,
            self.output_sha256,
        )
        succeeded = self.state == "SUCCEEDED"
        if succeeded != all(value is not None for value in output):
            raise ValueError("successful HWPX build requires one complete output pointer")
        if succeeded and (
            self.validation_state != "PASS"
            or self.section_count != self.item_count
            or self.completed_at is None
            or not self.download_available
            or self.failure_code is not None
        ):
            raise ValueError(
                "successful HWPX build must pass 25-section validation and be downloadable"
            )
        if not succeeded and self.download_available:
            raise ValueError("non-successful HWPX build cannot be downloadable")
        if self.state == "FAILED" and self.failure_code is None:
            raise ValueError("failed HWPX build requires a stable failure code")
        return self


class MockExamAnalysisReviewBindingPointerV1(ApiModel):
    """Identity-only binding covered by one explicit operator review-set hash."""

    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    position: int = Field(ge=1, le=25)
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    expected_resource_version: int = Field(ge=1)
    decision: Literal["APPROVE", "REJECT"]


class MockExamAnalysisReviewAuthorizationPointerV1(ApiModel):
    """Write-ahead pointer for an exact self-hashed analysis-review decision set."""

    decision_set_sha256: Sha256
    reviewer_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    authorized_at: UtcDatetime
    bindings: tuple[MockExamAnalysisReviewBindingPointerV1, ...] = Field(
        min_length=1,
        max_length=25,
    )

    @model_validator(mode="after")
    def bindings_are_ordered_and_unique(self) -> Self:
        positions = tuple(row.position for row in self.bindings)
        if positions != tuple(sorted(positions)) or len(positions) != len(set(positions)):
            raise ValueError("analysis-review authorization positions must be ordered and unique")
        if len({row.workflow_call_id for row in self.bindings}) != len(self.bindings) or len(
            {row.analysis_run_id for row in self.bindings}
        ) != len(self.bindings):
            raise ValueError("analysis-review authorization bindings must be unique")
        return self


class MockExamGraphPublicationAuthorizationPointerV1(ApiModel):
    """Write-ahead authorization for one exact atomic Graph publication command."""

    current_graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    current_graph_snapshot_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    authorized_at: UtcDatetime
    supersedes_authorization_sha256: Sha256 | None
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def authorization_is_self_hashed(self) -> Self:
        canonical = self.model_dump(mode="json", exclude={"authorization_sha256"})
        if self.authorization_sha256 != content_sha256(canonical):
            raise ValueError("Graph publication authorization SHA-256 does not match")
        return self


class MockExamProductionExecutionV1(ApiModel):
    """Immutable, resumable checkpoint for the whole sample-exam production chain."""

    schema_version: Literal["mock-exam-production-execution/1.0"]
    execution_id: str = Field(pattern=r"^productionexec_[0-9a-f]{32}$")
    execution_revision_id: str = Field(pattern=r"^productionexecrev_[0-9a-f]{32}$")
    production_request_id: str = Field(pattern=r"^productionreq_[0-9a-f]{32}$")
    production_plan_id: str = Field(pattern=r"^productionplan_[0-9a-f]{32}$")
    production_plan_sha256: Sha256
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    checkpoint_sequence: int = Field(ge=0)
    predecessor_execution_revision_id: str | None = Field(
        default=None, pattern=r"^productionexecrev_[0-9a-f]{32}$"
    )
    predecessor_checkpoint_sha256: Sha256 | None = None
    state: ProductionExecutionState
    generation_block_resolution: MockExamGenerationBlockResolutionV1 | None = None
    analysis_policy: MockExamAnalysisPolicyPointerV1 | None = None
    analysis_general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"] | None = None
    analysis_review_authorizations: tuple[MockExamAnalysisReviewAuthorizationPointerV1, ...] = (
        Field(max_length=25)
    )
    item_runs: tuple[MockExamProductionItemRunV1, ...] = Field(min_length=25, max_length=25)
    graph_publication_authorization: MockExamGraphPublicationAuthorizationPointerV1 | None = None
    graph_publications: tuple[MockExamGraphPublicationPointerV1, ...] = Field(max_length=1)
    rating_authorization: MockExamRatingAuthorizationPointerV1 | None = None
    assembly_intent: MockExamAssemblyIntentV1 | None = None
    assembly_plan: MockExamAssemblyPlanPointerV1 | None = None
    assembly: MockExamAssemblyPointerV1 | None = None
    hwpx_build: MockExamHwpxBuildPointerV1 | None = None
    failure: MockExamProductionFailureV1 | None = None
    created_at: UtcDatetime
    checkpointed_at: UtcDatetime
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def immutable_chain_is_closed(self) -> Self:
        execution_sha256 = content_sha256(
            {
                "production_request_id": self.production_request_id,
                "production_plan_id": self.production_plan_id,
                "production_plan_sha256": self.production_plan_sha256,
            }
        )
        if self.execution_id != ("productionexec_" + execution_sha256.removeprefix("sha256:")[:32]):
            raise ValueError("execution identity does not match its request, plan, and operator")
        positions = tuple(row.position for row in self.item_runs)
        call_ids = tuple(row.workflow_call_id for row in self.item_runs)
        if positions != tuple(range(1, 26)) or len(set(call_ids)) != 25:
            raise ValueError("execution must preserve the ordered 25-call production plan")
        if self.checkpoint_sequence == 0:
            if (
                self.predecessor_execution_revision_id is not None
                or self.predecessor_checkpoint_sha256 is not None
            ):
                raise ValueError("initial checkpoint cannot have a predecessor")
        elif (
            self.predecessor_execution_revision_id is None
            or self.predecessor_checkpoint_sha256 is None
        ):
            raise ValueError("successor checkpoint must pin its predecessor revision and hash")
        _unique_non_null((row.workflow_id for row in self.item_runs), "Workflow")
        _unique_non_null(
            (
                row.registration.item_id if row.registration is not None else None
                for row in self.item_runs
            ),
            "Item",
        )
        _unique_non_null(
            (
                row.registration.item_revision_id if row.registration is not None else None
                for row in self.item_runs
            ),
            "Item Revision",
        )
        _unique_non_null(
            (
                row.analysis.analysis_run_id if row.analysis is not None else None
                for row in self.item_runs
            ),
            "analysis run",
        )
        if any(row.workflow_id is not None for row in self.item_runs) and (
            self.generation_block_resolution is None
        ):
            raise ValueError("started workflows require the pinned generation-block resolution")
        if (self.analysis_policy is None) != (self.analysis_general_knowledge_mode is None):
            raise ValueError("analysis policy and general-knowledge mode must be pinned together")
        if any(row.analysis is not None for row in self.item_runs) and (
            self.analysis_policy is None
        ):
            raise ValueError("analysis pointers require the execution analysis-policy pin")
        if self.analysis_review_authorizations and self.analysis_policy is None:
            raise ValueError("analysis-review authorizations require the execution policy pin")
        if len({row.decision_set_sha256 for row in self.analysis_review_authorizations}) != len(
            self.analysis_review_authorizations
        ):
            raise ValueError("analysis-review authorization hashes must be unique")
        item_by_call = {row.workflow_call_id: row for row in self.item_runs}
        for authorization in self.analysis_review_authorizations:
            if authorization.reviewer_operator_id != self.operator_id:
                raise ValueError("analysis review must be authorized by the execution operator")
            for binding in authorization.bindings:
                item = item_by_call.get(binding.workflow_call_id)
                if (
                    item is None
                    or item.position != binding.position
                    or item.analysis is None
                    or item.analysis.analysis_run_id != binding.analysis_run_id
                    or item.analysis.resource_version < binding.expected_resource_version
                ):
                    raise ValueError("analysis-review authorization differs from its analysis run")
        analysis_policies = {
            (row.analysis.risk_policy_revision_id, row.analysis.risk_policy_sha256)
            for row in self.item_runs
            if row.analysis is not None
        }
        if len(analysis_policies) > 1:
            raise ValueError("one execution cannot mix analysis risk-policy revisions")
        if (
            analysis_policies
            and self.analysis_policy is not None
            and analysis_policies
            != {
                (
                    self.analysis_policy.risk_policy_revision_id,
                    self.analysis_policy.risk_policy_sha256,
                )
            }
        ):
            raise ValueError("analysis pointers differ from the execution policy pin")
        rating_policies = {
            (row.rating.rating_policy_revision_id, row.rating.rating_policy_sha256)
            for row in self.item_runs
            if row.rating is not None
        }
        if len(rating_policies) > 1:
            raise ValueError("one execution cannot mix rating-policy revisions")
        if any(row.rating is not None for row in self.item_runs) and (
            self.rating_authorization is None
        ):
            raise ValueError("published ratings require their explicit authorization pointer")
        if self.rating_authorization is not None:
            if self.rating_authorization.reviewer_operator_id != self.operator_id:
                raise ValueError("rating authorization must come from the execution operator")
            if rating_policies and rating_policies != {
                (
                    self.rating_authorization.rating_policy_revision_id,
                    self.rating_authorization.rating_policy_sha256,
                )
            }:
                raise ValueError("published ratings differ from their authorization policy")
            if all(row.rating is not None for row in self.item_runs):
                rating_set = {
                    "schema_version": "mock-exam-explicit-rating-set/1.0",
                    "execution_id": self.execution_id,
                    "operator_id": self.operator_id,
                    "assignments": [
                        {
                            "workflow_call_id": row.workflow_call_id,
                            "position": row.position,
                            "item_revision_id": row.rating.item_revision_id,
                            "final_rating": row.rating.final_rating,
                        }
                        for row in self.item_runs
                        if row.rating is not None
                    ],
                    "authorized_at": self.rating_authorization.authorized_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
                if content_sha256(rating_set) != self.rating_authorization.decision_set_sha256:
                    raise ValueError("published ratings differ from the authorized decision set")
        if self.graph_publications and self.graph_publication_authorization is None:
            raise ValueError("Graph publication requires its write-ahead authorization")
        if self.graph_publication_authorization is not None and (
            self.graph_publication_authorization.authorized_at
            < max(
                (
                    row.human_approval.approved_at
                    for row in self.item_runs
                    if row.human_approval is not None
                ),
                default=self.created_at,
            )
        ):
            raise ValueError("Graph authorization precedes a generated-Item approval")
        if self.graph_publication_authorization is not None and self.graph_publications:
            graph_authorization = self.graph_publication_authorization
            publication = self.graph_publications[0]
            if (
                publication.previous_graph_snapshot_revision_id
                != graph_authorization.current_graph_snapshot_revision_id
                or publication.previous_graph_snapshot_sha256
                != graph_authorization.current_graph_snapshot_sha256
                or publication.access_policy_revision_id
                != graph_authorization.access_policy_revision_id
                or publication.access_policy_sha256 != graph_authorization.access_policy_sha256
                or publication.authorized_at != graph_authorization.authorized_at
            ):
                raise ValueError("Graph publication differs from its write-ahead authorization")
        self._validate_graph_batches()
        expected_item_revisions = tuple(
            row.registration.item_revision_id
            for row in self.item_runs
            if row.registration is not None
        )
        if self.assembly_plan is not None:
            if self.assembly_intent is None:
                raise ValueError("assembly plan requires its immutable operator intent")
            if self.assembly_plan.item_revision_ids != expected_item_revisions:
                raise ValueError("assembly planner selected an Item outside this production run")
            if len(self.graph_publications) != 1 or (
                self.assembly_plan.graph_snapshot_revision_id
                != self.graph_publications[-1].graph_snapshot_revision_id
                or self.assembly_plan.graph_snapshot_sha256
                != self.graph_publications[-1].graph_snapshot_sha256
            ):
                raise ValueError(
                    "assembly plan does not pin the final generated-Item Graph snapshot"
                )
            cohort_body = {
                "schema_version": "mock-exam-assembly-cohort/1.0",
                "members": [
                    {"position": index, "item_revision_id": item_revision_id}
                    for index, item_revision_id in enumerate(expected_item_revisions, start=1)
                ],
            }
            cohort_sha256 = content_sha256(cohort_body)
            if (
                self.assembly_plan.cohort_sha256 != cohort_sha256
                or self.assembly_plan.cohort_id
                != "assemblycohort_" + cohort_sha256.removeprefix("sha256:")[:32]
            ):
                raise ValueError("assembly plan cohort identity differs from its 25 Items")
            assembly_key = "mockexam:" + content_sha256(
                [
                    self.execution_id,
                    cohort_sha256,
                    self.assembly_plan.plan_sha256,
                    "assembly",
                ]
            ).removeprefix("sha256:")
            if self.assembly_plan.assembly_idempotency_key_sha256 != content_sha256(assembly_key):
                raise ValueError("assembly plan does not pin its exact idempotency identity")
        if self.assembly is not None and (
            self.assembly_plan is None
            or self.assembly.item_revision_ids != self.assembly_plan.item_revision_ids
        ):
            raise ValueError("assembly differs from its exact READY plan")
        if self.hwpx_build is not None:
            if self.assembly is None or self.assembly_plan is None:
                raise ValueError("HWPX build requires the exact Assembly pointers")
            if (
                self.hwpx_build.assessment_assembly_id != self.assembly.assessment_assembly_id
                or self.hwpx_build.assessment_assembly_revision_id
                != self.assembly.assessment_assembly_revision_id
                or self.hwpx_build.assembly_manifest_sha256 != self.assembly.manifest_sha256
                or self.hwpx_build.item_set_sha256 != self.assembly.item_set_sha256
                or self.hwpx_build.policy_revision_id != self.assembly_plan.policy_revision_id
                or self.hwpx_build.policy_sha256 != self.assembly_plan.policy_sha256
                or self.hwpx_build.graph_snapshot_revision_id
                != self.assembly_plan.graph_snapshot_revision_id
                or self.hwpx_build.graph_snapshot_sha256 != self.assembly_plan.graph_snapshot_sha256
                or self.hwpx_build.item_revision_ids != self.assembly.item_revision_ids
                or self.hwpx_build.created_by_operator_id != self.operator_id
            ):
                raise ValueError("HWPX build does not bind the exact Assembly source pointers")
        timestamps = [self.created_at]
        if self.generation_block_resolution is not None:
            timestamps.append(self.generation_block_resolution.resolved_at)
            if self.generation_block_resolution.resolved_at < self.created_at:
                raise ValueError("generation-block resolution precedes execution creation")
        for row in self.item_runs:
            if (
                row.knowledge_provenance is not None
                and row.knowledge_provenance.resolved_at < self.created_at
            ):
                raise ValueError("Workflow knowledge provenance precedes execution creation")
            if row.human_approval is not None and (
                row.human_approval.approved_at < self.created_at
                or (
                    row.knowledge_provenance is not None
                    and row.human_approval.approved_at < row.knowledge_provenance.resolved_at
                )
            ):
                raise ValueError("human approval precedes its Workflow provenance")
            if row.failure is not None:
                if row.failure.observed_at < self.created_at:
                    raise ValueError("Item failure observation precedes execution creation")
                timestamps.append(row.failure.observed_at)
        timestamps.extend(
            row.human_approval.approved_at
            for row in self.item_runs
            if row.human_approval is not None
        )
        timestamps.extend(
            row.knowledge_provenance.resolved_at
            for row in self.item_runs
            if row.knowledge_provenance is not None
        )
        timestamps.extend(row.authorized_at for row in self.analysis_review_authorizations)
        if self.graph_publication_authorization is not None:
            timestamps.append(self.graph_publication_authorization.authorized_at)
        timestamps.extend(row.published_at for row in self.graph_publications)
        timestamps.extend(row.authorized_at for row in self.graph_publications)
        if self.graph_publications:
            graph_times = tuple(row.published_at for row in self.graph_publications)
            if graph_times != tuple(sorted(graph_times)) or any(
                published_at
                < max(
                    (
                        row.human_approval.approved_at
                        for row in self.item_runs
                        if row.human_approval is not None
                    ),
                    default=self.created_at,
                )
                for published_at in graph_times
            ):
                raise ValueError("Graph publication time is not monotonic")
        if self.rating_authorization is not None:
            timestamps.append(self.rating_authorization.authorized_at)
            if self.graph_publications and (
                self.rating_authorization.authorized_at < self.graph_publications[-1].published_at
            ):
                raise ValueError("rating authorization precedes final Graph publication")
        if self.assembly_plan is not None:
            timestamps.append(self.assembly_plan.planned_at)
            if self.rating_authorization is None or (
                self.assembly_plan.planned_at < self.rating_authorization.authorized_at
            ):
                raise ValueError("assembly plan precedes its rating authorization")
        if self.assembly is not None:
            timestamps.append(self.assembly.created_at)
            if self.assembly_plan is None or (
                self.assembly.created_at < self.assembly_plan.planned_at
            ):
                raise ValueError("assembly creation precedes its READY plan")
        if self.hwpx_build is not None:
            timestamps.append(self.hwpx_build.created_at)
            if self.assembly is None or self.hwpx_build.created_at < self.assembly.created_at:
                raise ValueError("HWPX build creation precedes its Assembly Revision")
            if self.hwpx_build.completed_at is not None:
                if self.hwpx_build.completed_at < self.hwpx_build.created_at:
                    raise ValueError("HWPX completion precedes build creation")
                timestamps.append(self.hwpx_build.completed_at)
        if self.failure is not None:
            if self.failure.observed_at < self.created_at:
                raise ValueError("execution failure observation precedes execution creation")
            timestamps.append(self.failure.observed_at)
        if self.checkpointed_at < self.created_at or any(
            value > self.checkpointed_at for value in timestamps
        ):
            raise ValueError("checkpoint timestamp precedes one of its immutable child pointers")
        expected_state = mock_exam_production_state_from_pointers(
            item_runs=self.item_runs,
            graph_publications=self.graph_publications,
            assembly_plan=self.assembly_plan,
            assembly=self.assembly,
            hwpx_build=self.hwpx_build,
            failure=self.failure,
        )
        if self.state != expected_state:
            raise ValueError("execution state does not match its pointer checkpoint")
        identity = self.model_dump(
            mode="json",
            exclude={"execution_revision_id", "checkpoint_sha256"},
        )
        expected_sha256 = content_sha256(identity)
        if self.checkpoint_sha256 != expected_sha256 or self.execution_revision_id != (
            "productionexecrev_" + expected_sha256.removeprefix("sha256:")[:32]
        ):
            raise ValueError("execution checkpoint revision and SHA-256 do not match")
        return self

    def _validate_graph_batches(self) -> None:
        if len({row.publication_id for row in self.graph_publications}) != len(
            self.graph_publications
        ):
            raise ValueError("Graph publication pointers must be unique")
        if tuple(row.batch_number for row in self.graph_publications) != tuple(
            range(1, len(self.graph_publications) + 1)
        ):
            raise ValueError("Graph publication batches must be contiguous and ordered")
        expected_pairs = tuple(
            (
                row.analysis.analysis_run_id,
                row.workflow_id,
                row.registration.item_revision_id,
            )
            for row in self.item_runs
            if row.analysis is not None
            and row.analysis.state == "ACCEPTED"
            and row.registration is not None
        )
        for publication in self.graph_publications:
            expected = expected_pairs
            if publication.analysis_run_ids != tuple(row[0] for row in expected) or (
                publication.workflow_ids != tuple(row[1] for row in expected)
                or publication.item_revision_ids != tuple(row[2] for row in expected)
            ):
                raise ValueError("Graph publication contains an analysis outside this run")
            selected_rows = self.item_runs
            if any(row.graph_publication_id != publication.publication_id for row in selected_rows):
                raise ValueError("Item Graph pointer differs from its atomic publication")


class MockExamExplicitRatingV1(ApiModel):
    """One operator-supplied rating; no model or coordinator may infer it."""

    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    position: int = Field(ge=1, le=25)
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    final_rating: Literal["A", "B", "C"]


class MockExamExplicitAnalysisReviewV1(ApiModel):
    """One operator-supplied analysis decision; never inferred by the coordinator."""

    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    position: int = Field(ge=1, le=25)
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    expected_resource_version: int = Field(ge=1)
    decision: Literal["APPROVE", "REJECT"]
    notes: str = Field(min_length=1, max_length=2000)


class MockExamExplicitAnalysisReviewSetV1(ApiModel):
    schema_version: Literal["mock-exam-explicit-analysis-review-set/1.0"]
    execution_id: str = Field(pattern=r"^productionexec_[0-9a-f]{32}$")
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    assignments: tuple[MockExamExplicitAnalysisReviewV1, ...] = Field(min_length=1, max_length=25)
    authorized_at: UtcDatetime
    decision_set_sha256: Sha256

    @model_validator(mode="after")
    def explicit_unique_set(self) -> Self:
        positions = tuple(row.position for row in self.assignments)
        if positions != tuple(sorted(positions)) or len(positions) != len(set(positions)):
            raise ValueError("analysis reviews must be ordered by unique production position")
        if len({row.workflow_call_id for row in self.assignments}) != len(self.assignments) or len(
            {row.analysis_run_id for row in self.assignments}
        ) != len(self.assignments):
            raise ValueError("analysis reviews must bind unique calls and analysis runs")
        value = self.model_dump(mode="json", exclude={"decision_set_sha256"})
        if self.decision_set_sha256 != content_sha256(value):
            raise ValueError("analysis review-set SHA-256 does not match")
        return self


class MockExamExplicitRatingSetV1(ApiModel):
    schema_version: Literal["mock-exam-explicit-rating-set/1.0"]
    execution_id: str = Field(pattern=r"^productionexec_[0-9a-f]{32}$")
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    assignments: tuple[MockExamExplicitRatingV1, ...] = Field(min_length=25, max_length=25)
    authorized_at: UtcDatetime
    decision_set_sha256: Sha256

    @model_validator(mode="after")
    def explicit_complete_set(self) -> Self:
        if tuple(row.position for row in self.assignments) != tuple(range(1, 26)):
            raise ValueError("explicit ratings must follow all 25 production positions")
        if (
            len({row.workflow_call_id for row in self.assignments}) != 25
            or len({row.item_revision_id for row in self.assignments}) != 25
        ):
            raise ValueError("explicit ratings must bind 25 unique generated Items")
        value = self.model_dump(mode="json", exclude={"decision_set_sha256"})
        if self.decision_set_sha256 != content_sha256(value):
            raise ValueError("explicit rating-set SHA-256 does not match")
        return self


class MockExamAnalysisPolicyPointerV1(ApiModel):
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    risk_policy_sha256: Sha256


class MockExamGraphPublicationInputV1(MockExamGraphPublicationAuthorizationPointerV1):
    """Caller input with the same canonical shape as the persisted authorization pointer."""


class MockExamRatingPolicyPointerV1(ApiModel):
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256


class MockExamAssemblyIntentV1(ApiModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)


def derive_mock_exam_production_state(
    checkpoint: MockExamProductionExecutionV1,
) -> ProductionExecutionState:
    """Derive the aggregate state from immutable child pointers in dependency order."""

    return mock_exam_production_state_from_pointers(
        item_runs=checkpoint.item_runs,
        graph_publications=checkpoint.graph_publications,
        assembly_plan=checkpoint.assembly_plan,
        assembly=checkpoint.assembly,
        hwpx_build=checkpoint.hwpx_build,
        failure=checkpoint.failure,
    )


def mock_exam_production_is_terminal(checkpoint: MockExamProductionExecutionV1) -> bool:
    """Return whether a checkpoint has no supported continuation under its pinned plan."""

    if checkpoint.state == "COMPLETED":
        return True
    if checkpoint.state != "BLOCKED":
        return False
    failures = (
        *((checkpoint.failure,) if checkpoint.failure is not None else ()),
        *(row.failure for row in checkpoint.item_runs if row.failure is not None),
    )
    return any(not failure.retryable for failure in failures)


def mock_exam_production_state_from_pointers(
    *,
    item_runs: tuple[MockExamProductionItemRunV1, ...],
    graph_publications: tuple[MockExamGraphPublicationPointerV1, ...],
    assembly_plan: MockExamAssemblyPlanPointerV1 | None,
    assembly: MockExamAssemblyPointerV1 | None,
    hwpx_build: MockExamHwpxBuildPointerV1 | None,
    failure: MockExamProductionFailureV1 | None,
) -> ProductionExecutionState:
    """Authoritative aggregate state rule shared by validation and the coordinator."""

    if failure is not None or any(row.failure is not None for row in item_runs):
        return "BLOCKED"
    if hwpx_build is not None:
        if hwpx_build.state == "SUCCEEDED" and hwpx_build.validation_state == "PASS":
            return "COMPLETED"
        return "HWPX"
    if assembly is not None or assembly_plan is not None:
        return "HWPX" if assembly is not None else "ASSEMBLY"
    if all(row.rating is not None for row in item_runs):
        return "ASSEMBLY"
    if len(graph_publications) == 1:
        return "RATING"
    if all(row.analysis is not None and row.analysis.state == "ACCEPTED" for row in item_runs):
        return "GRAPH_PUBLICATION"
    if all(row.registration is not None for row in item_runs):
        return "ANALYSIS"
    return "ITEM_PRODUCTION"


def build_mock_exam_explicit_rating_set(
    *,
    execution_id: str,
    operator_id: str,
    assignments: tuple[MockExamExplicitRatingV1, ...],
    authorized_at: datetime,
) -> MockExamExplicitRatingSetV1:
    value = {
        "schema_version": "mock-exam-explicit-rating-set/1.0",
        "execution_id": execution_id,
        "operator_id": operator_id,
        "assignments": [row.model_dump(mode="json") for row in assignments],
        "authorized_at": authorized_at.isoformat().replace("+00:00", "Z"),
    }
    return MockExamExplicitRatingSetV1.model_validate(
        {**value, "decision_set_sha256": content_sha256(value)}
    )


def build_mock_exam_explicit_analysis_review_set(
    *,
    execution_id: str,
    operator_id: str,
    assignments: tuple[MockExamExplicitAnalysisReviewV1, ...],
    authorized_at: datetime,
) -> MockExamExplicitAnalysisReviewSetV1:
    value = {
        "schema_version": "mock-exam-explicit-analysis-review-set/1.0",
        "execution_id": execution_id,
        "operator_id": operator_id,
        "assignments": [row.model_dump(mode="json") for row in assignments],
        "authorized_at": authorized_at.isoformat().replace("+00:00", "Z"),
    }
    return MockExamExplicitAnalysisReviewSetV1.model_validate(
        {**value, "decision_set_sha256": content_sha256(value)}
    )


def _unique_non_null(values: Iterable[str | None], label: str) -> None:
    present = tuple(value for value in values if value is not None)
    if len(present) != len(set(present)):
        raise ValueError(f"execution contains duplicate {label} pointers")


def _opaque_hex_id(value: str, prefix: str, width: int) -> bool:
    suffix = value.removeprefix(prefix)
    return (
        value.startswith(prefix)
        and len(suffix) == width
        and all(character in "0123456789abcdef" for character in suffix)
    )

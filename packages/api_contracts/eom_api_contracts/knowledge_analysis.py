"""Public bounded DTOs for source-grounded knowledge-analysis operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime

CurriculumUnitKeyInput = Annotated[
    str,
    Field(
        pattern=(
            r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|"
            r"5-\([1-7]\)|6-\([1-4]\))$"
        )
    ),
]


class ContentIntakeAnalysisSourceInput(ApiModel):
    source_kind: Literal["CONTENT_INTAKE_FILE"] = "CONTENT_INTAKE_FILE"
    source_class: Literal["CURRICULUM", "TEXTBOOK", "PAST_EXAM", "INTERNAL_GUIDE"]
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")


class ApprovedItemAnalysisSourceInput(ApiModel):
    source_kind: Literal["APPROVED_ITEM_REVISION"] = "APPROVED_ITEM_REVISION"
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")


class EducationalDocumentAnalysisSourceInput(ApiModel):
    source_kind: Literal["DOCUMENT_REVISION"] = "DOCUMENT_REVISION"
    source_class: Literal["TEXTBOOK", "CURRICULUM", "INTERNAL_GUIDE"]
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(ge=1, le=100000)
    last_physical_page: int = Field(ge=1, le=100000)
    curriculum_unit_keys: tuple[CurriculumUnitKeyInput, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def bounded_document_selection(self) -> EducationalDocumentAnalysisSourceInput:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("document analysis page range is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("document analysis page range exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("document curriculum keys must be sorted and unique")
        return self


class KnowledgeAnalysisBatchSourceInput(EducationalDocumentAnalysisSourceInput):
    """A batch range is intentionally restricted to registered textbook revisions."""

    source_class: Literal["TEXTBOOK"] = "TEXTBOOK"
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    curriculum_unit_keys: tuple[CurriculumUnitKeyInput, ...] = Field(max_length=32)


KnowledgeAnalysisSourceInput = Annotated[
    ContentIntakeAnalysisSourceInput
    | ApprovedItemAnalysisSourceInput
    | EducationalDocumentAnalysisSourceInput,
    Field(discriminator="source_kind"),
]


class ExecuteKnowledgeAnalysisBatchRangeInput(ApiModel):
    mode: Literal["EXECUTE"] = "EXECUTE"
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )


class ReuseKnowledgeAnalysisBatchRangeInput(ApiModel):
    mode: Literal["REUSE_ACCEPTED"] = "REUSE_ACCEPTED"
    accepted_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")


KnowledgeAnalysisBatchRangeExecutionInput = Annotated[
    ExecuteKnowledgeAnalysisBatchRangeInput | ReuseKnowledgeAnalysisBatchRangeInput,
    Field(discriminator="mode"),
]


class KnowledgeAnalysisBatchRangeInput(ApiModel):
    ordinal: int = Field(ge=0, le=999)
    source: KnowledgeAnalysisBatchSourceInput
    execution: KnowledgeAnalysisBatchRangeExecutionInput


class CreateKnowledgeAnalysisBatchRequest(ApiModel):
    preset_key: Literal["knowledge-analysis"] = "knowledge-analysis"
    general_knowledge_mode: Literal["AUXILIARY_UNATTRIBUTED"] = "AUXILIARY_UNATTRIBUTED"
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    review_policy: Literal["PREAUTHORIZED_APPROVE_VALIDATED"] = "PREAUTHORIZED_APPROVE_VALIDATED"
    range_failure_policy: Literal["CONTINUE_AND_COLLECT"] = "CONTINUE_AND_COLLECT"
    max_in_flight: Literal[1, 2] = 1
    ranges: tuple[KnowledgeAnalysisBatchRangeInput, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered_nonoverlapping_ranges(self) -> CreateKnowledgeAnalysisBatchRequest:
        if tuple(item.ordinal for item in self.ranges) != tuple(range(len(self.ranges))):
            raise ValueError("batch range ordinals must be contiguous from zero")
        prior_page_by_revision: dict[str, int] = {}
        analysis_run_ids: set[str] = set()
        for item in self.ranges:
            source = item.source
            prior_page = prior_page_by_revision.get(source.document_revision_id)
            if prior_page is not None and source.first_physical_page <= prior_page:
                raise ValueError("batch document page ranges overlap or are unordered")
            prior_page_by_revision[source.document_revision_id] = source.last_physical_page
            pointer = (
                item.execution.predecessor_analysis_run_id
                if isinstance(item.execution, ExecuteKnowledgeAnalysisBatchRangeInput)
                else item.execution.accepted_analysis_run_id
            )
            if pointer is not None:
                if pointer in analysis_run_ids:
                    raise ValueError("batch analysis run pointers must be unique")
                analysis_run_ids.add(pointer)
        return self


class CreateKnowledgeAnalysisRequest(ApiModel):
    source: KnowledgeAnalysisSourceInput
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"] = "DISABLED"
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )


class KnowledgeAnalysisReviewRequest(ApiModel):
    decision: Literal["APPROVE", "REJECT"]
    notes: str = Field(min_length=1, max_length=2000)

    @field_validator("notes")
    @classmethod
    def safe_notes(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("review notes contain a control character")
        return value


class KnowledgeAnalysisCountsView(ApiModel):
    anchors: int | None = Field(default=None, ge=0)
    nodes: int | None = Field(default=None, ge=0)
    edges: int | None = Field(default=None, ge=0)
    claims: int | None = Field(default=None, ge=0)
    component_observations: int | None = Field(default=None, ge=0)
    ambiguities: int | None = Field(default=None, ge=0)


class KnowledgeAnalysisRunView(ApiModel):
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    request_sha256: Sha256
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    source_kind: Literal["CONTENT_INTAKE_FILE", "APPROVED_ITEM_REVISION", "DOCUMENT_REVISION"]
    source_revision_id: str
    source_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: Sha256
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    platform_job_id: str | None = Field(default=None, pattern=r"^job_[0-9a-f]{32}$")
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
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
    proposal_artifact_id: str | None = Field(default=None, pattern=r"^artifact_[0-9a-f]{32}$")
    proposal_artifact_revision_id: str | None = Field(default=None, pattern=r"^rev_[0-9a-f]{32}$")
    proposal_content_set_sha256: Sha256 | None
    accepted_result_artifact_id: str | None = Field(
        default=None, pattern=r"^artifact_[0-9a-f]{32}$"
    )
    accepted_result_artifact_revision_id: str | None = Field(
        default=None, pattern=r"^rev_[0-9a-f]{32}$"
    )
    accepted_result_sha256: Sha256 | None
    counts: KnowledgeAnalysisCountsView
    resource_version: int = Field(ge=1)
    created_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")


class KnowledgeAnalysisBatchView(ApiModel):
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    request_sha256: Sha256
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: Sha256
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    risk_policy_sha256: Sha256
    general_knowledge_mode: Literal["AUXILIARY_UNATTRIBUTED"]
    review_policy: Literal["PREAUTHORIZED_APPROVE_VALIDATED"]
    range_failure_policy: Literal["STOP_ON_FIRST_FAILURE", "CONTINUE_AND_COLLECT"]
    scheduling_mode: Literal["SERIAL", "BOUNDED_PARALLEL"] = "SERIAL"
    max_in_flight: Literal[1, 2] = 1
    authorized_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    authorized_at: UtcDatetime
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


class KnowledgeAnalysisBatchRangeView(ApiModel):
    range_id: str = Field(pattern=r"^analysisrange_[0-9a-f]{32}$")
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    ordinal: int = Field(ge=0, le=999)
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(ge=1)
    last_physical_page: int = Field(ge=1)
    curriculum_unit_keys: tuple[str, ...] = Field(max_length=32)
    source_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: Sha256
    source_media_type: Literal["application/pdf"]
    source_schema_ref: Literal["eom://schemas/educational-document/pdf-source/1.0"]
    analysis_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    analysis_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    analysis_manifest_sha256: Sha256
    analysis_media_type: Literal["application/json"]
    analysis_schema_ref: Literal[
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0",
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0",
    ]
    rights_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    rights_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    rights_attestation_sha256: Sha256
    rights_media_type: Literal["application/json"]
    rights_schema_ref: Literal["eom://schemas/educational-document/rights-attestation/1.0"]
    execution_mode: Literal["EXECUTE", "REUSE_ACCEPTED"]
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    reuse_accepted_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    analysis_run_id: str | None = Field(default=None, pattern=r"^analysisrun_[0-9a-f]{32}$")
    state: Literal["PENDING", "CLAIMED", "SUBMITTED", "ACCEPTED", "FAILED", "CANCELLED"]
    submission_attempts: int = Field(ge=0, le=1)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    submitted_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    updated_at: UtcDatetime

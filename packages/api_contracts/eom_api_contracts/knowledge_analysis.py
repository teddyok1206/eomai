"""Public bounded DTOs for source-grounded knowledge-analysis operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime


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
    curriculum_unit_keys: tuple[
        Annotated[
            str,
            Field(
                pattern=(
                    r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|"
                    r"5-\([1-7]\)|6-\([1-4]\))$"
                )
            ),
        ],
        ...,
    ] = Field(max_length=16)

    @model_validator(mode="after")
    def bounded_document_selection(self) -> EducationalDocumentAnalysisSourceInput:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("document analysis page range is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("document analysis page range exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("document curriculum keys must be sorted and unique")
        return self


KnowledgeAnalysisSourceInput = Annotated[
    ContentIntakeAnalysisSourceInput
    | ApprovedItemAnalysisSourceInput
    | EducationalDocumentAnalysisSourceInput,
    Field(discriminator="source_kind"),
]


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

"""Public bounded DTOs for source-grounded knowledge-analysis operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

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


KnowledgeAnalysisSourceInput = Annotated[
    ContentIntakeAnalysisSourceInput | ApprovedItemAnalysisSourceInput,
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
    source_kind: Literal["CONTENT_INTAKE_FILE", "APPROVED_ITEM_REVISION"]
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

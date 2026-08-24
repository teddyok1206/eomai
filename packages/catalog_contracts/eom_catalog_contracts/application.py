"""Typed private protocol for orchestrator-owned Catalog application operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, RootModel, field_validator, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.models import ActorId, FrozenModel

ItemRevisionId = Annotated[str, Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")]

# The socket framing and filesystem identity are part of the private protocol,
# not an implementation detail of either endpoint.
CATALOG_APPLICATION_SOCKET_PATH = "/run/eom-catalog-api/manager.sock"
CATALOG_APPLICATION_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CATALOG_APPLICATION_SOCKET_MODE = 0o660
CATALOG_APPLICATION_RUNTIME_DIRECTORY_MODE = 0o750


class CatalogApplicationErrorCode(StrEnum):
    CATALOG_APPLICATION_INTERNAL_ERROR = "CATALOG_APPLICATION_INTERNAL_ERROR"
    CATALOG_APPLICATION_REQUEST_INVALID = "CATALOG_APPLICATION_REQUEST_INVALID"
    CATALOG_APPLICATION_UNAVAILABLE = "CATALOG_APPLICATION_UNAVAILABLE"
    CATALOG_ARTIFACT_COMMIT_FAILED = "CATALOG_ARTIFACT_COMMIT_FAILED"
    CATALOG_CONTENT_PACK_STAGING_INVALID = "CATALOG_CONTENT_PACK_STAGING_INVALID"
    CATALOG_CONCURRENCY_CONFLICT = "CATALOG_CONCURRENCY_CONFLICT"
    CATALOG_QUERY_INVALID = "CATALOG_QUERY_INVALID"
    CATALOG_CURSOR_INVALID = "CATALOG_CURSOR_INVALID"
    CATALOG_EXPORT_FAILED = "CATALOG_EXPORT_FAILED"
    CATALOG_REGISTRY_STAGING_INVALID = "CATALOG_REGISTRY_STAGING_INVALID"


class ReviewedItemContentImportCommand(FrozenModel):
    operation: Literal["IMPORT_REVIEWED_ITEM_CONTENT"] = "IMPORT_REVIEWED_ITEM_CONTENT"
    base_revision_id: ItemRevisionId
    expected_version: int = Field(ge=1)
    reviewed_by: ActorId
    review_reason: str = Field(min_length=10, max_length=2000)
    content: AssessmentItemContent

    @field_validator("review_reason")
    @classmethod
    def safe_review_reason(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("review reason contains a control character")
        return value


class ItemContentQuery(FrozenModel):
    operation: Literal["GET_ITEM_CONTENT"] = "GET_ITEM_CONTENT"
    item_revision_id: ItemRevisionId


class ContentIntakeKnowledgeAnalysisSelection(FrozenModel):
    source_kind: Literal["CONTENT_INTAKE_FILE"] = "CONTENT_INTAKE_FILE"
    source_class: Literal["CURRICULUM", "TEXTBOOK", "PAST_EXAM", "INTERNAL_GUIDE"]
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")


class ApprovedItemKnowledgeAnalysisSelection(FrozenModel):
    source_kind: Literal["APPROVED_ITEM_REVISION"] = "APPROVED_ITEM_REVISION"
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")


KnowledgeAnalysisSourceSelection = Annotated[
    ContentIntakeKnowledgeAnalysisSelection | ApprovedItemKnowledgeAnalysisSelection,
    Field(discriminator="source_kind"),
]


class CreateKnowledgeAnalysisCommand(FrozenModel):
    operation: Literal["CREATE_KNOWLEDGE_ANALYSIS"] = "CREATE_KNOWLEDGE_ANALYSIS"
    source: KnowledgeAnalysisSourceSelection
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"]
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")


class ReconcileKnowledgeAnalysisCommand(FrozenModel):
    operation: Literal["RECONCILE_KNOWLEDGE_ANALYSIS"] = "RECONCILE_KNOWLEDGE_ANALYSIS"
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    requested_by: ActorId


class ReviewKnowledgeAnalysisCommand(FrozenModel):
    operation: Literal["REVIEW_KNOWLEDGE_ANALYSIS"] = "REVIEW_KNOWLEDGE_ANALYSIS"
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    expected_version: int = Field(ge=1)
    decision: Literal["APPROVE", "REJECT"]
    notes: str = Field(min_length=1, max_length=2000)
    decided_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")

    @field_validator("notes")
    @classmethod
    def safe_notes(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("review notes contain a control character")
        return value


CatalogApplicationRequestValue = Annotated[
    ReviewedItemContentImportCommand
    | ItemContentQuery
    | CreateKnowledgeAnalysisCommand
    | ReconcileKnowledgeAnalysisCommand
    | ReviewKnowledgeAnalysisCommand,
    Field(discriminator="operation"),
]


class CatalogApplicationRequest(RootModel[CatalogApplicationRequestValue]):
    root: CatalogApplicationRequestValue


class ReviewedItemContentImportResult(FrozenModel):
    item_id: str = Field(pattern=r"^item_[a-z0-9]{8,59}$")
    item_revision_id: ItemRevisionId
    resource_version: int = Field(ge=1)
    content_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    content_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class KnowledgeAnalysisApplicationResult(FrozenModel):
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
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
    proposal_artifact_revision_id: str | None = Field(default=None, pattern=r"^rev_[0-9a-f]{32}$")
    accepted_result_artifact_revision_id: str | None = Field(
        default=None, pattern=r"^rev_[0-9a-f]{32}$"
    )


class CatalogApplicationResponse(FrozenModel):
    status: Literal["OK", "ERROR"]
    operation: Literal[
        "IMPORT_REVIEWED_ITEM_CONTENT",
        "GET_ITEM_CONTENT",
        "CREATE_KNOWLEDGE_ANALYSIS",
        "RECONCILE_KNOWLEDGE_ANALYSIS",
        "REVIEW_KNOWLEDGE_ANALYSIS",
    ]
    result: ReviewedItemContentImportResult | None = None
    analysis: KnowledgeAnalysisApplicationResult | None = None
    content: AssessmentItemContent | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> CatalogApplicationResponse:
        present = sum(
            value is not None
            for value in (self.result, self.analysis, self.content, self.error_code)
        )
        if present != 1:
            raise ValueError("catalog application response must contain exactly one payload")
        if self.status == "ERROR":
            if self.error_code is None:
                raise ValueError("catalog application error response requires error_code")
            return self
        if self.error_code is not None:
            raise ValueError("catalog application success response cannot contain error_code")
        if self.operation == "IMPORT_REVIEWED_ITEM_CONTENT" and self.result is None:
            raise ValueError("catalog import response requires result")
        if self.operation == "GET_ITEM_CONTENT" and self.content is None:
            raise ValueError("catalog content response requires content")
        if (
            self.operation
            in {
                "CREATE_KNOWLEDGE_ANALYSIS",
                "RECONCILE_KNOWLEDGE_ANALYSIS",
                "REVIEW_KNOWLEDGE_ANALYSIS",
            }
            and self.analysis is None
        ):
            raise ValueError("knowledge analysis response requires analysis result")
        return self

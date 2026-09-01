"""Typed private protocol for orchestrator-owned Catalog application operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, RootModel, field_validator, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.knowledge import (
    CurriculumRetrievalScope,
    EducationalRetrievalRequirement,
    EvidenceBudget,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    KnowledgeSourceClass,
    PermissionKeyValue,
)
from eom_catalog_contracts.knowledge_analysis_batch import (
    CreateKnowledgeAnalysisBatchCommand,
    KnowledgeAnalysisBatchApplicationResult,
)
from eom_catalog_contracts.models import ActorId, FrozenModel

ItemRevisionId = Annotated[str, Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")]

# The socket framing and filesystem identity are part of the private protocol,
# not an implementation detail of either endpoint.
CATALOG_APPLICATION_SOCKET_PATH = "/run/eom-catalog-api/manager.sock"
CATALOG_APPLICATION_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CATALOG_APPLICATION_SOCKET_MODE = 0o660
CATALOG_APPLICATION_RUNTIME_DIRECTORY_MODE = 0o750
CATALOG_ITEM_MEDIA_MAX_BYTES = 16 * 1024 * 1024


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


class ItemMediaQuery(FrozenModel):
    operation: Literal["GET_ITEM_MEDIA"] = "GET_ITEM_MEDIA"
    item_revision_id: ItemRevisionId
    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")


class CatalogItemMediaResponse(FrozenModel):
    status: Literal["OK", "ERROR"]
    operation: Literal["GET_ITEM_MEDIA"] = "GET_ITEM_MEDIA"
    media_type: Literal["image/png", "image/jpeg"] | None = None
    content_length: int | None = Field(default=None, ge=1, le=CATALOG_ITEM_MEDIA_MAX_BYTES)
    sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> CatalogItemMediaResponse:
        success_values = (self.media_type, self.content_length, self.sha256)
        if self.status == "OK" and all(value is not None for value in success_values):
            if self.error_code is not None:
                raise ValueError("Catalog media success cannot contain an error code")
            return self
        if self.status == "ERROR" and self.error_code is not None:
            if any(value is not None for value in success_values):
                raise ValueError("Catalog media error cannot contain success metadata")
            return self
        raise ValueError("Catalog media response variant is incomplete")


class ContentIntakeKnowledgeAnalysisSelection(FrozenModel):
    source_kind: Literal["CONTENT_INTAKE_FILE"] = "CONTENT_INTAKE_FILE"
    source_class: Literal["CURRICULUM", "TEXTBOOK", "PAST_EXAM", "INTERNAL_GUIDE"]
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")


class ApprovedItemKnowledgeAnalysisSelection(FrozenModel):
    source_kind: Literal["APPROVED_ITEM_REVISION"] = "APPROVED_ITEM_REVISION"
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")


class EducationalDocumentKnowledgeAnalysisSelection(FrozenModel):
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
    def bounded_page_range(self) -> EducationalDocumentKnowledgeAnalysisSelection:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("document analysis page range is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("document analysis page range exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("document curriculum keys must be sorted and unique")
        return self


KnowledgeAnalysisSourceSelection = Annotated[
    ContentIntakeKnowledgeAnalysisSelection
    | ApprovedItemKnowledgeAnalysisSelection
    | EducationalDocumentKnowledgeAnalysisSelection,
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


class CreateEvidenceBundleCommand(FrozenModel):
    operation: Literal["CREATE_EVIDENCE_BUNDLE"] = "CREATE_EVIDENCE_BUNDLE"
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    query_kind: Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]
    curriculum_scope: CurriculumRetrievalScope | None
    topic_keys: tuple[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")], ...] = Field(
        max_length=20
    )
    target_item_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    required_item_elements: tuple[
        Literal["paragraph", "table", "image", "equation", "statement_set", "choice"], ...
    ] = Field(max_length=8)
    source_classes: tuple[KnowledgeSourceClass, ...] = Field(min_length=1, max_length=5)
    evidence_budget: EvidenceBudget
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    requester_role: Literal["ADMIN", "EDITOR", "REVIEWER", "WORKER"]
    requester_permission_keys: tuple[PermissionKeyValue, ...] = Field(min_length=1, max_length=128)
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")
    submission_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def command_is_closed_and_hashed(self) -> CreateEvidenceBundleCommand:
        for values, label in (
            (self.topic_keys, "topic keys"),
            (self.required_item_elements, "required item elements"),
            (self.source_classes, "source classes"),
            (self.requester_permission_keys, "permission keys"),
        ):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise ValueError(f"evidence command {label} must be sorted and unique")
        if self.query_kind in {"CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE"} and (
            self.curriculum_scope is None
        ):
            raise ValueError("curriculum evidence command requires a pinned scope")
        if self.curriculum_scope is None and not self.topic_keys:
            raise ValueError("evidence command requires curriculum scope or topic keys")
        if self.query_kind == "APPROVED_ITEM_STRUCTURE" and not self.required_item_elements:
            raise ValueError("item structure evidence requires element filters")
        body = self.model_dump(mode="json", exclude={"idempotency_key", "submission_sha256"})
        if content_sha256(body) != self.submission_sha256:
            raise ValueError("evidence command hash does not match canonical input")
        return self


class CreateItemProductionEvidenceCommand(FrozenModel):
    """Private preset-resolved request; Catalog alone selects the current graph snapshot."""

    operation: Literal["CREATE_ITEM_PRODUCTION_EVIDENCE"] = "CREATE_ITEM_PRODUCTION_EVIDENCE"
    requirement: EducationalRetrievalRequirement
    evidence_budget: EvidenceBudget
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requester_role: Literal["ADMIN", "EDITOR", "REVIEWER"]
    requester_permission_keys: tuple[PermissionKeyValue, ...] = Field(min_length=1, max_length=128)
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")
    submission_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def preset_bounded_command_is_sorted_and_hashed(self) -> CreateItemProductionEvidenceCommand:
        if tuple(sorted(self.requester_permission_keys)) != self.requester_permission_keys or len(
            self.requester_permission_keys
        ) != len(set(self.requester_permission_keys)):
            raise ValueError("item evidence permission keys must be sorted and unique")
        body = self.model_dump(mode="json", exclude={"idempotency_key", "submission_sha256"})
        if content_sha256(body) != self.submission_sha256:
            raise ValueError("item evidence command hash does not match canonical input")
        return self


CatalogApplicationRequestValue = Annotated[
    ReviewedItemContentImportCommand
    | ItemContentQuery
    | CreateKnowledgeAnalysisCommand
    | ReconcileKnowledgeAnalysisCommand
    | ReviewKnowledgeAnalysisCommand
    | CreateKnowledgeAnalysisBatchCommand
    | CreateEvidenceBundleCommand
    | CreateItemProductionEvidenceCommand,
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
        "CREATE_KNOWLEDGE_ANALYSIS_BATCH",
        "CREATE_EVIDENCE_BUNDLE",
        "CREATE_ITEM_PRODUCTION_EVIDENCE",
    ]
    result: ReviewedItemContentImportResult | None = None
    analysis: KnowledgeAnalysisApplicationResult | None = None
    analysis_batch: KnowledgeAnalysisBatchApplicationResult | None = None
    evidence: (
        EvidenceBundlePublicationResult
        | EvidenceBundlePublicationResultV3
        | EvidenceBundlePublicationResultV4
        | None
    ) = None
    item_production_evidence: (
        EvidenceBundlePublicationResultV2
        | EvidenceBundlePublicationResultV3
        | EvidenceBundlePublicationResultV4
        | None
    ) = None
    content: AssessmentItemContent | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> CatalogApplicationResponse:
        present = sum(
            value is not None
            for value in (
                self.result,
                self.analysis,
                self.analysis_batch,
                self.evidence,
                self.item_production_evidence,
                self.content,
                self.error_code,
            )
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
        if self.operation == "CREATE_KNOWLEDGE_ANALYSIS_BATCH" and self.analysis_batch is None:
            raise ValueError("knowledge analysis batch response requires batch result")
        if self.operation == "CREATE_EVIDENCE_BUNDLE" and self.evidence is None:
            raise ValueError("evidence creation response requires publication result")
        if (
            self.operation == "CREATE_ITEM_PRODUCTION_EVIDENCE"
            and self.item_production_evidence is None
        ):
            raise ValueError("item production evidence response requires publication result")
        return self

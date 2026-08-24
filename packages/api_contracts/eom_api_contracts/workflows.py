"""Workflow command and query DTOs."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts import EducationalRetrievalRequirement, KnowledgeSourceClass
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, OpaqueId, Sha256, UtcDatetime


class KnowledgeItemBriefRequest(ApiModel):
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    task_type: Literal["calculation", "conceptual", "data_interpretation"]
    difficulty: Literal["easy", "medium", "hard"]
    choice_count: Literal[5] = 5
    equation_required: Literal[True] = True
    image_required: Literal[True] = True
    quality_profile: Literal["fast", "balanced", "deep"]
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowStartRequest(ApiModel):
    definition_key: str = Field(min_length=1, max_length=64)
    definition_version: str = Field(min_length=1, max_length=32)
    request_name: Literal[
        "PLACEHOLDER_REQUEST",
        "KNOWLEDGE_ITEM_REQUEST",
        "GENERATED_KNOWLEDGE_ITEM_REQUEST",
    ] = "PLACEHOLDER_REQUEST"
    image_mode: Literal["skip", "required"]
    pack_key: str | None = Field(default=None, max_length=64)
    environment: Literal["development", "test"] = "development"
    source_intake_batch_ids: tuple[Annotated[str, Field(pattern=r"^intake_[0-9a-f]{32}$")], ...] = (
        Field(default=(), max_length=100)
    )
    registry_mode: Literal["CREATE_ITEM", "REVISE_ITEM"] = "CREATE_ITEM"
    item_id: str | None = Field(default=None, max_length=128)
    base_revision_id: str | None = Field(default=None, max_length=128)
    item_brief: KnowledgeItemBriefRequest | None = None
    stimulus_asset_key: Literal["eom-question-template-reference-v1"] | None = None
    execution_preset_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,63}$")
    educational_retrieval: EducationalRetrievalRequirement | None = None

    @model_validator(mode="after")
    def validate_content_pack_pointer(self) -> WorkflowStartRequest:
        if self.pack_key is None and self.source_intake_batch_ids:
            raise ValueError("source intake batches require a content pack")
        if self.execution_preset_key is not None and self.pack_key is None:
            raise ValueError("execution preset requires a content pack workflow")
        if self.educational_retrieval is not None and (
            self.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            or self.execution_preset_key is None
        ):
            raise ValueError(
                "educational retrieval requires a generated item request and execution preset"
            )
        if (
            self.pack_key is not None
            and not self.source_intake_batch_ids
            and self.request_name
            not in {"KNOWLEDGE_ITEM_REQUEST", "GENERATED_KNOWLEDGE_ITEM_REQUEST"}
        ):
            raise ValueError("content pack workflows require at least one source intake batch")
        if self.request_name == "KNOWLEDGE_ITEM_REQUEST":
            if (
                self.pack_key != "general-knowledge-item"
                or self.image_mode != "required"
                or self.item_brief is None
                or self.stimulus_asset_key != "eom-question-template-reference-v1"
            ):
                raise ValueError("knowledge item request is missing its fixed workflow contract")
        elif self.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST":
            if (
                self.pack_key != "generated-knowledge-item"
                or self.image_mode != "required"
                or self.item_brief is None
                or self.stimulus_asset_key is not None
                or self.source_intake_batch_ids
            ):
                raise ValueError("generated item request is missing its workflow contract")
        elif self.item_brief is not None or self.stimulus_asset_key is not None:
            raise ValueError("placeholder request cannot include a knowledge item brief")
        return self


class WorkflowKnowledgeProvenanceView(ApiModel):
    """Pointer-only reviewer projection for one knowledge-backed execution plan."""

    schema_version: Literal["workflow-knowledge-provenance/1.0"] = (
        "workflow-knowledge-provenance/1.0"
    )
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    corpus_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    query_kind: Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]
    curriculum_root_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    required_item_elements: tuple[
        Literal["paragraph", "table", "image", "equation", "statement_set", "choice"], ...
    ] = Field(min_length=1, max_length=8)
    source_classes: tuple[KnowledgeSourceClass, ...] = Field(min_length=1, max_length=5)
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    retrieval_request_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    evidence_manifest_sha256: Sha256
    resolved_at: UtcDatetime


class WorkflowView(ApiModel):
    workflow_id: OpaqueId
    definition_key: str
    definition_version: str
    state: str
    stage: str
    current_step_key: str
    resource_version: int = Field(ge=1)
    rework_cycle_count: int = Field(ge=0)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    failure_code: str | None = None
    knowledge_provenance: WorkflowKnowledgeProvenanceView | None = None


class WorkflowActionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=2000)


class WorkflowStepView(ApiModel):
    step_run_id: OpaqueId
    workflow_id: OpaqueId
    step_key: str
    attempt: int = Field(ge=1)
    step_type: str
    worker_role: str | None = None
    state: str
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    error_code: str | None = None

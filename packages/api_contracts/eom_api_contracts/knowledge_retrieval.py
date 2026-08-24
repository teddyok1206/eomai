"""Public bounded DTOs for immutable Education Graph evidence retrieval."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime

TopicKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class CurriculumRetrievalScopeInput(ApiModel):
    framework_revision_id: str = Field(pattern=r"^curriculumrev_[0-9a-f]{32}$")
    root_unit_id: str = Field(pattern=r"^currunit_[0-9a-f]{32}$")
    include_descendants: bool = True


class EvidenceBudgetInput(ApiModel):
    max_documents: int = Field(default=8, ge=1, le=32)
    max_item_revisions: int = Field(default=8, ge=0, le=64)
    max_graph_nodes: int = Field(default=64, ge=1, le=256)
    max_claims: int = Field(default=32, ge=1, le=128)
    max_context_tokens: int = Field(default=8000, ge=1000, le=32000)


class CreateEvidenceBundleRequest(ApiModel):
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    query_kind: Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]
    curriculum_scope: CurriculumRetrievalScopeInput | None = None
    topic_keys: tuple[TopicKey, ...] = Field(default=(), max_length=20)
    target_item_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    required_item_elements: tuple[
        Literal["paragraph", "table", "image", "equation", "statement_set", "choice"], ...
    ] = Field(default=(), max_length=8)
    source_classes: tuple[
        Literal["CURRICULUM", "TEXTBOOK", "APPROVED_ITEM", "PAST_EXAM", "INTERNAL_GUIDE"],
        ...,
    ] = Field(min_length=1, max_length=5)
    evidence_budget: EvidenceBudgetInput
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def request_is_closed_and_sorted(self) -> CreateEvidenceBundleRequest:
        for values, label in (
            (self.topic_keys, "topic keys"),
            (self.required_item_elements, "required item elements"),
            (self.source_classes, "source classes"),
        ):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise ValueError(f"retrieval {label} must be sorted and unique")
        if self.query_kind in {"CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE"} and (
            self.curriculum_scope is None
        ):
            raise ValueError("curriculum retrieval requires an exact scope")
        if self.curriculum_scope is None and not self.topic_keys:
            raise ValueError("retrieval requires curriculum scope or topic keys")
        if self.query_kind == "APPROVED_ITEM_STRUCTURE" and not self.required_item_elements:
            raise ValueError("item structure retrieval requires element filters")
        return self


class EvidenceBundleBudgetView(ApiModel):
    document_count: int = Field(ge=0, le=32)
    item_revision_count: int = Field(ge=0, le=64)
    graph_node_count: int = Field(ge=1, le=256)
    claim_count: int = Field(ge=0, le=128)
    estimated_context_tokens: int = Field(ge=1, le=32000)


class EvidenceBundleView(ApiModel):
    evidence_bundle_id: str = Field(pattern=r"^evidence_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: Literal["PUBLISHED"]
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    retrieval_request_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    requester_permissions_sha256: Sha256
    context_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    context_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    context_sha256: Sha256
    manifest_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    manifest_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    manifest_artifact_sha256: Sha256
    manifest_sha256: Sha256
    budget: EvidenceBundleBudgetView
    created_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    resource_version: Literal[1] = 1

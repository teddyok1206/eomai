"""Shared immutable selection/request values; wire versions retain separate schema guards."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentView,
    ExperimentViewRecipe,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
    SimilarityConsumerPurpose,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_workflow.embedding_device_routing import EMBEDDING_DEVICE_ROUTING_SCHEMA_REF


def require_embedding_batch_plan_value(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


class EmbeddingBatchPlanValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


def validate_embedding_batch_value_hash(value: EmbeddingBatchPlanValue, name: str) -> None:
    require_embedding_batch_plan_value(
        getattr(value, name) == content_sha256(value.model_dump(mode="json", exclude={name}))
    )


class EmbeddingBatchQueryOptions(EmbeddingBatchPlanValue):
    consumer_purpose: SimilarityConsumerPurpose
    topics: tuple[str, ...] = Field(max_length=20)
    unit_ids: tuple[str, ...] = Field(max_length=20)
    maximum_sources: int = Field(ge=1, le=1024, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)

    @model_validator(mode="after")
    def sorted_unique(self) -> Self:
        require_embedding_batch_plan_value(
            all(values == tuple(sorted(set(values))) for values in (self.topics, self.unit_ids))
        )
        return self


class RegisteredReviewBatchAnchor(EmbeddingBatchPlanValue):
    basis: Literal["REGISTERED_ITEM_REVIEW"]
    source: ApprovedItemKnowledgeSourceV2
    profile: RegisteredReviewProfilePointer
    review_evidence: RegisteredItemReviewSolutionEvidence

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        require_embedding_batch_plan_value(self.source == self.review_evidence.source)
        return self


class EmbeddingBatchSelectionValues(EmbeddingBatchPlanValue):
    """Value closure only. Concrete wire models supply their own schema/version/size guards."""

    message_type: Literal["SELECTION"]
    purpose: Literal["INDEX", "REFERENCE_QUERY"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[ApprovedReferenceItemAnchor | RegisteredReviewBatchAnchor, ...] = Field(
        min_length=1, max_length=1024
    )
    recipe: ExperimentViewRecipe
    views: tuple[ExperimentView, ...] = Field(min_length=1, max_length=3)
    query: EmbeddingBatchQueryOptions | None
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        keys = tuple(
            (anchor.source.source_class, anchor.source.item_id, anchor.source.item_revision_id)
            for anchor in self.anchors
        )
        require_embedding_batch_plan_value(len(set(keys)) == len(keys))
        require_embedding_batch_plan_value(
            self.views == tuple(view for view in VIEWS if view in self.views)
        )
        require_embedding_batch_plan_value((self.query is None) == (self.purpose == "INDEX"))
        require_embedding_batch_plan_value(
            self.purpose != "REFERENCE_QUERY" or self.scope.actor_kind == "OPERATOR"
        )
        require_embedding_batch_plan_value(
            self.purpose != "REFERENCE_QUERY"
            or all(isinstance(anchor, ApprovedReferenceItemAnchor) for anchor in self.anchors)
        )
        require_embedding_batch_plan_value(
            self.graph_snapshot.manifest_artifact.sha256 == self.graph_snapshot.manifest_sha256
        )
        validate_embedding_batch_value_hash(self, "selection_sha256")
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        choices: tuple[int, ...] | tuple[ExperimentView, ...] = (
            tuple(range(len(self.anchors))) if self.purpose == "REFERENCE_QUERY" else self.views
        )
        return tuple(
            content_sha256({"selection_sha256": self.selection_sha256, "child": choice})
            for choice in choices
        )


class EmbeddingBatchPlanRequestValues(EmbeddingBatchPlanValue):
    selection_schema_ref: ClassVar[str]
    message_type: Literal["REQUEST"]
    batch_id: str = Field(pattern=r"^embeddingbatch_[0-9a-f]{32}$")
    parent_request_sha256: Sha256
    purpose: Literal["INDEX", "REFERENCE_QUERY"]
    scope: EmbeddingWorkBatchScope
    selection_manifest: ArtifactMemberPointer
    selection_sha256: Sha256
    routing_policy: ArtifactMemberPointer
    routing_policy_sha256: Sha256
    child_selection_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=32)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        for pointer, member, schema in (
            (self.selection_manifest, "selection.json", self.selection_schema_ref),
            (self.routing_policy, "policy.json", EMBEDDING_DEVICE_ROUTING_SCHEMA_REF),
        ):
            require_embedding_batch_plan_value(
                pointer.member_path == member
                and pointer.schema_ref == schema
                and pointer.media_type == "application/json"
            )
        require_embedding_batch_plan_value(
            len(set(self.child_selection_sha256s)) == len(self.child_selection_sha256s)
        )
        validate_embedding_batch_value_hash(self, "request_sha256")
        return self

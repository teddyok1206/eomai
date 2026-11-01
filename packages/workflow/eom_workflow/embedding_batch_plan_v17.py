"""Owned private question selection for the existing finite batch parent.

This closed metadata family neither admits a source nor activates a worker. One
question has one child; public INDEX/QUERY predecessors remain closed and immutable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    EmbeddingWorkBatchScope,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.private_chat_query_prepare import private_chat_query_context_request_id
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatPublicDocumentView
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_workflow.embedding_batch_plan import MAX_BATCH_PLAN_BYTES
from eom_workflow.embedding_batch_plan_v14 import (
    embedding_batch_public_query_plan_schema_registry,
    validate_public_query_index_pair_values,
)
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
    validate_embedding_batch_value_hash,
)
from eom_workflow.embedding_batch_plan_values import (
    require_embedding_batch_plan_value as require,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingPolicy,
)
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)

BATCH_PLAN_V17_PROTOCOL = "embedding-batch-plan/1.7"
BATCH_PLAN_V17_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.7"
BATCH_PLAN_V17_SCHEMA_SHA256 = (
    "sha256:e70ed76b9b274f1cc890b76b661860cd42b17ab600754d438f954cae5911a149"
)
BATCH_SELECTION_V17_SCHEMA_REF = BATCH_PLAN_V17_SCHEMA_REF + "#/$defs/selection"


def embedding_batch_private_query_plan_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.7.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    require(
        0 < len(raw) <= MAX_BATCH_PLAN_BYTES and sha256_bytes(raw) == BATCH_PLAN_V17_SCHEMA_SHA256
    )
    schema = json.loads(raw)
    require(schema.get("$id") == BATCH_PLAN_V17_SCHEMA_REF)
    Draft202012Validator.check_schema(schema)
    return dict(schema)


@lru_cache(maxsize=1)
def embedding_batch_private_query_plan_schema_registry() -> Registry[Any]:
    registry: Registry[Any] = embedding_batch_public_query_plan_schema_registry()
    result: Registry[Any] = registry.with_resource(
        BATCH_PLAN_V17_SCHEMA_REF,
        Resource.from_contents(embedding_batch_private_query_plan_schema()),
    )
    return result


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        embedding_batch_private_query_plan_schema(),
        registry=embedding_batch_private_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


class _PrivateQueryPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.7"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            require(len(canonical_json_bytes(document)) <= MAX_BATCH_PLAN_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


class PrivateChatBatchQueryOptions(EmbeddingBatchPlanValue):
    consumer_purpose: Literal["GENERAL_CHAT_READ"]
    context_request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    maximum_sources: int = Field(ge=1, le=16384, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)


class PrivateChatQueryIndexPair(EmbeddingBatchPlanValue):
    cpu: PrivateChatPublicDocumentView
    cuda: PrivateChatPublicDocumentView

    @model_validator(mode="after")
    def exact_devices(self) -> Self:
        require(self.cpu.recipe == self.cuda.recipe and self.cuda.index is not None)
        cuda = self.cuda.index
        assert cuda is not None
        require(cuda.spaces.document.runtime.device == cuda.spaces.query.runtime.device == "CUDA")
        if self.cpu.index is not None:
            # The common paired-space invariant is authoritative; only the
            # nullable CPU availability is private-specific.
            validate_public_query_index_pair_values(
                PublicSolutionSimilarityViewV4(recipe=self.cpu.recipe, index=self.cpu.index),
                PublicSolutionSimilarityViewV4(recipe=self.cuda.recipe, index=cuda),
            )
        return self

    def select(self, device: Literal["CPU", "CUDA"]) -> PrivateChatPublicDocumentView:
        require(device in {"CPU", "CUDA"})
        return self.cpu if device == "CPU" else self.cuda


class PrivateChatBatchPolicyPin(EmbeddingBatchPlanValue):
    member: ArtifactMemberPointer
    policy_sha256: Sha256

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        require(
            self.member.member_path == "policy.json"
            and self.member.schema_ref == PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF
            and self.member.media_type == "application/json"
        )
        return self


class PrivateChatBatchPolicies(EmbeddingBatchPlanValue):
    cpu: PrivateChatBatchPolicyPin
    cuda: PrivateChatBatchPolicyPin

    @model_validator(mode="after")
    def distinct_controls(self) -> Self:
        require(
            self.cpu.member != self.cuda.member
            and self.cpu.policy_sha256 != self.cuda.policy_sha256
            and (self.cpu.member.artifact_id, self.cpu.member.artifact_revision_id)
            != (self.cuda.member.artifact_id, self.cuda.member.artifact_revision_id)
        )
        return self


class EmbeddingBatchSelectionV17(_PrivateQueryPlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    origin: ChatPrivateQueryOrigin
    recipe: PublicSolutionEmbeddingRecipe
    views: tuple[Literal["CONCRETE_FACETS"], ...] = Field(min_length=1, max_length=1)
    query: PrivateChatBatchQueryOptions
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    index_pair: PrivateChatQueryIndexPair
    private_policies: PrivateChatBatchPolicies
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        require(
            self.scope.actor_kind == "OPERATOR"
            and self.scope.actor_id == self.origin.actor_id
            and self.query.context_request_id == private_chat_query_context_request_id(self.origin)
            and self.source_classes == tuple(sorted(set(self.source_classes)))
            and self.graph_snapshot.manifest_sha256 == self.graph_snapshot.manifest_artifact.sha256
            and all(
                view.recipe == self.recipe
                and (
                    view.index is None
                    or view.index.storage_partition == self.scope.storage_partition
                )
                for view in (self.index_pair.cpu, self.index_pair.cuda)
            )
        )
        validate_embedding_batch_value_hash(self, "selection_sha256")
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        return (content_sha256({"selection_sha256": self.selection_sha256, "child": 0}),)

    def selected_views(
        self, device: Literal["CPU", "CUDA"]
    ) -> tuple[PrivateChatPublicDocumentView, ...]:
        return (self.index_pair.select(device),)


class EmbeddingBatchPlanRequestV17(EmbeddingBatchPlanRequestValues, _PrivateQueryPlanMessage):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V17_SCHEMA_REF
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    child_selection_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=1)


def private_chat_batch_parent_request_sha256(selection: EmbeddingBatchSelectionV17) -> str:
    selection = EmbeddingBatchSelectionV17.model_validate(raw_similarity_contract_value(selection))
    return content_sha256(
        {
            "protocol": BATCH_PLAN_V17_PROTOCOL,
            "purpose": "PRIVATE_CHAT_QUERY",
            "origin_sha256": selection.origin.origin_sha256,
            "selection_sha256": selection.selection_sha256,
        }
    )


def validate_private_query_batch_plan_values(
    request: EmbeddingBatchPlanRequestV17,
    selection: EmbeddingBatchSelectionV17,
    routing: EmbeddingDeviceRoutingPolicy,
) -> tuple[EmbeddingBatchPlanRequestV17, EmbeddingBatchSelectionV17, EmbeddingDeviceRoutingPolicy]:
    """Canonical planning metadata only; actual origin and both leaf policies are separate."""
    request = EmbeddingBatchPlanRequestV17.model_validate(raw_similarity_contract_value(request))
    selection = EmbeddingBatchSelectionV17.model_validate(raw_similarity_contract_value(selection))
    routing = EmbeddingDeviceRoutingPolicy.model_validate(raw_similarity_contract_value(routing))
    require(
        request.scope == selection.scope
        and routing.purpose == request.purpose == selection.purpose
        and request.parent_request_sha256 == private_chat_batch_parent_request_sha256(selection)
        and request.selection_sha256 == selection.selection_sha256
        and request.child_selection_sha256s == selection.child_selection_sha256s
        and request.selection_manifest.sha256
        == sha256_bytes(canonical_json_bytes(selection.model_dump(mode="json")))
        and request.routing_policy_sha256 == routing.policy_sha256
        and request.routing_policy.sha256
        == sha256_bytes(canonical_json_bytes(routing.model_dump(mode="json")))
        and routing.view_recipe_sha256 == selection.recipe.recipe_sha256
        and routing.preferred_device == "CUDA"
        and routing.fallback_device == "CPU"
        and all(
            profile.resource_profile.timeout_seconds <= MAX_EMBEDDING_WORK_BATCH_SECONDS
            and (view.index is None or view.index.spaces.document == profile.space)
            for profile, view in (
                (routing.cpu.profile, selection.index_pair.cpu),
                (routing.cuda.profile, selection.index_pair.cuda),
            )
        )
    )
    return request, selection, routing


def validate_private_query_batch_controls(
    request: EmbeddingBatchPlanRequestV17,
    selection: EmbeddingBatchSelectionV17,
    routing: EmbeddingDeviceRoutingPolicy,
    cpu: PrivateChatQueryExecutionPolicyV2,
    cuda: PrivateChatQueryExecutionPolicyV2,
) -> None:
    request, selection, routing = validate_private_query_batch_plan_values(
        request, selection, routing
    )
    cpu = PrivateChatQueryExecutionPolicyV2.model_validate(raw_similarity_contract_value(cpu))
    cuda = PrivateChatQueryExecutionPolicyV2.model_validate(raw_similarity_contract_value(cuda))
    require(cpu.workflow_definition_sha256 == cuda.workflow_definition_sha256)
    for pin, policy, profile, view in (
        (selection.private_policies.cpu, cpu, routing.cpu.profile, selection.index_pair.cpu),
        (selection.private_policies.cuda, cuda, routing.cuda.profile, selection.index_pair.cuda),
    ):
        require(
            pin.member.sha256 == sha256_bytes(canonical_json_bytes(policy))
            and pin.policy_sha256 == policy.policy_sha256
            and policy.spaces.document == profile.space
            and policy.runtime_bundle == profile.runtime_bundle
            and policy.resource_profile == profile.resource_profile
            and (view.index is None or view.index.spaces == policy.spaces)
        )


def validate_private_batch_query_context(
    parent: EmbeddingBatchPlanRequestV17,
    selection: EmbeddingBatchSelectionV17,
    decision: EmbeddingDeviceRoutingDecision,
    ordinal: int,
    request: PrivateChatQueryWorkflowRequestV2,
) -> None:
    parent = EmbeddingBatchPlanRequestV17.model_validate(raw_similarity_contract_value(parent))
    selection = EmbeddingBatchSelectionV17.model_validate(raw_similarity_contract_value(selection))
    decision = EmbeddingDeviceRoutingDecision.model_validate(
        raw_similarity_contract_value(decision)
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        raw_similarity_contract_value(request)
    )
    selected = decision.selected
    view = selection.index_pair.select(selected.backend.device)
    pin = (
        selection.private_policies.cpu
        if selected.backend.device == "CPU"
        else selection.private_policies.cuda
    )
    context = request.context_request
    require(
        type(ordinal) is int
        and ordinal == 0
        and view.index is not None
        and parent.scope == selection.scope
        and parent.parent_request_sha256 == private_chat_batch_parent_request_sha256(selection)
        and parent.selection_sha256 == selection.selection_sha256
        and parent.child_selection_sha256s == selection.child_selection_sha256s
        and parent.selection_manifest.sha256
        == sha256_bytes(canonical_json_bytes(selection.model_dump(mode="json")))
        and decision.request_sha256 == parent.request_sha256
        and decision.policy_sha256 == parent.routing_policy_sha256
        and selected.backend.purpose == "PRIVATE_CHAT_QUERY"
        and context.request_id == selection.query.context_request_id
        and context.query_basis == selection.origin.basis
        and request.operator_audit.operator_id == selection.scope.actor_id
        and context.graph_snapshot == selection.graph_snapshot
        and context.policy_revision_id == selection.access_policy_revision_id
        and context.policy_sha256 == selection.scope.access_policy_sha256
        and context.views == (view,)
        and context.source_classes == selection.source_classes
        and context.maximum_sources == selection.query.maximum_sources
        and context.top_k == selection.query.top_k
        and request.native_execution_policy == pin.member
        and request.native_execution_policy_sha256 == pin.policy_sha256
        and request.resource_profile == selected.profile.resource_profile
        and request.runtime_bundle == selected.profile.runtime_bundle
        and view.index.spaces.document == selected.profile.space
    )

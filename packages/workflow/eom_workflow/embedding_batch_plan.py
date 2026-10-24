"""Device-neutral selection and immutable planning values; never execution or authority."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    EmbeddingWorkBatchScope,
)
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
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    embedding_device_routing_schema,
    validate_embedding_device_route_replay,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    NativeCudaBackendSelection,
    native_embedding_backend_selection_schema,
)
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_PROTOCOL = "embedding-batch-plan/1.0"
BATCH_PLAN_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.0"
BATCH_PLAN_SCHEMA_SHA256 = "sha256:94fe09d2dc756e15b77c3f61883a4dd76f6028b463199a5ad62bd6bf700f1337"
BATCH_SELECTION_SCHEMA_REF = BATCH_PLAN_SCHEMA_REF + "#/$defs/selection"
MAX_BATCH_PLAN_BYTES = 512 * 1024


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    if not 0 < len(raw) <= MAX_BATCH_PLAN_BYTES or sha256_bytes(raw) != BATCH_PLAN_SCHEMA_SHA256:
        raise ValueError("EMBEDDING_BATCH_PLAN_SCHEMA_INVALID")
    return raw


def embedding_batch_plan_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_batch_plan_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (
                EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
                Resource.from_contents(embedding_device_routing_schema()),
            ),
            (
                NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
                Resource.from_contents(native_embedding_backend_selection_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


class _PlanValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class _PlanMessage(_PlanValue):
    schema_version: Literal["embedding-batch-plan/1.0"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            _require(len(canonical_json_bytes(document)) <= MAX_BATCH_PLAN_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


def _hash(value: _PlanValue, name: str) -> None:
    _require(getattr(value, name) == content_sha256(value.model_dump(mode="json", exclude={name})))


class EmbeddingBatchQueryOptions(_PlanValue):
    consumer_purpose: SimilarityConsumerPurpose
    topics: tuple[str, ...] = Field(max_length=20)
    unit_ids: tuple[str, ...] = Field(max_length=20)
    maximum_sources: int = Field(ge=1, le=1024, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)

    @model_validator(mode="after")
    def sorted_unique(self) -> Self:
        _require(
            all(values == tuple(sorted(set(values))) for values in (self.topics, self.unit_ids))
        )
        return self


class RegisteredReviewBatchAnchor(_PlanValue):
    """INDEX-only original review pointers; never manufacture a V10 solution report."""

    basis: Literal["REGISTERED_ITEM_REVIEW"]
    source: ApprovedItemKnowledgeSourceV2
    profile: RegisteredReviewProfilePointer
    review_evidence: RegisteredItemReviewSolutionEvidence

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        _require(self.source == self.review_evidence.source)
        return self


class EmbeddingBatchSelection(_PlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["INDEX", "REFERENCE_QUERY"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[ApprovedReferenceItemAnchor | RegisteredReviewBatchAnchor, ...] = Field(
        min_length=1, max_length=32
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
        _require(len(set(keys)) == len(keys))
        _require(self.views == tuple(view for view in VIEWS if view in self.views))
        _require((self.query is None) == (self.purpose == "INDEX"))
        _require(self.purpose != "REFERENCE_QUERY" or self.scope.actor_kind == "OPERATOR")
        _require(
            self.purpose != "REFERENCE_QUERY"
            or all(isinstance(anchor, ApprovedReferenceItemAnchor) for anchor in self.anchors)
        )
        _require(
            self.graph_snapshot.manifest_artifact.sha256 == self.graph_snapshot.manifest_sha256
        )
        _hash(self, "selection_sha256")
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        """Immutable derived commitments, not extra entities or runtime-dependent encodings."""
        choices: tuple[int, ...] | tuple[ExperimentView, ...] = (
            tuple(range(len(self.anchors))) if self.purpose == "REFERENCE_QUERY" else self.views
        )
        return tuple(
            content_sha256({"selection_sha256": self.selection_sha256, "child": choice})
            for choice in choices
        )


class EmbeddingBatchPlanRequest(_PlanMessage):
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
            (self.selection_manifest, "selection.json", BATCH_SELECTION_SCHEMA_REF),
            (self.routing_policy, "policy.json", EMBEDDING_DEVICE_ROUTING_SCHEMA_REF),
        ):
            _require(
                pointer.member_path == member
                and pointer.schema_ref == schema
                and pointer.media_type == "application/json"
            )
        _require(len(set(self.child_selection_sha256s)) == len(self.child_selection_sha256s))
        _hash(self, "request_sha256")
        return self


class EmbeddingBatchAllocation(_PlanMessage):
    message_type: Literal["ALLOCATION"]
    request_sha256: Sha256
    control_request: EmbeddingGpuAllocationRequest
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        _hash(self, "record_sha256")
        return self


class EmbeddingBatchRoute(_PlanMessage):
    message_type: Literal["ROUTED"]
    request_sha256: Sha256
    allocation_record_sha256: Sha256
    observation: EmbeddingGpuAllocationObservation
    decision: EmbeddingDeviceRoutingDecision
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        _hash(self, "record_sha256")
        return self


class EmbeddingBatchFailure(_PlanMessage):
    message_type: Literal["FAILED"]
    request_sha256: Sha256
    error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    evidence: ArtifactMemberPointer
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        _require(self.evidence.media_type == "application/json")
        _hash(self, "record_sha256")
        return self


class EmbeddingBatchChildBinding(_PlanValue):
    selection_sha256: Sha256
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    native_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    launch_association_sha256: Sha256
    native_input_sha256: Sha256


class EmbeddingBatchBound(_PlanMessage):
    message_type: Literal["BOUND"]
    request_sha256: Sha256
    route_record_sha256: Sha256
    batch_request_sha256: Sha256
    resource_profile_sha256: Sha256
    children: tuple[EmbeddingBatchChildBinding, ...] = Field(min_length=1, max_length=32)
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_children(self) -> Self:
        for field in (
            "selection_sha256",
            "workflow_id",
            "step_run_id",
            "native_job_id",
            "native_input_sha256",
        ):
            _require(len({getattr(child, field) for child in self.children}) == len(self.children))
        _hash(self, "record_sha256")
        return self


def validate_embedding_batch_plan_controls(
    request: EmbeddingBatchPlanRequest,
    selection: EmbeddingBatchSelection,
    policy: EmbeddingDeviceRoutingPolicy,
) -> None:
    request = EmbeddingBatchPlanRequest.model_validate(request)
    selection = EmbeddingBatchSelection.model_validate(selection)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    _require(
        request.scope == selection.scope and request.purpose == selection.purpose == policy.purpose
    )
    _require(
        request.selection_sha256 == selection.selection_sha256
        and request.routing_policy_sha256 == policy.policy_sha256
        and request.child_selection_sha256s == selection.child_selection_sha256s
        and selection.recipe.recipe_sha256 == policy.view_recipe_sha256
    )
    _require(
        request.selection_manifest.sha256
        == sha256_bytes(canonical_json_bytes(selection.model_dump(mode="json")))
        and request.routing_policy.sha256
        == sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json")))
    )


def validate_embedding_batch_allocation(
    request: EmbeddingBatchPlanRequest,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
) -> None:
    request = EmbeddingBatchPlanRequest.model_validate(request)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    allocation = EmbeddingBatchAllocation.model_validate(allocation)
    cuda = policy.cuda.backend.backend
    _require(type(cuda) is NativeCudaBackendSelection)
    assert isinstance(cuda, NativeCudaBackendSelection)
    control = allocation.control_request
    _require(
        allocation.request_sha256 == request.request_sha256
        and control.parent_request_sha256 == request.request_sha256
        and control.child_set_sha256 == content_sha256(list(request.child_selection_sha256s))
        and control.routing_policy_sha256 == request.routing_policy_sha256 == policy.policy_sha256
        and control.purpose == request.purpose == policy.purpose
        and control.configuration == cuda.configuration
        and control.receipt_raw_sha256 == cuda.receipt_raw_sha256
    )


def validate_embedding_batch_route_record(
    request: EmbeddingBatchPlanRequest,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
    route: EmbeddingBatchRoute,
) -> None:
    validate_embedding_batch_allocation(request, policy, allocation)
    route = EmbeddingBatchRoute.model_validate(route)
    _require(
        route.request_sha256 == route.observation.request_sha256 == request.request_sha256
        and route.allocation_record_sha256 == allocation.record_sha256
        and route.observation.allocation_attempt_id
        == allocation.control_request.allocation_attempt_id
    )
    validate_embedding_device_route_replay(policy, route.observation, route.decision)


def validate_embedding_batch_binding(
    request: EmbeddingBatchPlanRequest,
    route: EmbeddingBatchRoute,
    bound: EmbeddingBatchBound,
    batch: EmbeddingWorkBatchInput | None = None,
) -> None:
    bound = EmbeddingBatchBound.model_validate(bound)
    _require(
        bound.request_sha256 == request.request_sha256
        and bound.route_record_sha256 == route.record_sha256
        and bound.resource_profile_sha256
        == route.decision.selected.profile.resource_profile.resource_profile_sha256
        and tuple(child.selection_sha256 for child in bound.children)
        == request.child_selection_sha256s
    )
    if batch is not None:
        _require(
            batch.scope == request.scope
            and batch.request_sha256 == bound.batch_request_sha256
            and batch.routing_decision_sha256 == route.decision.decision_sha256
            and batch.resource_profile_sha256 == bound.resource_profile_sha256
            and tuple(child.request.request_sha256 for child in batch.children)
            == tuple(child.native_input_sha256 for child in bound.children)
            and tuple(child.request.job_id for child in batch.children)
            == tuple(child.native_job_id for child in bound.children)
        )


def embedding_batch_query_key(request: EmbeddingBatchPlanRequest, ordinal: int) -> str:
    """Immutable parent→QUERY relationship in the existing unique Workflow key.

    This is identity, not authority. Reusing another parent's allocated Workflow
    is rejected before a native Job exists, without another registry or table.
    """
    request = EmbeddingBatchPlanRequest.model_validate(request)
    _require(
        request.purpose == "REFERENCE_QUERY"
        and type(ordinal) is int
        and 0 <= ordinal < len(request.child_selection_sha256s)
    )
    return "embedding-batch-query:" + content_sha256(
        {"parent_request_sha256": request.request_sha256, "child_ordinal": ordinal}
    ).removeprefix("sha256:")


def validate_embedding_batch_query_context(
    selection: EmbeddingBatchSelection,
    decision: EmbeddingDeviceRoutingDecision,
    ordinal: int,
    request: SupportedReferenceQueryWorkflowRequest,
) -> None:
    """One pure selection/profile closure before compute and on canonical replay.

    Actual Catalog source, original physical allocation and command/lease remain
    independent checks. An input-shaped selection never supplies permission.
    """
    selection = EmbeddingBatchSelection.model_validate(selection)
    decision = EmbeddingDeviceRoutingDecision.model_validate(decision)
    request = parse_supported_reference_query_workflow_request(request)
    context, query, profile = request.context_request, selection.query, decision.selected.profile
    _require(
        selection.purpose == "REFERENCE_QUERY"
        and selection.scope.actor_kind == "OPERATOR"
        and selection.scope.actor_id == request.operator_audit.operator_id
        and query is not None
        and type(ordinal) is int
        and 0 <= ordinal < len(selection.anchors)
    )
    assert query is not None
    indexes = tuple(row.index for row in context.views if row.index is not None)
    _require(
        context.anchor == selection.anchors[ordinal]
        and context.graph_snapshot == selection.graph_snapshot
        and context.policy_revision_id == selection.access_policy_revision_id
        and context.policy_sha256 == selection.scope.access_policy_sha256
        and tuple(row.view for row in context.views) == selection.views
        and context.consumer_purpose == query.consumer_purpose
        and context.topics == query.topics
        and context.unit_ids == query.unit_ids
        and context.maximum_sources == query.maximum_sources
        and context.top_k == query.top_k
        and all(row.recipe == selection.recipe for row in context.views)
        and bool(indexes)
        and all(
            index.storage_partition == selection.scope.storage_partition
            and index.spaces.document == profile.space
            for index in indexes
        )
        and request.resource_profile == profile.resource_profile
        and request.runtime_bundle == profile.runtime_bundle
    )

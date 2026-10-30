"""Public QUERY pointers; existing allocation, route, lease and numeric frames remain intact."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_model_recipe import same_embedding_payload_recipe
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityPurpose,
    PublicSolutionSimilarityView,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    embedding_batch_plan_schema,
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
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequestV3
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_V14_PROTOCOL = "embedding-batch-plan/1.4"
BATCH_PLAN_V14_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.4"
BATCH_PLAN_V14_SCHEMA_SHA256 = (
    "sha256:f0f44da9655632dc11b23a8656c88049e01f73257818e6a1add22c3e706181b5"
)
BATCH_SELECTION_V14_SCHEMA_REF = BATCH_PLAN_V14_SCHEMA_REF + "#/$defs/selection"


def embedding_batch_public_query_plan_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.4.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    require(
        0 < len(raw) <= MAX_BATCH_PLAN_BYTES and sha256_bytes(raw) == BATCH_PLAN_V14_SCHEMA_SHA256
    )
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return dict(schema)


@lru_cache(maxsize=1)
def embedding_batch_public_query_plan_schema_registry() -> Registry[Any]:
    return local_embedding_admission_schema_registry().with_resources(
        (
            (BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())),
            (
                BATCH_PLAN_V14_SCHEMA_REF,
                Resource.from_contents(embedding_batch_public_query_plan_schema()),
            ),
        )
    )


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        embedding_batch_public_query_plan_schema(),
        registry=embedding_batch_public_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


class _PublicQueryPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.4"]

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


class PublicSolutionBatchQueryOptions(EmbeddingBatchPlanValue):
    consumer_purpose: PublicSolutionSimilarityPurpose
    maximum_sources: int = Field(ge=1, le=16384, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)


class PublicSolutionQueryIndexPair(EmbeddingBatchPlanValue):
    cpu: PublicSolutionSimilarityView
    cuda: PublicSolutionSimilarityView

    @model_validator(mode="after")
    def exact_devices(self) -> Self:
        cpu, cuda = self.cpu.index, self.cuda.index
        require(
            self.cpu.recipe == self.cuda.recipe
            and cpu.storage_partition == cuda.storage_partition
            and cpu.spaces.document.runtime.device == "CPU"
            and cuda.spaces.document.runtime.device == "CUDA"
            and cpu.spaces.document.runtime.execution_runtime_sha256
            != cuda.spaces.document.runtime.execution_runtime_sha256
            and cpu.spaces.document.space_sha256 != cuda.spaces.document.space_sha256
            and same_embedding_payload_recipe(
                cpu.spaces.document.model_spec, cuda.spaces.document.model_spec
            )
            and cpu.index_id != cuda.index_id
            and cpu.index_revision_id != cuda.index_revision_id
            and (cpu.index_manifest.artifact_id, cpu.index_manifest.artifact_revision_id)
            != (cuda.index_manifest.artifact_id, cuda.index_manifest.artifact_revision_id)
        )
        return self

    def select(self, device: Literal["CPU", "CUDA"]) -> PublicSolutionSimilarityView:
        require(device in {"CPU", "CUDA"})
        return self.cpu if device == "CPU" else self.cuda


class EmbeddingBatchSelectionV14(_PublicQueryPlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["REFERENCE_QUERY"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[PublicSolutionSourceReference, ...] = Field(min_length=1, max_length=32)
    recipe: PublicSolutionEmbeddingRecipe
    views: tuple[Literal["CONCRETE_FACETS"], ...] = Field(min_length=1, max_length=1)
    query: PublicSolutionBatchQueryOptions
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    index_pairs: tuple[PublicSolutionQueryIndexPair, ...] = Field(min_length=1, max_length=1)
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        require(
            self.scope.actor_kind == "OPERATOR"
            and len({a.source.item_revision_id for a in self.anchors}) == len(self.anchors)
            and self.source_classes == tuple(sorted(set(self.source_classes)))
            and all(a.source.source_class in self.source_classes for a in self.anchors)
            and self.graph_snapshot.manifest_sha256 == self.graph_snapshot.manifest_artifact.sha256
            and all(
                view.recipe == self.recipe
                and view.index.storage_partition == self.scope.storage_partition
                for pair in self.index_pairs
                for view in (pair.cpu, pair.cuda)
            )
        )
        validate_embedding_batch_value_hash(self, "selection_sha256")
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        return tuple(
            content_sha256({"selection_sha256": self.selection_sha256, "child": ordinal})
            for ordinal in range(len(self.anchors))
        )

    def selected_views(
        self, device: Literal["CPU", "CUDA"]
    ) -> tuple[PublicSolutionSimilarityView, ...]:
        return tuple(pair.select(device) for pair in self.index_pairs)


class EmbeddingBatchPlanRequestV14(EmbeddingBatchPlanRequestValues, _PublicQueryPlanMessage):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V14_SCHEMA_REF
    purpose: Literal["REFERENCE_QUERY"]


def validate_public_query_index_controls(
    selection: EmbeddingBatchSelectionV14, policy: EmbeddingDeviceRoutingPolicy
) -> None:
    devices: tuple[Literal["CPU", "CUDA"], ...] = ("CPU", "CUDA")
    for device, profile in zip(devices, (policy.cpu.profile, policy.cuda.profile), strict=True):
        require(
            all(
                view.index.spaces.document == profile.space
                for view in selection.selected_views(device)
            )
        )


def validate_public_batch_query_context(
    selection: EmbeddingBatchSelectionV14,
    decision: EmbeddingDeviceRoutingDecision,
    ordinal: int,
    request: ReferenceQueryWorkflowRequestV3,
) -> None:
    context, query, profile = request.context_request, selection.query, decision.selected.profile
    require(type(ordinal) is int and 0 <= ordinal < len(selection.anchors))
    require(
        selection.scope.actor_kind == "OPERATOR"
        and selection.scope.actor_id == request.operator_audit.operator_id
        and context.anchor == selection.anchors[ordinal]
        and context.graph_snapshot == selection.graph_snapshot
        and context.policy_revision_id == selection.access_policy_revision_id
        and context.policy_sha256 == selection.scope.access_policy_sha256
        and context.views == selection.selected_views(decision.selected.backend.device)
        and context.source_classes == selection.source_classes
        and context.consumer_purpose == query.consumer_purpose
        and context.maximum_sources == query.maximum_sources
        and context.top_k == query.top_k
        and all(
            row.recipe == selection.recipe and row.index.spaces.document == profile.space
            for row in context.views
        )
        and request.resource_profile == profile.resource_profile
        and request.runtime_bundle == profile.runtime_bundle
    )

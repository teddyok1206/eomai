"""Registered public QUERY source pins; unchanged routing, lease and numerical contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionReferenceV4,
    PublicSolutionSimilarityViewV4,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_workflow.embedding_batch_plan import MAX_BATCH_PLAN_BYTES
from eom_workflow.embedding_batch_plan_v14 import (
    PublicSolutionBatchQueryOptions,
    embedding_batch_public_query_plan_schema_registry,
    validate_public_query_index_pair_values,
    validate_public_query_selection_values,
)
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
)
from eom_workflow.embedding_batch_plan_values import (
    require_embedding_batch_plan_value as require,
)

BATCH_PLAN_V15_PROTOCOL = "embedding-batch-plan/1.5"
BATCH_PLAN_V15_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.5"
BATCH_PLAN_V15_SCHEMA_SHA256 = (
    "sha256:b5eb531bfb9011ec88d80076c92ae2ea4e6e659842608d7a81fc8557e0306bee"
)
BATCH_SELECTION_V15_SCHEMA_REF = BATCH_PLAN_V15_SCHEMA_REF + "#/$defs/selection"


def embedding_batch_registered_public_query_plan_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.5.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    require(
        0 < len(raw) <= MAX_BATCH_PLAN_BYTES and sha256_bytes(raw) == BATCH_PLAN_V15_SCHEMA_SHA256
    )
    schema = json.loads(raw)
    require(schema.get("$id") == BATCH_PLAN_V15_SCHEMA_REF)
    Draft202012Validator.check_schema(schema)
    return dict(schema)


@lru_cache(maxsize=1)
def embedding_batch_registered_public_query_plan_schema_registry() -> Registry[Any]:
    return embedding_batch_public_query_plan_schema_registry().with_resources(
        (
            (
                BATCH_PLAN_V15_SCHEMA_REF,
                Resource.from_contents(embedding_batch_registered_public_query_plan_schema()),
            ),
        )
    )


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        embedding_batch_registered_public_query_plan_schema(),
        registry=embedding_batch_registered_public_query_plan_schema_registry(),
        format_checker=FormatChecker(),
    )


class _RegisteredPublicQueryPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.5"]

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


class RegisteredPublicSolutionQueryIndexPair(EmbeddingBatchPlanValue):
    cpu: PublicSolutionSimilarityViewV4
    cuda: PublicSolutionSimilarityViewV4

    @model_validator(mode="after")
    def exact_devices(self) -> Self:
        validate_public_query_index_pair_values(self.cpu, self.cuda)
        return self

    def select(self, device: Literal["CPU", "CUDA"]) -> PublicSolutionSimilarityViewV4:
        require(device in {"CPU", "CUDA"})
        return self.cpu if device == "CPU" else self.cuda


class EmbeddingBatchSelectionV15(_RegisteredPublicQueryPlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["REFERENCE_QUERY"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[PublicSolutionReferenceV4, ...] = Field(min_length=1, max_length=32)
    recipe: PublicSolutionEmbeddingRecipe
    views: tuple[Literal["CONCRETE_FACETS"], ...] = Field(min_length=1, max_length=1)
    query: PublicSolutionBatchQueryOptions
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    index_pairs: tuple[RegisteredPublicSolutionQueryIndexPair, ...] = Field(
        min_length=1, max_length=1
    )
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        validate_public_query_selection_values(self)
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        return tuple(
            content_sha256({"selection_sha256": self.selection_sha256, "child": ordinal})
            for ordinal in range(len(self.anchors))
        )

    def selected_views(
        self, device: Literal["CPU", "CUDA"]
    ) -> tuple[PublicSolutionSimilarityViewV4, ...]:
        return tuple(pair.select(device) for pair in self.index_pairs)


class EmbeddingBatchPlanRequestV15(
    EmbeddingBatchPlanRequestValues, _RegisteredPublicQueryPlanMessage
):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V15_SCHEMA_REF
    purpose: Literal["REFERENCE_QUERY"]

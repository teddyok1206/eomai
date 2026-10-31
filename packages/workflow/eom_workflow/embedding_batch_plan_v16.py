"""Registered public INDEX source pins; no new allocation or numerical protocol."""

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
from eom_catalog_contracts.registered_public_solution_similarity import PublicSolutionReferenceV4
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    embedding_batch_plan_schema,
)
from eom_workflow.embedding_batch_plan_v11 import MAX_BULK_BATCH_SELECTION_BYTES
from eom_workflow.embedding_batch_plan_v13 import validate_public_index_selection_values
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
)
from eom_workflow.embedding_batch_plan_values import (
    require_embedding_batch_plan_value as require,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_V16_PROTOCOL = "embedding-batch-plan/1.6"
BATCH_PLAN_V16_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.6"
BATCH_PLAN_V16_SCHEMA_SHA256 = (
    "sha256:dbf2c1cd06f69074ba4247da3765838c5bbe8605cf41a616ebca2d76cf9392a6"
)
BATCH_SELECTION_V16_SCHEMA_REF = BATCH_PLAN_V16_SCHEMA_REF + "#/$defs/selection"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.6.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BULK_BATCH_SELECTION_BYTES + 1)
    require(
        0 < len(raw) <= MAX_BULK_BATCH_SELECTION_BYTES
        and sha256_bytes(raw) == BATCH_PLAN_V16_SCHEMA_SHA256
    )
    schema = json.loads(raw)
    require(schema.get("$id") == BATCH_PLAN_V16_SCHEMA_REF)
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _RegisteredPublicIndexPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.6"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            maximum = (
                MAX_BULK_BATCH_SELECTION_BYTES
                if document.get("message_type") == "SELECTION"
                else MAX_BATCH_PLAN_BYTES
            )
            require(len(canonical_json_bytes(document)) <= maximum)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


class EmbeddingBatchSelectionV16(_RegisteredPublicIndexPlanMessage):
    message_type: Literal["SELECTION"]
    purpose: Literal["INDEX"]
    scope: EmbeddingWorkBatchScope
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    anchors: tuple[PublicSolutionReferenceV4, ...] = Field(min_length=1, max_length=1024)
    recipe: PublicSolutionEmbeddingRecipe
    views: tuple[Literal["CONCRETE_FACETS"], ...] = Field(min_length=1, max_length=1)
    query: None
    selection_sha256: Sha256

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        validate_public_index_selection_values(self)
        return self

    @property
    def child_selection_sha256s(self) -> tuple[str, ...]:
        return (
            content_sha256({"selection_sha256": self.selection_sha256, "child": self.views[0]}),
        )


class EmbeddingBatchPlanRequestV16(
    EmbeddingBatchPlanRequestValues, _RegisteredPublicIndexPlanMessage
):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V16_SCHEMA_REF
    purpose: Literal["INDEX"]
    child_selection_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=1)

"""Finite same-owner staged numerical inputs; no source authority, launch or activation."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSpace,
    IncrementalEmbeddingInput,
    StoragePartition,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256

EMBEDDING_WORK_BATCH_SCHEMA = "embedding-work-batch-input"
EMBEDDING_WORK_BATCH_SCHEMA_REF = "eom://schemas/knowledge/embedding-work-batch-input/1.0"
MAX_EMBEDDING_WORK_BATCH_BYTES = 64 * 1024**2
MAX_EMBEDDING_WORK_BATCH_CHILDREN = 32
MAX_EMBEDDING_WORK_BATCH_ROWS = 1024
MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES = 16 * 1024**2
MAX_EMBEDDING_WORK_BATCH_SECONDS = 180


class _BatchValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class EmbeddingWorkBatchScope(_BatchValue):
    """Exact owner/partition label; an installed source fence must verify every claim."""

    actor_kind: Literal["OPERATOR", "LOCAL_INDEXING_SERVICE"]
    actor_id: ActorId
    storage_partition: StoragePartition
    access_policy_sha256: Sha256
    scope_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> EmbeddingWorkBatchScope:
        if self.scope_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"scope_sha256"})
        ):
            raise ValueError("embedding work batch scope hash differs")
        return self


class EmbeddingWorkBatchChild(_BatchValue):
    scope_sha256: Sha256
    request: Annotated[
        EmbeddingReferenceQueryInputV11 | IncrementalEmbeddingInput,
        Field(discriminator="schema_version"),
    ]

    @property
    def space(self) -> EmbeddingSpace:
        if isinstance(self.request, EmbeddingReferenceQueryInputV11):
            return self.request.spaces.query
        return self.request.space


class EmbeddingWorkBatchInput(_BatchValue):
    """A single materialization scope, not a persistent queue or execution capability."""

    schema_version: Literal["embedding-work-batch-input/1.0"] = "embedding-work-batch-input/1.0"
    purpose: Literal["REFERENCE_QUERY", "DOCUMENT"]
    scope: EmbeddingWorkBatchScope
    routing_decision_sha256: Sha256
    resource_profile_sha256: Sha256
    timeout_seconds: int = Field(ge=1, le=MAX_EMBEDDING_WORK_BATCH_SECONDS, strict=True)
    vector_max_bytes: int = Field(ge=4, le=MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES, strict=True)
    children: tuple[EmbeddingWorkBatchChild, ...] = Field(
        min_length=1, max_length=MAX_EMBEDDING_WORK_BATCH_CHILDREN
    )
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, EMBEDDING_WORK_BATCH_SCHEMA, MAX_EMBEDDING_WORK_BATCH_BYTES
        )

    @model_validator(mode="after")
    def exact_children(self) -> EmbeddingWorkBatchInput:
        first = self.children[0]
        job_ids: set[str] = set()
        request_hashes: set[str] = set()
        query_ids: set[str] = set()
        total_rows = 0
        for child in self.children:
            request = child.request
            is_query = isinstance(request, EmbeddingReferenceQueryInputV11)
            if (
                is_query != (self.purpose == "REFERENCE_QUERY")
                or child.scope_sha256 != self.scope.scope_sha256
                or child.space != first.space
                or request.batch_size != first.request.batch_size
                or request.threads != first.request.threads
                or any(
                    row.encoding.storage_partition != self.scope.storage_partition
                    for row in request.rows
                )
                or request.job_id in job_ids
                or request.request_sha256 in request_hashes
            ):
                raise ValueError("embedding work batch child scope, recipe or identity differs")
            if isinstance(request, EmbeddingReferenceQueryInputV11):
                first_query = first.request
                if (
                    not isinstance(first_query, EmbeddingReferenceQueryInputV11)
                    or request.recipe != first_query.recipe
                    or request.spaces != first_query.spaces
                    or request.query_request_id in query_ids
                ):
                    raise ValueError("embedding work batch query recipe or identity differs")
                query_ids.add(request.query_request_id)
            job_ids.add(request.job_id)
            request_hashes.add(request.request_sha256)
            total_rows += len(request.rows)
        if (
            total_rows > MAX_EMBEDDING_WORK_BATCH_ROWS
            or self.expected_vector_bytes > self.vector_max_bytes
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("embedding work batch row/output bound or request hash differs")
        return self

    @property
    def expected_vector_bytes(self) -> int:
        return sum(
            len(child.request.rows) * child.space.model_spec.dimension * 4
            for child in self.children
        )


def parse_embedding_work_batch_input(value: object) -> EmbeddingWorkBatchInput:
    return EmbeddingWorkBatchInput.model_validate(value)

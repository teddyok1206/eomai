"""Local batch output ranges; exact child results stay canonical and independently owned."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    EmbeddingReferenceQueryResult,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_BYTES,
    MAX_EMBEDDING_WORK_BATCH_CHILDREN,
    MAX_EMBEDDING_WORK_BATCH_ROWS,
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingBinaryMember,
    IncrementalEmbeddingResult,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

EMBEDDING_WORK_BATCH_RESULT_SCHEMA = "embedding-work-batch-result"
EMBEDDING_WORK_BATCH_RESULT_REF = "eom://schemas/knowledge/embedding-work-batch-result/1.0"
type EmbeddingWorkChildResult = EmbeddingReferenceQueryResult | IncrementalEmbeddingResult


class _ResultValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class EmbeddingWorkBatchChildResult(_ResultValue):
    vector_offset: int = Field(ge=0, le=16 * 1024**2 - 4, strict=True)
    result: Annotated[
        EmbeddingReferenceQueryResult | IncrementalEmbeddingResult,
        Field(discriminator="schema_version"),
    ]


class EmbeddingWorkBatchResult(_ResultValue):
    schema_version: Literal["embedding-work-batch-result/1.0"] = "embedding-work-batch-result/1.0"
    purpose: Literal["REFERENCE_QUERY", "DOCUMENT"]
    request_sha256: Sha256
    routing_decision_sha256: Sha256
    children: tuple[EmbeddingWorkBatchChildResult, ...] = Field(
        min_length=1, max_length=MAX_EMBEDDING_WORK_BATCH_CHILDREN
    )
    vectors: EmbeddingBinaryMember
    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, EMBEDDING_WORK_BATCH_RESULT_SCHEMA, MAX_EMBEDDING_WORK_BATCH_BYTES
        )

    @model_validator(mode="after")
    def exact_layout(self) -> EmbeddingWorkBatchResult:
        position = 0
        row_count = 0
        jobs: set[str] = set()
        queries: set[str] = set()
        space = self.children[0].result.shard.space
        for child in self.children:
            result = child.result
            is_query = isinstance(result, EmbeddingReferenceQueryResult)
            if (
                is_query != (self.purpose == "REFERENCE_QUERY")
                or child.vector_offset != position
                or child.vector_offset % 4
                or result.shard.space != space
                or result.job_id in jobs
            ):
                raise ValueError("embedding batch output child identity, space or range differs")
            if isinstance(result, EmbeddingReferenceQueryResult):
                if result.query_request_id in queries:
                    raise ValueError("embedding batch output duplicates query identity")
                queries.add(result.query_request_id)
            jobs.add(result.job_id)
            position += result.shard.binary.byte_count
            row_count += result.shard.row_count
        if (
            row_count > MAX_EMBEDDING_WORK_BATCH_ROWS
            or position != self.vectors.byte_count
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("embedding batch output size, row bound or canonical hash differs")
        return self


def parse_embedding_work_batch_result(value: object) -> EmbeddingWorkBatchResult:
    return EmbeddingWorkBatchResult.model_validate(value)


def validate_embedding_work_batch_result(
    request: EmbeddingWorkBatchInput, result: EmbeddingWorkBatchResult
) -> None:
    """Exact original input closure, never substitute an uncommitted child or another route."""
    request = parse_embedding_work_batch_input(request)
    result = parse_embedding_work_batch_result(result)
    if (
        request.request_sha256 != result.request_sha256
        or request.routing_decision_sha256 != result.routing_decision_sha256
        or request.purpose != result.purpose
        or request.expected_vector_bytes != result.vectors.byte_count
        or len(request.children) != len(result.children)
    ):
        raise ValueError("embedding batch output differs from its pinned request")
    for source, output in zip(request.children, result.children, strict=True):
        if isinstance(source.request, EmbeddingReferenceQueryInputV11):
            if not isinstance(output.result, EmbeddingReferenceQueryResult):
                raise ValueError("embedding batch output child purpose differs")
            validate_reference_query_result_v11(source.request, output.result)
        else:
            if not isinstance(output.result, IncrementalEmbeddingResult):
                raise ValueError("embedding batch output child purpose differs")
            validate_incremental_embedding_result(source.request, output.result)


def build_embedding_work_batch_result(
    request: EmbeddingWorkBatchInput,
    children: tuple[EmbeddingWorkChildResult, ...],
    vectors_sha256: str,
) -> EmbeddingWorkBatchResult:
    """Build only metadata; actual binary hashing/validation belongs to the FD adapter."""
    request = parse_embedding_work_batch_input(request)
    if type(children) is not tuple or not 1 <= len(children) <= MAX_EMBEDDING_WORK_BATCH_CHILDREN:
        raise ValueError("embedding batch output child bound differs")
    position = 0
    outputs = []
    for child in children:
        outputs.append({"vector_offset": position, "result": raw_similarity_contract_value(child)})
        position += child.shard.binary.byte_count
    binary = EmbeddingBinaryMember(sha256=vectors_sha256, byte_count=position)
    body = {
        "schema_version": "embedding-work-batch-result/1.0",
        "purpose": request.purpose,
        "request_sha256": request.request_sha256,
        "routing_decision_sha256": request.routing_decision_sha256,
        "children": outputs,
        "vectors": binary.model_dump(mode="json"),
    }
    result = parse_embedding_work_batch_result(body | {"result_sha256": content_sha256(body)})
    validate_embedding_work_batch_result(request, result)
    return result


def embedding_work_batch_result_bytes(result: EmbeddingWorkBatchResult) -> bytes:
    return canonical_json_bytes(parse_embedding_work_batch_result(result).model_dump(mode="json"))

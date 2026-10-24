"""Owner-local immutable binary validation, never source resolution or Artifact commit."""

from __future__ import annotations

from eom_identifiers import sha256_bytes

from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
    EmbeddingWorkBatchInput,
)
from eom_catalog_contracts.embedding_work_batch_result import (
    EmbeddingWorkBatchResult,
    parse_embedding_work_batch_result,
    validate_embedding_work_batch_result,
)


def validate_embedding_work_batch_binary(
    request: EmbeddingWorkBatchInput,
    result: EmbeddingWorkBatchResult,
    payload: bytes,
) -> tuple[memoryview, ...]:
    """Return read-only child ranges sharing one explicitly materialized local buffer.

    Source/access/lifecycle and FD identity checks belong to the official owner. This
    boundary checks exact request closure, whole/child hashes, shape and unit norm.
    Existing per-child FLOAT32 validation uses temporary child bytes; returned ranges
    retain no duplicate payload or mutable canonical object and never enter DB rows.
    """
    if type(payload) is not bytes or not 4 <= len(payload) <= MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_LENGTH_MISMATCH")
    result = parse_embedding_work_batch_result(result)
    validate_embedding_work_batch_result(request, result)
    if len(payload) != result.vectors.byte_count:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_LENGTH_MISMATCH")
    if sha256_bytes(payload) != result.vectors.sha256:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_HASH_MISMATCH")
    buffer = memoryview(payload)
    ranges: list[memoryview] = []
    for child in result.children:
        shard = child.result.shard
        view = buffer[child.vector_offset : child.vector_offset + shard.binary.byte_count]
        read_unit_vectors(
            view.tobytes(),
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=shard.binary.sha256,
        )
        ranges.append(view)
    return tuple(ranges)

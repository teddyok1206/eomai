"""Build a typed native result from the exact admitted input and actual backend."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingBinaryMember,
    EmbeddingEncodingIdentity,
    EmbeddingExecutionRuntime,
    EmbeddingSpace,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_incremental_embedding_input,
    validate_incremental_embedding_result,
)
from eom_identifiers import content_sha256, sha256_bytes

from eom_catalog_service.embedding_execution_ports import (
    EncodedEmbeddingBatch,
    EncodedReferenceQueryBatch,
    NativeEmbeddingBackend,
)


class IncrementalEmbeddingEncodeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReferenceQueryEmbeddingEncodeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _actual_backend_mismatch(
    space: EmbeddingSpace, batch_size: int, threads: int, backend: NativeEmbeddingBackend
) -> Literal["MODEL_MISMATCH", "RUNTIME_MISMATCH", "RECIPE_MISMATCH"] | None:
    provenance = backend.provenance
    actual_dimension = backend.dimension
    actual_runtime = EmbeddingExecutionRuntime.model_validate(
        backend.execution_runtime.model_dump(mode="json")
    )
    if (
        provenance.kind != "PINNED_MODEL"
        or provenance.model_spec != space.model_spec
        or type(actual_dimension) is not int
        or actual_dimension != space.model_spec.dimension
    ):
        return "MODEL_MISMATCH"
    if actual_runtime != space.runtime:
        return "RUNTIME_MISMATCH"
    actual_batch, actual_threads = backend.batch_size, backend.threads
    if (
        type(actual_batch) is not int
        or type(actual_threads) is not int
        or actual_batch != batch_size
        or actual_threads != threads
    ):
        return "RECIPE_MISMATCH"
    return None


def _require_actual_backend(
    request: IncrementalEmbeddingInput, backend: NativeEmbeddingBackend
) -> None:
    mismatch = _actual_backend_mismatch(request.space, request.batch_size, request.threads, backend)
    if mismatch is not None:
        raise IncrementalEmbeddingEncodeError("INCREMENTAL_EMBEDDING_" + mismatch)


def _require_actual_query_backend(
    request: EmbeddingReferenceQueryInputV11, backend: NativeEmbeddingBackend
) -> None:
    mismatch = _actual_backend_mismatch(
        request.spaces.query, request.batch_size, request.threads, backend
    )
    if mismatch is not None:
        raise ReferenceQueryEmbeddingEncodeError("REFERENCE_QUERY_EMBEDDING_" + mismatch)


def _pack_shard(
    space: EmbeddingSpace,
    rows: tuple[EmbeddingEncodingIdentity, ...],
    input_set_sha256: str,
    vectors: tuple[tuple[float, ...], ...],
) -> tuple[EmbeddingVectorShardManifest, bytes]:
    payload = pack_unit_vectors(vectors, dimension=space.model_spec.dimension)
    member = EmbeddingBinaryMember(sha256=sha256_bytes(payload), byte_count=len(payload))
    shard_body = {
        "schema_version": "embedding-vector-shard/1.0",
        "space": space.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in rows],
        "input_set_sha256": input_set_sha256,
        "binary": member.model_dump(mode="json"),
        "dimension": space.model_spec.dimension,
        "row_count": len(rows),
    }
    shard = EmbeddingVectorShardManifest.model_validate(
        shard_body | {"shard_sha256": content_sha256(shard_body)}
    )
    return shard, payload


def encode_incremental_batch(
    request: IncrementalEmbeddingInput, backend: NativeEmbeddingBackend
) -> EncodedEmbeddingBatch:
    """Encode once in row order; this adapter grants no source rights and commits nothing."""

    request = parse_incremental_embedding_input(request.model_dump(mode="json"))
    _require_actual_backend(request, backend)
    vectors = backend.encode(tuple(row.text for row in request.rows), purpose="DOCUMENT")
    _require_actual_backend(request, backend)
    if len(vectors) != len(request.rows):
        raise IncrementalEmbeddingEncodeError("INCREMENTAL_EMBEDDING_ROW_COUNT_MISMATCH")
    shard, payload = _pack_shard(
        request.space,
        tuple(row.encoding for row in request.rows),
        request.input_set_sha256,
        vectors,
    )
    result_body = {
        "schema_version": "incremental-embedding-result/1.0",
        "job_id": request.job_id,
        "request_sha256": request.request_sha256,
        "input_set_sha256": request.input_set_sha256,
        "shard": shard.model_dump(mode="json"),
    }
    result = IncrementalEmbeddingResult.model_validate(
        result_body | {"result_sha256": content_sha256(result_body)}
    )
    validate_incremental_embedding_result(request, result)
    return EncodedEmbeddingBatch(result, payload)


def encode_reference_query_batch(
    request: EmbeddingReferenceQueryInputV11, backend: NativeEmbeddingBackend
) -> EncodedReferenceQueryBatch:
    """Encode genuine QUERY rows once; no installation, source grant or publication follows."""
    request = parse_embedding_reference_query_input_v11(request)
    _require_actual_query_backend(request, backend)
    vectors = backend.encode(tuple(row.text for row in request.rows), purpose="QUERY")
    _require_actual_query_backend(request, backend)
    if len(vectors) != len(request.rows):
        raise ReferenceQueryEmbeddingEncodeError("REFERENCE_QUERY_EMBEDDING_ROW_COUNT_MISMATCH")
    shard, payload = _pack_shard(
        request.spaces.query,
        tuple(row.encoding for row in request.rows),
        request.input_set_sha256,
        vectors,
    )
    result_body = {
        "schema_version": "embedding-reference-query-result/1.0",
        "job_id": request.job_id,
        "query_request_id": request.query_request_id,
        "context_request_sha256": request.context_request_sha256,
        "request_sha256": request.request_sha256,
        "spaces": request.spaces.model_dump(mode="json"),
        "recipe": request.recipe.model_dump(mode="json"),
        "input_set_sha256": request.input_set_sha256,
        "shard": shard.model_dump(mode="json"),
        "view_rows": [
            {
                "view": row.view,
                "row_index": index,
                "encoding_sha256": row.encoding.encoding_sha256,
            }
            for index, row in enumerate(request.rows)
        ],
    }
    result = EmbeddingReferenceQueryResult.model_validate(
        result_body | {"result_sha256": content_sha256(result_body)}
    )
    validate_reference_query_result_v11(request, result)
    return EncodedReferenceQueryBatch(result, payload)

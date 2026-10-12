"""Build a typed native result from the exact admitted input and actual backend."""

from __future__ import annotations

from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingBinaryMember,
    EmbeddingExecutionRuntime,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_incremental_embedding_input,
    validate_incremental_embedding_result,
)
from eom_identifiers import content_sha256, sha256_bytes

from eom_catalog_service.embedding_execution_ports import (
    EncodedEmbeddingBatch,
    NativeEmbeddingBackend,
)


class IncrementalEmbeddingEncodeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_actual_backend(
    request: IncrementalEmbeddingInput, backend: NativeEmbeddingBackend
) -> None:
    provenance = backend.provenance
    actual_dimension = backend.dimension
    actual_runtime = EmbeddingExecutionRuntime.model_validate(
        backend.execution_runtime.model_dump(mode="json")
    )
    if (
        provenance.kind != "PINNED_MODEL"
        or provenance.model_spec != request.space.model_spec
        or type(actual_dimension) is not int
        or actual_dimension != request.space.model_spec.dimension
    ):
        raise IncrementalEmbeddingEncodeError("INCREMENTAL_EMBEDDING_MODEL_MISMATCH")
    if actual_runtime != request.space.runtime:
        raise IncrementalEmbeddingEncodeError("INCREMENTAL_EMBEDDING_RUNTIME_MISMATCH")


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
    payload = pack_unit_vectors(vectors, dimension=request.space.model_spec.dimension)
    member = EmbeddingBinaryMember(
        sha256=sha256_bytes(payload),
        byte_count=len(payload),
    )
    shard_body = {
        "schema_version": "embedding-vector-shard/1.0",
        "space": request.space.model_dump(mode="json"),
        "rows": [row.encoding.model_dump(mode="json") for row in request.rows],
        "input_set_sha256": request.input_set_sha256,
        "binary": member.model_dump(mode="json"),
        "dimension": request.space.model_spec.dimension,
        "row_count": len(request.rows),
    }
    shard = EmbeddingVectorShardManifest.model_validate(
        shard_body | {"shard_sha256": content_sha256(shard_body)}
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

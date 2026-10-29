"""Shared numerical kernel with a synthetic backend, never installed GPU evidence."""

import pytest
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.public_solution_query import validate_public_solution_query_result
from eom_catalog_service.embedding_encoder_adapter import (
    ReferenceQueryEmbeddingEncodeError,
    encode_public_solution_query,
    encode_reference_query_batch,
)
from eom_identifiers import sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_public_solution_query_contracts import public_query_input


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("creative", [False, True])
def test_public_recipe_uses_one_query_call_and_the_same_native_row_packer(device, creative):
    request = public_query_input(device=device, creative=creative)
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = request.batch_size
    backend.threads = request.threads
    encoded = encode_public_solution_query(request, backend)
    validate_public_solution_query_result(request, encoded.result)
    assert backend.calls == [((request.rows[0].text,), "QUERY")]
    assert encoded.result.schema_version == "embedding-reference-query-result/2.0"
    shard = encoded.result.shard
    assert shard.row_count == 1 and shard.space == request.spaces.query
    assert shard.binary.sha256 == sha256_bytes(encoded.vectors)
    assert (
        read_unit_vectors(
            encoded.vectors,
            dimension=shard.dimension,
            row_count=1,
            expected_sha256=shard.binary.sha256,
        )[0][0]
        == 1.0
    )
    with pytest.raises((ValueError, SchemaError)):
        encode_reference_query_batch(request, backend)
    assert len(backend.calls) == 1


@pytest.mark.parametrize("phase", ["before", "after"])
def test_public_query_keeps_actual_backend_checks_on_both_sides(phase):
    request = public_query_input()
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size, backend.threads = request.batch_size, request.threads
    if phase == "before":
        backend.threads += 1
    else:
        original = backend.encode

        def drift(texts, *, purpose):
            output = original(texts, purpose=purpose)
            backend.threads += 1
            return output

        backend.encode = drift
    with pytest.raises(ReferenceQueryEmbeddingEncodeError, match="MISMATCH"):
        encode_public_solution_query(request, backend)
    assert len(backend.calls) == (1 if phase == "after" else 0)


def test_public_query_never_pads_or_retries_missing_numerical_output():
    request = public_query_input()
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size, backend.threads = request.batch_size, request.threads
    backend.output = ()
    with pytest.raises(ReferenceQueryEmbeddingEncodeError, match="ROW_COUNT_MISMATCH"):
        encode_public_solution_query(request, backend)
    assert len(backend.calls) == 1

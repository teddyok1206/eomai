"""Genuine purpose mechanics over a synthetic backend, never model/runtime admission."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_service.embedding_encoder_adapter import (
    ReferenceQueryEmbeddingEncodeError,
    encode_reference_query_batch,
)
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_space,
    encoding_identity,
    execution_runtime,
    seal,
)
from tests.unit.inference_transfer_fixtures import embedding_model, sha
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_reference_query_v11_contracts import input_body


def test_batch_four_one_partial_row_is_query_without_padding_or_prefix_rewrite() -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4
    encoded = encode_reference_query_batch(request, backend)
    assert backend.calls == [(tuple(row.text for row in request.rows), "QUERY")]
    assert len(request.rows) == encoded.result.shard.row_count == 1
    assert backend.batch_size == 4
    validate_reference_query_result_v11(request, encoded.result)
    assert encoded.result.schema_version == "embedding-reference-query-result/1.0"
    assert encoded.result.shard.space == request.spaces.query
    assert encoded.result.shard.space.purpose != request.spaces.document.purpose
    assert encoded.result.request_sha256 == request.request_sha256
    assert encoded.result.shard.binary.sha256 == sha256_bytes(encoded.vectors)
    assert len(encoded.vectors) == request.spaces.query.model_spec.dimension * 4
    metadata = canonical_json_bytes(encoded.result.model_dump(mode="json"))
    assert encoded.vectors not in metadata and b"vectors.f32" in metadata
    with pytest.raises(FrozenInstanceError):
        field = "vectors"
        setattr(encoded, field, b"other")


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("row_count", [1, 2, 3])
def test_exact_paired_space_shard_and_view_order(
    device: Literal["CPU", "CUDA"], row_count: int
) -> None:
    query = embedding_space(device=device, purpose="QUERY")
    body = input_body(row_count=row_count)
    body["spaces"] = {
        "query": query.model_dump(mode="json"),
        "document": embedding_space(device=device).model_dump(mode="json"),
    }
    for row in body["rows"]:
        row["encoding"] = encoding_identity(row["text"], query).model_dump(mode="json")
    body["rows"].sort(key=lambda row: row["encoding"]["encoding_sha256"])
    body["input_set_sha256"] = content_sha256([row["encoding"] for row in body["rows"]])
    request = parse_embedding_reference_query_input_v11(seal(body, "request_sha256"))
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = request.batch_size
    encoded = encode_reference_query_batch(request, backend)
    validate_reference_query_result_v11(request, encoded.result)
    shard = encoded.result.shard
    rows = read_unit_vectors(
        encoded.vectors,
        dimension=shard.dimension,
        row_count=shard.row_count,
        expected_sha256=shard.binary.sha256,
    )
    assert tuple(row.encoding for row in request.rows) == shard.rows
    assert tuple(row.view for row in request.rows) == tuple(
        row.view for row in encoded.result.view_rows
    )
    assert tuple(row.row_index for row in encoded.result.view_rows) == tuple(range(row_count))
    assert all(rows[row][row] == 1.0 for row in range(row_count))
    assert backend.calls == [(tuple(row.text for row in request.rows), "QUERY")]


@pytest.mark.parametrize("stage", ["BEFORE", "AFTER"])
@pytest.mark.parametrize(
    "fault",
    [
        "dimension",
        "boolean_dimension",
        "test_only",
        "model",
        "device",
        "runtime",
        "batch",
        "boolean_batch",
        "float_batch",
        "threads",
        "boolean_threads",
        "float_threads",
    ],
)
def test_actual_backend_is_checked_before_and_after_one_query(
    monkeypatch: pytest.MonkeyPatch, stage: str, fault: str
) -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4

    def drift() -> None:
        if fault == "dimension":
            backend.dimension += 1
        elif fault == "boolean_dimension":
            backend.dimension = True
        elif fault == "test_only":
            backend.provenance = EmbeddingRankerProvenance("TEST_ONLY", None)
        elif fault == "model":
            backend.provenance = EmbeddingRankerProvenance(
                "PINNED_MODEL", embedding_model("intfloat/multilingual-e5-base")
            )
        elif fault == "device":
            backend.execution_runtime = execution_runtime("CUDA")
        elif fault == "runtime":
            backend.execution_runtime = execution_runtime(fingerprint=sha("b"))
        elif fault == "batch":
            backend.batch_size = 3
        elif fault == "boolean_batch":
            backend.batch_size = True
        elif fault == "float_batch":
            monkeypatch.setattr(backend, "batch_size", 4.0)
        elif fault == "threads":
            backend.threads = 2
        elif fault == "boolean_threads":
            backend.threads = True
        else:
            monkeypatch.setattr(backend, "threads", 1.0)

    if stage == "BEFORE":
        drift()
    else:
        original = backend.encode

        def changed(
            texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
        ) -> tuple[tuple[float, ...], ...]:
            vectors = original(texts, purpose=purpose)
            drift()
            return vectors

        monkeypatch.setattr(backend, "encode", changed)
    with pytest.raises(ReferenceQueryEmbeddingEncodeError, match="MISMATCH"):
        encode_reference_query_batch(request, backend)
    assert len(backend.calls) == (0 if stage == "BEFORE" else 1)


@pytest.mark.parametrize("count", [0, 2, 4])
def test_wrong_result_row_count_is_neither_padded_nor_retried(count: int) -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4
    vector = (1.0,) + (0.0,) * (backend.dimension - 1)
    backend.output = (vector,) * count
    with pytest.raises(ReferenceQueryEmbeddingEncodeError, match="ROW_COUNT_MISMATCH"):
        encode_reference_query_batch(request, backend)
    assert len(backend.calls) == 1


@pytest.mark.parametrize("value", [2.0, float("nan"), float("inf"), True])
def test_authoritative_codec_rejects_invalid_vectors_without_renormalization(value: Any) -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4
    backend.output = ((value,) + (0.0,) * (backend.dimension - 1),)
    with pytest.raises(EmbeddingVectorBinaryError):
        encode_reference_query_batch(request, backend)
    assert len(backend.calls) == 1


def test_raw_copy_hash_authority_or_boolean_corruption_precedes_any_backend_call() -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4
    for copied in (
        request.model_copy(update={"request_sha256": sha("b")}),
        request.model_copy(update={"batch_size": True}),
        request.model_copy(update={"authority": "ADMIN"}),
        request.model_copy(
            update={"spaces": request.spaces.model_copy(update={"query": request.spaces.document})}
        ),
    ):
        with pytest.raises((ValueError, SchemaError)):
            encode_reference_query_batch(copied, backend)
    assert not backend.calls


def test_query_purpose_is_not_inferred_from_equal_prefix_strings() -> None:
    request = parse_embedding_reference_query_input_v11(input_body())
    spec = request.spaces.query.model_spec
    assert spec.query_prefix == spec.document_prefix
    backend = SyntheticNativeBackend(request.spaces.query)
    backend.batch_size = 4
    encode_reference_query_batch(request, backend)
    assert backend.calls[0][0] == tuple(row.text for row in request.rows)
    # The actual backend owns prefix/tokenization; this fake proves only the fixed QUERY argument.
    assert backend.calls[0][1] == "QUERY"

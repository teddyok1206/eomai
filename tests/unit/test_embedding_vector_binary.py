from __future__ import annotations

import math
import struct
from typing import Any

import pytest
from eom_catalog_contracts.embedding_vector_binary import (
    MAX_VECTOR_DIMENSION,
    MAX_VECTOR_ROWS,
    EmbeddingVectorBinaryError,
    pack_unit_vectors,
    read_unit_vectors,
    validate_unit_vector,
)
from eom_identifiers import sha256_bytes


@pytest.mark.parametrize("dimension", (False, True, 0, -1, 4097, 2.0))
def test_materialized_row_validation_keeps_the_same_bounded_shape_rule(dimension: Any) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="SHAPE_INVALID"):
        validate_unit_vector((1.0, 0.0), dimension)


def test_materialized_row_validation_neither_normalizes_nor_copies_binary() -> None:
    values = (0.6, 0.8)
    assert validate_unit_vector(values, 2) is None
    assert values == (0.6, 0.8)
    with pytest.raises(EmbeddingVectorBinaryError, match="NORM_INVALID"):
        validate_unit_vector((3.0, 4.0), 2)


def read(
    payload: bytes, *, dimension: int = 2, row_count: int = 1
) -> tuple[tuple[float, ...], ...]:
    return read_unit_vectors(
        payload,
        dimension=dimension,
        row_count=row_count,
        expected_sha256=sha256_bytes(payload),
    )


def test_row_major_float32_little_endian_round_trip_preserves_order() -> None:
    vectors = ((1.0, 0.0), (0.0, -1.0))
    payload = pack_unit_vectors(vectors, dimension=2)
    assert payload == struct.pack("<4f", 1.0, 0.0, 0.0, -1.0)
    assert read(payload, row_count=2) == vectors
    assert pack_unit_vectors(vectors, dimension=2) == payload


def test_float32_rounding_is_accepted_without_renormalizing_the_stored_values() -> None:
    value = 1.0 / math.sqrt(3.0)
    payload = pack_unit_vectors(((value, value, value),), dimension=3)
    stored = read(payload, dimension=3)
    assert stored == (struct.unpack("<3f", payload),)
    assert stored[0] != (value, value, value)
    assert abs(math.hypot(*stored[0]) - 1.0) < 1e-5


def test_exact_raw_member_hash_is_required() -> None:
    payload = pack_unit_vectors(((1.0, 0.0),), dimension=2)
    with pytest.raises(EmbeddingVectorBinaryError, match="HASH_MISMATCH"):
        read_unit_vectors(payload, dimension=2, row_count=1, expected_sha256="sha256:" + "0" * 64)


@pytest.mark.parametrize("payload", [b"", struct.pack("<f", 1.0), struct.pack("<3f", 1, 0, 0)])
def test_truncated_or_extra_bytes_are_not_silently_ignored(payload: bytes) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="LENGTH_MISMATCH"):
        read(payload)


@pytest.mark.parametrize("dimension", [True, 0, -1, 1.5, "2", MAX_VECTOR_DIMENSION + 1])
def test_dimension_is_strict_and_bounded(dimension: Any) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="SHAPE_INVALID"):
        pack_unit_vectors(((1.0, 0.0),), dimension=dimension)
    with pytest.raises(EmbeddingVectorBinaryError, match="SHAPE_INVALID"):
        read(b"", dimension=dimension)


@pytest.mark.parametrize("row_count", [True, 0, -1, 1.5, "1", MAX_VECTOR_ROWS + 1])
def test_row_count_is_strict_and_bounded(row_count: Any) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="SHAPE_INVALID"):
        read(b"", row_count=row_count)


@pytest.mark.parametrize(
    "vector",
    [(0.0, 0.0), (2.0, 0.0), (1.01, 0.0), (float("nan"), 0.0), (float("inf"), 0.0)],
)
def test_invalid_input_rows_are_rejected_not_normalized(vector: tuple[float, ...]) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match=r"(VALUE|NORM)_INVALID"):
        pack_unit_vectors((vector,), dimension=2)


@pytest.mark.parametrize(
    "vector", [(0.0, 0.0), (2.0, 0.0), (float("nan"), 0.0), (float("inf"), 0.0)]
)
def test_hash_matching_corrupt_stored_rows_are_still_rejected(vector: tuple[float, ...]) -> None:
    payload = struct.pack("<2f", *vector)
    with pytest.raises(EmbeddingVectorBinaryError, match=r"(VALUE|NORM)_INVALID"):
        read(payload)


@pytest.mark.parametrize("vector", [(True, 0.0), (1.0,), [1.0, 0.0]])
def test_input_rows_are_not_coerced(vector: Any) -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="VALUE_INVALID"):
        pack_unit_vectors((vector,), dimension=2)


def test_empty_shards_and_non_tuple_inputs_are_not_valid_artifacts() -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="SHAPE_INVALID"):
        pack_unit_vectors((), dimension=2)
    with pytest.raises(EmbeddingVectorBinaryError, match="VALUE_INVALID"):
        pack_unit_vectors([(1.0, 0.0)], dimension=2)  # type: ignore[arg-type]


def test_big_endian_input_is_not_repaired_into_little_endian() -> None:
    payload = struct.pack(">2f", 1.0, 0.0)
    with pytest.raises(EmbeddingVectorBinaryError, match="NORM_INVALID"):
        read(payload)


def test_replacing_binary_with_json_is_not_supported() -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="LENGTH_MISMATCH"):
        read(b"[1, 0]")


def test_bool_or_large_integer_does_not_escape_as_an_arithmetic_exception() -> None:
    with pytest.raises(EmbeddingVectorBinaryError, match="VALUE_INVALID"):
        pack_unit_vectors(((10**1000, 0),), dimension=2)

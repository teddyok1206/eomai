"""Pure float32-LE format checks shared by native encoders and Artifact owners."""

from __future__ import annotations

import math
import struct

from eom_identifiers import sha256_bytes

MAX_VECTOR_DIMENSION = 4096
MAX_VECTOR_ROWS = 3072
VECTOR_ELEMENT_BYTES = 4
UNIT_NORM_ABSOLUTE_TOLERANCE = 1e-5


class EmbeddingVectorBinaryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_shape(dimension: int, row_count: int) -> int:
    if (
        type(dimension) is not int
        or not 1 <= dimension <= MAX_VECTOR_DIMENSION
        or type(row_count) is not int
        or not 1 <= row_count <= MAX_VECTOR_ROWS
    ):
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_SHAPE_INVALID")
    return dimension * row_count * VECTOR_ELEMENT_BYTES


def validate_unit_vector(vector: tuple[float, ...], dimension: int) -> None:
    """Check an already materialized row without normalization or binary copying."""
    _require_shape(dimension, 1)
    if not isinstance(vector, tuple) or len(vector) != dimension:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_VALUE_INVALID")
    try:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_VALUE_INVALID")
        norm = math.hypot(*vector)
    except OverflowError as exc:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_VALUE_INVALID") from exc
    if not math.isfinite(norm) or abs(norm - 1.0) > UNIT_NORM_ABSOLUTE_TOLERANCE:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_NORM_INVALID")


def pack_unit_vectors(vectors: tuple[tuple[float, ...], ...], *, dimension: int) -> bytes:
    """Serialize already-normalized rows; never normalize or change their order."""

    if not isinstance(vectors, tuple):
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_VALUE_INVALID")
    expected_bytes = _require_shape(dimension, len(vectors))
    row_codec = struct.Struct(f"<{dimension}f")
    payload = bytearray(expected_bytes)
    for ordinal, vector in enumerate(vectors):
        validate_unit_vector(vector, dimension)
        try:
            row_codec.pack_into(payload, ordinal * row_codec.size, *vector)
        except (struct.error, OverflowError) as exc:
            raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_VALUE_INVALID") from exc
        # The durable values are float32, not the higher precision input values.
        validate_unit_vector(row_codec.unpack_from(payload, ordinal * row_codec.size), dimension)
    return bytes(payload)


def read_unit_vectors(
    payload: bytes,
    *,
    dimension: int,
    row_count: int,
    expected_sha256: str,
) -> tuple[tuple[float, ...], ...]:
    """Validate bytes once at the materialization boundary; do not repair stored rows."""

    expected_bytes = _require_shape(dimension, row_count)
    if not isinstance(payload, bytes) or len(payload) != expected_bytes:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_LENGTH_MISMATCH")
    if sha256_bytes(payload) != expected_sha256:
        raise EmbeddingVectorBinaryError("EMBEDDING_VECTOR_HASH_MISMATCH")
    rows = tuple(struct.iter_unpack(f"<{dimension}f", payload))
    for vector in rows:
        validate_unit_vector(vector, dimension)
    return rows

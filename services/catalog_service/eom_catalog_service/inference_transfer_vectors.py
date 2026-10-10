"""Shared pure vector validation and exact ordering, independent of numerical runtimes."""

from __future__ import annotations

import math

from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer

from eom_catalog_service.inference_transfer_ports import ScoredInferenceTransferProfile


def normalized_vector(vector: tuple[float, ...], dimension: int) -> tuple[float, ...]:
    if (
        not isinstance(vector, tuple)
        or len(vector) != dimension
        or any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            for value in vector
        )
    ):
        raise ValueError("LOCAL_EMBEDDING_VECTOR_INVALID")
    norm = math.hypot(*vector)
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("LOCAL_EMBEDDING_VECTOR_INVALID")
    result = tuple(value / norm for value in vector)
    if any(not math.isfinite(value) for value in result):
        raise ValueError("LOCAL_EMBEDDING_VECTOR_INVALID")
    return result


def rank_normalized_vectors(
    query: tuple[float, ...],
    candidates: tuple[tuple[InferenceTransferProfilePointer, tuple[float, ...]], ...],
    *,
    top_k: int,
) -> tuple[ScoredInferenceTransferProfile, ...]:
    """Caller normalizes once; ties use exact refs rather than rounded wire scores."""
    scores = tuple(
        ScoredInferenceTransferProfile(
            pointer,
            max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(query, vector, strict=True)))),
        )
        for pointer, vector in candidates
    )
    return tuple(
        sorted(
            scores,
            key=lambda row: (
                -row.cosine_similarity,
                row.profile.profile_id,
                row.profile.profile_revision_id,
                row.profile.profile_sha256,
            ),
        )[:top_k]
    )

"""Shared pure vector validation and exact ordering, independent of numerical runtimes."""

from __future__ import annotations

import math
from typing import Protocol

from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer

from eom_catalog_service.inference_transfer_ports import ScoredInferenceTransferProfile


class RankedProfileIdentity(Protocol):
    @property
    def profile_id(self) -> str: ...

    @property
    def profile_revision_id(self) -> str: ...

    @property
    def profile_sha256(self) -> str: ...


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


def normalized_cosine_similarity(query: tuple[float, ...], vector: tuple[float, ...]) -> float:
    """One exact scalar rule; callers validate and normalize at their input boundary."""
    return max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(query, vector, strict=True))))


def rank_normalized_vectors(
    query: tuple[float, ...],
    candidates: tuple[tuple[InferenceTransferProfilePointer, tuple[float, ...]], ...],
    *,
    top_k: int,
) -> tuple[ScoredInferenceTransferProfile, ...]:
    """Caller normalizes once; ties use exact refs rather than rounded wire scores."""
    return tuple(
        ScoredInferenceTransferProfile(pointer, score)
        for pointer, score in rank_normalized_values(query, candidates, top_k=top_k)
    )


def rank_normalized_values[Profile: RankedProfileIdentity](
    query: tuple[float, ...],
    candidates: tuple[tuple[Profile, tuple[float, ...]], ...],
    *,
    top_k: int,
) -> tuple[tuple[Profile, float], ...]:
    """Same exact score/tie rule for genuine profile1 and registered-review profile2."""
    scores = tuple(
        (pointer, normalized_cosine_similarity(query, vector)) for pointer, vector in candidates
    )
    return tuple(
        sorted(
            scores,
            key=lambda row: (
                -row[1],
                row[0].profile_id,
                row[0].profile_revision_id,
                row[0].profile_sha256,
            ),
        )[:top_k]
    )

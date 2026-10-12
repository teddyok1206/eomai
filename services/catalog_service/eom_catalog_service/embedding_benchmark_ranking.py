"""Bounded real-row ranking and CPU-only complete-span clusters; no IO or authority.

Artifact owners validate f32 bytes, hashes and purpose/space associations before calling.
The CPU owner seals these clusters before accepting CUDA output. This module cannot
prove when that happened, admit a runtime or establish actual source permissions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkRowRef, benchmark_row_key
from eom_catalog_contracts.embedding_vector_binary import UNIT_NORM_ABSOLUTE_TOLERANCE
from eom_catalog_contracts.inference_transfer_experiment import profile_key

from eom_catalog_service.inference_transfer_vectors import normalized_cosine_similarity

CPU_NEAR_TIE_MAX_SPAN = 4e-5
_DIMENSION = 1024


@dataclass(frozen=True, slots=True)
class ScoredBenchmarkRow:
    """Local exact score; durable float64 evidence remains an owner Artifact member."""

    row: BenchmarkRowRef
    cosine_similarity: float


def _unit_vector(vector: tuple[float, ...]) -> None:
    if (
        type(vector) is not tuple
        or len(vector) != _DIMENSION
        or any(type(value) is not float or not math.isfinite(value) for value in vector)
        or abs(math.hypot(*vector) - 1.0) > UNIT_NORM_ABSOLUTE_TOLERANCE
    ):
        raise ValueError("EMBEDDING_BENCHMARK_VECTOR_INVALID")


def rank_benchmark_rows(
    query_row: BenchmarkRowRef,
    query_vector: tuple[float, ...],
    candidates: tuple[tuple[BenchmarkRowRef, tuple[float, ...]], ...],
) -> tuple[ScoredBenchmarkRow, ...]:
    """Full exact rank, excluding every view of the query's real profile, never a fake ID.

    At most18 rows: O(Nd + N log N), one validation/score per row. Caller chooses
    top5 from the complete result only after the independently sealed CPU clusters.
    """
    query = BenchmarkRowRef.model_validate(query_row)
    if query.purpose != "QUERY" or type(candidates) is not tuple or not 6 <= len(candidates) <= 18:
        raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
    _unit_vector(query_vector)
    rows: list[tuple[BenchmarkRowRef, tuple[float, ...]]] = []
    keys: set[tuple[str, str, str, str, str]] = set()
    views: set[tuple[str, str, str, str]] = set()
    profiles: set[tuple[str, str, str]] = set()
    all_profiles: set[tuple[str, str, str]] = set()
    query_key = profile_key(query.profile)
    for candidate in candidates:
        if type(candidate) is not tuple or len(candidate) != 2:
            raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
        row = BenchmarkRowRef.model_validate(candidate[0])
        key = benchmark_row_key(row)
        view_key = (*profile_key(row.profile), row.view)
        if row.purpose != "DOCUMENT" or key in keys or view_key in views:
            raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
        keys.add(key)
        views.add(view_key)
        all_profiles.add(profile_key(row.profile))
        _unit_vector(candidate[1])
        if profile_key(row.profile) != query_key:
            profiles.add(profile_key(row.profile))
            rows.append((row, candidate[1]))
    if (
        len(profiles) != 5
        or len(all_profiles) != 6
        or len({key[0] for key in all_profiles}) != 6
        or query_key not in all_profiles
    ):
        raise ValueError("EMBEDDING_BENCHMARK_RANK_COVERAGE_INSUFFICIENT")
    scored = (
        ScoredBenchmarkRow(row, normalized_cosine_similarity(query_vector, vector))
        for row, vector in rows
    )
    return tuple(
        sorted(scored, key=lambda value: (-value.cosine_similarity, *benchmark_row_key(value.row)))
    )


def cluster_cpu_benchmark_rows(
    ranked: tuple[ScoredBenchmarkRow, ...],
) -> tuple[tuple[ScoredBenchmarkRow, ...], ...]:
    """Greedy descending complete-span clusters, not transitive close-score chains."""
    if type(ranked) is not tuple or not 5 <= len(ranked) <= 17:
        raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
    keys: set[tuple[str, str, str, str, str]] = set()
    views: set[tuple[str, str, str, str]] = set()
    profiles: set[tuple[str, str, str]] = set()
    previous: tuple[float, str, str, str, str, str] | None = None
    clusters: list[list[ScoredBenchmarkRow]] = []
    for value in ranked:
        if type(value) is not ScoredBenchmarkRow:
            raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
        row = BenchmarkRowRef.model_validate(value.row)
        score = value.cosine_similarity
        if type(score) is not float or not math.isfinite(score) or not -1.0 <= score <= 1.0:
            raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
        key = benchmark_row_key(row)
        view_key = (*profile_key(row.profile), row.view)
        order = (-score, *key)
        if (
            row.purpose != "DOCUMENT"
            or key in keys
            or view_key in views
            or (previous is not None and order < previous)
        ):
            raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
        keys.add(key)
        views.add(view_key)
        profiles.add(profile_key(row.profile))
        previous = order
        if not clusters or clusters[-1][0].cosine_similarity - score > CPU_NEAR_TIE_MAX_SPAN:
            clusters.append([])
        clusters[-1].append(ScoredBenchmarkRow(row, score))
    if len(profiles) != 5 or len({key[0] for key in profiles}) != 5:
        raise ValueError("EMBEDDING_BENCHMARK_RANK_COVERAGE_INSUFFICIENT")
    return tuple(tuple(cluster) for cluster in clusters)

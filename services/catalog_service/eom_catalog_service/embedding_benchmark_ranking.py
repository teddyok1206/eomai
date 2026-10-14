"""Real-row ranking and CPU-reference rank comparison; no IO or authority.

Artifact owners validate f32 bytes, hashes and purpose/space associations before calling.
The CPU owner seals these clusters before accepting CUDA output. This module cannot
prove when that happened, admit a runtime or establish actual source permissions.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkRowRef, benchmark_row_key
from eom_catalog_contracts.embedding_vector_binary import UNIT_NORM_ABSOLUTE_TOLERANCE
from eom_catalog_contracts.inference_transfer_experiment import profile_key

from eom_catalog_service.inference_transfer_vectors import normalized_cosine_similarity

CPU_NEAR_TIE_MAX_SPAN = 4e-5
QUERY_SCORE_ABSOLUTE_TOLERANCE = 2e-5
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


def _validated_ranking(
    ranked: tuple[ScoredBenchmarkRow, ...],
) -> tuple[ScoredBenchmarkRow, ...]:
    """Revalidate local score/reference values without coercion or changing their order."""
    if type(ranked) is not tuple or not 5 <= len(ranked) <= 17:
        raise ValueError("EMBEDDING_BENCHMARK_RANK_INPUT_INVALID")
    keys: set[tuple[str, str, str, str, str]] = set()
    views: set[tuple[str, str, str, str]] = set()
    profiles: set[tuple[str, str, str]] = set()
    previous: tuple[float, str, str, str, str, str] | None = None
    checked = []
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
        checked.append(ScoredBenchmarkRow(row, score))
    if len(profiles) != 5 or len({key[0] for key in profiles}) != 5:
        raise ValueError("EMBEDDING_BENCHMARK_RANK_COVERAGE_INSUFFICIENT")
    return tuple(checked)


def cluster_cpu_benchmark_rows(
    ranked: tuple[ScoredBenchmarkRow, ...],
) -> tuple[tuple[ScoredBenchmarkRow, ...], ...]:
    """Greedy descending complete-span clusters, not transitive close-score chains."""
    clusters: list[list[ScoredBenchmarkRow]] = []
    for value in _validated_ranking(ranked):
        if (
            not clusters
            or clusters[-1][0].cosine_similarity - value.cosine_similarity > CPU_NEAR_TIE_MAX_SPAN
        ):
            clusters.append([])
        clusters[-1].append(value)
    return tuple(tuple(cluster) for cluster in clusters)


@dataclass(frozen=True, slots=True)
class BenchmarkPairOrderObservation:
    """Local exact scalar trace; the owner stores f64 evidence, never JSON float arrays."""

    left_row_sha256: str
    right_row_sha256: str
    cpu_left_score: float
    cpu_right_score: float
    observed_left_score: float
    observed_right_score: float
    gap_class: Literal["WIDE_GAP", "NEAR_TIE", "EXACT_TIE"]
    order_preserved: bool
    top5_same_cluster: bool


@dataclass(frozen=True, slots=True)
class BenchmarkRankComparison:
    """Rank/score arithmetic only, not full numerical validity, admission or device selection."""

    query_score_failures: int
    wide_gap_order_failures: int
    cluster_order_failures: int
    top5_boundary_failures: int
    observations: tuple[BenchmarkPairOrderObservation, ...]

    @property
    def ranks_equivalent_within_tolerance(self) -> bool:
        return not (
            self.query_score_failures
            or self.wide_gap_order_failures
            or self.cluster_order_failures
            or self.top5_boundary_failures
        )


def compare_benchmark_row_rankings(
    cpu_reference: tuple[ScoredBenchmarkRow, ...],
    observed: tuple[ScoredBenchmarkRow, ...],
) -> BenchmarkRankComparison:
    """Compare every real row/pair using only the independently sealed CPU clusters.

    The actual owner must resolve/prove the reference before CUDA and validate all
    vector/token/space/Artifact inputs. This pure leaf cannot establish when scores
    were measured or authorize another execution. It never chooses GPU or a retry.
    """
    clusters = cluster_cpu_benchmark_rows(cpu_reference)
    baseline = tuple(value for cluster in clusters for value in cluster)
    actual = _validated_ranking(observed)
    by_row = {value.row.row_sha256: value for value in actual}
    if (
        len(by_row) != len(actual)
        or len(actual) != len(baseline)
        or any(
            value.row.row_sha256 not in by_row or by_row[value.row.row_sha256].row != value.row
            for value in baseline
        )
    ):
        raise ValueError("EMBEDDING_BENCHMARK_RANK_COVERAGE_INSUFFICIENT")
    positions = {value.row.row_sha256: index for index, value in enumerate(actual)}
    cluster_ids = {
        value.row.row_sha256: ordinal
        for ordinal, cluster in enumerate(clusters)
        for value in cluster
    }
    expected_top = {value.row.row_sha256 for value in baseline[:5]}
    actual_top = {value.row.row_sha256 for value in actual[:5]}
    removed, added = expected_top - actual_top, actual_top - expected_top
    removed_clusters = Counter(cluster_ids[key] for key in removed)
    added_clusters = Counter(cluster_ids[key] for key in added)
    boundary_failures = sum((removed_clusters - added_clusters).values())
    score_failures = sum(
        abs(value.cosine_similarity - by_row[value.row.row_sha256].cosine_similarity)
        > QUERY_SCORE_ABSOLUTE_TOLERANCE
        for value in baseline
    )
    wide_failures = cluster_failures = 0
    observations = []
    for left, right in combinations(baseline, 2):
        left_key, right_key = left.row.row_sha256, right.row.row_sha256
        gap = left.cosine_similarity - right.cosine_similarity
        gap_class: Literal["WIDE_GAP", "NEAR_TIE", "EXACT_TIE"] = (
            "EXACT_TIE" if gap == 0.0 else "WIDE_GAP" if gap > CPU_NEAR_TIE_MAX_SPAN else "NEAR_TIE"
        )
        preserved = positions[left_key] < positions[right_key]
        same_cluster = cluster_ids[left_key] == cluster_ids[right_key]
        wide_failures += int(gap_class == "WIDE_GAP" and not preserved)
        # CPU exact ties have the existing stable-key order, even inside a cluster.
        cluster_failures += int((not same_cluster or gap_class == "EXACT_TIE") and not preserved)
        boundary_pair = (left_key in removed and right_key in added) or (
            left_key in added and right_key in removed
        )
        observations.append(
            BenchmarkPairOrderObservation(
                left_key,
                right_key,
                left.cosine_similarity,
                right.cosine_similarity,
                by_row[left_key].cosine_similarity,
                by_row[right_key].cosine_similarity,
                gap_class,
                preserved,
                not boundary_pair or same_cluster,
            )
        )
    return BenchmarkRankComparison(
        score_failures,
        wide_failures,
        cluster_failures,
        boundary_failures,
        tuple(observations),
    )

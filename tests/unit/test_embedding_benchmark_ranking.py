"""Pure synthetic ranking: no model, source grant, Artifact, clock or GPU execution."""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import pairwise
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkRowRef, benchmark_row_key
from eom_catalog_contracts.inference_transfer_experiment import profile_key
from eom_catalog_service.embedding_benchmark_ranking import (
    CPU_NEAR_TIE_MAX_SPAN,
    QUERY_SCORE_ABSOLUTE_TOLERANCE,
    ScoredBenchmarkRow,
    cluster_cpu_benchmark_rows,
    compare_benchmark_row_rankings,
    rank_benchmark_rows,
)
from eom_catalog_service.inference_transfer_vectors import (
    normalized_cosine_similarity,
    rank_normalized_vectors,
)
from eom_identifiers import content_sha256

from tests.unit.embedding_device_benchmark_fixtures import owner_request
from tests.unit.inference_transfer_embedding_fixtures import seal


def vector(score: float = 1.0) -> tuple[float, ...]:
    return (score, math.sqrt(1.0 - score**2), *((0.0,) * 1022))


def rows() -> tuple[tuple[BenchmarkRowRef, tuple[float, ...]], ...]:
    return tuple((row, vector()) for row in owner_request().document_rows)


def ranked_single_views() -> tuple[ScoredBenchmarkRow, ...]:
    plan = owner_request()
    return tuple(
        ScoredBenchmarkRow(row, 0.0)
        for row in plan.document_rows
        if row.view == "CONTENT_ONLY"
        and profile_key(row.profile) != profile_key(plan.query_rows[0].profile)
    )


def test_full_rank_excludes_all_query_profile_views_and_retains_real_refs() -> None:
    plan = owner_request()
    ranked = rank_benchmark_rows(plan.query_rows[0], vector(), rows())
    assert len(ranked) == 15
    assert len({profile_key(value.row.profile) for value in ranked}) == 5
    assert all(
        profile_key(value.row.profile) != profile_key(plan.query_rows[0].profile)
        for value in ranked
    )
    assert {value.row for value in ranked} <= set(plan.document_rows)
    assert tuple(benchmark_row_key(value.row) for value in ranked) == tuple(
        sorted(benchmark_row_key(value.row) for value in ranked)
    )
    assert rank_benchmark_rows(plan.query_rows[0], vector(), tuple(reversed(rows()))) == ranked


def test_exact_existing_scalar_and_profile_order_rule_is_preserved() -> None:
    plan = owner_request()
    query = vector(0.25)
    candidates = tuple((row, vector(0.7)) for row, _ in rows() if row.view == "CONTENT_ONLY")
    ranked = rank_benchmark_rows(plan.query_rows[0], query, candidates)
    old = rank_normalized_vectors(
        query,
        tuple(
            (row.profile, values)
            for row, values in candidates
            if row.profile != plan.query_rows[0].profile
        ),
        top_k=5,
    )
    assert tuple(value.row.profile for value in ranked) == tuple(value.profile for value in old)
    assert tuple(value.cosine_similarity for value in ranked) == tuple(
        value.cosine_similarity for value in old
    )
    expected = max(
        -1.0, min(1.0, math.fsum(a * b for a, b in zip(query, vector(0.7), strict=True)))
    )
    assert normalized_cosine_similarity(query, vector(0.7)) == expected


def test_duplicate_text_on_distinct_real_profiles_remains_distinct_rows() -> None:
    plan = owner_request()
    shared_text = content_sha256("same synthetic input on six different real profiles")
    candidates = []
    for row, values in rows():
        body = row.model_dump(mode="json")
        body["input_text_sha256"] = shared_text
        candidates.append((BenchmarkRowRef.model_validate(seal(body, "row_sha256")), values))
    ranked = rank_benchmark_rows(plan.query_rows[0], vector(), tuple(candidates))
    assert len(ranked) == 15
    assert len({value.row.row_sha256 for value in ranked}) == 15
    assert {value.row.input_text_sha256 for value in ranked} == {shared_text}
    assert len({value.row.profile for value in ranked}) == 5


def test_unrounded_score_controls_order_before_stable_reference_key() -> None:
    plan = owner_request()
    candidates = tuple((row, vector(0.8 + index * 1e-8)) for index, (row, _) in enumerate(rows()))
    ranked = rank_benchmark_rows(plan.query_rows[0], vector(), candidates)
    assert all(left.cosine_similarity > right.cosine_similarity for left, right in pairwise(ranked))
    assert ranked[0].row == candidates[-1][0]


def test_complete_span_cluster_does_not_join_transitive_close_score_chain() -> None:
    ranked = ranked_single_views()
    ranked = tuple(
        replace(row, cosine_similarity=-index * 3e-5) for index, row in enumerate(ranked)
    )
    clusters = cluster_cpu_benchmark_rows(ranked)
    assert tuple(len(cluster) for cluster in clusters) == (2, 2, 1)
    assert tuple(value for cluster in clusters for value in cluster) == ranked
    assert all(
        cluster[0].cosine_similarity - cluster[-1].cosine_similarity <= CPU_NEAR_TIE_MAX_SPAN
        for cluster in clusters
    )


def test_span_threshold_is_inclusive_and_exact_ties_keep_the_stable_key() -> None:
    ranked = ranked_single_views()
    scores = (0.0, -4e-5, -0.5, -0.5, -0.75)
    ranked = tuple(
        replace(row, cosine_similarity=score) for row, score in zip(ranked, scores, strict=True)
    )
    assert tuple(len(cluster) for cluster in cluster_cpu_benchmark_rows(ranked)) == (2, 2, 1)
    ties = tuple(replace(row, cosine_similarity=0.0) for row in ranked)
    assert cluster_cpu_benchmark_rows(ties) == (ties,)
    with pytest.raises(ValueError, match="RANK_INPUT_INVALID"):
        cluster_cpu_benchmark_rows(tuple(reversed(ties)))


@pytest.mark.parametrize("bad", [True, 1, float("nan"), float("inf"), 2.0, -2.0])
def test_cluster_raw_score_values_are_not_coerced(bad: Any) -> None:
    ranked = ranked_single_views()
    with pytest.raises(ValueError, match="RANK_INPUT_INVALID"):
        cluster_cpu_benchmark_rows((replace(ranked[0], cosine_similarity=bad), *ranked[1:]))


@pytest.mark.parametrize(
    "case", ["empty", "duplicate", "wrong_purpose", "unordered", "few_profiles", "extra_view_text"]
)
def test_cluster_ref_and_order_closure_rejects_invalid_data(case: str) -> None:
    ranked = ranked_single_views()
    if case == "empty":
        ranked = ()
    elif case == "duplicate":
        ranked = (ranked[0], *ranked)
    elif case == "wrong_purpose":
        ranked = (replace(ranked[0], row=owner_request().query_rows[0]), *ranked[1:])
    elif case == "unordered":
        ranked = (replace(ranked[0], cosine_similarity=-0.1), *ranked[1:])
    elif case == "few_profiles":
        ranked = tuple(
            ScoredBenchmarkRow(row, 0.0)
            for row, _ in rows()
            if row.profile in {ranked[0].row.profile, ranked[1].row.profile}
        )
    else:
        body = ranked[-1].row.model_dump(mode="json")
        body["input_text_sha256"] = content_sha256("different synthetic text")
        another = BenchmarkRowRef.model_validate(seal(body, "row_sha256"))
        ranked = (*ranked, ScoredBenchmarkRow(another, 0.0))
    with pytest.raises(ValueError, match=r"RANK_(INPUT_INVALID|COVERAGE_INSUFFICIENT)"):
        cluster_cpu_benchmark_rows(ranked)


@pytest.mark.parametrize(
    "bad",
    [
        (),
        (0.0,) * 1024,
        (True, *((0.0,) * 1023)),
        (float("nan"), *((0.0,) * 1023)),
        (float("inf"), *((0.0,) * 1023)),
        (1.1, *((0.0,) * 1023)),
    ],
)
@pytest.mark.parametrize("where", ["query", "candidate", "self"])
def test_invalid_vectors_fail_even_on_excluded_self_row(bad: Any, where: str) -> None:
    plan = owner_request()
    query, candidates = vector(), rows()
    if where == "query":
        query = bad
    else:
        index = 0 if where == "self" else 4
        candidates = (*candidates[:index], (candidates[index][0], bad), *candidates[index + 1 :])
    with pytest.raises(ValueError, match="VECTOR_INVALID"):
        rank_benchmark_rows(plan.query_rows[0], query, candidates)


@pytest.mark.parametrize(
    "case",
    ["empty", "duplicate", "query_candidate", "document_query", "missing_self", "few_profiles"],
)
def test_rank_requires_exact_real_six_profile_scope(case: str) -> None:
    plan = owner_request()
    query, candidates = plan.query_rows[0], rows()
    if case == "empty":
        candidates = ()
    elif case == "duplicate":
        candidates = (*candidates[:-1], candidates[0])
    elif case == "query_candidate":
        candidates = ((query, vector()), *candidates[1:])
    elif case == "document_query":
        query = plan.document_rows[0]
    elif case == "missing_self":
        candidates = tuple(
            pair
            for pair in candidates
            if profile_key(pair[0].profile) != profile_key(query.profile)
        )
    else:
        candidates = candidates[:6]
    with pytest.raises(ValueError, match=r"RANK_(INPUT_INVALID|COVERAGE_INSUFFICIENT)"):
        rank_benchmark_rows(query, vector(), candidates)


def scored_matrix(scores: tuple[float, ...] | None = None) -> tuple[ScoredBenchmarkRow, ...]:
    plan = owner_request()
    ranked = rank_benchmark_rows(plan.query_rows[0], vector(), rows())
    values = scores if scores is not None else tuple(0.9 - index * 0.03 for index in range(15))
    assert len(values) == len(ranked)
    return tuple(
        replace(value, cosine_similarity=score) for value, score in zip(ranked, values, strict=True)
    )


def changed_scores(
    values: tuple[ScoredBenchmarkRow, ...], changes: dict[int, float]
) -> tuple[ScoredBenchmarkRow, ...]:
    return tuple(
        sorted(
            (
                replace(value, cosine_similarity=changes.get(index, value.cosine_similarity))
                for index, value in enumerate(values)
            ),
            key=lambda value: (-value.cosine_similarity, *benchmark_row_key(value.row)),
        )
    )


def test_identity_rank_comparison_retains_all_real_rows_and_pair_scores() -> None:
    baseline = scored_matrix()
    result = compare_benchmark_row_rankings(baseline, baseline)
    assert result.ranks_equivalent_within_tolerance
    assert len(result.observations) == 105  # All15 rows, not just the top5.
    assert all(value.order_preserved and value.top5_same_cluster for value in result.observations)
    by_row = {value.row.row_sha256: value.cosine_similarity for value in baseline}
    for value in result.observations:
        assert value.cpu_left_score == value.observed_left_score == by_row[value.left_row_sha256]
        assert value.cpu_right_score == value.observed_right_score == by_row[value.right_row_sha256]
        assert value.gap_class == "WIDE_GAP"


def test_same_cpu_cluster_can_swap_top5_boundary_within_fixed_score_tolerance() -> None:
    gap = 2.0**-16
    baseline = scored_matrix(
        (
            0.95,
            0.9,
            0.85,
            0.8,
            0.5 + gap / 2,
            0.5 - gap / 2,
            *(0.4 - index * 0.03 for index in range(9)),
        )
    )
    observed = changed_scores(
        baseline, {4: baseline[5].cosine_similarity, 5: baseline[4].cosine_similarity}
    )
    result = compare_benchmark_row_rankings(baseline, observed)
    assert result.ranks_equivalent_within_tolerance and result.top5_boundary_failures == 0
    swaps = tuple(value for value in result.observations if not value.order_preserved)
    assert len(swaps) == 1 and swaps[0].gap_class == "NEAR_TIE" and swaps[0].top5_same_cluster


@pytest.mark.parametrize("at_top5_boundary", [False, True])
def test_transitive_near_score_chain_cannot_excuse_cross_cluster_swap(
    at_top5_boundary: bool,
) -> None:
    gap = 2.0**-16
    prefix = (0.95, 0.9, 0.85) if at_top5_boundary else ()
    rest = tuple(0.4 - index * 0.03 for index in range(12 - len(prefix)))
    baseline = scored_matrix((*prefix, 0.5 + 2 * gap, 0.5, 0.5 - gap, *rest))
    left, right = len(prefix) + 1, len(prefix) + 2
    observed = changed_scores(
        baseline, {left: baseline[right].cosine_similarity, right: baseline[left].cosine_similarity}
    )
    result = compare_benchmark_row_rankings(baseline, observed)
    assert not result.ranks_equivalent_within_tolerance
    assert result.query_score_failures == result.wide_gap_order_failures == 0
    assert result.cluster_order_failures == 1
    assert result.top5_boundary_failures == int(at_top5_boundary)
    if at_top5_boundary:
        assert any(not value.top5_same_cluster for value in result.observations)


def test_wide_gap_swaps_outside_top5_are_still_detected() -> None:
    baseline = scored_matrix()
    observed = changed_scores(
        baseline, {10: baseline[11].cosine_similarity, 11: baseline[10].cosine_similarity}
    )
    result = compare_benchmark_row_rankings(baseline, observed)
    assert result.top5_boundary_failures == 0
    assert result.query_score_failures == 2
    assert result.wide_gap_order_failures == result.cluster_order_failures == 1
    assert not result.ranks_equivalent_within_tolerance


def test_cpu_exact_tie_stable_order_is_not_waived_by_close_cuda_scores() -> None:
    baseline = scored_matrix((0.9, 0.9, *(0.8 - index * 0.03 for index in range(13))))
    observed = changed_scores(baseline, {1: 0.9 + 2.0**-16})
    result = compare_benchmark_row_rankings(baseline, observed)
    assert result.query_score_failures == result.wide_gap_order_failures == 0
    assert result.cluster_order_failures == 1 and not result.ranks_equivalent_within_tolerance
    assert any(
        value.gap_class == "EXACT_TIE" and not value.order_preserved
        for value in result.observations
    )


@pytest.mark.parametrize("outside", [False, True])
def test_score_absolute_tolerance_is_inclusive_without_rounding(outside: bool) -> None:
    baseline = ranked_single_views()
    score = (
        math.nextafter(QUERY_SCORE_ABSOLUTE_TOLERANCE, math.inf)
        if outside
        else QUERY_SCORE_ABSOLUTE_TOLERANCE
    )
    observed = changed_scores(baseline, {0: score})
    result = compare_benchmark_row_rankings(baseline, observed)
    assert result.query_score_failures == int(outside)


@pytest.mark.parametrize("case", ["missing", "duplicate", "changed_text", "unordered", "list"])
def test_comparator_requires_identical_full_real_row_sets_and_valid_order(case: str) -> None:
    baseline = scored_matrix()
    observed = baseline
    if case == "missing":
        observed = observed[1:]
    elif case == "duplicate":
        observed = (*observed, observed[-1])
    elif case == "changed_text":
        body = observed[-1].row.model_dump(mode="json")
        body["input_text_sha256"] = content_sha256("a different synthetic source text")
        observed = (
            *observed[:-1],
            replace(observed[-1], row=BenchmarkRowRef.model_validate(seal(body, "row_sha256"))),
        )
    elif case == "unordered":
        observed = tuple(reversed(observed))
    else:
        observed = list(observed)
    with pytest.raises(ValueError, match=r"RANK_(INPUT_INVALID|COVERAGE_INSUFFICIENT)"):
        compare_benchmark_row_rankings(baseline, observed)


@pytest.mark.parametrize("bad", [True, 1, float("nan"), float("inf"), 1.01, -1.01])
@pytest.mark.parametrize("side", ["reference", "observed"])
def test_comparison_revalidates_raw_score_types_on_both_sides(bad: Any, side: str) -> None:
    baseline = scored_matrix()
    invalid = (replace(baseline[0], cosine_similarity=bad), *baseline[1:])
    reference, observed = (invalid, baseline) if side == "reference" else (baseline, invalid)
    with pytest.raises(ValueError, match="RANK_INPUT_INVALID"):
        compare_benchmark_row_rankings(reference, observed)

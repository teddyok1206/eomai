from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_contracts.item_inference_transfer import (
    HumanTransferEvaluation,
    InferenceTransferProfilePointer,
    InferenceTransferRubricPointer,
)
from eom_catalog_service.inference_transfer_evaluation import (
    TransferEvaluationError,
    TransferRankingMetrics,
    evaluate_transfer_ranking,
)
from eom_identifiers import content_sha256

# Synthetic evaluator records exercise metrics; they are not educational acceptance.
RUBRIC = InferenceTransferRubricPointer(
    rubric_id="transferrubric_" + "a" * 32,
    rubric_revision_id="transferrubricrev_" + "b" * 32,
    rubric_sha256="sha256:" + "c" * 64,
)


def _pointer(seed: str) -> InferenceTransferProfilePointer:
    return InferenceTransferProfilePointer(
        profile_id="inferenceprofile_" + seed * 32,
        profile_revision_id="inferenceprofilerev_" + seed * 32,
        profile_sha256="sha256:" + seed * 64,
    )


def _evaluation(seed: str, label: str) -> HumanTransferEvaluation:
    value = {
        "schema_version": "item-inference-transfer-human-evaluation/1.0",
        "evaluation_id": "transferevaluation_" + seed * 32,
        "evaluation_revision_id": "transferevaluationrev_" + seed * 32,
        "left_profile": _pointer("1").model_dump(mode="json"),
        "right_profile": _pointer(seed).model_dump(mode="json"),
        "direction": "A_TO_B",
        "rubric": RUBRIC.model_dump(mode="json"),
        "reviewer_id": "synthetic-reviewer",
        "label": label,
        "where_helped": ["공통 변수를 찾아 총량을 나누는 조건 연결"]
        if label == "CRUX_TRANSFERS"
        else [],
        "reason": "Synthetic fixture, not a real reviewer decision.",
        "evaluated_at": datetime(2026, 10, 10, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }
    return HumanTransferEvaluation.model_validate(
        {**value, "evaluation_sha256": content_sha256(value)}
    )


def _metrics(
    candidates: tuple[str, ...],
    evaluations: tuple[HumanTransferEvaluation, ...],
    *,
    k: int = 3,
) -> TransferRankingMetrics:
    return evaluate_transfer_ranking(
        query=_pointer("1"),
        ranked_candidates=tuple(_pointer(seed) for seed in candidates),
        evaluations=evaluations,
        reviewer_id="synthetic-reviewer",
        rubric=RUBRIC,
        k=k,
    )


def test_no_human_evaluation_does_not_become_quality_pass() -> None:
    metrics = _metrics(("2", "3"), ())
    assert metrics.status == "NOT_EVALUATED"
    assert metrics.judged_precision_at_k is None
    assert metrics.recall_in_judged_pool is None
    assert metrics.judgement_coverage_at_k == 0


def test_transfer_precision_and_near_duplicate_are_separate() -> None:
    records = (
        _evaluation("2", "CRUX_TRANSFERS"),
        _evaluation("3", "NEAR_IDENTICAL"),
        _evaluation("4", "SAME_CONCEPT_DIFFERENT_CRUX"),
        _evaluation("5", "CRUX_TRANSFERS"),
    )
    metrics = _metrics(("2", "3", "4"), records)
    assert metrics.status == "EVALUATED"
    assert metrics.crux_transfers_at_k == 1
    assert metrics.near_identical_at_k == 1
    assert metrics.judged_precision_at_k == pytest.approx(1 / 3)
    assert metrics.recall_in_judged_pool == 0.5
    assert metrics.judgement_coverage_at_k == 1


def test_partial_labels_expose_denominator_and_undetermined_is_not_negative() -> None:
    metrics = _metrics(
        ("2", "3", "4"),
        (_evaluation("2", "CRUX_TRANSFERS"), _evaluation("3", "UNDETERMINED")),
    )
    assert metrics.status == "PARTIALLY_EVALUATED"
    assert metrics.judged_at_k == 1
    assert metrics.judgement_coverage_at_k == pytest.approx(1 / 3)
    assert metrics.judged_precision_at_k == 1
    assert metrics.recall_in_judged_pool == 1


def test_zero_judged_positives_has_no_recall_not_fake_zero() -> None:
    metrics = _metrics(("2",), (_evaluation("2", "SURFACE_ONLY"),))
    assert metrics.judged_precision_at_k == 0
    assert metrics.recall_in_judged_pool is None


def test_exact_identical_replay_does_not_double_evaluation_denominator() -> None:
    record = _evaluation("2", "CRUX_TRANSFERS")
    metrics = _metrics(("2",), (record, record))
    assert metrics.judged_candidates == 1
    assert metrics.evaluation_sha256s == (record.evaluation_sha256,)


@pytest.mark.parametrize("candidates", [("2", "2"), ("1",)])
def test_duplicate_or_self_ranking_fails(candidates: tuple[str, ...]) -> None:
    with pytest.raises(TransferEvaluationError, match="DUPLICATE_OR_SELF"):
        _metrics(candidates, ())


def test_conflicting_human_history_cannot_be_averaged_or_silently_latest() -> None:
    with pytest.raises(TransferEvaluationError, match="CONFLICT"):
        _metrics(("2",), (_evaluation("2", "CRUX_TRANSFERS"), _evaluation("2", "SURFACE_ONLY")))


def test_other_reviewer_or_reversed_pair_cannot_contaminate_scorecard() -> None:
    record = _evaluation("2", "SURFACE_ONLY")
    value = record.model_dump(mode="json", exclude={"evaluation_sha256"})
    value["reviewer_id"] = "another-reviewer"
    other = HumanTransferEvaluation.model_validate(
        {**value, "evaluation_sha256": content_sha256(value)}
    )
    with pytest.raises(TransferEvaluationError, match="SCOPE_MISMATCH"):
        _metrics(("2",), (other,))


@pytest.mark.parametrize("k", [0, 129, True, 1.5])
def test_invalid_k_fails(k: int) -> None:
    with pytest.raises(TransferEvaluationError, match="BUDGET_INVALID"):
        _metrics(("2",), (), k=k)


def test_forged_human_label_cannot_reuse_original_evaluation_hash() -> None:
    forged = _evaluation("2", "SURFACE_ONLY").model_copy(
        update={"label": "CRUX_TRANSFERS", "where_helped": ("forged help",)}
    )
    with pytest.raises(TransferEvaluationError, match="INPUT_INVALID"):
        _metrics(("2",), (forged,))


@pytest.mark.parametrize("field", ["query", "ranked_candidates", "rubric"])
def test_unvalidated_pointer_copy_is_rejected(field: str) -> None:
    query = _pointer("1")
    candidates = (_pointer("2"),)
    rubric = RUBRIC
    if field == "query":
        query = query.model_copy(update={"profile_sha256": "invalid"})
    elif field == "ranked_candidates":
        candidates = (candidates[0].model_copy(update={"profile_revision_id": "invalid"}),)
    else:
        rubric = rubric.model_copy(update={"rubric_sha256": "invalid"})
    with pytest.raises(TransferEvaluationError, match="INPUT_INVALID"):
        evaluate_transfer_ranking(
            query=query,
            ranked_candidates=candidates,
            evaluations=(),
            reviewer_id="synthetic-reviewer",
            rubric=rubric,
            k=1,
        )


def test_large_fixture_uses_one_label_per_candidate() -> None:
    # O(N+k) map lookups rather than nested scans; no model or database is used.
    candidates = tuple(
        InferenceTransferProfilePointer(
            profile_id=f"inferenceprofile_{number:032x}",
            profile_revision_id=f"inferenceprofilerev_{number:032x}",
            profile_sha256=f"sha256:{number:064x}",
        )
        for number in range(2, 522)
    )
    metrics = evaluate_transfer_ranking(
        query=_pointer("1"),
        ranked_candidates=candidates,
        evaluations=(),
        reviewer_id="synthetic-reviewer",
        rubric=RUBRIC,
        k=128,
    )
    assert metrics.retrieved_at_k == 128
    assert metrics.status == "NOT_EVALUATED"

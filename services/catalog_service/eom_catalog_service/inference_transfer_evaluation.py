"""Pure, explicitly scoped retrieval metrics from human transfer judgements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.item_inference_transfer import (
    HumanTransferEvaluation,
    InferenceTransferProfilePointer,
    InferenceTransferRubricPointer,
)


class TransferEvaluationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TransferRankingMetrics:
    """Recall concerns this judged pool, never the unlabelled global corpus."""

    status: Literal["NOT_EVALUATED", "PARTIALLY_EVALUATED", "EVALUATED"]
    requested_k: int
    retrieved_at_k: int
    judged_at_k: int
    crux_transfers_at_k: int
    near_identical_at_k: int
    judged_candidates: int
    judged_positive_pool: int
    judgement_coverage_at_k: float | None
    judged_precision_at_k: float | None
    recall_in_judged_pool: float | None
    evaluation_sha256s: tuple[str, ...]


def _key(pointer: InferenceTransferProfilePointer) -> tuple[str, str, str]:
    return (pointer.profile_id, pointer.profile_revision_id, pointer.profile_sha256)


def evaluate_transfer_ranking(
    *,
    query: InferenceTransferProfilePointer,
    ranked_candidates: tuple[InferenceTransferProfilePointer, ...],
    evaluations: tuple[HumanTransferEvaluation, ...],
    reviewer_id: str,
    rubric: InferenceTransferRubricPointer,
    k: int,
) -> TransferRankingMetrics:
    """Evaluate one exact direction/reviewer/rubric; conflicting history is not averaged.

    Inputs must already be authorized and resolved by the owning application. This
    function grants no read access and performs no publication or human approval.
    A NEAR_IDENTICAL result is counted separately, not rewarded as a useful variant.
    """

    if (
        type(k) is not int
        or not 1 <= k <= 128
        or len(ranked_candidates) > 1024
        or len(evaluations) > 1024
    ):
        raise TransferEvaluationError("TRANSFER_EVALUATION_BUDGET_INVALID")
    # Frozen DTOs can still be created with model_copy/model_construct. Re-enter
    # the public validation boundary before treating their labels or pins as data.
    try:
        query = InferenceTransferProfilePointer.model_validate(query.model_dump(mode="json"))
        rubric = InferenceTransferRubricPointer.model_validate(rubric.model_dump(mode="json"))
        ranked_candidates = tuple(
            InferenceTransferProfilePointer.model_validate(pointer.model_dump(mode="json"))
            for pointer in ranked_candidates
        )
        evaluations = tuple(
            HumanTransferEvaluation.model_validate(evaluation.model_dump(mode="json"))
            for evaluation in evaluations
        )
    except ValueError as error:
        raise TransferEvaluationError("TRANSFER_EVALUATION_INPUT_INVALID") from error
    candidate_keys = tuple(_key(pointer) for pointer in ranked_candidates)
    if len(set(candidate_keys)) != len(candidate_keys) or _key(query) in candidate_keys:
        raise TransferEvaluationError("TRANSFER_RANKING_DUPLICATE_OR_SELF")
    labels: dict[tuple[str, str, str], HumanTransferEvaluation] = {}
    for evaluation in evaluations:
        if (
            evaluation.left_profile != query
            or evaluation.reviewer_id != reviewer_id
            or evaluation.rubric != rubric
        ):
            raise TransferEvaluationError("TRANSFER_EVALUATION_SCOPE_MISMATCH")
        key = _key(evaluation.right_profile)
        if key == _key(query):
            raise TransferEvaluationError("TRANSFER_EVALUATION_SELF_PAIR")
        existing = labels.get(key)
        if existing is not None and existing != evaluation:
            raise TransferEvaluationError("TRANSFER_EVALUATION_CONFLICT")
        labels[key] = evaluation
    determined = {key: value for key, value in labels.items() if value.label != "UNDETERMINED"}
    top = candidate_keys[:k]
    judged = tuple(determined[key] for key in top if key in determined)
    positives = sum(value.label == "CRUX_TRANSFERS" for value in determined.values())
    retrieved_positives = sum(value.label == "CRUX_TRANSFERS" for value in judged)
    status: Literal["NOT_EVALUATED", "PARTIALLY_EVALUATED", "EVALUATED"]
    if not determined:
        status = "NOT_EVALUATED"
    elif len(judged) != len(top) or not top:
        status = "PARTIALLY_EVALUATED"
    else:
        status = "EVALUATED"
    return TransferRankingMetrics(
        status=status,
        requested_k=k,
        retrieved_at_k=len(top),
        judged_at_k=len(judged),
        crux_transfers_at_k=retrieved_positives,
        near_identical_at_k=sum(value.label == "NEAR_IDENTICAL" for value in judged),
        judged_candidates=len(determined),
        judged_positive_pool=positives,
        judgement_coverage_at_k=len(judged) / len(top) if top else None,
        judged_precision_at_k=retrieved_positives / len(judged) if judged else None,
        recall_in_judged_pool=retrieved_positives / positives if positives else None,
        evaluation_sha256s=tuple(sorted(value.evaluation_sha256 for value in labels.values())),
    )

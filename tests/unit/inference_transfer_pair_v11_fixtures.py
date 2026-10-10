"""Synthetic three-axis values, never human labels or scientific acceptance."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.inference_transfer_pair_result_v11 import (
    PairComparisonResultV11,
    parse_pair_comparison_result_v11,
)
from eom_catalog_contracts.item_inference_transfer import PairComparisonRequest
from eom_identifiers import content_sha256

from tests.unit.inference_transfer_fixtures import result


def pair_result_body_v11(
    query: PairComparisonRequest | None = None, **updates: Any
) -> dict[str, Any]:
    body = result(query).model_dump(mode="json", exclude={"result_sha256"})
    body["schema_version"] = "item-inference-transfer-pair-result/1.1"
    body["axes"] = [
        {
            "axis": "CONCEPT",
            "judgement": "PARTIAL",
            "explanation": "합성 개념 설명: 보존 관계가 연결되지만 실제 과학 정확성 검증은 아니다.",
            "left_claim_ids": ["transferclaim_decisive"],
            "right_claim_ids": ["transferclaim_decisive"],
        },
        {
            "axis": "MATERIAL",
            "judgement": "DIFFERENT",
            "explanation": "합성 소재 설명: 주어진 상황을 비교하는 예시이며 사람 평가는 아니다.",
            "left_claim_ids": ["transferclaim_condition"],
            "right_claim_ids": ["transferclaim_condition"],
        },
        {
            "axis": "CRUX",
            "judgement": "SAME",
            "explanation": "합성 핵심 추론 설명: 결정 관계의 대응이라는 모델 가설이다.",
            "left_claim_ids": ["transferclaim_decisive"],
            "right_claim_ids": ["transferclaim_decisive"],
        },
    ]
    body.update(updates)
    body["result_sha256"] = content_sha256(body)
    return body


def pair_result_v11(
    query: PairComparisonRequest | None = None, **updates: Any
) -> PairComparisonResultV11:
    return parse_pair_comparison_result_v11(pair_result_body_v11(query, **updates))

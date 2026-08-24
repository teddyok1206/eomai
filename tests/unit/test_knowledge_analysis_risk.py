from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts import (
    ContentIntakeKnowledgeSourceV2,
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisRiskPolicy,
    KnowledgeProposalCounts,
    validate_contract,
)
from eom_catalog_service.knowledge_analysis_risk import evaluate_knowledge_analysis_risk
from eom_identifiers import content_sha256

ROOT = Path(__file__).resolve().parents[2]


def _receipt(
    *,
    source_class: str = "TEXTBOOK",
    general_knowledge_used: bool = False,
    confidence: int | None = 900,
    blocking: int = 0,
    nodes: int = 2,
) -> KnowledgeAnalysisProposalReceipt:
    source = ContentIntakeKnowledgeSourceV2.model_construct(source_class=source_class)
    return KnowledgeAnalysisProposalReceipt.model_construct(
        source=source,
        counts=KnowledgeProposalCounts(
            anchors=2,
            nodes=nodes,
            edges=1,
            claims=1,
            component_observations=1,
            ambiguities=blocking,
        ),
        general_knowledge_used=general_knowledge_used,
        minimum_confidence_milli=confidence,
        blocking_ambiguity_count=blocking,
    )


def _policy() -> KnowledgeAnalysisRiskPolicy:
    return KnowledgeAnalysisRiskPolicy.model_construct(
        minimum_confidence_milli=700,
        review_source_classes=("PAST_EXAM",),
        review_when_general_knowledge_used=True,
        review_when_blocking_ambiguity_present=True,
        maximum_auto_accept_counts=KnowledgeProposalCounts(
            anchors=10,
            nodes=10,
            edges=10,
            claims=10,
            component_observations=10,
            ambiguities=10,
        ),
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def test_low_risk_proposal_is_auto_acceptable() -> None:
    assert evaluate_knowledge_analysis_risk(_receipt(), _policy()).reason_codes == ()


def test_risk_reasons_are_complete_deduplicated_and_deterministic() -> None:
    result = evaluate_knowledge_analysis_risk(
        _receipt(
            source_class="PAST_EXAM",
            general_knowledge_used=True,
            confidence=699,
            blocking=1,
            nodes=11,
        ),
        _policy(),
    )
    assert result.requires_review is True
    assert result.reason_codes == tuple(sorted(result.reason_codes))
    assert set(result.reason_codes) == {
        "BLOCKING_AMBIGUITY_PRESENT",
        "CONFIDENCE_BELOW_POLICY",
        "GENERAL_KNOWLEDGE_USED",
        "PROPOSAL_COUNT_REQUIRES_REVIEW",
        "SOURCE_CLASS_REQUIRES_REVIEW",
    }


def test_default_risk_policy_is_schema_valid_and_self_hashed() -> None:
    policy = json.loads(
        (ROOT / "config/knowledge-analysis/default-risk-policy.v1.json").read_text(encoding="utf-8")
    )
    validate_contract("knowledge-analysis-risk-policy", policy)
    expected = content_sha256(
        {key: value for key, value in policy.items() if key != "content_sha256"}
    )
    assert policy["content_sha256"] == expected
    assert expected == "sha256:fa6efb2e77a3e639061317ca7d7617f072c01ecae807859f0222eaeccd208c0f"

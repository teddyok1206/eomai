"""Deterministic, side-effect-free knowledge-analysis review policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisProposalReceiptV5,
    KnowledgeAnalysisProposalReceiptV6,
    KnowledgeAnalysisRiskPolicy,
)


@dataclass(frozen=True)
class KnowledgeAnalysisRiskEvaluation:
    requires_review: bool
    reason_codes: tuple[str, ...]


def evaluate_knowledge_analysis_risk(
    receipt: (
        KnowledgeAnalysisProposalReceipt
        | KnowledgeAnalysisProposalReceiptV2
        | KnowledgeAnalysisProposalReceiptV3
        | KnowledgeAnalysisProposalReceiptV4
        | KnowledgeAnalysisProposalReceiptV5
        | KnowledgeAnalysisProposalReceiptV6
    ),
    policy: KnowledgeAnalysisRiskPolicy,
) -> KnowledgeAnalysisRiskEvaluation:
    """Evaluate one validated receipt in O(1) from its bounded summary counts."""

    reasons: set[str] = set()
    if receipt.source.source_class in policy.review_source_classes:
        reasons.add("SOURCE_CLASS_REQUIRES_REVIEW")
    if policy.review_when_general_knowledge_used and receipt.general_knowledge_used:
        reasons.add("GENERAL_KNOWLEDGE_USED")
    if policy.review_when_blocking_ambiguity_present and receipt.blocking_ambiguity_count > 0:
        reasons.add("BLOCKING_AMBIGUITY_PRESENT")
    if (
        receipt.minimum_confidence_milli is not None
        and receipt.minimum_confidence_milli < policy.minimum_confidence_milli
    ):
        reasons.add("CONFIDENCE_BELOW_POLICY")
    limits = policy.maximum_auto_accept_counts
    counts = receipt.counts
    if any(
        observed > maximum
        for observed, maximum in (
            (counts.anchors, limits.anchors),
            (counts.nodes, limits.nodes),
            (counts.edges, limits.edges),
            (counts.claims, limits.claims),
            (counts.component_observations, limits.component_observations),
            (counts.ambiguities, limits.ambiguities),
        )
    ):
        reasons.add("PROPOSAL_COUNT_REQUIRES_REVIEW")
    ordered = tuple(sorted(reasons))
    return KnowledgeAnalysisRiskEvaluation(bool(ordered), ordered)

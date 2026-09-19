"""Bounded domain policy for review-driven authoring rework."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from eom_identifiers import content_sha256

from eom_workflow.models import ArtifactPointer, WorkflowReviewReworkDirective
from eom_workflow.schemas import (
    load_review_rework_directive_schema,
    validate_schema_message,
)

REPAIRABLE_REVIEW_FINDING_CODES = frozenset(
    {
        "CANDIDATE_VISIBLE_IMAGE_INSTRUCTION",
        "CURRICULUM_SCOPE_INVALID",
        "DIFFICULTY_MISMATCH",
        "EXPLANATION_INCONSISTENT",
        "INDEPENDENT_ANSWER_MISMATCH",
        "INQUIRY_MISMATCH",
        "KNOWLEDGE_SOURCE_MODE_MISMATCH",
        "MATERIAL_PROFILE_MISMATCH",
        "MATERIAL_REQUIREMENT_MISMATCH",
        "ORIGINALITY_RISK",
        "REQUIRED_MATERIAL_STRUCTURE_EVIDENCE_MISSING",
        "SCORE_MISMATCH",
        "VISUAL_CONTENT_INCONSISTENT",
    }
)

HUMAN_REQUIRED_REVIEW_FINDING_CODES = frozenset(
    {
        "ORIGINALITY_EVIDENCE_INSUFFICIENT",
    }
)


def build_review_rework_directive(
    *,
    prior_authoring: ArtifactPointer,
    source_review: ArtifactPointer,
    blocking_finding_codes: Iterable[str],
    disregarded_finding_codes: Iterable[str],
    observed_rework_cycle_count: int,
    max_rework_cycles: int,
) -> WorkflowReviewReworkDirective:
    """Classify one bounded code set and bind it to exact immutable result revisions."""

    if max_rework_cycles != 3:
        raise ValueError("review rework directive requires the released three-cycle limit")
    blocking = set(blocking_finding_codes)
    disregarded = set(disregarded_finding_codes)
    if not disregarded.issubset(blocking):
        raise ValueError("disregarded findings must be present in the blocking review")
    verified = blocking - disregarded
    repairable = verified & REPAIRABLE_REVIEW_FINDING_CODES
    human = verified & HUMAN_REQUIRED_REVIEW_FINDING_CODES
    # Unknown future codes deliberately remain human-owned rather than entering an automatic loop.
    human.update(verified - repairable - human)
    outcome: Literal["READY_FOR_HUMAN", "REWORK_AUTHORING", "HUMAN_REVIEW_REQUIRED"]
    if human:
        outcome = "HUMAN_REVIEW_REQUIRED"
    elif repairable and observed_rework_cycle_count < max_rework_cycles:
        outcome = "REWORK_AUTHORING"
    elif repairable:
        outcome = "HUMAN_REVIEW_REQUIRED"
    else:
        outcome = "READY_FOR_HUMAN"
    unsigned = {
        "schema_version": "workflow-review-rework-directive/1.0",
        "observed_rework_cycle_count": observed_rework_cycle_count,
        "max_rework_cycles": max_rework_cycles,
        "outcome": outcome,
        "prior_authoring": prior_authoring.model_dump(mode="json"),
        "source_review": source_review.model_dump(mode="json"),
        "verified_blocking_finding_codes": sorted(verified),
        "repairable_finding_codes": sorted(repairable),
        "human_required_finding_codes": sorted(human),
        "disregarded_finding_codes": sorted(disregarded),
    }
    document = {**unsigned, "decision_sha256": content_sha256(unsigned)}
    validate_schema_message(
        load_review_rework_directive_schema(),
        document,
        "workflow-review-rework-directive/1.0",
    )
    return WorkflowReviewReworkDirective.model_validate(document)

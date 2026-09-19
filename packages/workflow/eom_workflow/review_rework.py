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


def validate_review_rework_history(
    raw_history: object,
    *,
    max_rework_cycles: int = 3,
) -> tuple[WorkflowReviewReworkDirective, ...]:
    """Validate the complete bounded decision chain, not only its latest member.

    One review decision exists for cycle zero and for every subsequent rework cycle. Step attempts
    may skip because infrastructure retries have their own attempt budget, but review source
    attempts must advance and an unchanged authoring attempt must keep the exact same immutable
    pointer. The released history is bounded, so full validation is O(H) with H <= 4.
    """

    if max_rework_cycles != 3:
        raise ValueError("review rework history requires the released three-cycle limit")
    if not isinstance(raw_history, list):
        raise ValueError("review rework history must be an array")
    if len(raw_history) > max_rework_cycles + 1:
        raise ValueError("review rework history exceeds its bounded decision count")

    directives: list[WorkflowReviewReworkDirective] = []
    decision_hashes: set[str] = set()
    review_revisions: set[str] = set()
    for expected_cycle, raw_directive in enumerate(raw_history):
        validate_schema_message(
            load_review_rework_directive_schema(),
            raw_directive,
            "workflow-review-rework-directive/1.0",
        )
        directive = WorkflowReviewReworkDirective.model_validate(raw_directive)
        if directive.max_rework_cycles != max_rework_cycles:
            raise ValueError("review rework history limit differs")
        if directive.observed_rework_cycle_count != expected_cycle:
            raise ValueError("review rework history cycle sequence differs")
        if directive.decision_sha256 in decision_hashes:
            raise ValueError("review rework history repeats a decision hash")
        if directive.source_review.revision_id in review_revisions:
            raise ValueError("review rework history repeats a review revision")

        if directives:
            previous = directives[-1]
            if directive.source_review.attempt <= previous.source_review.attempt:
                raise ValueError("review rework history review attempts do not advance")
            if directive.prior_authoring.attempt < previous.prior_authoring.attempt:
                raise ValueError("review rework history authoring attempts move backward")
            if (
                directive.prior_authoring.attempt == previous.prior_authoring.attempt
                and directive.prior_authoring != previous.prior_authoring
            ):
                raise ValueError("review rework history changes an immutable authoring attempt")

        decision_hashes.add(directive.decision_sha256)
        review_revisions.add(directive.source_review.revision_id)
        directives.append(directive)
    return tuple(directives)


def append_review_rework_directive(
    raw_history: object,
    directive: WorkflowReviewReworkDirective,
    *,
    max_rework_cycles: int = 3,
) -> list[dict[str, object]]:
    """Append exactly one cycle decision, or adopt its byte-equivalent replay."""

    history = validate_review_rework_history(
        raw_history,
        max_rework_cycles=max_rework_cycles,
    )
    observed = directive.observed_rework_cycle_count
    if len(history) == observed + 1:
        if history[-1] != directive:
            raise ValueError("recorded review rework directive differs on replay")
        return [entry.model_dump(mode="json") for entry in history]
    if len(history) != observed:
        raise ValueError("review rework history differs from the observed cycle")

    appended = [
        *(entry.model_dump(mode="json") for entry in history),
        directive.model_dump(mode="json"),
    ]
    validate_review_rework_history(
        appended,
        max_rework_cycles=max_rework_cycles,
    )
    return appended


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

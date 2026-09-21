"""Deterministic item-review complexity, escalation, and source-result closure."""

from __future__ import annotations

from collections.abc import Iterable

from eom_identifiers import content_sha256

from eom_workflow.control_plane import ResolvedStepExecutionV12, WorkerRole
from eom_workflow.models import (
    ArtifactPointer,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV12,
    IndependentReviewReportV2,
    ReviewEscalationReason,
    WorkflowReviewEscalationDirective,
)

MAX_REVIEW_ESCALATIONS_PER_WORKFLOW = 4
REVIEW_COMPLEXITY_ESCALATION_THRESHOLD = 4


def structural_review_complexity(authoring: ContentTeamAuthoringRoleResultV12) -> int:
    """Return the bounded score from exact typed draft structure in O(component count)."""

    draft = authoring.output.draft
    score = 0
    if draft.visuals:
        score += 1
    if len(draft.visuals) == 2:
        score += 1
    if draft.statements:
        score += 1
    if draft.inquiry is not None:
        score += 1
    if draft.equation_sources:
        score += 1
    if len(draft.labeled_blocks) == 2:
        score += 1
    return min(score, 10)


def expected_review_escalation_reasons(
    report: IndependentReviewReportV2,
    *,
    structural_complexity_score: int,
) -> tuple[ReviewEscalationReason, ...]:
    """Derive the closed escalation reason set from bounded review data."""

    reasons: set[ReviewEscalationReason] = set()
    if any(
        candidate.disposition in {"CONFIRMED", "UNCERTAIN"}
        for candidate in report.candidate_findings
    ):
        reasons.add("CANDIDATE_FINDING_PRESENT")
    if structural_complexity_score >= REVIEW_COMPLEXITY_ESCALATION_THRESHOLD:
        reasons.add("COMPLEX_ITEM")
    if any(
        target.evidence_status == "INSUFFICIENT"
        and target.target_kind in {"SCIENTIFIC_CLAIM", "ANSWER_DERIVATION", "CURRICULUM_SCOPE"}
        for target in report.verification_targets
    ):
        reasons.add("EVIDENCE_GAP")
    if any(candidate.disposition == "UNCERTAIN" for candidate in report.candidate_findings):
        reasons.add("EVIDENCE_UNCERTAINTY")
    if any(
        candidate.axis == "VISUAL" and candidate.disposition in {"CONFIRMED", "UNCERTAIN"}
        for candidate in report.candidate_findings
    ):
        reasons.add("VISUAL_RISK")
    return tuple(sorted(reasons))


def validate_primary_review_escalation_policy(
    *,
    authoring: ContentTeamAuthoringRoleResultV12,
    review: ContentTeamReviewRoleResultV12,
) -> tuple[ReviewEscalationReason, ...]:
    """Recompute complexity and reasons without trusting worker-authored routing fields."""

    assessment = review.output.independent_review_report.escalation_assessment
    if assessment.review_pass != "PRIMARY":
        raise ValueError("primary review classification received an escalated result")
    score = structural_review_complexity(authoring)
    if assessment.structural_complexity_score != score:
        raise ValueError("review structural complexity score differs from the typed draft")
    reasons = expected_review_escalation_reasons(
        review.output.independent_review_report,
        structural_complexity_score=score,
    )
    if assessment.reason_codes != reasons:
        raise ValueError("review escalation reasons differ from the application policy")
    expected_decision = "REQUIRED" if reasons else "NOT_REQUIRED"
    if assessment.decision != expected_decision:
        raise ValueError("review escalation decision differs from the application policy")
    return reasons


def build_review_escalation_directive(
    *,
    workflow_id: str,
    reviewed_authoring: ArtifactPointer,
    source_review: ArtifactPointer,
    authoring_result: ContentTeamAuthoringRoleResultV12,
    review_result: ContentTeamReviewRoleResultV12,
    plan_step: ResolvedStepExecutionV12,
) -> WorkflowReviewEscalationDirective | None:
    """Build one plan-bound successor directive, or return None for a low-risk primary review."""

    reasons = validate_primary_review_escalation_policy(
        authoring=authoring_result,
        review=review_result,
    )
    if not reasons:
        return None
    escalation = plan_step.escalation_candidate
    if plan_step.role != WorkerRole.REVIEW or plan_step.step_key != "review" or escalation is None:
        raise ValueError("review escalation is not authorized by the resolved plan")
    document: dict[str, object] = {
        "schema_version": "workflow-review-escalation-directive/1.0",
        "workflow_id": workflow_id,
        "reviewed_authoring": reviewed_authoring.model_dump(mode="json"),
        "source_review": source_review.model_dump(mode="json"),
        "source_attempt": source_review.attempt,
        "next_attempt": source_review.attempt + 1,
        "reason_codes": list(reasons),
        "structural_complexity_score": structural_review_complexity(authoring_result),
        "primary_model": plan_step.model,
        "primary_reasoning_effort": plan_step.reasoning_effort,
        "escalation_model": escalation.model,
        "escalation_reasoning_effort": escalation.reasoning_effort,
        "decision_sha256": "sha256:" + "0" * 64,
    }
    document["decision_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "decision_sha256"}
    )
    return WorkflowReviewEscalationDirective.model_validate(document)


def validate_escalated_review_against_source(
    *,
    directive: WorkflowReviewEscalationDirective,
    source: ContentTeamReviewRoleResultV12,
    escalated: ContentTeamReviewRoleResultV12,
) -> None:
    """Require a stronger pass to close the exact primary target and candidate sets."""

    source_report = source.output.independent_review_report
    final_report = escalated.output.independent_review_report
    source_assessment = source_report.escalation_assessment
    final_assessment = final_report.escalation_assessment
    if (
        source_assessment.review_pass != "PRIMARY"
        or source_assessment.reason_codes != directive.reason_codes
        or source_assessment.structural_complexity_score != directive.structural_complexity_score
        or final_assessment.review_pass != "ESCALATED"
        or final_assessment.reason_codes != directive.reason_codes
        or final_assessment.structural_complexity_score != directive.structural_complexity_score
        or final_assessment.source_review_artifact is None
        or final_assessment.source_review_artifact.model_dump(mode="json")
        != {
            "logical_artifact_id": directive.source_review.logical_artifact_id,
            "revision_id": directive.source_review.revision_id,
            "content_hash": directive.source_review.content_hash,
            "result_schema": directive.source_review.result_schema,
        }
    ):
        raise ValueError("escalated review assessment differs from its source directive")

    source_targets = {target.target_id: target for target in source_report.verification_targets}
    final_targets = {target.target_id: target for target in final_report.verification_targets}
    if source_targets.keys() != final_targets.keys():
        raise ValueError("escalated review verification target identities differ")
    for target_id, source_target in source_targets.items():
        final_target = final_targets[target_id]
        if source_target.model_dump(
            mode="json", exclude={"evidence_status", "conclusion"}
        ) != final_target.model_dump(mode="json", exclude={"evidence_status", "conclusion"}):
            raise ValueError("escalated review verification target pins differ")

    source_candidates = {
        candidate.candidate_id: candidate for candidate in source_report.candidate_findings
    }
    final_candidates = {
        candidate.candidate_id: candidate for candidate in final_report.candidate_findings
    }
    if source_candidates.keys() != final_candidates.keys():
        raise ValueError("escalated review candidate identities differ")
    for candidate_id, source_candidate in source_candidates.items():
        final_candidate = final_candidates[candidate_id]
        if source_candidate.model_dump(
            mode="json", exclude={"disposition", "conclusion"}
        ) != final_candidate.model_dump(mode="json", exclude={"disposition", "conclusion"}):
            raise ValueError("escalated review candidate evidence differs")
        if final_candidate.disposition == "UNCERTAIN":
            raise ValueError("escalated review did not close a candidate")


def validate_review_escalation_history(
    values: Iterable[object],
) -> tuple[WorkflowReviewEscalationDirective, ...]:
    """Validate bounded append-only history without reading mutable workflow state."""

    history = tuple(WorkflowReviewEscalationDirective.model_validate(value) for value in values)
    if len(history) > MAX_REVIEW_ESCALATIONS_PER_WORKFLOW:
        raise ValueError("review escalation history exceeds the workflow bound")
    source_keys = tuple(
        (item.source_review.revision_id, item.source_review.content_hash) for item in history
    )
    decision_hashes = tuple(item.decision_sha256 for item in history)
    if len(source_keys) != len(set(source_keys)) or len(decision_hashes) != len(
        set(decision_hashes)
    ):
        raise ValueError("review escalation history contains duplicate sources or decisions")
    return history


def append_review_escalation_directive(
    values: Iterable[object],
    directive: WorkflowReviewEscalationDirective,
) -> list[dict[str, object]]:
    """Append exactly one new directive after validating bounded history."""

    history = validate_review_escalation_history(values)
    if len(history) >= MAX_REVIEW_ESCALATIONS_PER_WORKFLOW:
        raise ValueError("review escalation history is full")
    return [
        *(item.model_dump(mode="json") for item in history),
        directive.model_dump(mode="json"),
    ]

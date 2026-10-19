"""Lossless projection of registered public review conclusions; no IO or solving."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.registered_review_profile import (
    RegisteredReviewClaim,
    RegisteredReviewProfile,
    RegisteredReviewSourceBasis,
    ReviewClaimKind,
    ReviewClaimVerdict,
    build_registered_review_profile,
)
from eom_identifiers import content_sha256
from eom_orchestrator.evidence_usage_validation import validate_independent_review_draft
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV11,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV11,
    ContentTeamReviewRoleResultV12,
)
from eom_workflow.schemas import validate_role_result

_REPORT = "/output/independent_review_report"
AuthoringResult = ContentTeamAuthoringRoleResultV11 | ContentTeamAuthoringRoleResultV12
ReviewResult = ContentTeamReviewRoleResultV11 | ContentTeamReviewRoleResultV12


def _claim(
    kind: ReviewClaimKind,
    subject: str,
    verdict: ReviewClaimVerdict | None,
    text: str,
    *,
    review_paths: tuple[str, ...],
    draft_paths: tuple[str, ...],
    evidence_ids: tuple[str, ...],
) -> RegisteredReviewClaim:
    body = {
        "kind": kind,
        "subject": subject,
        "verdict": verdict,
        "text": text,
        "review_json_pointers": sorted(review_paths),
        "draft_json_paths": list(draft_paths),
        "evidence_ids": list(evidence_ids),
    }
    return RegisteredReviewClaim.model_validate(
        body | {"claim_id": "reviewclaim_" + content_sha256(body)[7:39]}
    )


def project_registered_review_solution(
    *,
    source_basis: RegisteredReviewSourceBasis,
    authoring: AuthoringResult,
    review: ReviewResult,
    created_at: datetime,
) -> RegisteredReviewProfile:
    """Use owner-resolved original values, not model-claimed authority or raw hashes.

    The resolver must first prove the actual raw member SHA/bytes, registered Item
    materialization, final successful attempts and trusted receipts. A normalized
    Pydantic serialization is deliberately NOT compared to a historical raw SHA.
    This boundary revalidates shape, exact envelopes and the existing draft-leaf
    invariant, then preserves conclusions verbatim in O(report bytes + pointers).
    """
    basis = RegisteredReviewSourceBasis.model_validate(source_basis)
    if type(authoring) not in (
        ContentTeamAuthoringRoleResultV11,
        ContentTeamAuthoringRoleResultV12,
    ) or type(review) not in (ContentTeamReviewRoleResultV11, ContentTeamReviewRoleResultV12):
        raise ValueError("registered review requires the exact supported authoring/review types")
    successor = type(authoring) is ContentTeamAuthoringRoleResultV12
    if successor != (type(review) is ContentTeamReviewRoleResultV12):
        raise ValueError("registered review authoring/review families differ")
    family = "12.0" if successor else "11.0"
    authoring = cast(
        AuthoringResult,
        validate_role_result(
            raw_similarity_contract_value(authoring), "authoring", f"authoring-result@{family}"
        ),
    )
    review = cast(
        ReviewResult,
        validate_role_result(
            raw_similarity_contract_value(review), "review", f"review-result@{family}"
        ),
    )
    evidence = basis.review_evidence
    for result, reference, schema in (
        (authoring, evidence.authoring, f"authoring-result@{family}"),
        (review, evidence.review, f"review-result@{family}"),
    ):
        if (
            result.workflow_id != evidence.workflow_id
            or result.step_run_id != reference.step_run_id
            or result.job_id != reference.job_id
            or result.artifact.logical_artifact_id != reference.artifact.artifact_id
            or result.artifact.revision_id != reference.artifact.artifact_revision_id
            or result.artifact.file_name != reference.artifact.member_path
            or result.artifact.media_type != reference.artifact.media_type
            or reference.artifact.schema_ref != schema
        ):
            raise ValueError("registered review result envelope differs from its pinned evidence")
    attestation = review.output.evidence_usage_attestation
    if authoring.output.evidence_usage is None or attestation is None:
        raise ValueError("registered review requires original grounded evidence declarations")
    if (
        attestation.authoring_artifact.logical_artifact_id
        != evidence.authoring.artifact.artifact_id
        or attestation.authoring_artifact.revision_id
        != evidence.authoring.artifact.artifact_revision_id
        or attestation.authoring_artifact.content_hash != evidence.authoring.artifact.sha256
        or attestation.authoring_artifact.result_schema != evidence.authoring.artifact.schema_ref
    ):
        raise ValueError("registered review attestation points at another authoring result")
    validate_independent_review_draft(review, authoring.output.draft.model_dump(mode="json"))
    report = review.output.independent_review_report
    answer = report.answer_review
    claims = [
        _claim(
            "ANSWER_SUMMARY",
            answer.derived_answer_number,
            answer.alignment,
            answer.verification_summary,
            review_paths=tuple(
                f"{_REPORT}/answer_review/{field}"
                for field in (
                    "authored_answer_number",
                    "derived_answer_number",
                    "alignment",
                    "verification_summary",
                )
            ),
            draft_paths=("/answer/number",),
            evidence_ids=(),
        )
    ]
    for index, claim in enumerate(answer.claims):
        claims.append(
            _claim(
                "ANSWER_CLAIM",
                claim.claim_key,
                None,
                claim.conclusion,
                review_paths=(f"{_REPORT}/answer_review/claims/{index}/conclusion",),
                draft_paths=claim.draft_json_paths,
                evidence_ids=claim.evidence_ids,
            )
        )
    for index, diagnostic in enumerate(report.choice_diagnostics):
        claims.append(
            _claim(
                "CHOICE_DIAGNOSTIC",
                diagnostic.number,
                diagnostic.verdict,
                diagnostic.rationale,
                review_paths=tuple(
                    f"{_REPORT}/choice_diagnostics/{index}/{field}"
                    for field in ("number", "verdict", "rationale")
                ),
                draft_paths=diagnostic.draft_json_paths,
                evidence_ids=diagnostic.evidence_ids,
            )
        )
    for index, statement in enumerate(report.statement_diagnostics):
        claims.append(
            _claim(
                "STATEMENT_DIAGNOSTIC",
                statement.label,
                statement.verdict,
                statement.rationale,
                review_paths=tuple(
                    f"{_REPORT}/statement_diagnostics/{index}/{field}"
                    for field in ("label", "verdict", "rationale")
                ),
                draft_paths=statement.draft_json_paths,
                evidence_ids=statement.evidence_ids,
            )
        )
    return build_registered_review_profile(
        source_basis=basis,
        claims=tuple(sorted(claims, key=lambda claim: claim.claim_id)),
        created_at=created_at,
    )

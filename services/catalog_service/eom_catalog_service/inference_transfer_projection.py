"""Pure, bounded projection of an accepted, verifiable solution report.

This is a comparison input, not a new solution or an assertion that two Items
share a decisive idea.  Concrete text and exact local references are retained;
generic operation labels are never similarity features by themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts import KnowledgeAnalysisSolutionReport
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferClaim,
    InferenceTransferExtractionProvenance,
    InferenceTransferProfile,
    InferenceTransferSourceBasis,
    TransferFacet,
    validate_inference_transfer_profile_references,
)
from eom_identifiers import content_sha256

PROJECTION_VERSION = "accepted-solution-comparison/1.0"
MAX_PROFILE_CLAIMS = 128
MAX_CLAIM_CHARACTERS = 4000
DECISIVE_CANDIDATE_LIMITATION = (
    "DECISIVE_INFERENCE는 승인 풀이보고서의 개념-추론 연결에서 얻은 비교 후보입니다. "
    "이 문항의 결정적 착상이나 다른 문항으로의 풀이 전이를 확정한 판정이 아닙니다."
)


def _comparison_text(parts: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    """Keep complete scientific fields; a tail negation must never be sliced off."""
    full = "\n".join(f"{label}: {value}" for label, value in parts)
    if len(full) <= MAX_CLAIM_CHARACTERS:
        return (full,)
    if any(len(value) > MAX_CLAIM_CHARACTERS for _, value in parts):
        return ()
    return tuple(
        f"{label}: {value}" if len(label) + 2 + len(value) <= MAX_CLAIM_CHARACTERS else value
        for label, value in parts
    )


def project_accepted_solution_report(
    *,
    source_basis: InferenceTransferSourceBasis,
    report: KnowledgeAnalysisSolutionReport,
    created_at: datetime,
) -> InferenceTransferProfile:
    """Build a deterministic derived value; callers own approval/permission checks.

    ``created_at`` must be the pinned accepted-result timestamp for repeatable
    output, not the current wall clock. No source or report is mutated.
    """
    # Frozen models can still be forged with model_copy/model_construct.
    # Validate the bounded public values, not merely their Python class names.
    source_basis = InferenceTransferSourceBasis.model_validate(source_basis.model_dump(mode="json"))
    report = KnowledgeAnalysisSolutionReport.model_validate(report.model_dump(mode="json"))
    if report.base_analysis_result_id != source_basis.solution_evidence.base_analysis_result_id:
        raise ValueError("solution report does not belong to the pinned base analysis")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("profile timestamp must be explicitly timezone-aware")
    steps = {step.step_id: step for step in report.solution_steps}
    claims: list[InferenceTransferClaim] = []
    limitations: list[str] = []

    def append_claim(
        *,
        facet: TransferFacet,
        parts: tuple[tuple[str, str], ...],
        step_ids: tuple[str, ...],
        node_ids: tuple[str, ...],
        anchor_ids: tuple[str, ...],
        inferred: bool = False,
    ) -> None:
        texts = _comparison_text(parts)
        if not texts:
            limitations.append("4,000자를 넘는 개별 과학적 필드의 비교 claim은 UNAVAILABLE입니다.")
            return
        if len(claims) + len(texts) > MAX_PROFILE_CLAIMS:
            limitations.append("일부 완전한 비교 feature가 128개 claim 한도로 UNAVAILABLE입니다.")
            return
        if len(set(step_ids)) > 32 or len(set(node_ids)) > 32 or len(set(anchor_ids)) > 32:
            limitations.append("32개를 넘는 참조가 필요한 비교 feature는 UNAVAILABLE입니다.")
            return
        for text in texts:
            body = {
                "facet": facet.value,
                "text": text,
                "reasoning_step_ids": tuple(sorted(set(step_ids))),
                "node_ids": tuple(sorted(set(node_ids))),
                "anchor_ids": tuple(sorted(set(anchor_ids))),
                "inferred": inferred,
            }
            digest = content_sha256(body).removeprefix("sha256:")
            claims.append(
                InferenceTransferClaim.model_validate(
                    {"claim_id": "transferclaim_" + digest[:32], **body}
                )
            )

    for step in report.solution_steps:
        if step.operation == "INTERPRET_GIVEN":
            facet = TransferFacet.GIVEN_CONDITION
        elif step.operation in {"CONCLUDE", "EVALUATE_STATEMENT", "EVALUATE_CHOICE"}:
            facet = TransferFacet.ASKED_JUDGEMENT
        else:
            facet = TransferFacet.INTERMEDIATE_RELATION
        append_claim(
            facet=facet,
            parts=(("근거", step.rationale), ("도출 결과", step.outcome)),
            step_ids=(step.step_id,),
            node_ids=tuple((*step.node_ids, *step.item_element_node_ids)),
            anchor_ids=step.anchor_ids,
        )

    # Existing role mappings identify candidates, not a newly inferred crux.
    inference_links = tuple(
        link for link in report.concept_assessment_links if link.role == "INFERENCE_OPERATION"
    )
    for link in inference_links:
        linked_steps = tuple(steps[step_id] for step_id in link.reasoning_step_ids)
        append_claim(
            facet=TransferFacet.DECISIVE_INFERENCE,
            parts=(
                ("추론 연결 설명", link.summary),
                *(("연결된 구체적 결과", step.outcome) for step in linked_steps),
            ),
            step_ids=link.reasoning_step_ids,
            node_ids=tuple(
                (
                    link.concept_node_id,
                    *link.assessment_pattern_node_ids,
                    *link.item_element_node_ids,
                )
            ),
            anchor_ids=tuple(anchor for step in linked_steps for anchor in step.anchor_ids),
            inferred=True,
        )
    if inference_links:
        limitations.append(DECISIVE_CANDIDATE_LIMITATION)
    else:
        limitations.append(
            "승인 풀이보고서에 INFERENCE_OPERATION 연결이 없어 핵심 착상 후보가 없습니다."
        )
    for diagnostic in report.choice_diagnostics:
        if diagnostic.targeted_misconception is None:
            continue
        append_claim(
            facet=TransferFacet.MISCONCEPTION,
            parts=(
                ("겨냥한 오개념", diagnostic.targeted_misconception),
                ("구체적 판단 근거", diagnostic.rationale),
            ),
            step_ids=diagnostic.reasoning_step_ids,
            node_ids=diagnostic.node_ids,
            anchor_ids=diagnostic.anchor_ids,
        )
    if report.unresolved_issues:
        limitations.append(
            "승인 풀이보고서에 미해결 쟁점이 있어 비교 결과를 확정 판단으로 사용할 수 없습니다."
        )
    if report.official_explanation_comparison.status != "CONSISTENT":
        limitations.append("공식 해설 대조 상태: " + report.official_explanation_comparison.status)
    if report.general_knowledge_used:
        limitations.append("승인 풀이보고서 작성에 일반 지식이 사용됐습니다.")

    # Identical claims are one comparison feature; retain canonical stable ordering.
    unique_claims = {claim.claim_id: claim for claim in claims}
    ordered = tuple(sorted(unique_claims.values(), key=lambda claim: claim.claim_id))
    extraction = InferenceTransferExtractionProvenance(
        method="DETERMINISTIC_REPORT_PROJECTION", extractor_version=PROJECTION_VERSION
    )
    body = {
        "schema_version": "item-inference-transfer-profile/1.0",
        "source_basis": source_basis.model_dump(mode="json"),
        "claims": [claim.model_dump(mode="json") for claim in ordered],
        "limitations": tuple(dict.fromkeys(limitations)),
        "extraction": extraction.model_dump(mode="json"),
        "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    identity = content_sha256(body).removeprefix("sha256:")
    logical_identity = content_sha256(
        {
            "item_id": source_basis.source.item_id,
            "item_revision_id": source_basis.source.item_revision_id,
            "method": extraction.method,
            "extractor_version": extraction.extractor_version,
        }
    ).removeprefix("sha256:")
    document = {
        **body,
        "profile_id": "inferenceprofile_" + logical_identity[:32],
        "profile_revision_id": "inferenceprofilerev_" + identity[32:],
    }
    profile = InferenceTransferProfile.model_validate(
        {**document, "profile_sha256": content_sha256(document)}
    )
    validate_inference_transfer_profile_references(profile, report)
    return profile

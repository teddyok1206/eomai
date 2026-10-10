"""Offline tests: comparison projections are derived evidence, not new solutions."""

from __future__ import annotations

from datetime import datetime

import pytest
from eom_catalog_contracts import KnowledgeAnalysisSolutionReport
from eom_catalog_contracts.item_inference_transfer import TransferFacet
from eom_catalog_service.inference_transfer_projection import (
    DECISIVE_CANDIDATE_LIMITATION,
    project_accepted_solution_report,
)
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_fixtures import NOW, profile, report


def test_concrete_report_text_and_source_identity_are_preserved_without_mutation() -> None:
    original = report("마찰이 없고 속력은 -36 km/h이다.", "외력이 한 일이 0 J이므로 합이 일정하다.")
    before = canonical_json_bytes(original)
    basis = profile().source_basis
    result = project_accepted_solution_report(source_basis=basis, report=original, created_at=NOW)
    assert result.source_basis == basis
    assert canonical_json_bytes(original) == before
    text = "\n".join(claim.text for claim in result.claims)
    assert "-36 km/h" in text and "0 J" in text
    assert "INTERPRET_GIVEN" not in text and "CONCLUDE" not in text
    assert {claim.facet for claim in result.claims} >= {
        TransferFacet.GIVEN_CONDITION,
        TransferFacet.DECISIVE_INFERENCE,
        TransferFacet.ASKED_JUDGEMENT,
    }
    decisive = tuple(
        claim for claim in result.claims if claim.facet == TransferFacet.DECISIVE_INFERENCE
    )
    assert decisive and all(claim.inferred for claim in decisive)
    assert DECISIVE_CANDIDATE_LIMITATION in result.limitations
    assert result.extraction.model_id is None and result.extraction.prompt_sha256 is None


def test_repeatable_timestamp_produces_exact_profile_revision_and_hash() -> None:
    args = {"source_basis": profile().source_basis, "report": report(), "created_at": NOW}
    a = project_accepted_solution_report(**args)
    b = project_accepted_solution_report(**args)
    assert a == b
    assert a.profile_revision_id.startswith("inferenceprofilerev_")
    assert a.profile_id.startswith("inferenceprofile_")


def test_changed_concrete_condition_changes_identity_even_when_operations_match() -> None:
    basis = profile().source_basis
    a = project_accepted_solution_report(source_basis=basis, report=report(), created_at=NOW)
    b = project_accepted_solution_report(
        source_basis=basis, report=report("마찰이 있고 속력은 36 km/h이다."), created_at=NOW
    )
    assert a.profile_sha256 != b.profile_sha256
    assert a.profile_revision_id != b.profile_revision_id
    assert a.profile_id == b.profile_id


def test_mismatched_base_report_and_naive_timestamp_fail_explicitly() -> None:
    original = report().model_dump(mode="json")
    original["base_analysis_result_id"] = "knowledgeanalysisresult_" + "e" * 32
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    with pytest.raises(ValueError, match="pinned base"):
        project_accepted_solution_report(
            source_basis=profile().source_basis, report=changed, created_at=NOW
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        project_accepted_solution_report(
            source_basis=profile().source_basis, report=report(), created_at=datetime(2026, 10, 10)
        )


def test_forged_frozen_report_and_source_hash_are_revalidated() -> None:
    original = report()
    forged_step = original.solution_steps[0].model_copy(update={"rationale": "가" * 4001})
    forged_report = original.model_copy(
        update={"solution_steps": (forged_step, *original.solution_steps[1:])}
    )
    with pytest.raises(ValueError):
        project_accepted_solution_report(
            source_basis=profile().source_basis, report=forged_report, created_at=NOW
        )
    basis = profile().source_basis
    forged_pointer = basis.solution_evidence.model_copy(
        update={"pointer_sha256": "sha256:" + "0" * 64}
    )
    with pytest.raises(ValueError, match="pointer hash"):
        project_accepted_solution_report(
            source_basis=basis.model_copy(update={"solution_evidence": forged_pointer}),
            report=original,
            created_at=NOW,
        )


def test_missing_inference_mapping_is_explicit_not_an_invented_decisive_step() -> None:
    original = report().model_dump(mode="json")
    original["concept_assessment_links"][1]["role"] = "ANSWER_CRITERION"
    original["concept_assessment_links"].sort(
        key=lambda link: (link["concept_node_id"], link["role"])
    )
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    result = project_accepted_solution_report(
        source_basis=profile().source_basis, report=changed, created_at=NOW
    )
    assert all(claim.facet != TransferFacet.DECISIVE_INFERENCE for claim in result.claims)
    assert any("후보가 없습니다" in limitation for limitation in result.limitations)


def test_long_concrete_fields_split_losslessly_and_preserve_terminal_negation() -> None:
    original = report().model_dump(mode="json")
    rationale = "조건 " * 1300 + "에너지가 보존되지 않는다."
    outcome = "결과 " * 1300 + "외력의 합은 0이 아니다."
    original["solution_steps"][0]["rationale"] = rationale
    original["solution_steps"][0]["outcome"] = outcome
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    result = project_accepted_solution_report(
        source_basis=profile().source_basis, report=changed, created_at=NOW
    )
    given = tuple(claim for claim in result.claims if claim.facet == TransferFacet.GIVEN_CONDITION)
    assert len(given) == 2 and all(len(claim.text) <= 4000 for claim in given)
    assert any(rationale in claim.text for claim in given)
    assert any(outcome in claim.text for claim in given)
    assert not any("잘렸습니다" in limitation for limitation in result.limitations)


def test_maximum_length_field_never_loses_negation_to_make_room_for_a_label() -> None:
    original = report().model_dump(mode="json")
    condition = "가" * 3992 + "보존되지않는다."
    assert len(condition) == 4000
    original["solution_steps"][0]["rationale"] = condition
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    result = project_accepted_solution_report(
        source_basis=profile().source_basis, report=changed, created_at=NOW
    )
    assert any(claim.text == condition for claim in result.claims)
    assert all(len(claim.text) <= 4000 for claim in result.claims)


def test_claim_budget_omits_whole_features_not_partial_scientific_fields() -> None:
    original = report().model_dump(mode="json")
    long_field = "조건 " * 1300 + "보존되지 않는다."
    initial = original["solution_steps"]
    original["solution_steps"] = [
        (initial[index] if index < 2 else initial[0] | {"step_id": f"solutionstep_{index:02d}"})
        | {"ordinal": index + 1, "rationale": long_field, "outcome": long_field}
        for index in range(64)
    ]
    original["solution_steps"][-1]["operation"] = "CONCLUDE"
    for index, link in enumerate(original["concept_assessment_links"]):
        link["reasoning_step_ids"] = sorted(
            step["step_id"] for step in original["solution_steps"][index * 32 : (index + 1) * 32]
        )
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    result = project_accepted_solution_report(
        source_basis=profile().source_basis, report=changed, created_at=NOW
    )
    assert len(result.claims) <= 128
    assert all(long_field in claim.text for claim in result.claims)
    assert any(
        "128개" in limitation and "UNAVAILABLE" in limitation for limitation in result.limitations
    )


def test_misconception_and_unresolved_scientific_issue_remain_visible() -> None:
    original = report().model_dump(mode="json")
    original["choice_diagnostics"] = [
        {
            "choice_key": "ㄱ",
            "verdict": "INCORRECT",
            "rationale": "마찰이 있으므로 보존되지 않는다.",
            "targeted_misconception": "마찰이 있어도 항상 역학적 에너지가 보존된다.",
            "reasoning_step_ids": ["solutionstep_decisive"],
            "node_ids": ["knode_concept_motion"],
            "anchor_ids": ["anchor_problem"],
        }
    ]
    original["unresolved_issues"] = [
        {
            "code": "VALUE_UNCERTAIN",
            "summary": "수치가 불명확하다.",
            "anchor_ids": ["anchor_problem"],
        }
    ]
    original["official_explanation_comparison"] = {
        "status": "UNAVAILABLE",
        "summary": "원문 해설 없음",
        "answer_explanation_anchor_ids": [],
    }
    original["general_knowledge_used"] = True
    changed = KnowledgeAnalysisSolutionReport.model_validate(original)
    result = project_accepted_solution_report(
        source_basis=profile().source_basis, report=changed, created_at=NOW
    )
    assert any(
        claim.facet == TransferFacet.MISCONCEPTION and "마찰이 있어도" in claim.text
        for claim in result.claims
    )
    assert any("미해결" in text for text in result.limitations)
    assert any("UNAVAILABLE" in text for text in result.limitations)
    assert any("일반 지식" in text for text in result.limitations)

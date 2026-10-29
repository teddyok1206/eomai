"""Same public science, different report layout: identical derived encoding text."""

from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_catalog_contracts.external_item_learning_result_v2 import (
    stamp_external_item_learning_result_v2,
)
from eom_catalog_contracts.knowledge import KnowledgeAnalysisSolutionReport
from eom_catalog_contracts.public_solution_text import (
    PublicSolutionText,
    build_public_solution_text,
)
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_fixtures import report
from tests.unit.test_creative_source_content import _disagreement
from tests.unit.test_external_item_learning_result_v2 import result_v2

ROOT = Path(__file__).resolve().parents[2]


def source_report(parts: tuple[str, ...], *, successor: bool):
    value = result_v2() if successor else _disagreement()
    container = value["solution_report"] if successor else value["proposal"]
    previous = container["solution_steps"][0]
    container["solution_steps"] = [
        previous | {"step_number": index, "reasoning_summary": text}
        for index, text in enumerate(parts, 1)
    ]
    if successor:
        value.pop("result_sha256", None)
        return stamp_external_item_learning_result_v2(value)
    value["result_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "result_sha256"}
    )
    return ExternalItemLearningResult.model_validate(value)


@pytest.mark.parametrize("successor", [False, True])
@pytest.mark.parametrize("joined_steps", [False, True])
def test_past_and_creative_same_public_facts_have_identical_actual_text_and_hash(
    successor, joined_steps
):
    past = report("속도는 -36 km/h이다.", "합력은 0 N이 아니다.")
    parts = tuple(value for step in past.solution_steps for value in (step.rationale, step.outcome))
    creative_parts = ("\r\n\t".join(parts),) if joined_steps else parts
    creative = source_report(creative_parts, successor=successor)
    before = tuple(canonical_json_bytes(value) for value in (past, creative))
    a, b = map(project_public_solution_text, (past, creative))
    assert a == b and a.status == "AVAILABLE"
    assert a.text_sha256 == b.text_sha256 == content_sha256(a.text)
    assert "-36 km/h" in a.text and "0 N이 아니다." in a.text
    assert before == tuple(canonical_json_bytes(value) for value in (past, creative))
    assert "source_id" not in a.text and "solutionstep_" not in a.text
    assert "ANSWER_DISAGREEMENT" not in a.text and "NEEDS_DECISION" not in a.text


def test_metadata_ids_and_report_explanation_do_not_become_numerical_features():
    original = source_report(("질량이 일정하다.", "합력은 0 N이다."), successor=True)
    value = original.model_dump(mode="json")
    value.update(result_id="extlearnresult_" + "f" * 32, external_number="19999")
    value["solution_report"]["explanation"] = "별도 보고서 표시 설명."
    value["result_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "result_sha256"}
    )
    changed = type(original).model_validate(value)
    assert project_public_solution_text(original) == project_public_solution_text(changed)
    assert original.conflicts == changed.conflicts  # warnings remain in the real report


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("보존된다.", "보존되지 않는다."),
        ("속도는 -36 km/h이다.", "속도는 36 km/h이다."),
        ("속도는 36 km/h이다.", "속도는 36 m/s이다."),
        ("a²이다.", "a2이다."),
        ("x₁이다.", "x1이다."),
    ],
)
def test_scientific_difference_is_not_erased_to_equalize_a_score(original, changed):
    assert (
        build_public_solution_text((original,)).text_sha256
        != build_public_solution_text((changed,)).text_sha256
    )


def test_korean_unicode_composition_and_layout_only_are_normalized():
    assert build_public_solution_text(("가\r\n나\t다",)) == build_public_solution_text(
        ("가 나 다",)
    )
    assert build_public_solution_text(("1 0",)) != build_public_solution_text(("10",))
    assert build_public_solution_text(("N·m",)).text == "N·m"


def test_missing_public_reasoning_is_unavailable_not_editorial_fallback():
    value = result_v2()
    value["solution_report"].update(
        answer_state="UNDETERMINED",
        answer_labels=[],
        accepted_answers=[],
        answer_cross_check="NOT_DETERMINED",
        editorial_region_ids=[],
        solution_steps=[],
    )
    value.update(status="NEEDS_DECISION")
    value["conflicts"] = [
        {
            "conflict_code": "MISSING_SOLUTION",
            "description": "독립 풀이의 근거를 확정하지 못했다.",
            "source_region_ids": [value["regions"][0]["region_id"]],
            "blocking": True,
        }
    ]
    value.pop("result_sha256", None)
    result = stamp_external_item_learning_result_v2(value)
    assert result.proposal is not None and result.solution_report.explanation
    assert project_public_solution_text(result) == PublicSolutionText(
        status="UNAVAILABLE", text=None, text_sha256=None
    )


def test_unsupported_review_conclusions_are_not_invented_full_solution():
    with pytest.raises(ValueError, match="FAMILY_UNAVAILABLE"):
        project_public_solution_text(object())


def test_forged_frozen_step_is_revalidated():
    value = report()
    forged = value.model_copy(
        update={
            "solution_steps": (
                value.solution_steps[0].model_copy(update={"rationale": "bad\x00field"}),
                *value.solution_steps[1:],
            )
        }
    )
    with pytest.raises(ValueError):
        project_public_solution_text(forged)


@pytest.mark.parametrize("parts", [("bad\x00field",), ("a" * 524289,), ["not a tuple"]])
def test_untrusted_or_over_budget_text_is_not_silently_truncated(parts):
    with pytest.raises(ValueError):
        build_public_solution_text(parts)


def test_schema_is_packaged_and_json_schema_2020_12_is_enforced():
    import json

    canonical = ROOT / "schemas/knowledge/public-solution-text-v1.schema.json"
    packaged = ROOT / (
        "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
        "public-solution-text-v1.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)
    result = build_public_solution_text(("합력은 0 N이다.",))
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))
    with pytest.raises(ValueError):
        PublicSolutionText.model_validate(
            result.model_dump() | {"text_sha256": "sha256:" + "0" * 64}
        )
    assert KnowledgeAnalysisSolutionReport.model_validate(report().model_dump())

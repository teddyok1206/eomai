"""A source draft cannot replace the independent report or borrow attached evidence."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.external_item_learning_result import (
    validate_external_item_learning_result_for_source,
)
from eom_catalog_contracts.external_item_learning_result_v2 import (
    ExternalItemLearningResultV2,
    stamp_external_item_learning_result_v2,
)
from eom_catalog_contracts.validation import validate_contract

from tests.unit.test_external_item_learning_result_contract import _rehash, _result


def result_v2():
    value = deepcopy(_result())
    value["schema_version"] = "external-item-learning-result/2.0"
    proposal = value["proposal"]
    steps = proposal.pop("solution_steps")
    cross_check = proposal.pop("answer_cross_check")
    proposal["content"]["schema_version"] = "creative-source-item-draft/1.0"
    proposal["content"]["score"] = {"state": "UNPRINTED", "points": None}
    proposal["content"]["solution_origin"] = "EDITORIAL_SOURCE"
    for block in proposal["content"]["body"]:
        if block["type"] == "table":
            block["caption"] = None
    for mapping in proposal["content_region_map"]:
        if mapping["content_path"] == "score.points":
            mapping["content_path"] = "score"
    value["solution_report"] = {
        "answer_state": "DETERMINED",
        "answer_labels": ["1"],
        "accepted_answers": [],
        "explanation": "독립 풀이 결과이며 원문 편집 답안과 구분한다.",
        "solution_steps": steps,
        "answer_cross_check": cross_check,
        "editorial_region_ids": [value["regions"][1]["region_id"]],
    }
    _rehash(value)
    return value


def undetermined_result_v2():
    value = result_v2()
    value["status"] = "NEEDS_DECISION"
    value["solution_report"].update(
        answer_state="UNDETERMINED",
        answer_labels=[],
        accepted_answers=[],
        answer_cross_check="NOT_DETERMINED",
    )
    value["conflicts"] = [
        {
            "conflict_code": "ANSWER_DISAGREEMENT",
            "description": "원문 해설을 확인했지만 독립 답안은 확정할 수 없다.",
            "source_region_ids": value["solution_report"]["editorial_region_ids"],
            "blocking": True,
        }
    ]
    _rehash(value)
    return value


def test_undetermined_answer_keeps_observed_editorial_evidence_without_claiming_agreement():
    value = undetermined_result_v2()
    before = deepcopy(value)
    validate_contract("external-item-learning-result-v2", value)
    result = ExternalItemLearningResultV2.model_validate(value)
    assert value == before
    assert result.solution_report.editorial_region_ids == (value["regions"][1]["region_id"],)
    assert result.solution_report.answer_cross_check == "NOT_DETERMINED"
    assert result.solution_report.answer_labels == result.solution_report.accepted_answers == ()
    assert result.proposal.content.solution.correct_choice_ids == ("choice_1",)
    assert result.status == "NEEDS_DECISION" and result.conflicts[0].blocking
    assert ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json")) == result


@pytest.mark.parametrize("region", ["target", "attachment", "unknown"])
def test_undetermined_answer_cannot_cite_foreign_or_unrelated_editorial_evidence(region):
    value = undetermined_result_v2()
    identifier = {
        "target": value["regions"][0]["region_id"],
        "attachment": value["regions"][2]["region_id"],
        "unknown": "extregion_" + "f" * 32,
    }[region]
    value["solution_report"]["editorial_region_ids"] = [identifier]
    _rehash(value)
    with pytest.raises(ValueError, match="unrelated source"):
        ExternalItemLearningResultV2.model_validate(value)


@pytest.mark.parametrize("comparison", ["MATCHES_EDITORIAL_SOLUTION", "DISAGREES"])
def test_determined_editorial_comparison_still_requires_actual_editorial_references(comparison):
    value = result_v2()
    value["solution_report"].update(answer_cross_check=comparison, editorial_region_ids=[])
    _rehash(value)
    with pytest.raises(ValueError, match="cross-check differs"):
        ExternalItemLearningResultV2.model_validate(value)


def test_no_editorial_solution_still_rejects_editorial_references():
    value = result_v2()
    value["solution_report"]["answer_cross_check"] = "NO_EDITORIAL_SOLUTION"
    _rehash(value)
    with pytest.raises(ValueError, match="cross-check differs"):
        ExternalItemLearningResultV2.model_validate(value)


def test_source_draft_and_independent_report_are_distinct_with_unprinted_score():
    value = result_v2()
    validate_contract("external-item-learning-result-v2", value)
    result = ExternalItemLearningResultV2.model_validate(value)
    assert ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json")) == result
    assert result.proposal.content.score.points is None
    assert result.solution_report.explanation != result.proposal.content.solution.explanation
    validate_external_item_learning_result_for_source(
        result,
        value["input_sha256"],
        value["source_id"],
        value["source_revision_id"],
        value["external_number"],
    )
    with pytest.raises(ValueError, match="pinned source"):
        validate_external_item_learning_result_for_source(
            result, value["input_sha256"], value["source_id"], value["source_revision_id"], "99999"
        )


def test_original_wrong_answer_is_preserved_beside_independent_disagreement():
    value = result_v2()
    value["status"] = "NEEDS_DECISION"
    value["solution_report"]["answer_labels"] = ["2"]
    value["solution_report"]["answer_cross_check"] = "DISAGREES"
    value["conflicts"] = [
        {
            "conflict_code": "ANSWER_DISAGREEMENT",
            "description": "정답이 불일치한다.",
            "source_region_ids": [value["regions"][1]["region_id"]],
            "blocking": True,
        }
    ]
    _rehash(value)
    result = ExternalItemLearningResultV2.model_validate(value)
    assert result.proposal.content.solution.correct_choice_ids == ("choice_1",)
    assert result.solution_report.answer_labels == ("2",)
    assert result.conflicts[0].blocking  # preservation does not reclassify the finding


def test_public_solution_survives_even_when_native_reconstruction_is_not_available():
    value = result_v2()
    value["proposal"] = None
    value["status"] = "NEEDS_DECISION"
    value["conflicts"] = [
        {
            "conflict_code": "UNSUPPORTED_STRUCTURE",
            "description": "정본 변환은 미완료다.",
            "source_region_ids": [value["regions"][0]["region_id"]],
            "blocking": True,
        }
    ]
    _rehash(value)
    result = ExternalItemLearningResultV2.model_validate(value)
    assert result.proposal is None and result.solution_report.solution_steps
    assert result.solution_report.answer_labels == ("1",)


@pytest.mark.parametrize("path", ["step", "editorial", "stem"])
def test_original_attachment_cannot_supply_new_source_or_solution(path):
    value = result_v2()
    reference = value["regions"][2]["region_id"]
    if path == "step":
        value["solution_report"]["solution_steps"][0]["source_region_ids"] = [reference]
    elif path == "editorial":
        value["solution_report"]["editorial_region_ids"] = [reference]
    else:
        value["proposal"]["content_region_map"][0]["region_ids"] = [reference]
    _rehash(value)
    with pytest.raises(ValueError, match="unrelated"):
        ExternalItemLearningResultV2.model_validate(value)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_step",
        "unknown_choice",
        "false_match",
        "unbacked_disagreement",
        "undetermined_answer",
        "unmapped_score",
    ],
)
def test_report_and_source_inconsistencies_are_explicit(change):
    value = result_v2()
    report = value["solution_report"]
    if change == "duplicate_step":
        report["solution_steps"].append(report["solution_steps"][0])
    elif change == "unknown_choice":
        report["answer_labels"] = ["99"]
    elif change == "false_match":
        report["answer_labels"] = ["2"]
    elif change == "unbacked_disagreement":
        report["answer_cross_check"] = "DISAGREES"
    elif change == "undetermined_answer":
        report["answer_state"] = "UNDETERMINED"
    else:
        value["proposal"]["content_region_map"] = [
            x for x in value["proposal"]["content_region_map"] if x["content_path"] != "score"
        ]
    _rehash(value)
    with pytest.raises(ValueError):
        ExternalItemLearningResultV2.model_validate(value)


def test_successor_hash_does_not_accept_tampered_report():
    value = result_v2()
    value["solution_report"]["explanation"] = "해시 계산 후 바뀐 보고서"
    with pytest.raises(ValueError, match="hash differs"):
        ExternalItemLearningResultV2.model_validate(value)


def test_unstamped_defaults_cannot_produce_a_stored_result_that_fails_replay():
    value = result_v2()
    del value["proposal"]["content"]["body"][0]["caption"]
    _rehash(value)
    with pytest.raises(ValueError, match="not canonical"):
        ExternalItemLearningResultV2.model_validate(value)


def test_owner_stamps_validated_defaults_and_refuses_a_model_supplied_hash():
    value = result_v2()
    del value["proposal"]["content"]["body"][0]["caption"]
    value.pop("result_sha256")
    before = deepcopy(value)
    result = stamp_external_item_learning_result_v2(value)
    assert result.proposal.content.body[0].caption is None
    assert ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json")) == result
    assert value == before
    value["result_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        stamp_external_item_learning_result_v2(value)

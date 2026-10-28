"""Editorial correctness warnings must not become silent edits or rejected sources."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_catalog_service.creative_source_content import (
    CreativeSourceContentError,
    materialize_creative_source_content,
)

from tests.unit.test_external_item_learning_result_contract import _rehash, _result


def _disagreement():
    value = deepcopy(_result())
    value["status"] = "NEEDS_DECISION"
    value["regions"][1]["observed_text"] = "답: 3 (원본 답안)\n원본의 편집 해설이다."
    value["proposal"]["answer_cross_check"] = "DISAGREES"
    value["conflicts"] = [
        {
            "conflict_code": "ANSWER_DISAGREEMENT",
            "description": "독립 풀이와 원본의 답안이 일치하지 않는다.",
            "source_region_ids": [value["regions"][1]["region_id"]],
            "blocking": True,
        }
    ]
    _rehash(value)
    return value


def test_register_source_preserves_even_inconsistent_editorial_answer_and_full_warning():
    proposal = ExternalItemLearningResult.model_validate(_disagreement())
    original_result = proposal.model_dump(mode="json")
    registered = materialize_creative_source_content(proposal)
    assert registered.content.solution.correct_choice_ids == ("choice_3",)
    assert registered.content.solution.explanation == proposal.regions[1].observed_text
    assert registered.source_answer_mode == "EDITORIAL_SOURCE"
    assert registered.warning_codes == ("ANSWER_DISAGREEMENT",)
    assert registered.proposed_content_sha256 != registered.registered_content_sha256
    assert proposal.model_dump(mode="json") == original_result
    assert proposal.proposal.content.solution.correct_choice_ids == ("choice_1",)
    assert proposal.status == "NEEDS_DECISION" and proposal.conflicts[0].blocking


@pytest.mark.parametrize("text", ["원문 해설에 답안 표지가 없다.", "답: 2\n답: 3"])
def test_unreadable_or_ambiguous_source_answer_keeps_visible_unverified_status(text):
    value = _disagreement()
    value["regions"][1]["observed_text"] = text
    _rehash(value)
    registered = materialize_creative_source_content(
        ExternalItemLearningResult.model_validate(value)
    )
    assert registered.content.solution.correct_choice_ids == ("choice_1",)
    assert registered.source_answer_mode == "MODEL_PROPOSAL_UNVERIFIED"
    assert "SOURCE_EDITORIAL_ANSWER_NOT_UNAMBIGUOUS" in registered.warning_codes
    assert "ANSWER_DISAGREEMENT" in registered.warning_codes


def test_original_attachment_answer_is_never_used_to_fill_the_creative_item():
    value = _disagreement()
    value["regions"][1]["observed_text"] = "편집 해설에는 명확한 답안 표지가 없다."
    value["regions"][2]["observed_text"] = "답: 5"
    _rehash(value)
    registered = materialize_creative_source_content(
        ExternalItemLearningResult.model_validate(value)
    )
    assert registered.source_answer_mode == "MODEL_PROPOSAL_UNVERIFIED"
    assert registered.content.solution.correct_choice_ids != ("choice_5",)


def test_explicit_fullwidth_answer_separator_and_actual_choice_labels_are_supported():
    value = _disagreement()
    for index, choice in enumerate(value["proposal"]["content"]["interaction"]["choices"]):
        choice["label"] = chr(ord("\u2460") + index)
    value["regions"][1]["observed_text"] = "정답\uff1a \u2462 (원문)"
    _rehash(value)
    registered = materialize_creative_source_content(
        ExternalItemLearningResult.model_validate(value)
    )
    assert registered.content.solution.correct_choice_ids == ("choice_3",)


def test_missing_extraction_stays_explicit_instead_of_manufacturing_a_question():
    value = _disagreement()
    value["proposal"] = None
    value["conflicts"][0]["conflict_code"] = "UNREADABLE_CONTENT"
    _rehash(value)
    with pytest.raises(CreativeSourceContentError, match="CREATIVE_SOURCE_ITEM_UNREADABLE"):
        materialize_creative_source_content(ExternalItemLearningResult.model_validate(value))

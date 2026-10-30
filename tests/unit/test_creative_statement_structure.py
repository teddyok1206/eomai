"""Conditions are not judged propositions; missing explanations are never repaired."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.creative_source_draft import CREATIVE_SOURCE_STATEMENT_GUIDANCE
from eom_catalog_contracts.external_item_learning_result_v2 import (
    ExternalItemLearningResultV2,
    stamp_external_item_learning_result_v2,
)
from eom_workflow.schemas import load_codex_result_schema

from tests.unit.test_external_item_learning_result_contract import _rehash
from tests.unit.test_external_item_learning_result_v2 import result_v2


def test_both_creative_answer_branches_expose_statement_structure_and_coverage():
    current = load_codex_result_schema("external-item-learning-result@2.0")
    previous = load_codex_result_schema("external-item-learning-result@1.0")
    branches = current["$defs"]["CreativeSourceItemDraft"]["anyOf"]
    assert len(branches) == 2
    for branch in branches:
        properties = branch["properties"]
        assert CREATIVE_SOURCE_STATEMENT_GUIDANCE in properties["body"]["description"]
        explanations = properties["solution"]["properties"]["statement_explanations"]
        assert CREATIVE_SOURCE_STATEMENT_GUIDANCE in explanations["description"]
    assert CREATIVE_SOURCE_STATEMENT_GUIDANCE not in str(previous)


def _with_judged_statement():
    value = result_v2()
    content = value["proposal"]["content"]
    content["body"].append(
        {
            "block_id": "block_view",
            "type": "statement_set",
            "statements": [
                {"statement_id": "statement_giyeok", "label": "ㄱ", "text": "관계가 성립한다."},
                {"statement_id": "statement_nieun", "label": "ㄴ", "text": "다른 관계가 성립한다."},
            ],
        }
    )
    value["proposal"]["content_region_map"].append(
        {"content_path": "body[1]", "region_ids": [value["regions"][0]["region_id"]]}
    )
    content["solution"]["statement_explanations"] = [
        {"statement_id": "statement_giyeok", "text": "관측한 해설의 설명."},
        {"statement_id": "statement_nieun", "text": "관측한 두 번째 해설."},
    ]
    return stamp_external_item_learning_result_v2(
        {key: entry for key, entry in value.items() if key != "result_sha256"}
    ).model_dump(mode="json")


@pytest.mark.parametrize("change", ["missing", "extra_condition"])
def test_statement_coverage_still_fails_without_mutating_the_original_result(change):
    value = _with_judged_statement()
    ExternalItemLearningResultV2.model_validate(value)
    content = value["proposal"]["content"]
    if change == "missing":
        content["solution"]["statement_explanations"] = []
    else:
        # Reproduces 10369: a condition is declared as judged, but only 보기 has explanations.
        content["body"][1]["statements"].append(
            {"statement_id": "statement_condition_1", "label": "1", "text": "주어진 조건."}
        )
    _rehash(value)
    before = deepcopy(value)
    with pytest.raises(ValueError, match="statement explanations must exactly cover"):
        ExternalItemLearningResultV2.model_validate(value)
    assert value == before

"""Field policy is explicit, shared with generation, and cannot widen answer evidence."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.assessment_item import ItemSolution
from eom_catalog_contracts.creative_source_draft import (
    creative_source_field_region_roles,
    creative_source_region_policy_description,
)
from eom_catalog_contracts.external_item_learning_result import resolve_external_item_content_path
from eom_catalog_contracts.external_item_learning_result_v2 import (
    INDEPENDENT_SOURCE_SOLUTION_GUIDANCE,
    ExternalItemLearningResultV2,
)
from eom_workflow.schemas import load_codex_result_schema

from tests.unit.test_external_item_learning_result_contract import _rehash
from tests.unit.test_external_item_learning_result_v2 import result_v2, undetermined_result_v2

CONTENT = frozenset({"TARGET_ITEM"})
SOLUTION = CONTENT | {"EDITORIAL_SOLUTION"}
METADATA = SOLUTION | {"OTHER"}
FIELD_ROLES = {
    "title": CONTENT,
    "body[0]": CONTENT,
    "body[0].rows[0][1]": CONTENT,
    "interaction": CONTENT,
    "interaction.choices[0].text": CONTENT,
    "solution": SOLUTION,
    "solution.correct_choice_ids": SOLUTION,
    "solution.accepted_answers": SOLUTION,
    "solution.explanation": SOLUTION,
    "solution.statement_explanations": SOLUTION,
    "solution.authoring_intent": METADATA,
    "score": METADATA,
    "score.points": METADATA,
    "score.state": METADATA,
}


def mapped(path, role):
    value = result_v2()
    if role == "OTHER":
        metadata = deepcopy(value["regions"][0])
        metadata.update(
            region_id="extregion_" + "a" * 32, role="OTHER", observed_text="출제의도와 편집 메모"
        )
        value["regions"].append(metadata)
    identifier = next(region["region_id"] for region in value["regions"] if region["role"] == role)
    references = [identifier]
    if path == "solution.correct_choice_ids" and role != "EDITORIAL_SOLUTION":
        references.append(value["regions"][1]["region_id"])
    mappings = value["proposal"]["content_region_map"]
    existing = next((entry for entry in mappings if entry["content_path"] == path), None)
    if existing is None:
        mappings.append({"content_path": path, "region_ids": references})
    else:
        existing["region_ids"] = references
    _rehash(value)
    return value


@pytest.mark.parametrize("path,allowed", FIELD_ROLES.items())
@pytest.mark.parametrize(
    "role", ["TARGET_ITEM", "EDITORIAL_SOLUTION", "OTHER", "REFERENCE_ORIGINAL"]
)
def test_all_source_fields_against_all_region_roles(path, allowed, role):
    assert creative_source_field_region_roles(path) == allowed
    value = mapped(path, role)
    before = deepcopy(value)
    if role in allowed:
        parsed = ExternalItemLearningResultV2.model_validate(value)
        assert (
            parsed.proposal.content.solution.authoring_intent
            == value["proposal"]["content"]["solution"]["authoring_intent"]
        )
        assert ExternalItemLearningResultV2.model_validate(parsed.model_dump(mode="json")) == parsed
    else:
        with pytest.raises(ValueError, match="unrelated source regions"):
            ExternalItemLearningResultV2.model_validate(value)
    assert value == before


def test_every_solution_field_has_an_explicit_policy_and_metadata_does_not_widen_parent():
    expected = {
        "correct_choice_ids",
        "accepted_answers",
        "explanation",
        "authoring_intent",
        "statement_explanations",
    }
    assert set(ItemSolution.model_fields) == expected
    for field in ItemSolution.model_fields:
        assert creative_source_field_region_roles(f"solution.{field}") == (
            METADATA if field == "authoring_intent" else SOLUTION
        )
    assert creative_source_field_region_roles("solution") == SOLUTION
    assert creative_source_field_region_roles("solution.statement_explanations[0].text") == SOLUTION


def test_editorial_source_answer_still_requires_an_editorial_anchor():
    value = mapped("solution.correct_choice_ids", "TARGET_ITEM")
    entry = next(
        mapping
        for mapping in value["proposal"]["content_region_map"]
        if mapping["content_path"] == "solution.correct_choice_ids"
    )
    entry["region_ids"] = [value["regions"][0]["region_id"]]
    _rehash(value)
    with pytest.raises(ValueError, match="lacks an editorial anchor"):
        ExternalItemLearningResultV2.model_validate(value)


@pytest.mark.parametrize(
    "path",
    [
        "solution.authoring_intent_extra",
        "solution.answers",
        "solution_origin",
        "scoreboard",
        "bodyguard",
    ],
)
def test_similar_prefix_or_new_unknown_field_is_not_implicitly_authorized(path):
    with pytest.raises(ValueError, match="SOURCE_FIELD_UNKNOWN"):
        creative_source_field_region_roles(path)


def test_generation_uses_the_same_policy_without_modifying_the_historical_family():
    description = creative_source_region_policy_description()
    current = load_codex_result_schema("external-item-learning-result@2.0")
    previous = load_codex_result_schema("external-item-learning-result@1.0")
    key = "ExternalItemLearningResult_contentRegionMap"
    assert description in current["$defs"][key]["description"]
    assert description not in previous["$defs"][key].get("description", "")
    assert "solution.authoring_intent: EDITORIAL_SOLUTION, OTHER, TARGET_ITEM" in description
    assert "solution.explanation: EDITORIAL_SOLUTION, TARGET_ITEM" in description
    assert (
        current["$defs"]["ExternalItemLearningResultV2_solutionReport"]["description"]
        == INDEPENDENT_SOURCE_SOLUTION_GUIDANCE
    )


def test_no_matching_choice_finding_is_preserved_as_uncertainty_not_a_fabricated_choice():
    value = mapped("solution.authoring_intent", "OTHER")
    value["solution_report"]["answer_labels"] = ["제시된 선택지 없음"]
    value["solution_report"]["answer_cross_check"] = "DISAGREES"
    value["conflicts"] = [
        {
            "conflict_code": "ANSWER_DISAGREEMENT",
            "description": "독립 결론에 해당하는 선지가 없다.",
            "source_region_ids": [value["regions"][1]["region_id"]],
            "blocking": False,
        }
    ]
    _rehash(value)
    with pytest.raises(ValueError, match="not a declared source choice"):
        ExternalItemLearningResultV2.model_validate(value)
    valid = undetermined_result_v2()
    valid["solution_report"]["explanation"] = value["conflicts"][0]["description"]
    _rehash(valid)
    parsed = ExternalItemLearningResultV2.model_validate(valid)
    assert parsed.proposal.content.solution.correct_choice_ids == ("choice_1",)
    assert parsed.solution_report.answer_labels == ()
    assert parsed.solution_report.explanation == "독립 결론에 해당하는 선지가 없다."
    assert parsed.solution_report.editorial_region_ids
    assert parsed.status == "NEEDS_DECISION" and parsed.conflicts[0].blocking


def test_real_table_cell_and_legacy_scalar_paths_resolve_without_modifying_content():
    content = result_v2()["proposal"]["content"]
    before = deepcopy(content)
    assert resolve_external_item_content_path(content, "body[0].rows[0][1]") == "1"
    assert resolve_external_item_content_path(content, "interaction.choices[0].text") == "선지 1"
    assert resolve_external_item_content_path(content, "score.points") is None
    assert content == before


@pytest.mark.parametrize(
    "path",
    [
        "body[0].rows[0][2]",
        "body[0].rows[8][0]",
        "body[-1]",
        "body[0].rows[0][-1]",
        "body[0].rows[0][x]",
        "body[0].rows[0][0]junk",
        "body[0].missing",
        "title[0]",
        "body[0].rows..value",
        "solution.__class__",
    ],
)
def test_missing_or_outside_or_invalid_content_path_remains_an_explicit_error(path):
    with pytest.raises(ValueError, match="does not resolve"):
        resolve_external_item_content_path(result_v2()["proposal"]["content"], path)


def test_unknown_or_duplicate_metadata_regions_are_not_normalized_away():
    value = mapped("solution.authoring_intent", "OTHER")
    entry = value["proposal"]["content_region_map"][-1]
    for references in (["extregion_" + "f" * 32], entry["region_ids"] * 2):
        broken = deepcopy(value)
        broken["proposal"]["content_region_map"][-1]["region_ids"] = references
        _rehash(broken)
        with pytest.raises(ValueError):
            ExternalItemLearningResultV2.model_validate(broken)

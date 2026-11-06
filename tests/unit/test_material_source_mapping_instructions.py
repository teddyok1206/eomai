"""Published instruction successor reinforces, but never relaxes, the existing source map."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningProposalV2
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import extraction_result

ROOT = Path(__file__).resolve().parents[2]


def test_mapping_instruction_successor_names_the_existing_required_leaf_paths():
    instructions = (
        ROOT / "config/control-plane/material-learning-v2/instructions/source-region-mapping.md"
    ).read_text()
    proposal = ExternalItemLearningProposalV2.model_validate(extraction_result()["proposal"])
    paths = {mapping.content_path for mapping in proposal.content_region_map}
    assert {
        "title",
        "interaction",
        "score",
        "solution.explanation",
        "solution.correct_choice_ids",
    } <= paths
    for required in (
        "title",
        "interaction",
        "score",
        "body[i]",
        "solution.explanation",
        "solution.correct_choice_ids",
        "solution.accepted_answers",
    ):
        assert f"`{required}`" in instructions
    assert "does NOT replace" in instructions
    assert "EDITORIAL_SOLUTION" in instructions
    assert "solution_report" in instructions


def test_parent_solution_mapping_does_not_satisfy_existing_leaf_contract():
    value = deepcopy(extraction_result()["proposal"])
    mappings = value["content_region_map"]
    source_regions = mappings[0]["region_ids"]
    value["content_region_map"] = [
        mapping for mapping in mappings if not mapping["content_path"].startswith("solution.")
    ] + [{"content_path": "solution", "region_ids": source_regions}]
    with pytest.raises(ValidationError, match="complete unique region mapping"):
        ExternalItemLearningProposalV2.model_validate(value)

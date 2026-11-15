"""New source scores keep all existing region, answer and independent-solution rules."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.material_learning import (
    MaterialExtractionResult,
    MaterialExtractionResultV2,
    MaterialExtractionWork,
    validate_material_extraction,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.creative_source_content import materialize_source_observation_content
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_material_learning_contracts import extraction_result, extraction_work


def exact_result(points="1.5"):
    value = deepcopy(extraction_result())
    value["schema_version"] = "material-learning-extraction-result/2.0"
    value["proposal"]["content"]["schema_version"] = "creative-source-item-draft/2.0"
    value["proposal"]["content"]["score"] = {"state": "PRINTED", "points": points}
    return value


@pytest.mark.parametrize("points", ["1.5", "2.5", 2])
def test_extraction_roundtrips_exact_scores_with_original_solution_and_regions(points):
    value = exact_result(points)
    validate_contract("material-learning-extraction-result-v2", value)
    result = MaterialExtractionResultV2.model_validate(value)
    validate_material_extraction(result, MaterialExtractionWork.model_validate(extraction_work()))
    snapshot = result.model_dump(mode="json")
    content = materialize_source_observation_content(result, resolved_images={})
    assert content.content.score.points == points
    assert result.model_dump(mode="json") == snapshot
    assert content.content.solution == result.proposal.content.solution
    assert result.solution_report.model_dump(mode="json") == value["solution_report"]
    assert result.regions == MaterialExtractionResult.model_validate(extraction_result()).regions


def test_old_result_never_accepts_the_successor_or_fractional_draft():
    value = exact_result()
    with pytest.raises(ValueError):
        MaterialExtractionResult.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("material-learning-extraction-result-v1", value)


@pytest.mark.parametrize(
    "change",
    [
        "missing_body_mapping",
        "unknown_region",
        "answer_mismatch",
        "missing_score_mapping",
        "wrong_input",
    ],
)
def test_old_closure_and_input_binding_rules_still_apply(change):
    value = exact_result()
    proposal = value["proposal"]
    if change == "missing_body_mapping":
        proposal["content_region_map"] = [
            entry for entry in proposal["content_region_map"] if entry["content_path"] != "body[0]"
        ]
    elif change == "missing_score_mapping":
        proposal["content_region_map"] = [
            entry for entry in proposal["content_region_map"] if entry["content_path"] != "score"
        ]
    elif change == "unknown_region":
        proposal["content_region_map"][0]["region_ids"] = ["extregion_" + "f" * 32]
    elif change == "answer_mismatch":
        value["solution_report"]["answer_labels"] = ["unknown"]
    else:
        value["input_sha256"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError):
        result = MaterialExtractionResultV2.model_validate(value)
        validate_material_extraction(
            result, MaterialExtractionWork.model_validate(extraction_work())
        )

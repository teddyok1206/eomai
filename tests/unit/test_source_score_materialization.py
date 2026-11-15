"""A fractional score changes neither the source blocks nor historical formats."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.assessment_item import (
    AssessmentItemContent,
    AssessmentItemContentV1_1,
)
from eom_catalog_contracts.creative_source_draft import (
    CreativeSourceItemDraft,
    CreativeSourceItemDraftV2,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.creative_source_draft_materialization import (
    materialize_creative_source_draft,
)
from eom_catalog_service.item_content_contract import read_item_content
from jsonschema.exceptions import ValidationError as SchemaValidationError

from tests.unit.test_creative_source_draft import draft_value, resolved_image


@pytest.mark.parametrize("points", ["1.5", "2.5", "99.5"])
def test_half_points_survive_without_mutating_source_or_editorial_content(points):
    value = draft_value()
    value["schema_version"] = "creative-source-item-draft/2.0"
    value["score"] = {"state": "PRINTED", "points": points}
    before = deepcopy(value)
    validate_contract("creative-source-item-draft-v2", value)
    draft = CreativeSourceItemDraftV2.model_validate(value)
    draft_before = draft.model_dump(mode="json")
    image = resolved_image()
    result = materialize_creative_source_draft(draft, resolved_images={image.block_id: image})
    assert isinstance(result.content, AssessmentItemContentV1_1)
    assert result.content.schema_version == "1.1"
    assert result.content.score.points == points
    assert type(result.content.score.points) is str
    validate_contract("assessment-item-content-v1_1", result.content.model_dump(mode="json"))
    assert result.content.solution == draft.solution
    assert result.content.body[:-1] == draft.body[:-1]
    assert result.content.body[-1] == image
    assert value == before
    assert draft.model_dump(mode="json") == draft_before
    assert result.warning_codes == ()
    with pytest.raises(SchemaValidationError):
        validate_contract("assessment-item-content", result.content.model_dump(mode="json"))
    with pytest.raises(ValueError):
        result.content.score.points = 15


@pytest.mark.parametrize(
    "score", [{"state": "PRINTED", "points": 2}, {"state": "UNPRINTED", "points": None}]
)
def test_integer_and_unprinted_drafts_keep_the_exact_old_materialization(score):
    value = draft_value()
    value["score"] = score
    old = CreativeSourceItemDraft.model_validate(value)
    value["schema_version"] = "creative-source-item-draft/2.0"
    new = CreativeSourceItemDraftV2.model_validate(value)
    image = resolved_image()
    images = {image.block_id: image}
    old_result = materialize_creative_source_draft(old, resolved_images=images)
    new_result = materialize_creative_source_draft(new, resolved_images=images)
    assert old_result == new_result
    assert isinstance(new_result.content, AssessmentItemContent)
    validate_contract("assessment-item-content", new_result.content.model_dump(mode="json"))


@pytest.mark.parametrize("points", [1.5, True, "1.50", "0.25", "1.5 "])
def test_both_typed_and_wire_successors_reject_coercion(points):
    value = draft_value()
    value["schema_version"] = "creative-source-item-draft/2.0"
    value["score"] = {"state": "PRINTED", "points": points}
    with pytest.raises(ValueError):
        CreativeSourceItemDraftV2.model_validate(value)
    with pytest.raises(SchemaValidationError):
        validate_contract("creative-source-item-draft-v2", value)


def test_new_draft_preserves_the_old_reference_closure():
    value = draft_value()
    value["schema_version"] = "creative-source-item-draft/2.0"
    value["score"] = {"state": "PRINTED", "points": "1.5"}
    value["solution"]["correct_choice_ids"] = ["choice_absent"]
    with pytest.raises(ValueError, match="correct choice pointer does not resolve"):
        CreativeSourceItemDraftV2.model_validate(value)


@pytest.mark.parametrize(
    "schema",
    ["eom.assessment.item-content/1.1", "eom://schemas/item-registry/assessment-item-content-v1_1"],
)
def test_official_reader_preserves_exact_version_and_rejects_old_schema_alias(schema):
    value = draft_value()
    value["schema_version"] = "creative-source-item-draft/2.0"
    value["score"] = {"state": "PRINTED", "points": "2.5"}
    draft = CreativeSourceItemDraftV2.model_validate(value)
    image = resolved_image()
    content = materialize_creative_source_draft(
        draft, resolved_images={image.block_id: image}
    ).content
    document = content.model_dump(mode="json")
    assert read_item_content(schema, document) == content
    with pytest.raises(SchemaValidationError):
        read_item_content("eom.assessment.item-content/1.0", document)

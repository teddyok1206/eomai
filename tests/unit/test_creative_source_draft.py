"""Source visual recipes and absent scores do not require invented evidence."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.assessment_item import ImageBlock
from eom_catalog_contracts.creative_source_draft import (
    CreativeSourceItemDraft,
    validate_source_draft_visual_regions,
)
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningRegion
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.creative_source_draft_materialization import (
    materialize_creative_source_draft,
)

from tests.unit.test_external_item_learning_result_contract import _result

TARGET, VISUAL, ORIGINAL = ("extregion_" + character * 32 for character in "abc")


def draft_value():
    value = deepcopy(_result()["proposal"]["content"])
    value["schema_version"] = "creative-source-item-draft/1.0"
    value["score"] = {"state": "UNPRINTED", "points": None}
    value["solution_origin"] = "EDITORIAL_SOURCE"
    value["body"].append(
        {
            "block_id": "block_source_diagram",
            "type": "source_image",
            "purpose": "stimulus",
            "source_region_id": VISUAL,
            "target_region_id": TARGET,
            "alt_text": "원본 실험 장치",
        }
    )
    return value


def source_regions():
    return tuple(
        ExternalItemLearningRegion.model_validate(
            {
                "region_id": identifier,
                "role": role,
                "physical_page": 1,
                "bounding_box": dict(zip(("left", "top", "right", "bottom"), bounds, strict=True)),
                "observed_text": "관측한 원본 영역",
                "confidence_milli": 990,
            }
        )
        for identifier, role, bounds in (
            (TARGET, "TARGET_ITEM", (100, 100, 9000, 9000)),
            (VISUAL, "TARGET_ITEM", (1000, 1500, 4000, 3000)),
            (ORIGINAL, "REFERENCE_ORIGINAL", (9100, 100, 9999, 9000)),
        )
    )


def resolved_image():
    return ImageBlock.model_validate(
        {
            "block_id": "block_source_diagram",
            "type": "image",
            "purpose": "stimulus",
            "artifact": {
                "artifact_id": "artifact_" + "1" * 32,
                "artifact_revision_id": "rev_" + "2" * 32,
                "artifact_member": "images/crop.png",
                "sha256": "sha256:" + "3" * 64,
                "media_type": "image/png",
            },
            "alt_text": "원본 실험 장치",
            "width_px": 320,
            "height_px": 160,
        }
    )


def test_draft_is_schema_valid_without_fabricated_media_or_printed_score():
    value = draft_value()
    validate_contract("creative-source-item-draft-v1", value)
    draft = CreativeSourceItemDraft.model_validate(value)
    validate_source_draft_visual_regions(draft, source_regions())
    assert draft.score.state == "UNPRINTED" and draft.score.points is None
    assert "artifact" not in type(draft.body[-1]).model_fields


def test_native_source_and_independent_warning_are_preserved_after_owner_materialization():
    value = draft_value()
    value["solution_origin"] = "INDEPENDENT_PROPOSAL_UNVERIFIED"
    draft = CreativeSourceItemDraft.model_validate(value)
    before = draft.model_dump(mode="json")
    image = resolved_image()
    materialized = materialize_creative_source_draft(draft, resolved_images={image.block_id: image})
    assert materialized.content.score.points == 0
    assert materialized.source_score_state == "UNPRINTED"
    assert materialized.warning_codes == ("SOURCE_SCORE_NOT_PRINTED", "SOURCE_SOLUTION_UNVERIFIED")
    assert materialized.content.solution == draft.solution
    assert materialized.content.body[:-1] == draft.body[:-1]
    assert materialized.content.body[-1] == image
    assert draft.model_dump(mode="json") == before


@pytest.mark.parametrize("points", [0, 2, 3])
def test_printed_zero_is_distinct_from_unprinted_score(points):
    value = draft_value()
    value["score"] = {"state": "PRINTED", "points": points}
    draft = CreativeSourceItemDraft.model_validate(value)
    image = resolved_image()
    materialized = materialize_creative_source_draft(draft, resolved_images={image.block_id: image})
    assert materialized.content.score.points == points
    assert materialized.source_score_state == "PRINTED"
    assert materialized.warning_codes == ()


def test_unprinted_score_cannot_smuggle_a_guessed_value():
    value = draft_value()
    value["score"]["points"] = 3
    with pytest.raises(ValueError):
        CreativeSourceItemDraft.model_validate(value)


def test_model_cannot_emit_a_fake_artifact_pointer_instead_of_source_recipe():
    value = draft_value()
    value["body"][-1]["artifact"] = resolved_image().artifact.model_dump(mode="json")
    with pytest.raises(ValueError):
        CreativeSourceItemDraft.model_validate(value)


@pytest.mark.parametrize("failure", ["missing", "role", "page", "outside", "overlap", "duplicate"])
def test_source_visual_geometry_and_role_closure_fail_explicitly(failure):
    regions = list(source_regions())
    raw = [region.model_dump(mode="json") for region in regions]
    if failure == "missing":
        raw.pop(1)
    elif failure == "role":
        raw[1]["role"] = "EDITORIAL_SOLUTION"
    elif failure == "page":
        raw[1]["physical_page"] = 2
    elif failure == "outside":
        raw[1]["bounding_box"]["left"] = 50
    elif failure == "overlap":
        raw[2]["bounding_box"] = {"left": 3000, "top": 2000, "right": 5500, "bottom": 3500}
    else:
        raw.append(raw[1])
    regions = tuple(ExternalItemLearningRegion.model_validate(value) for value in raw)
    with pytest.raises(ValueError, match="CREATIVE_DRAFT_"):
        validate_source_draft_visual_regions(
            CreativeSourceItemDraft.model_validate(draft_value()), regions
        )


@pytest.mark.parametrize("failure", ["missing", "extra", "wrong_block", "changed_alt"])
def test_materialization_never_silently_substitutes_resolved_media(failure):
    image = resolved_image()
    resolved = {image.block_id: image}
    if failure == "missing":
        resolved = {}
    elif failure == "extra":
        resolved["block_extra"] = image
    else:
        field = "block_id" if failure == "wrong_block" else "alt_text"
        resolved[image.block_id] = image.model_copy(update={field: "block_other"})
    with pytest.raises(ValueError, match="CREATIVE_DRAFT_RESOLVED_IMAGE"):
        materialize_creative_source_draft(
            CreativeSourceItemDraft.model_validate(draft_value()), resolved_images=resolved
        )

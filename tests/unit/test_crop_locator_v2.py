from __future__ import annotations

from eom_image_contracts import ImageEvaluationBoundingBox, ScienceVisualLocatorPolicyV2
from eom_image_trainer.crop_locator import LocatedVisualRegion, filter_visual_regions_v2
from PIL import Image, ImageDraw  # type: ignore[import-not-found]


def _policy(**overrides: int) -> ScienceVisualLocatorPolicyV2:
    value = {
        "max_candidates_per_page": 4,
        "max_candidates_per_source": 12,
        "maximum_redaction_area_milli": 350,
        "minimum_interior_ink_milli": 8,
        "maximum_border_ink_fraction_milli": 650,
        "minimum_aspect_ratio_milli": 200,
        "maximum_aspect_ratio_milli": 5000,
    }
    value.update(overrides)
    return ScienceVisualLocatorPolicyV2.model_validate(value)


def _region(
    *,
    left: int = 1000,
    top: int = 1000,
    right: int = 9000,
    bottom: int = 9000,
    redactions: tuple[ImageEvaluationBoundingBox, ...] = (),
    rank: int = 1,
) -> LocatedVisualRegion:
    return LocatedVisualRegion(
        crop_bounding_box=ImageEvaluationBoundingBox(
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        ),
        redaction_boxes=redactions,
        candidate_rank=rank,
        ink_fraction_milli=100,
    )


def test_locator_v2_rejects_empty_answer_frame_but_keeps_internal_table_grid() -> None:
    empty_frame = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(empty_frame).rectangle((40, 40, 359, 359), outline="black", width=4)

    table = empty_frame.copy()
    drawing = ImageDraw.Draw(table)
    for coordinate in (120, 200, 280):
        drawing.line((coordinate, 40, coordinate, 359), fill="black", width=4)
        drawing.line((40, coordinate, 359, coordinate), fill="black", width=4)

    assert filter_visual_regions_v2(empty_frame, regions=(_region(),), policy=_policy()) == ()
    assert len(filter_visual_regions_v2(table, regions=(_region(),), policy=_policy())) == 1


def test_locator_v2_rejects_redaction_dominant_region_and_thin_rule() -> None:
    image = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(image).ellipse((100, 100, 300, 300), outline="black", width=8)
    redaction = ImageEvaluationBoundingBox(left=1500, top=1500, right=8500, bottom=8500)

    assert (
        filter_visual_regions_v2(
            image,
            regions=(_region(redactions=(redaction,)),),
            policy=_policy(),
        )
        == ()
    )
    assert (
        filter_visual_regions_v2(
            image,
            regions=(_region(left=500, top=4500, right=9500, bottom=4700),),
            policy=_policy(),
        )
        == ()
    )


def test_locator_v2_keeps_plot_and_apparatus_and_applies_deterministic_cap() -> None:
    image = Image.new("RGB", (400, 400), "white")
    drawing = ImageDraw.Draw(image)
    drawing.line((60, 340, 340, 340), fill="black", width=4)
    drawing.line((60, 340, 60, 60), fill="black", width=4)
    drawing.line((70, 320, 160, 220, 250, 240, 330, 100), fill="black", width=5)
    drawing.ellipse((110, 110, 290, 290), outline="black", width=6)
    drawing.line((200, 110, 200, 290), fill="black", width=5)

    regions = tuple(_region(rank=index + 1) for index in range(4))
    result = filter_visual_regions_v2(
        image,
        regions=regions,
        policy=_policy(max_candidates_per_page=2),
    )

    assert len(result) == 2
    assert tuple(value.candidate_rank for value in result) == (1, 2)
    assert result[0].ink_fraction_milli >= 8

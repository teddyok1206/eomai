from __future__ import annotations

import pytest
from eom_image_candidate_runner.layout_lock import LayoutLockError, lock_reference_layout
from PIL import Image, ImageDraw


def _box_image(size: tuple[int, int], bounds: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(bounds, fill="black")
    return image


def test_layout_lock_maps_reference_bounds_and_retains_raw_measurement() -> None:
    conditioning = _box_image((800, 504), (100, 101, 299, 301))
    raw = _box_image((800, 500), (20, 30, 719, 429))

    outcome = lock_reference_layout(
        conditioning=conditioning,
        raw_candidate=raw,
        threshold=245,
    )

    assert outcome.reference_bbox.model_dump() == {
        "x_min": 100,
        "y_min": 100,
        "x_max": 300,
        "y_max": 300,
    }
    assert outcome.locked_candidate_bbox == outcome.reference_bbox
    assert outcome.raw_candidate_bbox.model_dump() == {
        "x_min": 20,
        "y_min": 30,
        "x_max": 720,
        "y_max": 430,
    }
    assert outcome.raw_area_ratio_milli == 7000
    assert outcome.raw_center_distance_milli > 0
    assert outcome.image.size == (800, 500)


def test_layout_lock_rejects_empty_or_wrong_size_raster() -> None:
    white_conditioning = Image.new("RGB", (800, 504), "white")
    raw = _box_image((800, 500), (20, 30, 200, 100))
    with pytest.raises(LayoutLockError, match="foreground is empty"):
        lock_reference_layout(
            conditioning=white_conditioning,
            raw_candidate=raw,
            threshold=245,
        )

    with pytest.raises(LayoutLockError, match="dimensions"):
        lock_reference_layout(
            conditioning=_box_image((800, 504), (10, 10, 20, 20)),
            raw_candidate=Image.new("RGB", (799, 500), "white"),
            threshold=245,
        )

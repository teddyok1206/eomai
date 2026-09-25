from __future__ import annotations

from io import BytesIO

from eom_image_contracts import ImageEvaluationBoundingBox
from eom_image_trainer.crop_processing import (
    PerceptualIndex,
    average_hash,
    materialize_training_crop,
    png_bytes,
)
from PIL import Image


def test_materialize_training_crop_applies_redaction_before_resize() -> None:
    source = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(20, 80):
        for y in range(20, 80):
            source.putpixel((x, y), (0, 0, 0))
    crop = materialize_training_crop(
        source,
        crop_box=ImageEvaluationBoundingBox(left=1000, top=1000, right=9000, bottom=9000),
        redaction_boxes=(
            ImageEvaluationBoundingBox(left=2000, top=2000, right=8000, bottom=8000),
        ),
    )
    assert crop.size == (768, 512)
    assert crop.getpixel((384, 256)) == (255, 255, 255)
    payload = png_bytes(crop)
    with Image.open(BytesIO(payload)) as decoded:
        assert decoded.size == (768, 512)
        assert decoded.mode == "RGB"


def test_perceptual_index_rejects_exact_and_near_duplicate() -> None:
    first = Image.new("RGB", (768, 512), (255, 255, 255))
    for value in range(100, 300):
        first.putpixel((value, 250), (0, 0, 0))
    second = first.copy()
    first_hash, first_value = average_hash(first)
    second_hash, second_value = average_hash(second)
    assert first_hash == second_hash
    index = PerceptualIndex()
    assert not index.contains_near_duplicate(first_value)
    index.add(first_value)
    assert index.contains_near_duplicate(second_value)

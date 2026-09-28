from __future__ import annotations

import hashlib
import io

import pytest
from eom_image_contracts import LocalImageReferenceSimplification
from eom_image_provider.reference_simplification import (
    ReferenceSimplificationError,
    simplify_visual_reference,
)
from PIL import Image, ImageDraw  # type: ignore[import-not-found]


def _reference_png(*, cluttered_border: bool = False, texture: bool = False) -> bytes:
    image = Image.new("RGB", (800, 504), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((180, 92, 620, 412), fill=(205, 205, 205), outline=(20, 20, 20), width=5)
    drawing.line((245, 252, 555, 252), fill=(40, 40, 40), width=4)
    if texture:
        for x in range(220, 581, 8):
            drawing.line((x, 130, x, 374), fill=(120, 120, 120), width=1)
        for y in range(130, 375, 8):
            drawing.line((220, y, 580, y), fill=(135, 135, 135), width=1)
    if cluttered_border:
        drawing.rectangle((0, 0, 799, 60), fill=(30, 30, 30))
        drawing.rectangle((0, 443, 799, 503), fill=(30, 30, 30))
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9)
    return target.getvalue()


def test_reference_simplification_is_deterministic_bounded_and_self_describing() -> None:
    source = _reference_png(texture=True)
    policy = LocalImageReferenceSimplification()

    first = simplify_visual_reference(source, policy=policy)
    second = simplify_visual_reference(source, policy=policy)

    assert first == second
    assert first.output.member_path == "reference-conditioning.png"
    assert first.output.sha256 == "sha256:" + hashlib.sha256(first.png_bytes).hexdigest()
    assert first.output.size_bytes == len(first.png_bytes)
    assert first.metrics.conditioning_edge_density < first.metrics.source_edge_density
    assert first.metrics.border_foreground_ratio == 0
    with Image.open(io.BytesIO(first.png_bytes)) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (800, 504)
        assert sum(1 for count in image.convert("L").histogram() if count) <= 4


def test_reference_simplification_rejects_cluttered_border_without_segmentation() -> None:
    with pytest.raises(
        ReferenceSimplificationError,
        match="REFERENCE_SIMPLIFICATION_BACKGROUND_COMPLEX",
    ):
        simplify_visual_reference(
            _reference_png(cluttered_border=True),
            policy=LocalImageReferenceSimplification(),
        )


def test_reference_simplification_rejects_wrong_canvas_and_nearly_empty_input() -> None:
    target = io.BytesIO()
    Image.new("RGB", (799, 504), "white").save(target, format="PNG")
    with pytest.raises(
        ReferenceSimplificationError,
        match="REFERENCE_SIMPLIFICATION_INPUT_INVALID",
    ):
        simplify_visual_reference(
            target.getvalue(),
            policy=LocalImageReferenceSimplification(),
        )

    empty = io.BytesIO()
    Image.new("RGB", (800, 504), "white").save(empty, format="PNG")
    with pytest.raises(
        ReferenceSimplificationError,
        match="REFERENCE_SIMPLIFICATION_FOREGROUND_INVALID",
    ):
        simplify_visual_reference(
            empty.getvalue(),
            policy=LocalImageReferenceSimplification(),
        )

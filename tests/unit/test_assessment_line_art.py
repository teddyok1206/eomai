from __future__ import annotations

import io

import pytest
from eom_image_contracts import LocalImageAssessmentLineArtPostprocess
from eom_image_provider.assessment_line_art import (
    AssessmentLineArtError,
    assessment_line_art,
)
from PIL import Image, ImageDraw  # type: ignore[import-not-found]


def _textured_subject_png() -> bytes:
    image = Image.new("RGB", (800, 500), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((190, 90, 610, 410), fill=(164, 148, 132), outline=(42, 42, 42), width=9)
    for x in range(220, 590, 24):
        drawing.line((x, 115, x - 40, 385), fill=(96, 89, 82), width=4)
    for y in range(145, 370, 28):
        drawing.arc((215, y - 38, 585, y + 38), 8, 172, fill=(56, 56, 56), width=4)
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9)
    return target.getvalue()


def test_assessment_line_art_is_deterministic_grayscale_and_border_safe() -> None:
    policy = LocalImageAssessmentLineArtPostprocess()
    first = assessment_line_art(_textured_subject_png(), policy=policy)
    second = assessment_line_art(_textured_subject_png(), policy=policy)

    assert first == second
    assert policy.foreground_ratio_min <= first.metrics.output_foreground_ratio
    assert first.metrics.output_foreground_ratio <= policy.foreground_ratio_max
    assert first.metrics.output_border_foreground_ratio == 0
    assert policy.edge_density_min <= first.metrics.output_edge_density
    assert first.metrics.output_edge_density <= policy.edge_density_max
    with Image.open(io.BytesIO(first.png_bytes)) as output:
        output.load()
        assert output.mode == "RGB"
        assert output.size == (800, 500)
        red, green, blue = output.split()
        assert red.tobytes() == green.tobytes() == blue.tobytes()
        assert {value for value, count in enumerate(red.histogram()) if count} <= set(
            policy.output_tones
        )
        assert output.getpixel((0, 0)) == (255, 255, 255)


def test_assessment_line_art_rejects_blank_output() -> None:
    image = Image.new("RGB", (800, 500), "white")
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9)

    with pytest.raises(
        AssessmentLineArtError,
        match="LOCAL_IMAGE_LINE_ART_FOREGROUND_INVALID",
    ):
        assessment_line_art(
            target.getvalue(),
            policy=LocalImageAssessmentLineArtPostprocess(),
        )

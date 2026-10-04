from __future__ import annotations

import io

import pytest
from eom_image_contracts import (
    LocalImageAssessmentLineArtMetricsV2,
    LocalImageAssessmentLineArtPostprocess,
    LocalImageAssessmentLineArtPostprocessV2,
    LocalImageAssessmentLineArtRuntimeV2,
)
from eom_image_contracts.visual_reference import LineArtPolicyViolation
from eom_image_provider.assessment_line_art import (
    AssessmentLineArtError,
    assessment_line_art,
    assessment_line_art_v2,
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


@pytest.mark.parametrize(
    ("field", "invalid", "code"),
    [
        ("output_foreground_ratio", 0.99, "LOCAL_IMAGE_LINE_ART_FOREGROUND_INVALID"),
        ("output_border_foreground_ratio", 0.99, "LOCAL_IMAGE_LINE_ART_BORDER_INVALID"),
        ("output_edge_density", 0.99, "LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID"),
        ("output_fine_detail_ratio", 0.99, "LOCAL_IMAGE_LINE_ART_FINE_DETAIL_INVALID"),
        ("output_tiny_component_ratio", 0.99, "LOCAL_IMAGE_LINE_ART_TINY_COMPONENTS_INVALID"),
        ("output_component_count", 400_000, "LOCAL_IMAGE_LINE_ART_COMPONENT_COUNT_INVALID"),
    ],
)
def test_shared_v2_policy_uses_typed_stable_errors(field, invalid, code):
    policy = LocalImageAssessmentLineArtPostprocessV2()
    valid = dict(
        input_foreground_ratio=0.1,
        output_foreground_ratio=0.1,
        output_border_foreground_ratio=0,
        input_edge_density=0.05,
        output_edge_density=0.05,
        output_fine_detail_ratio=0,
        output_tiny_component_ratio=0,
        output_component_count=1,
    )
    LocalImageAssessmentLineArtMetricsV2.model_validate(valid).validate_policy(policy)
    invalid_metrics = LocalImageAssessmentLineArtMetricsV2.model_validate({**valid, field: invalid})
    with pytest.raises(LineArtPolicyViolation) as raised:
        invalid_metrics.validate_policy(policy)
    assert raised.value.code == code and isinstance(raised.value, ValueError)


def _textured_subject_with_speckles_png() -> bytes:
    with Image.open(io.BytesIO(_textured_subject_png())) as source:
        image = source.copy()
    drawing = ImageDraw.Draw(image)
    for x, y in ((105, 85), (680, 95), (120, 420), (690, 405)):
        drawing.rectangle((x, y, x + 3, y + 3), fill=(32, 32, 32))
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


def test_assessment_line_art_v2_is_deterministic_and_detail_bounded() -> None:
    policy = LocalImageAssessmentLineArtPostprocessV2()
    first = assessment_line_art_v2(_textured_subject_png(), policy=policy)
    second = assessment_line_art_v2(_textured_subject_png(), policy=policy)

    assert first == second
    assert isinstance(first.metrics, LocalImageAssessmentLineArtMetricsV2)
    assert isinstance(first.runtime, LocalImageAssessmentLineArtRuntimeV2)
    assert first.metrics.output_fine_detail_ratio <= policy.fine_detail_fraction_max
    assert first.metrics.output_tiny_component_ratio <= policy.tiny_component_fraction_max
    assert first.metrics.output_component_count <= policy.component_count_max
    with Image.open(io.BytesIO(first.png_bytes)) as output:
        output.load()
        red, green, blue = output.split()
        assert red.tobytes() == green.tobytes() == blue.tobytes()
        assert {value for value, count in enumerate(red.histogram()) if count} <= set(
            policy.final_output_tones
        )


def test_assessment_line_art_v2_removes_detached_speckles_and_clears_full_border() -> None:
    policy = LocalImageAssessmentLineArtPostprocessV2()
    result = assessment_line_art_v2(_textured_subject_with_speckles_png(), policy=policy)

    assert result.metrics.output_tiny_component_ratio == 0
    with Image.open(io.BytesIO(result.png_bytes)) as output:
        output.load()
        assert output.crop((0, 0, 800, policy.vertical_border_px)).getextrema() == (
            (255, 255),
            (255, 255),
            (255, 255),
        )

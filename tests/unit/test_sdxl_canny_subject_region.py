"""Region retention is pixel protection, not object detection or final image quality."""

from __future__ import annotations

import io

import pytest
from eom_image_contracts.models import ImageEvaluationBoundingBox
from eom_image_contracts.sdxl_canny_conditioning import (
    SdxlCannyPolicy,
    validate_canny_retained_region,
)
from eom_image_provider import sdxl_canny_pixels as pixels
from eom_image_provider.provider import ProviderError
from PIL import Image, ImageDraw

POLICY = SdxlCannyPolicy()
RETAINED = ImageEvaluationBoundingBox(left=100, top=80, right=700, bottom=420)
PROTECTED = (ImageEvaluationBoundingBox(left=180, top=120, right=620, bottom=380),)


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()


def _source() -> Image.Image:
    image = Image.new("RGB", (832, 512), (0, 0, 0))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((200, 150, 610, 280), outline="white", width=1)
    for x in (245, 550):
        drawing.ellipse((x - 25, 260, x + 25, 310), outline="white", width=1)
    # Subject marks stay at the exact coordinates; unrelated exterior noise may disappear.
    drawing.line((20, 20, 810, 30), fill="white", width=2)
    drawing.line((20, 475, 810, 490), fill="white", width=2)
    return image


def test_retention_keeps_all_internal_pixels_and_removes_only_exterior() -> None:
    original = _source()
    payload = _png(original)
    final = pixels.retained_canny_conditioning_png(
        payload, policy=POLICY, retained_box=RETAINED, protected_boxes=PROTECTED
    )
    with Image.open(io.BytesIO(final)) as image:
        assert image.size == original.size and image.mode == "RGB"
        assert (
            image.crop((100, 80, 700, 420)).tobytes()
            == original.crop((100, 80, 700, 420)).tobytes()
        )
        assert image.crop((0, 0, 832, 80)).getbbox() is None
        assert image.crop((0, 420, 832, 512)).getbbox() is None
        assert image.crop((0, 80, 100, 420)).getbbox() is None
        assert image.crop((700, 80, 832, 420)).getbbox() is None
        # Clipping existing edges must not introduce a visible rectangle boundary.
        assert image.getpixel((100, 80)) == image.getpixel((699, 419)) == (0, 0, 0)
    assert pixels.canny_png_edge_count(final) < pixels.canny_png_edge_count(payload)
    assert (
        pixels.retained_canny_conditioning_png(
            payload, policy=POLICY, retained_box=RETAINED, protected_boxes=PROTECTED
        )
        == final
    )


def test_full_frame_is_byte_exact_identity_not_reencoding() -> None:
    payload = _png(_source())
    assert (
        pixels.retained_canny_conditioning_png(
            payload,
            policy=POLICY,
            retained_box=ImageEvaluationBoundingBox(left=0, top=0, right=832, bottom=512),
            protected_boxes=PROTECTED,
        )
        is payload
    )


def test_region_decode_is_single_and_does_not_reextract_canny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _png(_source())
    original_open = Image.open
    calls: list[object] = []

    def observed(*args: object, **kwargs: object) -> Image.Image:
        calls.append(args[0])
        return original_open(*args, **kwargs)  # type: ignore[arg-type]

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("region retention must not rerun a model/edge extractor")

    monkeypatch.setattr(Image, "open", observed)
    monkeypatch.setattr(pixels, "opencv_canny_pixels", forbidden)
    pixels.retained_canny_conditioning_png(
        payload, policy=POLICY, retained_box=RETAINED, protected_boxes=PROTECTED
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "retained,protected",
    [
        (ImageEvaluationBoundingBox(left=0, top=0, right=833, bottom=512), PROTECTED),
        (ImageEvaluationBoundingBox(left=0, top=0, right=832, bottom=513), PROTECTED),
        (RETAINED, ()),
        (RETAINED, PROTECTED * 2),
        (RETAINED, (ImageEvaluationBoundingBox(left=99, top=120, right=620, bottom=380),)),
        (RETAINED, (ImageEvaluationBoundingBox(left=180, top=120, right=701, bottom=380),)),
        (RETAINED, (ImageEvaluationBoundingBox(left=180, top=79, right=620, bottom=380),)),
        (RETAINED, (ImageEvaluationBoundingBox(left=180, top=120, right=620, bottom=421),)),
    ],
)
def test_invalid_or_unprotected_region_rejected_before_pixels(
    retained: ImageEvaluationBoundingBox,
    protected: tuple[ImageEvaluationBoundingBox, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid coordinates must fail before image decode")

    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError, match="SDXL_CANNY_RETAINED_REGION_"):
        validate_canny_retained_region(
            policy=POLICY, retained_box=retained, protected_boxes=protected
        )
    with pytest.raises(ProviderError, match="SDXL_CANNY_INPUT_INVALID"):
        pixels.retained_canny_conditioning_png(
            b"not read", policy=POLICY, retained_box=retained, protected_boxes=protected
        )


@pytest.mark.parametrize("fault", ["mode", "color", "tones", "dimensions", "empty", "corrupt"])
def test_invalid_control_pixels_rejected(fault: str) -> None:
    image = _source()
    if fault == "mode":
        image = image.convert("RGBA")
    elif fault == "color":
        image.putpixel((250, 180), (255, 0, 0))
    elif fault == "tones":
        image.putpixel((250, 180), (128, 128, 128))
    elif fault == "dimensions":
        image = image.crop((0, 0, 831, 512))
    elif fault == "empty":
        image = Image.new("RGB", (832, 512), (0, 0, 0))
    payload = b"corrupt PNG" if fault == "corrupt" else _png(image)
    with pytest.raises(ProviderError, match="SDXL_CANNY_EDGE_INVALID"):
        pixels.retained_canny_conditioning_png(
            payload, policy=POLICY, retained_box=RETAINED, protected_boxes=PROTECTED
        )


def test_no_retained_marks_cannot_become_valid_blank_control() -> None:
    image = Image.new("RGB", (832, 512), (0, 0, 0))
    image.putpixel((30, 30), (255, 255, 255))
    with pytest.raises(ProviderError, match="SDXL_CANNY_EDGE_INVALID"):
        pixels.retained_canny_conditioning_png(
            _png(image), policy=POLICY, retained_box=RETAINED, protected_boxes=PROTECTED
        )

"""Pixel preparation does not establish TRAIN authorization or generated-image quality."""

from __future__ import annotations

import hashlib
import io
from dataclasses import FrozenInstanceError

import pytest
from eom_image_contracts.sdxl_ip_style import SdxlIpStylePreprocessing
from eom_image_contracts.sdxl_native_lora import SdxlNativeLoraSample
from eom_image_contracts.sdxl_native_training_targets import NATIVE_TARGET_CANVASES
from eom_image_provider import sdxl_ip_style_pixels as pixels
from eom_image_provider.provider import ProviderError
from PIL import Image, ImageDraw

from tests.unit.test_sdxl_native_lora_contracts import _command_value


@pytest.fixture(autouse=True)
def synthetic_runtime_metadata(monkeypatch):
    # This unit environment has a different Pillow build. Geometry tests are not
    # pinned numerical acceptance; a separate real lab smoke must use11.3.0.
    monkeypatch.setattr(pixels.metadata, "version", lambda name: "11.3.0")


def _png(image, *, format="PNG", **kwargs):
    stream = io.BytesIO()
    image.save(stream, format=format, **kwargs)
    return stream.getvalue()


def _sample(raw, canvas="SQUARE_1024"):
    value = _command_value()["training_samples"][0]
    value["canvas"] = canvas
    value["source_image"]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return SdxlNativeLoraSample.model_validate(value)


def _prepare(raw, canvas="SQUARE_1024"):
    return pixels.prepare_sdxl_ip_style_pixels(
        raw, sample=_sample(raw, canvas), preprocessing=SdxlIpStylePreprocessing()
    )


def _denied(raw, code="SDXL_PROBE_INPUT_INVALID"):
    with pytest.raises(ProviderError) as error:
        _prepare(raw)
    assert error.value.code == code


@pytest.mark.parametrize(
    "canvas,fitted,offset",
    [
        ("SQUARE_1024", (224, 224), (0, 0)),
        ("PORTRAIT_768X1024", (168, 224), (28, 0)),
        ("LANDSCAPE_1024X768", (224, 168), (0, 28)),
    ],
)
def test_whole_frame_fit_retains_corners_gray_color_and_white_padding(canvas, fitted, offset):
    size = NATIVE_TARGET_CANVASES[canvas]
    image = Image.new("RGB", size, (160, 160, 160))
    draw = ImageDraw.Draw(image)
    for x, y, color in (
        (0, 0, "red"),
        (size[0] - 80, 0, "blue"),
        (0, size[1] - 80, "green"),
        (size[0] - 80, size[1] - 80, "black"),
    ):
        draw.rectangle((x, y, x + 79, y + 79), fill=color)
    raw = _png(image)
    result = _prepare(raw, canvas)
    repeated = _prepare(raw, canvas)
    assert result == repeated
    assert result.source.sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert result.fitted_size == fitted and result.offset == offset
    assert len(result.rgb_bytes) == 224 * 224 * 3
    assert result.rgb_sha256 == "sha256:" + hashlib.sha256(result.rgb_bytes).hexdigest()
    with Image.frombytes("RGB", (224, 224), result.rgb_bytes) as output:
        assert output.getpixel((112, 112)) == (160, 160, 160)
        for x, y, color in (
            (offset[0] + 3, offset[1] + 3, (255, 0, 0)),
            (offset[0] + fitted[0] - 4, offset[1] + 3, (0, 0, 255)),
            (offset[0] + 3, offset[1] + fitted[1] - 4, (0, 128, 0)),
            (offset[0] + fitted[0] - 4, offset[1] + fitted[1] - 4, (0, 0, 0)),
        ):
            assert output.getpixel((x, y)) == color
        if offset[0]:
            assert output.getpixel((offset[0] - 1, 112)) == (255, 255, 255)
            assert output.getpixel((offset[0] + fitted[0], 112)) == (255, 255, 255)
        if offset[1]:
            assert output.getpixel((112, offset[1] - 1)) == (255, 255, 255)
            assert output.getpixel((112, offset[1] + fitted[1])) == (255, 255, 255)
    with pytest.raises(FrozenInstanceError):
        result.offset = (1, 1)


def test_hash_failure_precedes_image_decode(monkeypatch):
    raw = _png(Image.new("RGB", (1024, 1024), "white"))
    sample = _sample(raw)

    def forbidden(*args, **kwargs):
        pytest.fail("hash-invalid bytes reached decoder")

    monkeypatch.setattr(pixels.Image, "open", forbidden)
    with pytest.raises(ProviderError) as error:
        pixels.prepare_sdxl_ip_style_pixels(
            raw + b"changed", sample=sample, preprocessing=SdxlIpStylePreprocessing()
        )
    assert error.value.code == "SDXL_PROBE_HASH_MISMATCH"


@pytest.mark.parametrize("fault", ["pillow", "profile", "sample-media", "sample-path"])
def test_pinned_runtime_profile_and_pointer_fail_before_decode(monkeypatch, fault):
    raw = _png(Image.new("RGB", (1024, 1024), "white"))
    sample, profile = _sample(raw), SdxlIpStylePreprocessing()
    if fault == "pillow":
        monkeypatch.setattr(pixels.metadata, "version", lambda name: "11.4.0")
    elif fault == "profile":
        profile = profile.model_copy(update={"processor_center_crop": True})
    else:
        pin = sample.source_image.model_copy(
            update={"media_type": "image/svg+xml"}
            if fault == "sample-media"
            else {"member_path": "../../escape.png"}
        )
        sample = sample.model_copy(update={"source_image": pin})

    def forbidden(*args, **kwargs):
        pytest.fail("invalid admission values reached decoder")

    monkeypatch.setattr(pixels.Image, "open", forbidden)
    with pytest.raises(ProviderError) as error:
        pixels.prepare_sdxl_ip_style_pixels(raw, sample=sample, preprocessing=profile)
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID"


@pytest.mark.parametrize("mode", ["L", "RGBA", "P"])
def test_wrong_pixel_mode_is_not_silently_normalized(mode):
    _denied(_png(Image.new(mode, (1024, 1024))))


@pytest.mark.parametrize("format", ["JPEG", "TIFF", "BMP"])
def test_other_media_is_not_silently_converted(format):
    _denied(_png(Image.new("RGB", (1024, 1024)), format=format))


def test_dimensions_fail_before_pixel_load(monkeypatch):
    raw = _png(Image.new("RGB", (2048, 2048), "white"))
    from PIL import PngImagePlugin

    def forbidden(*args, **kwargs):
        pytest.fail("wrong-size image reached pixel load")

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", forbidden)
    _denied(raw)


@pytest.mark.parametrize("raw", [b"", b"not a PNG", b"x" * (pixels.MAX_STYLE_PNG_BYTES + 1)])
def test_missing_malformed_or_over_budget_input_fails(raw):
    _denied(raw)


def test_multiframe_png_rejected():
    first = Image.new("RGB", (1024, 1024), "white")
    second = Image.new("RGB", (1024, 1024), "gray")
    _denied(_png(first, save_all=True, append_images=[second], duration=10))


def test_truncated_png_rejected_even_with_matching_byte_hash():
    raw = _png(Image.new("RGB", (1024, 1024), "gray"))
    _denied(raw[: len(raw) // 2])


def test_preprocessing_performs_no_network_model_or_file_write(monkeypatch):
    import builtins
    import socket

    raw = _png(Image.new("RGB", (1024, 1024), (200, 200, 200)))

    def forbidden(*args, **kwargs):
        pytest.fail("pixel preparation attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    # Distribution metadata was already verified in runtime-pin tests; isolate pixel behavior here.
    monkeypatch.setattr(pixels.metadata, "version", lambda name: "11.3.0")
    result = _prepare(raw)
    assert result.rgb_bytes[:3] == bytes((200, 200, 200))

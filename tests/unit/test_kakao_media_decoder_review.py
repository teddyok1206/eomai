"""Independent original-image decoder boundaries using anonymous synthetic fixtures."""

from __future__ import annotations

import builtins
import io
from unittest.mock import MagicMock

import pytest
from eom_catalog_service import kakao_media_publication as media
from PIL import Image

BINDING = "kakaobinding_" + "1" * 32


def image_bytes(kind="PNG", *, animated=False, orientation=None):
    output = io.BytesIO()
    with Image.new("RGB", (18, 12), (30, 70, 110)) as first:
        options = {}
        if orientation is not None:
            exif = first.getexif()
            exif[274] = orientation
            options["exif"] = exif
        if animated:
            with Image.new("RGB", (18, 12), (120, 80, 40)) as second:
                first.save(output, kind, save_all=True, append_images=[second], duration=100)
        else:
            first.save(output, kind, **options)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["PNG", "WEBP"])
def test_actual_animated_input_is_not_flattened_to_first_frame(kind):
    original = image_bytes(kind, animated=True)
    with Image.open(io.BytesIO(original)) as image:
        assert image.n_frames == 2
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_ANIMATION_UNSUPPORTED$"):
        media.inspect_kakao_media(BINDING, original)


@pytest.mark.parametrize("kind", ["GIF", "TIFF", "BMP", "PPM"])
def test_real_unsupported_format_never_becomes_an_allowed_receipt(kind):
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_DECODE_FAILED$"):
        media.inspect_kakao_media(BINDING, image_bytes(kind))


@pytest.mark.parametrize("kind", ["PNG", "JPEG", "WEBP"])
def test_actual_truncated_picture_is_rejected(kind):
    original = image_bytes(kind)
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_DECODE_FAILED$"):
        media.inspect_kakao_media(BINDING, original[: len(original) // 2])


@pytest.mark.parametrize("orientation", range(1, 9))
def test_all_exif_orientations_preserve_encoded_dimensions_and_original(orientation):
    original = image_bytes("JPEG", orientation=orientation)
    result = media.inspect_kakao_media(BINDING, original)
    assert (result.width_px, result.height_px, result.pixel_count) == (18, 12, 216)
    assert result.source_bytes == len(original)
    assert result.source_sha256 == media.sha256_bytes(original)
    with Image.open(io.BytesIO(original)) as image:
        assert image.getexif()[274] == orientation


def test_header_verify_is_not_a_substitute_for_actual_pixel_decode(monkeypatch):
    verified = MagicMock(size=(18, 12), format="PNG", n_frames=1)
    verified.__enter__.return_value = verified
    decoded = MagicMock(size=(18, 12), format="PNG")
    decoded.__enter__.return_value = decoded
    decoded.load.side_effect = OSError("private source details must not escape")
    monkeypatch.setattr(Image, "open", MagicMock(side_effect=[verified, decoded]))
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_DECODE_FAILED$") as error:
        media.inspect_kakao_media(BINDING, image_bytes())
    assert "private" not in str(error.value) and error.value.__suppress_context__
    verified.verify.assert_called_once()
    decoded.load.assert_called_once()


def test_optional_missing_decoder_fails_before_receipt_without_importing_worker(monkeypatch):
    original = image_bytes()
    imported = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("not installed")
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_DECODER_UNAVAILABLE$"):
        media.inspect_kakao_media(BINDING, original)


@pytest.mark.parametrize("input_value", [None, "not bytes", bytearray(b"abc"), memoryview(b"abc")])
def test_input_type_is_exact_bytes_before_decoder(input_value):
    with pytest.raises(ValueError, match=r"^KAKAO_ARCHIVE_MEDIA_SIZE_INVALID$"):
        media.inspect_kakao_media(BINDING, input_value)

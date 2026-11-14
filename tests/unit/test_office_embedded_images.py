from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import types
import zipfile
import zlib
from pathlib import Path

import pytest
from eom_image_contracts.models import content_sha256
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImageSet
from eom_image_contracts.validation import load_schema, validate_contract
from eom_image_provider.office_embedded_images import (
    OfficeEmbeddedImageError,
    _inflate,
    extract_office_embedded_images,
)
from PIL import Image


def raster(format: str = "PNG") -> bytes:
    image = Image.new("RGB", (19, 13), "white")
    # Non-white pixels on ALL four corners detect even one-row/column loss.
    for point, color in (
        ((0, 0), "red"),
        ((18, 0), "green"),
        ((0, 12), "blue"),
        ((18, 12), "black"),
    ):
        image.putpixel(point, Image.new("RGB", (1, 1), color).getpixel((0, 0)))
    output = io.BytesIO()
    image.save(output, format=format)
    return output.getvalue()


def hwpx(tmp_path: Path, members: tuple[tuple[str, bytes], ...]) -> Path:
    # Extension intentionally HWP: detection must use bytes, not the suffix.
    path = tmp_path / "original.hwp"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        for name, payload in members:
            archive.writestr(name, payload)
    return path


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("format", ["PNG", "BMP", "JPEG", "GIF", "TIFF"])
def test_whole_image_normalization_keeps_size_and_every_pixel(tmp_path: Path, format: str) -> None:
    raw = raster(format)
    source = hwpx(tmp_path, ((f"BinData/image.{format.lower()}", raw),))
    output = tmp_path / "output"
    result = extract_office_embedded_images(source, expected_sha256=sha(source), workspace=output)
    assert result.source_format == "HWPX"
    assert len(result.images) == 1
    image = result.images[0]
    assert (image.width_px, image.height_px) == (19, 13)
    with Image.open(io.BytesIO(raw)) as before, Image.open(output / image.member_path) as after:
        assert before.convert("RGBA").tobytes() == after.convert("RGBA").tobytes()
    if format == "PNG":
        assert (output / image.member_path).read_bytes() == raw
    assert (
        OfficeEmbeddedImageSet.model_validate_json((output / "embedded-images.json").read_bytes())
        == result
    )
    validate_contract("office-embedded-image-set", result.model_dump(mode="json"))
    assert source.read_bytes().startswith(b"PK")


def test_duplicate_rasters_have_one_output_but_separate_source_members(tmp_path: Path) -> None:
    raw = raster()
    source = hwpx(tmp_path, (("BinData/a.png", raw), ("BinData/b.png", raw)))
    output = tmp_path / "output"
    result = extract_office_embedded_images(source, expected_sha256=sha(source), workspace=output)
    assert len(result.images) == 2
    assert len(list((output / "images").iterdir())) == 1
    assert result.images[0].sha256 == result.images[1].sha256


@pytest.mark.parametrize("format", ["JPEG", "TIFF"])
def test_cmyk_images_preserve_every_decoded_pixel_when_saved_as_png(
    tmp_path: Path, format: str
) -> None:
    with Image.open(io.BytesIO(raster())) as original, original.convert("CMYK") as cmyk:
        encoded = io.BytesIO()
        cmyk.save(encoded, format=format)
    raw = encoded.getvalue()
    source = hwpx(tmp_path, ((f"BinData/image.{format.lower()}", raw),))
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert len(result.images) == 1 and result.unsupported_members == ()
    image = result.images[0]
    assert image.source_format == format
    assert image.source_member_sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()
    with (
        Image.open(io.BytesIO(raw)) as before,
        Image.open(tmp_path / "output" / image.member_path) as after,
    ):
        assert before.mode == "CMYK" and after.mode == "RGBA"
        assert before.size == after.size == (19, 13)
        assert before.convert("RGBA").tobytes() == after.tobytes()
        pixel_bytes = struct.pack("<II", *before.size) + before.convert("RGBA").tobytes()
        assert image.pixel_sha256 == "sha256:" + hashlib.sha256(pixel_bytes).hexdigest()


@pytest.mark.parametrize("mode", ["RGB", "L", "P", "RGBA"])
def test_png_modes_keep_original_bytes_including_palette_and_alpha(
    tmp_path: Path, mode: str
) -> None:
    with Image.open(io.BytesIO(raster())) as original, original.convert(mode) as pixels:
        if mode == "RGBA":
            pixels.putpixel((0, 0), (23, 45, 67, 89))
        encoded = io.BytesIO()
        pixels.save(encoded, format="PNG")
    raw = encoded.getvalue()
    source = hwpx(tmp_path, (("BinData/original.png", raw),))
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert (tmp_path / "output" / result.images[0].member_path).read_bytes() == raw


def test_rgb_jpeg_keeps_predecessor_png_encoding(tmp_path: Path) -> None:
    raw = raster("JPEG")
    with Image.open(io.BytesIO(raw)) as original:
        original.load()
        predecessor = io.BytesIO()
        original.save(predecessor, format="PNG", compress_level=9)
    source = hwpx(tmp_path, (("BinData/image.jpg", raw),))
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert (
        tmp_path / "output" / result.images[0].member_path
    ).read_bytes() == predecessor.getvalue()


def test_truncated_cmyk_jpeg_is_not_silently_repaired(tmp_path: Path) -> None:
    encoded = io.BytesIO()
    Image.new("CMYK", (19, 13), (17, 128, 192, 33)).save(encoded, format="JPEG")
    raw = encoded.getvalue()[:-20]
    source = hwpx(tmp_path, (("BinData/broken.jpg", raw),))
    with pytest.raises(OfficeEmbeddedImageError, match="RASTER_INVALID"):
        extract_office_embedded_images(
            source, expected_sha256=sha(source), workspace=tmp_path / "output"
        )


def test_cmyk_decompression_bomb_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoded = io.BytesIO()
    Image.new("CMYK", (19, 13), (17, 128, 192, 33)).save(encoded, format="JPEG")
    source = hwpx(tmp_path, (("BinData/image.jpg", encoded.getvalue()),))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    with pytest.raises(OfficeEmbeddedImageError, match="RASTER_INVALID"):
        extract_office_embedded_images(
            source, expected_sha256=sha(source), workspace=tmp_path / "output"
        )


def test_reference_images_are_not_implicitly_approved_for_the_item(tmp_path: Path) -> None:
    source = hwpx(
        tmp_path, (("BinData/question.png", raster()), ("BinData/reference.png", raster("BMP")))
    )
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    # Inventory proves whole pixels, NOT target-region selection. Owner must map
    # actual question placement and exclude the reference/explanation regions.
    assert len(result.images) == 2
    assert all("selected" not in image.model_dump() for image in result.images)


def test_unknown_binary_is_reported_without_loading_external_image_handlers(tmp_path: Path) -> None:
    source = hwpx(tmp_path, (("BinData/a.eps", b"%!PS-Adobe-3.0\nnot executed"),))
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert result.images == ()
    assert result.unsupported_members == ("BinData/a.eps",)


@pytest.mark.parametrize(
    "name", ["../outside.png", "BinData/../escape.png", "BinData/sub/image.png", "BinData\\a.png"]
)
def test_untrusted_member_names_are_rejected(tmp_path: Path, name: str) -> None:
    source = hwpx(tmp_path, ((name, raster()),))
    with pytest.raises(OfficeEmbeddedImageError):
        extract_office_embedded_images(
            source, expected_sha256=sha(source), workspace=tmp_path / "output"
        )
    assert not (tmp_path / "outside.png").exists()


def test_case_colliding_members_are_rejected(tmp_path: Path) -> None:
    source = hwpx(tmp_path, (("BinData/a.png", raster()), ("BinData/A.png", raster())))
    with pytest.raises(OfficeEmbeddedImageError, match="ZIP_MEMBER_INVALID"):
        extract_office_embedded_images(
            source, expected_sha256=sha(source), workspace=tmp_path / "output"
        )


def test_changed_hash_and_existing_output_fail_without_overwriting(tmp_path: Path) -> None:
    source = hwpx(tmp_path, (("BinData/a.png", raster()),))
    output = tmp_path / "output"
    with pytest.raises(OfficeEmbeddedImageError, match="SOURCE_HASH_MISMATCH"):
        extract_office_embedded_images(
            source, expected_sha256="sha256:" + "0" * 64, workspace=output
        )
    assert not output.exists()
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(OfficeEmbeddedImageError, match="WORKSPACE_INVALID"):
        extract_office_embedded_images(source, expected_sha256=sha(source), workspace=output)
    assert sentinel.read_text() == "keep"


def test_member_expansion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import eom_image_provider.office_embedded_images as implementation

    monkeypatch.setattr(implementation, "_MAX_MEMBER", 32)
    encoder = zlib.compressobj(wbits=-15)
    compressed = encoder.compress(b"x" * 64) + encoder.flush()
    with pytest.raises(OfficeEmbeddedImageError, match="EXPANSION_LIMIT"):
        _inflate(compressed)


def test_hwp_raw_deflate_admits_only_a_valid_crc32_size_trailer() -> None:
    raw = raster("BMP")
    encoder = zlib.compressobj(wbits=-15)
    compressed = encoder.compress(raw) + encoder.flush()
    trailer = struct.pack("<II", zlib.crc32(raw) & 0xFFFFFFFF, len(raw))
    assert _inflate(compressed + trailer) == raw
    with pytest.raises(OfficeEmbeddedImageError, match="TRAILER_INVALID"):
        _inflate(compressed + trailer[:-1] + b"\xff")


def test_hwp_read_only_stream_extraction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = raster("BMP")
    encoder = zlib.compressobj(wbits=-15)
    compressed = encoder.compress(raw) + encoder.flush()
    header = b"HWP Document File".ljust(32, b"\0") + b"\0\1\0\5" + struct.pack("<I", 1)
    streams = {"FileHeader": header, "BinData/BIN0001.bmp": compressed}

    class ReadOnlyOle:
        def __init__(self, source: object, *, write_mode: bool, raise_defects: int) -> None:
            assert write_mode is False

        def __enter__(self) -> ReadOnlyOle:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def exists(self, name: str) -> bool:
            return name in streams

        def get_size(self, name: str | list[str]) -> int:
            return len(streams[name if isinstance(name, str) else "/".join(name)])

        def openstream(self, name: str | list[str]) -> io.BytesIO:
            return io.BytesIO(streams[name if isinstance(name, str) else "/".join(name)])

        def listdir(self) -> list[list[str]]:
            return [name.split("/") for name in streams]

    monkeypatch.setitem(
        sys.modules, "olefile", types.SimpleNamespace(OleFileIO=ReadOnlyOle, DEFECT_INCORRECT=30)
    )
    source = tmp_path / "source.hwp"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"synthetic source")
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    assert result.source_format == "HWP5"
    assert result.images[0].source_member == "BinData/BIN0001.bmp"
    assert (
        result.images[0].source_member_sha256 == "sha256:" + hashlib.sha256(compressed).hexdigest()
    )


def test_receipt_tampering_and_duplicate_sources_are_rejected(tmp_path: Path) -> None:
    source = hwpx(tmp_path, (("BinData/a.png", raster()),))
    result = extract_office_embedded_images(
        source, expected_sha256=sha(source), workspace=tmp_path / "output"
    )
    value = result.model_dump(mode="json")
    value["images"][0]["width_px"] -= 1
    with pytest.raises(ValueError):
        OfficeEmbeddedImageSet.model_validate(value)
    value = result.model_dump(mode="json")
    value["images"] *= 2
    value["manifest_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "manifest_sha256"}
    )
    with pytest.raises(ValueError):
        OfficeEmbeddedImageSet.model_validate(value)


def test_schema_is_2020_12_and_the_wheel_resource_matches_repository() -> None:
    schema = load_schema("office-embedded-image-set")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    root = Path(__file__).resolve().parents[2]
    assert schema == json.loads(
        (root / "schemas/image-provider/office-embedded-image-set-v1.schema.json").read_text()
    )


def test_cpu_extractor_does_not_import_gpu_or_any_persistence_adapter() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "services/image_provider/eom_image_provider/office_embedded_images.py"
    ).read_text()
    assert "import torch" not in source
    assert "from eom_gpu" not in source
    assert "from eom_catalog_service" not in source
    assert "from eom_orchestrator" not in source
    assert "get_pixmap" not in source

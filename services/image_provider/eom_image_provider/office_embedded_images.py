"""CPU-only HWP/HWPX image extraction: whole original pixels, no page capture."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import stat
import struct
import warnings
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImage, OfficeEmbeddedImageSet
from PIL import Image

_MAX_SOURCE = 256 * 1024 * 1024
_MAX_MEMBER = 64 * 1024 * 1024
_MAX_EXPANDED = 512 * 1024 * 1024
_RASTER_FORMATS = frozenset({"PNG", "JPEG", "BMP", "GIF", "TIFF"})
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class OfficeEmbeddedImageError(ValueError):
    """A stable source/expansion/identity error, never execution of document code."""


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_member(name: str) -> bool:
    return (
        name.startswith("BinData/")
        and len(name) <= 256
        and len(PurePosixPath(name).parts) == 2
        and not any(part in {"", ".", ".."} for part in name.split("/"))
        and "\\" not in name
        and not any(ord(char) < 32 for char in name)
    )


def _inflate(payload: bytes) -> bytes:
    try:
        decoder = zlib.decompressobj(-15)
        result = decoder.decompress(payload, _MAX_MEMBER + 1)
    except zlib.error as exc:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_COMPRESSION_INVALID") from exc
    if len(result) > _MAX_MEMBER or not decoder.eof or decoder.unconsumed_tail:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_EXPANSION_LIMIT")
    # Observed HWP BinData streams may append the gzip CRC32/ISIZE trailer
    # after raw DEFLATE. Admit only that exact checked trailer, not arbitrary
    # ignored bytes or a concatenated stream.
    if decoder.unused_data not in (
        b"",
        struct.pack("<II", zlib.crc32(result) & 0xFFFFFFFF, len(result) & 0xFFFFFFFF),
    ):
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_COMPRESSION_TRAILER_INVALID")
    return result


def _hwp_members(payload: bytes) -> Iterator[tuple[str, str, bytes]]:
    # This optional pure-Python CFB reader does not execute OLE objects or HWP scripts.
    try:
        import olefile
    except ImportError as exc:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_READER_UNAVAILABLE") from exc
    with olefile.OleFileIO(
        io.BytesIO(payload), write_mode=False, raise_defects=olefile.DEFECT_INCORRECT
    ) as document:
        if not document.exists("FileHeader") or document.get_size("FileHeader") > 4096:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_HEADER_INVALID")
        header = document.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File") or len(header) < 40:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_HEADER_INVALID")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 6:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_PROTECTED")
        members = sorted(
            ("/".join(parts), parts)
            for parts in document.listdir()
            if parts and parts[0] == "BinData"
        )
        if len(members) > 512:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_COUNT_EXCEEDED")
        for name, parts in members:
            if not _safe_member(name) or not 0 < document.get_size(parts) <= _MAX_MEMBER:
                raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_INVALID")
            raw = document.openstream(parts).read(_MAX_MEMBER + 1)
            if len(raw) != document.get_size(parts):
                raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_INVALID")
            # An uncompressed member is possible even when the document is compressed.
            raster_signature = raw.startswith(
                (_PNG_SIGNATURE, b"\xff\xd8\xff", b"BM", b"GIF8", b"II*\x00", b"MM\x00*")
            )
            data = _inflate(raw) if flags & 1 and not raster_signature else raw
            yield name, _sha(raw), data


def _hwpx_members(payload: bytes) -> Iterator[tuple[str, str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as document:
        infos = document.infolist()
        if not 0 < len(infos) <= 20_000:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_COUNT_EXCEEDED")
        names: set[str] = set()
        total = 0
        selected = []
        for info in infos:
            name = info.filename
            parts = name.split("/")
            if (
                name.casefold() in names
                or name.startswith("/")
                or "\\" in name
                or any(part in {"", ".", ".."} for part in parts)
                or info.flag_bits & 1
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or stat.S_ISLNK(info.external_attr >> 16)
                or not 0 <= info.file_size <= _MAX_MEMBER
            ):
                raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_ZIP_MEMBER_INVALID")
            names.add(name.casefold())
            total += info.file_size
            if total > _MAX_EXPANDED:
                raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_EXPANSION_LIMIT")
            if name.startswith("BinData/"):
                if not _safe_member(name):
                    raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_INVALID")
                selected.append(info)
        if "mimetype" not in names or document.read("mimetype") != b"application/hwp+zip":
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWPX_MIMETYPE_INVALID")
        if len(selected) > 512:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_COUNT_EXCEEDED")
        for info in sorted(selected, key=lambda item: item.filename):
            raw = document.read(info)
            if len(raw) != info.file_size:
                raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_MEMBER_INVALID")
            yield info.filename, _sha(raw), raw


def _normalize_raster(payload: bytes) -> tuple[bytes, str, str, int, int] | None:
    # Do not let Pillow dispatch EPS/WMF or any external program for unknown data.
    if not payload.startswith(
        (_PNG_SIGNATURE, b"\xff\xd8\xff", b"BM", b"GIF8", b"II*\x00", b"MM\x00*")
    ):
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format not in _RASTER_FORMATS or getattr(source, "n_frames", 1) != 1:
                    return None
                source_format = source.format
                width, height = source.size
                if not 0 < width <= 10000 or not 0 < height <= 10000 or width * height > 20_000_000:
                    raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_PIXEL_LIMIT")
                source.load()
                pixel_sha256 = _sha(
                    struct.pack("<II", width, height) + source.convert("RGBA").tobytes()
                )
                if source_format == "PNG":
                    result = payload
                else:
                    output = io.BytesIO()
                    source.save(output, format="PNG", compress_level=9)
                    result = output.getvalue()
            # Require the normalized PNG to retain every decoded source pixel.
            with Image.open(io.BytesIO(result)) as normalized:
                if (
                    normalized.size != (width, height)
                    or _sha(
                        struct.pack("<II", width, height) + normalized.convert("RGBA").tobytes()
                    )
                    != pixel_sha256
                ):
                    raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_PIXELS_CHANGED")
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_RASTER_INVALID") from exc
    if not 24 <= len(result) <= _MAX_MEMBER:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_OUTPUT_LIMIT")
    return result, pixel_sha256, source_format, width, height


def read_verified_office_source(source: Path, *, expected_sha256: str) -> bytes:
    """One bounded, hash-verified materialization shared by pixels and native records."""
    if not source.is_absolute():
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_SOURCE_INVALID")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_SOURCE:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_SOURCE_INVALID")
        payload = stream.read(_MAX_SOURCE + 1)
        after = os.fstat(stream.fileno())
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(payload) != before.st_size
        or _sha(payload) != expected_sha256
    ):
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_SOURCE_HASH_MISMATCH")
    return payload


def extract_office_embedded_images(
    source: Path, *, expected_sha256: str, workspace: Path
) -> OfficeEmbeddedImageSet:
    """Extract complete source pixels in the isolated local document workspace."""
    if not source.is_absolute() or not workspace.is_absolute() or os.path.lexists(workspace):
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_WORKSPACE_INVALID")
    payload = read_verified_office_source(source, expected_sha256=expected_sha256)
    return _extract_office_image_payload(
        payload, expected_sha256=expected_sha256, workspace=workspace
    )


def _extract_office_image_payload(
    payload: bytes, *, expected_sha256: str, workspace: Path
) -> OfficeEmbeddedImageSet:
    """Internal pixel half of the same verified Office materialization."""
    if payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        source_format: Literal["HWP5", "HWPX"] = "HWP5"
        members = _hwp_members(payload)
    elif payload.startswith(b"PK\x03\x04"):
        source_format = "HWPX"
        members = _hwpx_members(payload)
    else:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_SOURCE_FORMAT_UNSUPPORTED")
    workspace.mkdir(mode=0o700)
    (workspace / "images").mkdir(mode=0o700)
    images = []
    unsupported = []
    written: set[str] = set()
    total_expanded = 0
    total_pixels = 0
    for member, source_hash, raw in members:
        total_expanded += len(raw)
        if total_expanded > _MAX_EXPANDED:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_EXPANSION_LIMIT")
        normalized = _normalize_raster(raw)
        if normalized is None:
            unsupported.append(member)
            continue
        png, pixel_sha, raster_format, width, height = normalized
        total_pixels += width * height
        if total_pixels > 100_000_000:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_PIXEL_LIMIT")
        sha = _sha(png)
        output_member = f"images/{sha[7:]}.png"
        if output_member not in written:
            with (workspace / output_member).open("xb") as stream:
                stream.write(png)
            written.add(output_member)
        images.append(
            OfficeEmbeddedImage(
                source_member=member,
                source_member_sha256=source_hash,
                source_format=cast(Literal["PNG", "JPEG", "BMP", "GIF", "TIFF"], raster_format),
                pixel_sha256=pixel_sha,
                member_path=output_member,
                sha256=sha,
                width_px=width,
                height_px=height,
                content_length=len(png),
            )
        )
    value = {
        "schema_version": "office-embedded-image-set/1.0",
        "source_sha256": expected_sha256,
        "source_format": source_format,
        "extractor_profile": "WHOLE_EMBEDDED_RASTER_V1",
        "images": [image.model_dump(mode="json") for image in images],
        "unsupported_members": sorted(unsupported),
    }
    result = OfficeEmbeddedImageSet.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    with (workspace / "embedded-images.json").open("xb") as stream:
        stream.write(content_json_bytes(result.model_dump(mode="json")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    result = extract_office_embedded_images(
        arguments.source, expected_sha256=arguments.source_sha256, workspace=arguments.workspace
    )
    print(
        f"office_embedded_images=PASS images={len(result.images)} "
        f"unsupported={len(result.unsupported_members)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

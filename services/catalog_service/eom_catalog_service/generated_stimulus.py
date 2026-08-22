"""Deterministic materialization for bounded worker-authored science diagrams."""

from __future__ import annotations

import binascii
import itertools
import os
import stat
import struct
import zlib
from pathlib import Path

from eom_workflow.models import GeneratedLineGraphDrawing

from eom_catalog_service.settings import CatalogSettings, CatalogStagingArea
from eom_catalog_service.staging import (
    create_catalog_operation_directory,
    require_fixed_catalog_staging_root,
)

PNG_MEMBER = "generated-stimulus.png"
PNG_WIDTH = 800
PNG_HEIGHT = 500
PNG_MAX_BYTES = 2 * 1024 * 1024
_WHITE = (255, 255, 255)
_GRID = (222, 228, 235)
_AXIS = (31, 41, 55)
_COLORS = {
    "blue": (37, 99, 235),
    "green": (22, 163, 74),
    "orange": (234, 88, 12),
}


def render_generated_stimulus(
    settings: CatalogSettings,
    *,
    workflow_id: str,
    result_revision_id: str,
    drawing: GeneratedLineGraphDrawing,
) -> Path:
    """Render one immutable drawing value beneath Catalog-owned disposable staging."""

    if not workflow_id.startswith("workflow_") or not result_revision_id.startswith("rev_"):
        raise ValueError("generated stimulus identity is invalid")
    root = require_fixed_catalog_staging_root(settings, CatalogStagingArea.REGISTRY)
    name = f"generated-{workflow_id}-{result_revision_id}"
    operation = create_catalog_operation_directory(
        root,
        name,
        message="generated stimulus staging directory is unsafe",
    )
    target = operation / PNG_MEMBER
    if target.exists() or target.is_symlink():
        validate_generated_png(target)
        return target

    pixels = bytearray(bytes(_WHITE) * (PNG_WIDTH * PNG_HEIGHT))
    _draw_graph(pixels, drawing)
    payload = _encode_png(pixels)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o640)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
    validate_generated_png(target)
    return target


def validate_generated_png(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > PNG_MAX_BYTES
        or stat.S_IMODE(metadata.st_mode) != 0o640
    ):
        raise ValueError("generated stimulus PNG metadata is invalid")
    with path.open("rb") as source:
        header = source.read(24)
    if (
        len(header) != 24
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[12:16] != b"IHDR"
        or struct.unpack(">II", header[16:24]) != (PNG_WIDTH, PNG_HEIGHT)
    ):
        raise ValueError("generated stimulus PNG structure is invalid")


def _draw_graph(pixels: bytearray, drawing: GeneratedLineGraphDrawing) -> None:
    left, top, right, bottom = 90, 55, 750, 420
    for index in range(6):
        x = left + (right - left) * index // 5
        y = top + (bottom - top) * index // 5
        _line(pixels, x, top, x, bottom, _GRID)
        _line(pixels, left, y, right, y, _GRID)
    _line(pixels, left, bottom, right, bottom, _AXIS, width=3)
    _line(pixels, left, bottom, left, top, _AXIS, width=3)
    _line(pixels, right, bottom, right - 14, bottom - 8, _AXIS, width=3)
    _line(pixels, right, bottom, right - 14, bottom + 8, _AXIS, width=3)
    _line(pixels, left, top, left - 8, top + 14, _AXIS, width=3)
    _line(pixels, left, top, left + 8, top + 14, _AXIS, width=3)

    minimum_x, maximum_x = min(drawing.x_values), max(drawing.x_values)
    minimum_y, maximum_y = min(drawing.y_values), max(drawing.y_values)
    if minimum_y == maximum_y:
        minimum_y -= 1
        maximum_y += 1
    points = tuple(
        (
            left + (value_x - minimum_x) * (right - left) // (maximum_x - minimum_x),
            bottom - (value_y - minimum_y) * (bottom - top) // (maximum_y - minimum_y),
        )
        for value_x, value_y in zip(drawing.x_values, drawing.y_values, strict=True)
    )
    color = _COLORS[drawing.stroke_color]
    for start, end in itertools.pairwise(points):
        _line(pixels, *start, *end, color, width=4)
    for x, y in points:
        if drawing.point_style == "circle":
            _disc(pixels, x, y, 7, color)
        else:
            _rectangle(pixels, x - 6, y - 6, x + 6, y + 6, color)


def _pixel(pixels: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < PNG_WIDTH and 0 <= y < PNG_HEIGHT:
        offset = (y * PNG_WIDTH + x) * 3
        pixels[offset : offset + 3] = bytes(color)


def _line(
    pixels: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    *,
    width: int = 1,
) -> None:
    delta_x = abs(x1 - x0)
    delta_y = -abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = delta_x + delta_y
    while True:
        radius = width // 2
        _rectangle(pixels, x0 - radius, y0 - radius, x0 + radius, y0 + radius, color)
        if x0 == x1 and y0 == y1:
            return
        twice = 2 * error
        if twice >= delta_y:
            error += delta_y
            x0 += step_x
        if twice <= delta_x:
            error += delta_x
            y0 += step_y


def _rectangle(
    pixels: bytearray,
    left: int,
    top: int,
    right: int,
    bottom: int,
    color: tuple[int, int, int],
) -> None:
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            _pixel(pixels, x, y, color)


def _disc(
    pixels: bytearray, center_x: int, center_y: int, radius: int, color: tuple[int, int, int]
) -> None:
    radius_squared = radius * radius
    for delta_y in range(-radius, radius + 1):
        for delta_x in range(-radius, radius + 1):
            if delta_x * delta_x + delta_y * delta_y <= radius_squared:
                _pixel(pixels, center_x + delta_x, center_y + delta_y, color)


def _encode_png(pixels: bytearray) -> bytes:
    rows = b"".join(
        b"\x00" + bytes(pixels[offset : offset + PNG_WIDTH * 3])
        for offset in range(0, len(pixels), PNG_WIDTH * 3)
    )
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", PNG_WIDTH, PNG_HEIGHT, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(rows, level=9)),
            _chunk(b"IEND", b""),
        )
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))

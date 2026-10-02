"""Bounded raster measurements for institutional-style blind evaluation."""

from __future__ import annotations

import io
from collections import deque

from eom_image_contracts import InstitutionalStyleImageMetrics
from PIL import (
    Image,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 4_000_000
FOREGROUND_THRESHOLD = 245
DARK_THRESHOLD = 96
EDGE_THRESHOLD = 25
BORDER_WIDTH = 24
TINY_COMPONENT_MAX_PIXELS = 16
PRESENTATION_WIDTH = 800
PRESENTATION_HEIGHT = 500
PRESENTATION_INNER_WIDTH = 720
PRESENTATION_INNER_HEIGHT = 420


class InstitutionalStyleMetricsError(ValueError):
    """Stable invalid-image failure at the evaluation boundary."""


def normalize_institutional_style_presentation(payload: bytes) -> bytes:
    """Fit foreground to one pinned canvas so crop whitespace cannot reveal origin."""

    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if (
                source.format != "PNG"
                or source.width < 32
                or source.height < 32
                or source.width * source.height > MAX_PIXELS
            ):
                raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID")
            grayscale = ImageOps.grayscale(source)
    except InstitutionalStyleMetricsError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID") from exc

    foreground_mask = grayscale.point(
        tuple(255 if value < FOREGROUND_THRESHOLD else 0 for value in range(256))
    )
    bounding_box = foreground_mask.getbbox()
    if bounding_box is None:
        raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_FOREGROUND_MISSING")
    foreground = grayscale.crop(bounding_box)
    scale = min(
        PRESENTATION_INNER_WIDTH / foreground.width,
        PRESENTATION_INNER_HEIGHT / foreground.height,
    )
    foreground = foreground.resize(
        (
            max(1, round(foreground.width * scale)),
            max(1, round(foreground.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("L", (PRESENTATION_WIDTH, PRESENTATION_HEIGHT), 255)
    canvas.paste(
        foreground,
        (
            (PRESENTATION_WIDTH - foreground.width) // 2,
            (PRESENTATION_HEIGHT - foreground.height) // 2,
        ),
    )
    target = io.BytesIO()
    canvas.save(target, format="PNG", optimize=False, compress_level=9)
    return target.getvalue()


def institutional_style_presentation_metrics(payload: bytes) -> InstitutionalStyleImageMetrics:
    """Measure the exact canvas used by the blinded reviewer."""

    return institutional_style_metrics(normalize_institutional_style_presentation(payload))


def _milli(count: int, total: int) -> int:
    return round(count * 1000 / total) if total else 0


def _component_metrics(mask: bytearray, width: int, height: int) -> tuple[int, int]:
    """Return component count and foreground pixels in components up to the tiny bound."""

    visited = bytearray(len(mask))
    components = 0
    tiny_pixels = 0
    for start, foreground in enumerate(mask):
        if not foreground or visited[start]:
            continue
        components += 1
        visited[start] = 1
        pending: deque[int] = deque((start,))
        size = 0
        while pending:
            index = pending.popleft()
            size += 1
            x = index % width
            for neighbor in (
                index - width if index >= width else -1,
                index + width if index < width * (height - 1) else -1,
                index - 1 if x else -1,
                index + 1 if x + 1 < width else -1,
            ):
                if neighbor >= 0 and mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    pending.append(neighbor)
        if size <= TINY_COMPONENT_MAX_PIXELS:
            tiny_pixels += size
    return components, tiny_pixels


def institutional_style_metrics(payload: bytes) -> InstitutionalStyleImageMetrics:
    """Measure one untrusted PNG in O(W*H) time with bounded decoded size."""

    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if (
                source.format != "PNG"
                or source.width < 32
                or source.height < 32
                or source.width * source.height > MAX_PIXELS
            ):
                raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID")
            grayscale = ImageOps.grayscale(source)
    except InstitutionalStyleMetricsError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise InstitutionalStyleMetricsError("INSTITUTIONAL_STYLE_IMAGE_INVALID") from exc

    pixels = grayscale.tobytes()
    total = len(pixels)
    foreground_mask = bytearray(value < FOREGROUND_THRESHOLD for value in pixels)
    foreground = sum(foreground_mask)
    dark = sum(value < DARK_THRESHOLD for value in pixels)
    mid_tone = sum(DARK_THRESHOLD <= value < FOREGROUND_THRESHOLD for value in pixels)

    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    edge_count = sum(value >= EDGE_THRESHOLD for value in edges.tobytes())
    border = 0
    border_foreground = 0
    for y in range(grayscale.height):
        for x in range(grayscale.width):
            if (
                x < BORDER_WIDTH
                or x >= grayscale.width - BORDER_WIDTH
                or y < BORDER_WIDTH
                or y >= grayscale.height - BORDER_WIDTH
            ):
                border += 1
                if foreground_mask[y * grayscale.width + x]:
                    border_foreground += 1

    # Morphological opening removes isolated/thin dark detail but retains wider connected strokes.
    opened = grayscale.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    opened_foreground = sum(value < FOREGROUND_THRESHOLD for value in opened.tobytes())
    fine_detail = max(0, foreground - opened_foreground)
    component_count, tiny_component_pixels = _component_metrics(
        foreground_mask,
        grayscale.width,
        grayscale.height,
    )
    return InstitutionalStyleImageMetrics(
        foreground_fraction_milli=_milli(foreground, total),
        dark_fraction_milli=_milli(dark, total),
        mid_tone_fraction_milli=_milli(mid_tone, total),
        edge_fraction_milli=_milli(edge_count, total),
        border_foreground_fraction_milli=_milli(border_foreground, border),
        fine_detail_fraction_milli=_milli(fine_detail, foreground),
        tiny_component_fraction_milli=_milli(tiny_component_pixels, foreground),
        component_count=component_count,
    )

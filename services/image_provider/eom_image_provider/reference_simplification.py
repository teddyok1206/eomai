"""Deterministic low-detail morphology conditioning for reviewed visual references."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from importlib import metadata
from typing import Literal

from eom_image_contracts import (
    LocalImageReferenceConditioningOutput,
    LocalImageReferenceSimplification,
    LocalImageReferenceSimplificationMetrics,
    LocalImageReferenceSimplificationMetricsV2,
    LocalImageReferenceSimplificationV2,
    LocalImageReferenceSimplifierRuntime,
)
from PIL import (  # type: ignore[import-not-found]
    Image,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

WIDTH = 800
HEIGHT = 504
MAX_INPUT_BYTES = 8 * 1024 * 1024


class ReferenceSimplificationError(ValueError):
    """Stable failure raised before any GPU inference."""


@dataclass(frozen=True)
class SimplifiedVisualReference:
    png_bytes: bytes
    output: LocalImageReferenceConditioningOutput
    metrics: LocalImageReferenceSimplificationMetrics | LocalImageReferenceSimplificationMetricsV2
    runtime: LocalImageReferenceSimplifierRuntime


def _ratio(count: int, total: int) -> float:
    return round(count / total, 8) if total else 0.0


def _foreground_ratio(image: Image.Image, threshold: int) -> float:
    histogram = image.histogram()
    return _ratio(sum(histogram[:threshold]), image.width * image.height)


def _border_foreground_ratio(image: Image.Image, *, threshold: int, width: int) -> float:
    pixels = image.load()
    foreground = 0
    total = 0
    for y in range(image.height):
        for x in range(image.width):
            if x < width or x >= image.width - width or y < width or y >= image.height - width:
                total += 1
                if pixels[x, y] < threshold:
                    foreground += 1
    return _ratio(foreground, total)


def _edge_density(image: Image.Image) -> float:
    edges = image.filter(ImageFilter.FIND_EDGES)
    pixels = edges.load()
    count = 0
    total = 0
    for y in range(4, image.height - 4):
        for x in range(4, image.width - 4):
            total += 1
            if pixels[x, y] > 24:
                count += 1
    return _ratio(count, total)


def _light_fill_tone(value: int) -> int:
    if value >= 240:
        return 255
    if value >= 176:
        return 248
    if value >= 96:
        return 236
    return 224


def _contour_tone(value: int) -> int:
    if value < 30:
        return 255
    if value < 80:
        return 224
    if value < 150:
        return 160
    return 48


def _source_preserving_tone(value: int) -> int:
    if value >= 245:
        return 255
    if value >= 224:
        return 248
    if value >= 176:
        return 236
    if value >= 96:
        return 160
    return 48


def _classification_ratios(
    source: Image.Image,
    grayscale: Image.Image,
    *,
    policy: LocalImageReferenceSimplificationV2,
) -> tuple[float, float, float]:
    pixels = source.convert("RGB").load()
    near_monochrome = 0
    white_background = 0
    total = source.width * source.height
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue = pixels[x, y]
            if max(red, green, blue) - min(red, green, blue) <= policy.line_art_channel_spread_max:
                near_monochrome += 1
            if min(red, green, blue) >= policy.foreground_luma_threshold:
                white_background += 1
    histogram = grayscale.histogram()
    foreground = sum(histogram[: policy.foreground_luma_threshold])
    dark = sum(histogram[: policy.line_art_dark_luma_threshold])
    return (
        _ratio(near_monochrome, total),
        _ratio(white_background, total),
        _ratio(dark, foreground),
    )


def simplify_visual_reference(
    payload: bytes,
    *,
    policy: LocalImageReferenceSimplification | LocalImageReferenceSimplificationV2,
) -> SimplifiedVisualReference:
    """Reduce microtexture without changing the normalized canvas or inventing pixels."""

    if not payload or len(payload) > MAX_INPUT_BYTES:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if source.format != "PNG" or source.size != (WIDTH, HEIGHT):
                raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID")
            source_rgb = source.convert("RGB")
            grayscale = ImageOps.grayscale(source_rgb)
    except (OSError, UnidentifiedImageError) as exc:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID") from exc

    source_foreground_ratio = _foreground_ratio(
        grayscale,
        policy.foreground_luma_threshold,
    )
    source_edge_density = _edge_density(grayscale)
    near_monochrome_ratio = 0.0
    white_background_ratio = 0.0
    dark_foreground_fraction = 0.0
    selected_mode: Literal["PRESERVE_LINE_ART", "REDUCE_PHOTOGRAPHIC_DETAIL"] = (
        "REDUCE_PHOTOGRAPHIC_DETAIL"
    )
    if isinstance(policy, LocalImageReferenceSimplificationV2):
        (
            near_monochrome_ratio,
            white_background_ratio,
            dark_foreground_fraction,
        ) = _classification_ratios(source_rgb, grayscale, policy=policy)
        if (
            near_monochrome_ratio >= policy.line_art_near_monochrome_ratio_min
            and white_background_ratio >= policy.line_art_white_background_ratio_min
            and dark_foreground_fraction >= policy.line_art_dark_foreground_fraction_min
        ):
            selected_mode = "PRESERVE_LINE_ART"
    if selected_mode == "PRESERVE_LINE_ART":
        simplified = grayscale.point(tuple(_source_preserving_tone(value) for value in range(256)))
    else:
        fill_source = grayscale.filter(ImageFilter.MedianFilter(size=5)).filter(
            ImageFilter.GaussianBlur(radius=1.2)
        )
        fill = ImageOps.autocontrast(fill_source, cutoff=1).point(
            tuple(_light_fill_tone(value) for value in range(256))
        )
        contour_source = (
            grayscale.filter(ImageFilter.MaxFilter(size=5))
            .filter(ImageFilter.MedianFilter(size=7))
            .filter(ImageFilter.GaussianBlur(radius=2.0))
        )
        contours = ImageOps.autocontrast(
            contour_source.filter(ImageFilter.FIND_EDGES),
            cutoff=1,
        ).point(tuple(_contour_tone(value) for value in range(256)))
        fill_pixels = fill.load()
        contour_pixels = contours.load()
        for y in range(fill.height):
            for x in range(fill.width):
                fill_pixels[x, y] = (
                    255
                    if x < 5 or x >= fill.width - 5 or y < 5 or y >= fill.height - 5
                    else min(fill_pixels[x, y], contour_pixels[x, y])
                )
        simplified = fill
    conditioning_foreground_ratio = _foreground_ratio(
        simplified,
        policy.foreground_luma_threshold,
    )
    border_foreground_ratio = _border_foreground_ratio(
        simplified,
        threshold=policy.foreground_luma_threshold,
        width=policy.border_width_px,
    )
    conditioning_edge_density = _edge_density(simplified)
    edge_density_ratio = round(
        conditioning_edge_density / source_edge_density if source_edge_density else 0.0,
        8,
    )
    metrics_body = {
        "source_foreground_ratio": source_foreground_ratio,
        "conditioning_foreground_ratio": conditioning_foreground_ratio,
        "border_foreground_ratio": border_foreground_ratio,
        "source_edge_density": source_edge_density,
        "conditioning_edge_density": conditioning_edge_density,
        "edge_density_ratio": edge_density_ratio,
    }
    metrics: LocalImageReferenceSimplificationMetrics | LocalImageReferenceSimplificationMetricsV2
    if isinstance(policy, LocalImageReferenceSimplificationV2):
        metrics = LocalImageReferenceSimplificationMetricsV2(
            **metrics_body,
            selected_mode=selected_mode,
            near_monochrome_ratio=near_monochrome_ratio,
            white_background_ratio=white_background_ratio,
            dark_foreground_fraction=dark_foreground_fraction,
        )
    else:
        metrics = LocalImageReferenceSimplificationMetrics(**metrics_body)
    if source_foreground_ratio < policy.foreground_ratio_min:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_FOREGROUND_INVALID")
    if (
        conditioning_foreground_ratio < policy.foreground_ratio_min
        or conditioning_foreground_ratio > policy.foreground_ratio_max
    ):
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_FOREGROUND_INVALID")
    if border_foreground_ratio > policy.border_foreground_ratio_max:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_BACKGROUND_COMPLEX")

    target = io.BytesIO()
    simplified.convert("RGB").save(target, format="PNG", compress_level=9, optimize=False)
    png_bytes = target.getvalue()
    output = LocalImageReferenceConditioningOutput(
        sha256="sha256:" + hashlib.sha256(png_bytes).hexdigest(),
        size_bytes=len(png_bytes),
    )
    runtime = LocalImageReferenceSimplifierRuntime(pillow_version=metadata.version("Pillow"))
    return SimplifiedVisualReference(
        png_bytes=png_bytes,
        output=output,
        metrics=metrics,
        runtime=runtime,
    )

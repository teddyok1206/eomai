"""Deterministic low-detail morphology conditioning for reviewed visual references."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from importlib import metadata

from eom_image_contracts import (
    LocalImageReferenceConditioningOutput,
    LocalImageReferenceSimplification,
    LocalImageReferenceSimplificationMetrics,
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
    metrics: LocalImageReferenceSimplificationMetrics
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


def _posterize_four_levels(value: int) -> int:
    if value >= 240:
        return 255
    if value >= 176:
        return 224
    if value >= 96:
        return 160
    return 48


def simplify_visual_reference(
    payload: bytes,
    *,
    policy: LocalImageReferenceSimplification,
) -> SimplifiedVisualReference:
    """Reduce microtexture without changing the normalized canvas or inventing pixels."""

    if not payload or len(payload) > MAX_INPUT_BYTES:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if source.format != "PNG" or source.size != (WIDTH, HEIGHT):
                raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID")
            grayscale = ImageOps.grayscale(source)
    except (OSError, UnidentifiedImageError) as exc:
        raise ReferenceSimplificationError("REFERENCE_SIMPLIFICATION_INPUT_INVALID") from exc

    source_foreground_ratio = _foreground_ratio(
        grayscale,
        policy.foreground_luma_threshold,
    )
    source_edge_density = _edge_density(grayscale)
    denoised = grayscale.filter(ImageFilter.MedianFilter(size=5)).filter(
        ImageFilter.GaussianBlur(radius=1.2)
    )
    contrasted = ImageOps.autocontrast(denoised, cutoff=1)
    simplified = contrasted.point(tuple(_posterize_four_levels(value) for value in range(256)))
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
    metrics = LocalImageReferenceSimplificationMetrics(
        source_foreground_ratio=source_foreground_ratio,
        conditioning_foreground_ratio=conditioning_foreground_ratio,
        border_foreground_ratio=border_foreground_ratio,
        source_edge_density=source_edge_density,
        conditioning_edge_density=conditioning_edge_density,
        edge_density_ratio=edge_density_ratio,
    )
    for ratio in (source_foreground_ratio, conditioning_foreground_ratio):
        if ratio < policy.foreground_ratio_min or ratio > policy.foreground_ratio_max:
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

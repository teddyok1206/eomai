"""Deterministic assessment line-art cleanup for local model rasters."""

from __future__ import annotations

import io
from dataclasses import dataclass
from importlib import metadata

from eom_image_contracts import (
    LocalImageAssessmentLineArtMetrics,
    LocalImageAssessmentLineArtPostprocess,
    LocalImageAssessmentLineArtRuntime,
)
from PIL import (  # type: ignore[import-not-found]
    Image,
    ImageDraw,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

WIDTH = 800
HEIGHT = 500


class AssessmentLineArtError(ValueError):
    """Stable cleanup failure raised before an output is committed."""


@dataclass(frozen=True)
class AssessmentLineArtResult:
    png_bytes: bytes
    metrics: LocalImageAssessmentLineArtMetrics
    runtime: LocalImageAssessmentLineArtRuntime


def _ratio(count: int, total: int) -> float:
    return round(count / total, 8) if total else 0.0


def _foreground_ratio(image: Image.Image, threshold: int) -> float:
    histogram = image.histogram()
    return _ratio(sum(histogram[:threshold]), image.width * image.height)


def _border_foreground_ratio(
    image: Image.Image,
    *,
    threshold: int,
    horizontal: int,
    vertical: int,
) -> float:
    pixels = image.load()
    foreground = 0
    total = 0
    for y in range(image.height):
        for x in range(image.width):
            if (
                x < horizontal
                or x >= image.width - horizontal
                or y < vertical
                or y >= image.height - vertical
            ):
                total += 1
                if pixels[x, y] < threshold:
                    foreground += 1
    return _ratio(foreground, total)


def _edge_density(image: Image.Image) -> float:
    edges = image.filter(ImageFilter.FIND_EDGES)
    histogram = edges.histogram()
    return _ratio(sum(histogram[25:]), image.width * image.height)


def assessment_line_art(
    payload: bytes,
    *,
    policy: LocalImageAssessmentLineArtPostprocess,
) -> AssessmentLineArtResult:
    """Remove photographic background texture while preserving the inferred subject contour."""

    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if source.format != "PNG" or source.size != (WIDTH, HEIGHT):
                raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_INPUT_INVALID")
            grayscale = ImageOps.grayscale(source)
    except AssessmentLineArtError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_INPUT_INVALID") from exc

    input_foreground_ratio = _foreground_ratio(
        grayscale,
        policy.foreground_luma_threshold,
    )
    input_edge_density = _edge_density(grayscale)
    smooth = grayscale.filter(ImageFilter.MedianFilter(size=policy.median_filter_size))
    broad = grayscale.filter(ImageFilter.GaussianBlur(radius=policy.mask_blur_radius))
    mask = broad.point(
        tuple(255 if value < policy.mask_luma_threshold else 0 for value in range(256))
    )
    mask = mask.filter(ImageFilter.MaxFilter(size=policy.mask_expand_size)).filter(
        ImageFilter.MinFilter(size=policy.mask_contract_size)
    )
    edges = ImageOps.autocontrast(smooth.filter(ImageFilter.FIND_EDGES), cutoff=1)
    dark, mid, white = policy.output_tones
    line_art = edges.point(
        tuple(
            dark
            if value >= policy.edge_dark_threshold
            else mid
            if value >= policy.edge_mid_threshold
            else white
            for value in range(256)
        )
    )
    line_art = Image.composite(line_art, Image.new("L", line_art.size, white), mask)
    drawing = ImageDraw.Draw(line_art)
    drawing.rectangle(
        (0, 0, policy.horizontal_border_px - 1, HEIGHT - 1),
        fill=white,
    )
    drawing.rectangle(
        (WIDTH - policy.horizontal_border_px, 0, WIDTH - 1, HEIGHT - 1),
        fill=white,
    )
    drawing.rectangle((0, 0, WIDTH - 1, policy.vertical_border_px - 1), fill=white)
    drawing.rectangle(
        (0, HEIGHT - policy.vertical_border_px, WIDTH - 1, HEIGHT - 1),
        fill=white,
    )

    output_foreground_ratio = _foreground_ratio(
        line_art,
        policy.foreground_luma_threshold,
    )
    output_border_foreground_ratio = _border_foreground_ratio(
        line_art,
        threshold=policy.foreground_luma_threshold,
        horizontal=policy.horizontal_border_px,
        vertical=policy.vertical_border_px,
    )
    output_edge_density = _edge_density(line_art)
    metrics = LocalImageAssessmentLineArtMetrics(
        input_foreground_ratio=input_foreground_ratio,
        output_foreground_ratio=output_foreground_ratio,
        output_border_foreground_ratio=output_border_foreground_ratio,
        input_edge_density=input_edge_density,
        output_edge_density=output_edge_density,
    )
    if not (policy.foreground_ratio_min <= output_foreground_ratio <= policy.foreground_ratio_max):
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_FOREGROUND_INVALID")
    if output_border_foreground_ratio > policy.border_foreground_ratio_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_BORDER_INVALID")
    if not policy.edge_density_min <= output_edge_density <= policy.edge_density_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID")

    target = io.BytesIO()
    line_art.convert("RGB").save(target, format="PNG", optimize=False, compress_level=9)
    return AssessmentLineArtResult(
        png_bytes=target.getvalue(),
        metrics=metrics,
        runtime=LocalImageAssessmentLineArtRuntime(pillow_version=metadata.version("Pillow")),
    )

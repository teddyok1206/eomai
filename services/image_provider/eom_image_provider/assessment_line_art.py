"""Deterministic assessment line-art cleanup for local model rasters."""

from __future__ import annotations

import io
from collections import deque
from dataclasses import dataclass
from importlib import metadata

from eom_image_contracts import (
    LocalImageAssessmentLineArtMetrics,
    LocalImageAssessmentLineArtMetricsV2,
    LocalImageAssessmentLineArtPostprocess,
    LocalImageAssessmentLineArtPostprocessV2,
    LocalImageAssessmentLineArtRuntime,
    LocalImageAssessmentLineArtRuntimeV2,
)
from PIL import (
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
    metrics: LocalImageAssessmentLineArtMetrics | LocalImageAssessmentLineArtMetricsV2
    runtime: LocalImageAssessmentLineArtRuntime | LocalImageAssessmentLineArtRuntimeV2


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
    top = image.crop((0, 0, image.width, vertical))
    bottom = image.crop((0, image.height - vertical, image.width, image.height))
    middle_height = image.height - 2 * vertical
    left = image.crop((0, vertical, horizontal, image.height - vertical))
    right = image.crop((image.width - horizontal, vertical, image.width, image.height - vertical))
    regions = (top, bottom, left, right)
    foreground = sum(sum(region.histogram()[:threshold]) for region in regions)
    total = 2 * image.width * vertical + 2 * horizontal * middle_height
    return _ratio(foreground, total)


def _edge_density(image: Image.Image) -> float:
    edges = image.filter(ImageFilter.FIND_EDGES)
    histogram = edges.histogram()
    return _ratio(sum(histogram[25:]), image.width * image.height)


def _detail_metrics(image: Image.Image, *, threshold: int) -> tuple[float, float, int]:
    pixels = image.tobytes()
    mask = bytearray(value < threshold for value in pixels)
    foreground = sum(mask)
    opened = image.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    opened_foreground = sum(value < threshold for value in opened.tobytes())
    fine_detail_ratio = _ratio(max(0, foreground - opened_foreground), foreground)

    visited = bytearray(len(mask))
    component_count = 0
    tiny_pixels = 0
    for start, is_foreground in enumerate(mask):
        if not is_foreground or visited[start]:
            continue
        component_count += 1
        visited[start] = 1
        pending: deque[int] = deque((start,))
        size = 0
        while pending:
            index = pending.popleft()
            size += 1
            x = index % image.width
            for neighbor in (
                index - image.width if index >= image.width else -1,
                index + image.width if index < image.width * (image.height - 1) else -1,
                index - 1 if x else -1,
                index + 1 if x + 1 < image.width else -1,
            ):
                if neighbor >= 0 and mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    pending.append(neighbor)
        if size <= 16:
            tiny_pixels += size
    return fine_detail_ratio, _ratio(tiny_pixels, foreground), component_count


def _remove_small_components(
    image: Image.Image,
    *,
    threshold: int,
    maximum_pixels: int,
) -> Image.Image:
    """Remove disconnected specks in O(W*H) while preserving larger subject strokes."""

    payload = bytearray(image.tobytes())
    mask = bytearray(value < threshold for value in payload)
    visited = bytearray(len(mask))
    for start, is_foreground in enumerate(mask):
        if not is_foreground or visited[start]:
            continue
        visited[start] = 1
        pending: deque[int] = deque((start,))
        component: list[int] = []
        while pending:
            index = pending.popleft()
            component.append(index)
            x = index % image.width
            for neighbor in (
                index - image.width if index >= image.width else -1,
                index + image.width if index < image.width * (image.height - 1) else -1,
                index - 1 if x else -1,
                index + 1 if x + 1 < image.width else -1,
            ):
                if neighbor >= 0 and mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    pending.append(neighbor)
        if len(component) <= maximum_pixels:
            for index in component:
                payload[index] = 255
    return Image.frombytes("L", image.size, bytes(payload))


def _clear_output_border(
    image: Image.Image,
    *,
    horizontal: int,
    vertical: int,
) -> None:
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((0, 0, horizontal - 1, image.height - 1), fill=255)
    drawing.rectangle((image.width - horizontal, 0, image.width - 1, image.height - 1), fill=255)
    drawing.rectangle((0, 0, image.width - 1, vertical - 1), fill=255)
    drawing.rectangle((0, image.height - vertical, image.width - 1, image.height - 1), fill=255)


def assessment_line_art(
    payload: bytes,
    *,
    policy: LocalImageAssessmentLineArtPostprocess | LocalImageAssessmentLineArtPostprocessV2,
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


def assessment_line_art_v2(
    payload: bytes,
    *,
    policy: LocalImageAssessmentLineArtPostprocessV2,
) -> AssessmentLineArtResult:
    """Apply the V1 contour extraction followed by bounded microdetail normalization."""

    predecessor = assessment_line_art(payload, policy=policy)
    with Image.open(io.BytesIO(predecessor.png_bytes)) as source:
        source.load()
        grayscale = ImageOps.grayscale(source)
    normalized = grayscale.filter(
        ImageFilter.GaussianBlur(radius=policy.microdetail_blur_radius)
    ).filter(ImageFilter.MedianFilter(size=policy.final_median_filter_size))
    dark, mid, white = policy.final_output_tones
    normalized = normalized.point(
        tuple(
            dark
            if value < policy.final_dark_threshold
            else mid
            if value < policy.final_mid_threshold
            else white
            for value in range(256)
        )
    )
    normalized = _remove_small_components(
        normalized,
        threshold=policy.foreground_luma_threshold,
        maximum_pixels=policy.cleanup_component_max_pixels,
    )
    _clear_output_border(
        normalized,
        horizontal=policy.horizontal_border_px,
        vertical=policy.vertical_border_px,
    )
    output_foreground_ratio = _foreground_ratio(
        normalized,
        policy.foreground_luma_threshold,
    )
    output_border_foreground_ratio = _border_foreground_ratio(
        normalized,
        threshold=policy.foreground_luma_threshold,
        horizontal=policy.horizontal_border_px,
        vertical=policy.vertical_border_px,
    )
    output_edge_density = _edge_density(normalized)
    fine_detail, tiny_components, component_count = _detail_metrics(
        normalized,
        threshold=policy.foreground_luma_threshold,
    )
    if not policy.foreground_ratio_min <= output_foreground_ratio <= policy.foreground_ratio_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_FOREGROUND_INVALID")
    if output_border_foreground_ratio > policy.border_foreground_ratio_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_BORDER_INVALID")
    if not policy.edge_density_min <= output_edge_density <= policy.edge_density_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID")
    if fine_detail > policy.fine_detail_fraction_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_FINE_DETAIL_INVALID")
    if tiny_components > policy.tiny_component_fraction_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_TINY_COMPONENTS_INVALID")
    if component_count > policy.component_count_max:
        raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_COMPONENT_COUNT_INVALID")

    target = io.BytesIO()
    normalized.convert("RGB").save(target, format="PNG", optimize=False, compress_level=9)
    return AssessmentLineArtResult(
        png_bytes=target.getvalue(),
        metrics=LocalImageAssessmentLineArtMetricsV2(
            input_foreground_ratio=predecessor.metrics.input_foreground_ratio,
            output_foreground_ratio=output_foreground_ratio,
            output_border_foreground_ratio=output_border_foreground_ratio,
            input_edge_density=predecessor.metrics.input_edge_density,
            output_edge_density=output_edge_density,
            output_fine_detail_ratio=fine_detail,
            output_tiny_component_ratio=tiny_components,
            output_component_count=component_count,
        ),
        runtime=LocalImageAssessmentLineArtRuntimeV2(pillow_version=metadata.version("Pillow")),
    )

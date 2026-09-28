"""Deterministic placement adapter for evaluation-only reference probes."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, hypot

from eom_image_contracts import Flux2ReferenceProbeBoundingBox
from PIL import Image  # type: ignore[import-not-found]


class LayoutLockError(ValueError):
    """A raster cannot satisfy the pinned layout-lock contract."""


@dataclass(frozen=True, slots=True)
class LayoutLockOutcome:
    image: Image.Image
    reference_bbox: Flux2ReferenceProbeBoundingBox
    raw_candidate_bbox: Flux2ReferenceProbeBoundingBox
    locked_candidate_bbox: Flux2ReferenceProbeBoundingBox
    raw_area_ratio_milli: int
    raw_center_distance_milli: int


def _foreground_bbox(
    image: Image.Image,
    *,
    threshold: int,
) -> Flux2ReferenceProbeBoundingBox:
    if image.mode != "RGB":
        image = image.convert("RGB")
    foreground = image.convert("L").point(lambda value: 255 if value < threshold else 0)
    bounds = foreground.getbbox()
    if bounds is None:
        raise LayoutLockError("foreground is empty")
    x_min, y_min, x_max, y_max = bounds
    return Flux2ReferenceProbeBoundingBox(
        x_min=x_min,
        y_min=y_min,
        x_max=x_max,
        y_max=y_max,
    )


def _map_reference_bbox(
    bbox: Flux2ReferenceProbeBoundingBox,
    *,
    source_height: int,
    delivery_height: int,
) -> Flux2ReferenceProbeBoundingBox:
    y_min = floor(bbox.y_min * delivery_height / source_height)
    y_max = ceil(bbox.y_max * delivery_height / source_height)
    return Flux2ReferenceProbeBoundingBox(
        x_min=bbox.x_min,
        y_min=max(0, min(delivery_height - 1, y_min)),
        x_max=bbox.x_max,
        y_max=max(y_min + 1, min(delivery_height, y_max)),
    )


def _area(bbox: Flux2ReferenceProbeBoundingBox) -> int:
    return (bbox.x_max - bbox.x_min) * (bbox.y_max - bbox.y_min)


def _center_distance_milli(
    source: Flux2ReferenceProbeBoundingBox,
    candidate: Flux2ReferenceProbeBoundingBox,
    *,
    canvas_width: int,
    canvas_height: int,
) -> int:
    source_x2 = source.x_min + source.x_max
    source_y2 = source.y_min + source.y_max
    candidate_x2 = candidate.x_min + candidate.x_max
    candidate_y2 = candidate.y_min + candidate.y_max
    distance = hypot(candidate_x2 - source_x2, candidate_y2 - source_y2) / 2
    diagonal = hypot(canvas_width, canvas_height)
    return round(distance / diagonal * 1000)


def lock_reference_layout(
    *,
    conditioning: Image.Image,
    raw_candidate: Image.Image,
    threshold: int,
) -> LayoutLockOutcome:
    """Place candidate foreground into the exact mapped reference bounding box."""

    if conditioning.size != (800, 504) or raw_candidate.size != (800, 500):
        raise LayoutLockError("layout-lock raster dimensions are incompatible")
    source_bbox = _foreground_bbox(conditioning, threshold=threshold)
    reference_bbox = _map_reference_bbox(
        source_bbox,
        source_height=504,
        delivery_height=500,
    )
    raw_bbox = _foreground_bbox(raw_candidate, threshold=threshold)
    raw_crop = raw_candidate.crop((raw_bbox.x_min, raw_bbox.y_min, raw_bbox.x_max, raw_bbox.y_max))
    target_size = (
        reference_bbox.x_max - reference_bbox.x_min,
        reference_bbox.y_max - reference_bbox.y_min,
    )
    resized = raw_crop.resize(target_size, resample=Image.Resampling.LANCZOS)
    locked = Image.new("RGB", (800, 500), "white")
    locked.paste(resized, (reference_bbox.x_min, reference_bbox.y_min))
    locked_bbox = _foreground_bbox(locked, threshold=threshold)
    if locked_bbox != reference_bbox:
        raise LayoutLockError("locked foreground does not match reference bounds")
    return LayoutLockOutcome(
        image=locked,
        reference_bbox=reference_bbox,
        raw_candidate_bbox=raw_bbox,
        locked_candidate_bbox=locked_bbox,
        raw_area_ratio_milli=max(1, round(_area(raw_bbox) / _area(reference_bbox) * 1000)),
        raw_center_distance_milli=_center_distance_milli(
            reference_bbox,
            raw_bbox,
            canvas_width=800,
            canvas_height=500,
        ),
    )

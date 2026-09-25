"""Deterministic visual-region proposals over one staged assessment page.

The dominant operation is a single raster pass followed by row-run component grouping.  OCR boxes
are membership masks, connected components use a union-find over row runs, and the bounded result
is sorted once.  For an image with ``p`` pixels and ``r`` ink runs this is O(p + r alpha(r)) time,
O(p + r) space, and at most eight immutable proposals.  The module reads no database, NAS, network,
or filesystem path; callers supply already validated image bytes or decoded images.
"""

from __future__ import annotations

import csv
import io
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np  # type: ignore[import-not-found]
from eom_image_contracts import ImageEvaluationBoundingBox
from PIL import Image, ImageFilter  # type: ignore[import-not-found]

MAX_LOCATOR_DIMENSION = 700
MAX_OCR_TSV_BYTES = 8 * 1024 * 1024
MAX_TESSERACT_INPUT_BYTES = 64 * 1024 * 1024
MAX_PROPOSALS = 8
MAX_REDACTION_BOXES_PER_PROPOSAL = 64
_THRESHOLD = 185
_DILATION_SIZE = 15


class CropLocatorError(RuntimeError):
    """Stable fail-closed locator error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class LocatedVisualRegion:
    crop_bounding_box: ImageEvaluationBoundingBox
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...]
    candidate_rank: int
    ink_fraction_milli: int


def _clip_box(
    value: ImageEvaluationBoundingBox,
    outer: ImageEvaluationBoundingBox,
) -> ImageEvaluationBoundingBox | None:
    left = max(value.left, outer.left)
    top = max(value.top, outer.top)
    right = min(value.right, outer.right)
    bottom = min(value.bottom, outer.bottom)
    if left >= right or top >= bottom:
        return None
    return ImageEvaluationBoundingBox(left=left, top=top, right=right, bottom=bottom)


def _pixel_box(
    value: ImageEvaluationBoundingBox,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    return (
        max(0, value.left * width // 10_000),
        max(0, value.top * height // 10_000),
        min(width, (value.right * width + 9_999) // 10_000),
        min(height, (value.bottom * height + 9_999) // 10_000),
    )


def _normalized_box(
    value: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
) -> ImageEvaluationBoundingBox:
    left, top, right, bottom = value
    return ImageEvaluationBoundingBox(
        left=max(0, min(9_999, left * 10_000 // width)),
        top=max(0, min(9_999, top * 10_000 // height)),
        right=max(1, min(10_000, (right * 10_000 + width - 1) // width)),
        bottom=max(1, min(10_000, (bottom * 10_000 + height - 1) // height)),
    )


def parse_tesseract_tsv(
    payload: bytes,
    *,
    width: int,
    height: int,
    minimum_confidence: float = 10.0,
) -> tuple[ImageEvaluationBoundingBox, ...]:
    """Parse bounded TSV into sorted boxes without retaining recognized text."""

    if not payload or len(payload) > MAX_OCR_TSV_BYTES or width < 1 or height < 1:
        raise CropLocatorError("IMAGE_TRAINING_OCR_RESULT_INVALID")
    try:
        rows = csv.DictReader(io.StringIO(payload.decode("utf-8", errors="strict")), delimiter="\t")
        boxes: set[tuple[int, int, int, int]] = set()
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            confidence = float(row["conf"])
            if confidence < minimum_confidence:
                continue
            left = int(row["left"])
            top = int(row["top"])
            box_width = int(row["width"])
            box_height = int(row["height"])
            if (
                left < 0
                or top < 0
                or box_width < 1
                or box_height < 1
                or left + box_width > width
                or top + box_height > height
            ):
                raise ValueError("OCR box is outside the page")
            expanded = (
                max(0, left - 4),
                max(0, top - 3),
                min(width, left + box_width + 4),
                min(height, top + box_height + 3),
            )
            normalized = _normalized_box(expanded, width=width, height=height)
            boxes.add((normalized.top, normalized.left, normalized.bottom, normalized.right))
    except (KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise CropLocatorError("IMAGE_TRAINING_OCR_RESULT_INVALID") from exc
    return tuple(
        ImageEvaluationBoundingBox(left=left, top=top, right=right, bottom=bottom)
        for top, left, bottom, right in sorted(boxes)
    )


def run_tesseract(
    image: Image.Image,
    *,
    executable: Path = Path("/usr/bin/tesseract"),
) -> tuple[ImageEvaluationBoundingBox, ...]:
    """Run the pinned local OCR adapter over an already validated staged image."""

    if executable != Path("/usr/bin/tesseract") or not executable.is_file():
        raise CropLocatorError("IMAGE_TRAINING_OCR_RUNTIME_INVALID")
    buffer = io.BytesIO()
    image.convert("L").save(buffer, format="PNG", optimize=False)
    payload = buffer.getvalue()
    if len(payload) > MAX_TESSERACT_INPUT_BYTES:
        raise CropLocatorError("IMAGE_TRAINING_OCR_INPUT_TOO_LARGE")
    try:
        completed = subprocess.run(
            [str(executable), "stdin", "stdout", "-l", "kor+eng", "--psm", "11", "tsv"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CropLocatorError("IMAGE_TRAINING_OCR_EXEC_FAILED") from exc
    if completed.returncode != 0:
        raise CropLocatorError("IMAGE_TRAINING_OCR_EXEC_FAILED")
    return parse_tesseract_tsv(
        completed.stdout,
        width=image.width,
        height=image.height,
    )


def _components(mask: np.ndarray) -> tuple[tuple[int, int, int, int], ...]:
    """Label connected row runs without an all-pairs pixel/component scan."""

    parent: list[int] = []
    geometry: list[list[int]] = []
    previous: list[tuple[int, int, int]] = []

    def create(left: int, right: int, row: int) -> int:
        identity = len(parent)
        parent.append(identity)
        geometry.append([left, row, right, row + 1])
        return identity

    def find(identity: int) -> int:
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    def union(first: int, second: int) -> int:
        root_first = find(first)
        root_second = find(second)
        if root_first == root_second:
            return root_first
        parent[root_second] = root_first
        current = geometry[root_first]
        other = geometry[root_second]
        current[0] = min(current[0], other[0])
        current[1] = min(current[1], other[1])
        current[2] = max(current[2], other[2])
        current[3] = max(current[3], other[3])
        return root_first

    for row_number, row in enumerate(mask):
        padded = np.pad(row.astype(np.int8), (1, 1))
        changes = np.diff(padded)
        starts = np.where(changes == 1)[0]
        ends = np.where(changes == -1)[0]
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        for raw_left, raw_right in zip(starts, ends, strict=True):
            left = int(raw_left)
            right = int(raw_right)
            identity = create(left, right, row_number)
            while previous_index < len(previous) and previous[previous_index][1] < left - 1:
                previous_index += 1
            candidate_index = previous_index
            while candidate_index < len(previous) and previous[candidate_index][0] <= right + 1:
                identity = union(identity, previous[candidate_index][2])
                candidate_index += 1
            current.append((left, right, identity))
        previous = current
    roots = {find(identity) for identity in range(len(parent))}
    return tuple(
        (
            geometry[root][0],
            geometry[root][1],
            geometry[root][2],
            geometry[root][3],
        )
        for root in roots
    )


def locate_visual_regions(
    image: Image.Image,
    *,
    context_bounding_box: ImageEvaluationBoundingBox | None,
    ocr_boxes: tuple[ImageEvaluationBoundingBox, ...],
) -> tuple[LocatedVisualRegion, ...]:
    """Return ranked, bounded visual proposals; never decide training eligibility."""

    if image.width < 64 or image.height < 64 or image.width * image.height > 100_000_000:
        raise CropLocatorError("IMAGE_TRAINING_SOURCE_PAGE_INVALID")
    context = context_bounding_box or ImageEvaluationBoundingBox(
        left=0,
        top=0,
        right=10_000,
        bottom=10_000,
    )
    page_width, page_height = image.size
    context_pixels = _pixel_box(context, width=page_width, height=page_height)
    context_image = image.convert("L").crop(context_pixels)
    scale = min(1.0, MAX_LOCATOR_DIMENSION / max(context_image.size))
    working = context_image.resize(
        (
            max(1, int(context_image.width * scale)),
            max(1, int(context_image.height * scale)),
        )
    )
    working_width, working_height = working.size
    raw = np.asarray(working) < _THRESHOLD
    redaction_mask = np.zeros((working_height, working_width), dtype=np.bool_)
    context_left, context_top, context_right, context_bottom = context_pixels
    context_width = context_right - context_left
    context_height = context_bottom - context_top
    for ocr_box in ocr_boxes:
        clipped = _clip_box(ocr_box, context)
        if clipped is None:
            continue
        page_pixels = _pixel_box(clipped, width=page_width, height=page_height)
        left = max(0, int((page_pixels[0] - context_left) * scale))
        top = max(0, int((page_pixels[1] - context_top) * scale))
        right = min(working_width, int((page_pixels[2] - context_left) * scale) + 1)
        bottom = min(working_height, int((page_pixels[3] - context_top) * scale) + 1)
        redaction_mask[top:bottom, left:right] = True
    ink = raw & ~redaction_mask
    expanded = (
        np.asarray(
            Image.fromarray((ink * 255).astype(np.uint8)).filter(
                ImageFilter.MaxFilter(_DILATION_SIZE)
            )
        )
        > 0
    )
    total_area = working_width * working_height
    ranked: list[tuple[float, tuple[int, int, int, int], int]] = []
    for left, top, right, bottom in _components(expanded):
        width = right - left
        height = bottom - top
        area = width * height
        if (
            width < max(25, int(working_width * 0.05))
            or height < max(18, int(working_height * 0.025))
            or area < total_area * 0.002
            or area > total_area * 0.45
        ):
            continue
        actual_ink = int(ink[top:bottom, left:right].sum())
        if actual_ink < 120 or actual_ink / area < 0.006:
            continue
        score = actual_ink * (1 + min(width, height) / max(width, height))
        ranked.append((score, (left, top, right, bottom), actual_ink))
    ranked.sort(key=lambda value: (-value[0], value[1]))

    regions: list[LocatedVisualRegion] = []
    for _, work_box, actual_ink in ranked:
        left, top, right, bottom = work_box
        context_relative = (
            max(0, math.floor(left / scale)),
            max(0, math.floor(top / scale)),
            min(context_width, math.ceil(right / scale)),
            min(context_height, math.ceil(bottom / scale)),
        )
        page_box = (
            context_left + context_relative[0],
            context_top + context_relative[1],
            context_left + context_relative[2],
            context_top + context_relative[3],
        )
        normalized = _normalized_box(page_box, width=page_width, height=page_height)
        redactions = tuple(
            sorted(
                (
                    clipped
                    for value in ocr_boxes
                    if (clipped := _clip_box(value, normalized)) is not None
                ),
                key=lambda value: (value.top, value.left, value.bottom, value.right),
            )
        )
        if len(redactions) > MAX_REDACTION_BOXES_PER_PROPOSAL:
            continue
        fraction = max(1, min(1000, round(actual_ink * 1000 / max(1, area))))
        regions.append(
            LocatedVisualRegion(
                crop_bounding_box=normalized,
                redaction_boxes=redactions,
                candidate_rank=len(regions) + 1,
                ink_fraction_milli=fraction,
            )
        )
        if len(regions) == MAX_PROPOSALS:
            break
    return tuple(regions)

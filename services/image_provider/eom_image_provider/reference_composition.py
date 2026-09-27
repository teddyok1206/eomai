"""Deterministic composition-preservation evaluation for reference-conditioned images."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import numpy as np  # type: ignore[import-not-found]
from eom_image_contracts import (
    LocalImageReferenceCompositionEvaluation,
    LocalImageVisualReferencePointer,
    ReferenceCompositionCandidateMember,
    ReferenceCompositionConditioningMember,
    ReferenceCompositionEvaluator,
    ReferenceCompositionMetrics,
    ReferenceCompositionThresholds,
    composition_failure_reasons,
    content_sha256,
    validate_contract,
)
from PIL import (  # type: ignore[import-not-found]
    Image,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)
from PIL import __version__ as pillow_version

_WIDTH = 800
_HEIGHT = 504
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_EDGE_THRESHOLD = 40
_EDGE_DILATION_SIZE = 7
_IGNORED_BORDER_PX = 4


class ReferenceCompositionEvaluationError(RuntimeError):
    """Stable failure raised before an invalid evaluation can be published."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _safe_png(path: Path, *, expected_height: int) -> tuple[bytes, np.ndarray]:
    if not path.is_absolute():
        raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_PATH_INVALID")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_INVALID") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 64 <= before.st_size <= _MAX_IMAGE_BYTES
        ):
            raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_INVALID")
        payload = bytearray()
        while len(payload) <= _MAX_IMAGE_BYTES:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_IMAGE_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_CHANGED")
    finally:
        os.close(descriptor)
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.format != "PNG" or source.size != (_WIDTH, expected_height):
                raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_INVALID")
            source.verify()
        with Image.open(io.BytesIO(payload)) as source:
            normalized = source.convert("RGB")
            if expected_height != _HEIGHT:
                normalized = normalized.resize(
                    (_WIDTH, _HEIGHT),
                    resample=Image.Resampling.BILINEAR,
                )
            rgb = np.asarray(normalized, dtype=np.uint8)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        if isinstance(exc, ReferenceCompositionEvaluationError):
            raise
        raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_INPUT_INVALID") from exc
    return bytes(payload), rgb


def _edge_mask(rgb: np.ndarray) -> np.ndarray:
    image = Image.fromarray(rgb).convert("L")
    image = ImageOps.autocontrast(image)
    edges = np.asarray(
        image.filter(ImageFilter.GaussianBlur(1.0)).filter(ImageFilter.FIND_EDGES),
        dtype=np.uint8,
    )
    mask = (edges > _EDGE_THRESHOLD).copy()
    mask[:_IGNORED_BORDER_PX, :] = False
    mask[-_IGNORED_BORDER_PX:, :] = False
    mask[:, :_IGNORED_BORDER_PX] = False
    mask[:, -_IGNORED_BORDER_PX:] = False
    if not bool(mask.any()):
        raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_EDGE_MAP_EMPTY")
    return mask


def _dilate(mask: np.ndarray) -> np.ndarray:
    image = Image.fromarray(mask.astype(np.uint8) * 255)
    return np.asarray(image.filter(ImageFilter.MaxFilter(_EDGE_DILATION_SIZE))) > 0


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask)
    if xs.size == 0:
        raise ReferenceCompositionEvaluationError("IMAGE_COMPOSITION_EDGE_MAP_EMPTY")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _bbox_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / max(1, left_area + right_area - intersection)


def _measure(reference: np.ndarray, candidate: np.ndarray) -> ReferenceCompositionMetrics:
    reference_edges = _edge_mask(reference)
    candidate_edges = _edge_mask(candidate)
    reference_dilated = _dilate(reference_edges)
    candidate_dilated = _dilate(candidate_edges)
    precision = float(
        np.logical_and(candidate_edges, reference_dilated).sum()
        / max(1, int(candidate_edges.sum()))
    )
    recall = float(
        np.logical_and(reference_edges, candidate_dilated).sum()
        / max(1, int(reference_edges.sum()))
    )
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    reference_bbox = _bbox(reference_edges)
    candidate_bbox = _bbox(candidate_edges)
    reference_center = (
        (reference_bbox[0] + reference_bbox[2]) / (2 * _WIDTH),
        (reference_bbox[1] + reference_bbox[3]) / (2 * _HEIGHT),
    )
    candidate_center = (
        (candidate_bbox[0] + candidate_bbox[2]) / (2 * _WIDTH),
        (candidate_bbox[1] + candidate_bbox[3]) / (2 * _HEIGHT),
    )
    center_shift = (
        (reference_center[0] - candidate_center[0]) ** 2
        + (reference_center[1] - candidate_center[1]) ** 2
    ) ** 0.5
    width_scale = (candidate_bbox[2] - candidate_bbox[0]) / max(
        1, reference_bbox[2] - reference_bbox[0]
    )
    height_scale = (candidate_bbox[3] - candidate_bbox[1]) / max(
        1, reference_bbox[3] - reference_bbox[1]
    )
    reference_occupancy = float(reference_edges.mean())
    candidate_occupancy = float(candidate_edges.mean())
    channels = candidate.astype(np.float32) / 255.0
    foreground = channels.min(axis=2) < (250 / 255)
    chroma_pixels = channels.max(axis=2) - channels.min(axis=2)
    chroma = float(chroma_pixels[foreground].mean()) if bool(foreground.any()) else 0.0
    return ReferenceCompositionMetrics(
        edge_precision=round(precision, 6),
        edge_recall=round(recall, 6),
        edge_f1=round(f1, 6),
        foreground_bbox_iou=round(_bbox_iou(reference_bbox, candidate_bbox), 6),
        center_shift_ratio=round(center_shift, 6),
        width_scale_ratio=round(width_scale, 6),
        height_scale_ratio=round(height_scale, 6),
        edge_occupancy_delta_ratio=round(abs(reference_occupancy - candidate_occupancy), 6),
        mean_chroma_ratio=round(chroma, 6),
    )


def evaluate_reference_composition(
    *,
    reference_path: Path,
    candidate_path: Path,
    visual_reference: LocalImageVisualReferencePointer,
    source_commit: str,
    evaluated_at: datetime | None = None,
) -> LocalImageReferenceCompositionEvaluation:
    """Evaluate one exact candidate without model, network, database, or NAS access."""

    reference_payload, reference_rgb = _safe_png(reference_path, expected_height=504)
    candidate_payload, candidate_rgb = _safe_png(candidate_path, expected_height=500)
    metrics = _measure(reference_rgb, candidate_rgb)
    thresholds = ReferenceCompositionThresholds()
    failures = composition_failure_reasons(metrics, thresholds)
    evaluator = ReferenceCompositionEvaluator(
        source_commit=source_commit,
        pillow_version=pillow_version,
        numpy_version=np.__version__,
    )
    reference_member = ReferenceCompositionConditioningMember(
        member_path="inputs/reference-conditioning.png",
        sha256="sha256:" + hashlib.sha256(reference_payload).hexdigest(),
        size_bytes=len(reference_payload),
    )
    candidate_member = ReferenceCompositionCandidateMember(
        member_path="outputs/candidate.png",
        sha256="sha256:" + hashlib.sha256(candidate_payload).hexdigest(),
        size_bytes=len(candidate_payload),
    )
    body = {
        "schema_version": "local-image-reference-composition-evaluation/1.0",
        "policy": "COMPOSITION_PRESERVING_LINE_ART",
        "visual_reference": visual_reference.model_dump(mode="json"),
        "reference_conditioning": reference_member.model_dump(mode="json"),
        "candidate_output": candidate_member.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "thresholds": thresholds.model_dump(mode="json"),
        "failure_reasons": list(failures),
        "outcome": "PASS" if not failures else "FAIL",
        "evaluator": evaluator.model_dump(mode="json"),
        "evaluated_at": (evaluated_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "evaluation_id": "imgcompositioneval_" + identity[:32]}
    value = {**with_id, "evaluation_sha256": content_sha256(with_id)}
    validate_contract("reference-composition-evaluation", value)
    return LocalImageReferenceCompositionEvaluation.model_validate(value)

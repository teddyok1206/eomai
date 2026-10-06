"""Bounded pixel verification for already-resolved reviewed object support.

No model, path, source substitution or publication. The Orchestrator owns pointer
access/lineage admission; this adapter verifies exact bytes and edge-subset claims.
"""

from __future__ import annotations

import hashlib
import io

from eom_image_contracts.photo_object_support import (
    PhotoObjectSupportPixelObservation,
    PhotoObjectSupportReview,
)
from PIL import Image, ImageChops

from eom_image_provider.provider import ProviderError


def _decode(raw: bytes, *, expected_sha256: str, size: tuple[int, int], mode: str) -> Image.Image:
    if not 0 < len(raw) <= 16 * 1024**2:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_BYTE_BOUND_INVALID")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_HASH_MISMATCH")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.format != "PNG"
                or image.size != size
                or image.mode != mode
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("PNG mode/dimension/frame mismatch")
            image.load()
            return image.copy()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_PNG_INVALID") from exc


def _binary_control(image: Image.Image) -> Image.Image:
    red, green, blue = image.split()
    if (
        red.tobytes() != green.tobytes()
        or red.tobytes() != blue.tobytes()
        or set(red.tobytes()) != {0, 255}
    ):
        raise ProviderError("PHOTO_OBJECT_SUPPORT_CONTROL_PIXELS_INVALID")
    return red


def validate_photo_object_support_pixels(
    review: PhotoObjectSupportReview,
    *,
    source: bytes,
    prior_control: bytes,
    support_mask: bytes,
    candidate_control: bytes,
) -> PhotoObjectSupportPixelObservation:
    """O(bounded bytes/pixels); never invent an edge or silently re-encode input.

    Pixel verification is not scientific/semantic correctness or independent
    review. It cannot establish prior-control/source lineage or access permission.
    """
    _decode(source, expected_sha256=review.source.sha256, size=(800, 504), mode="RGB")
    prior = _binary_control(
        _decode(
            prior_control,
            expected_sha256=review.prior_control.sha256,
            size=(832, 512),
            mode="RGB",
        )
    )
    mask = _decode(
        support_mask,
        expected_sha256=review.support_mask.sha256,
        size=(832, 512),
        mode="L",
    )
    candidate = _binary_control(
        _decode(
            candidate_control,
            expected_sha256=review.candidate_control.sha256,
            size=(832, 512),
            mode="RGB",
        )
    )
    if set(mask.tobytes()) != {0, 255}:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_MASK_PIXELS_INVALID")
    expected = ImageChops.multiply(prior, mask)
    if expected.tobytes() != candidate.tobytes():
        raise ProviderError("PHOTO_OBJECT_SUPPORT_EDGE_RELATION_INVALID")
    original_edges = prior.histogram()[255]
    retained_edges = candidate.histogram()[255]
    if not 0 < retained_edges < original_edges:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_EDGE_COUNTS_INVALID")
    facts = PhotoObjectSupportPixelObservation(
        support_area_pixels=mask.histogram()[255],
        original_edges=original_edges,
        retained_edges=retained_edges,
        deleted_edges=original_edges - retained_edges,
        added_edges=0,
    )
    if facts != review.pixel_observation:
        raise ProviderError("PHOTO_OBJECT_SUPPORT_PIXEL_OBSERVATION_MISMATCH")
    return facts

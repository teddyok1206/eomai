"""Explicit exterior-only white replacement; no OCR, inpainting or object inference."""

from __future__ import annotations

from eom_image_contracts.models import ImageEvaluationBoundingBox
from eom_image_contracts.sdxl_native_training_targets import SdxlExteriorPrepareTargetDecision
from PIL import Image, ImageDraw, ImageStat


class ExteriorAnnotationError(ValueError):
    """The declared reviewer recipe cannot be applied without crossing its fixed guard."""


def _box(value: ImageEvaluationBoundingBox, width: int, height: int) -> tuple[int, int, int, int]:
    return (
        value.left * width // 10000,
        value.top * height // 10000,
        (value.right * width + 9999) // 10000,
        (value.bottom * height + 9999) // 10000,
    )


def remove_reviewed_exterior_annotations(
    source: Image.Image, decision: SdxlExteriorPrepareTargetDecision
) -> Image.Image:
    """Return a derivative only; all pixels outside declared rectangles stay identical.

    A white ring is a contact check, not proof that a disconnected interior mark is
    irrelevant. Explicit subject protection and subsequent human review remain required.
    """
    frame = _box(decision.framing_box, source.width, source.height)
    protected = tuple(
        _box(b, source.width, source.height) for b in decision.protected_subject_boxes
    )
    masks = tuple(_box(b, source.width, source.height) for b in decision.redaction_boxes)
    grayscale = source.convert("L")
    for left, top, right, bottom in masks:
        if not (frame[0] <= left < right <= frame[2] and frame[1] <= top < bottom <= frame[3]):
            raise ExteriorAnnotationError("SDXL_TARGET_ANNOTATION_PIXEL_BOUNDS_INVALID")
        outer = (
            max(frame[0], left - 3),
            max(frame[1], top - 3),
            min(frame[2], right + 3),
            min(frame[3], bottom + 3),
        )
        if any(
            outer[0] < b[2] and b[0] < outer[2] and outer[1] < b[3] and b[1] < outer[3]
            for b in protected
        ):
            raise ExteriorAnnotationError("SDXL_TARGET_ANNOTATION_PROTECTED_CONTACT")
        strips = (
            (outer[0], outer[1], outer[2], top),
            (outer[0], bottom, outer[2], outer[3]),
            (outer[0], top, left, bottom),
            (right, top, outer[2], bottom),
        )
        for strip in strips:
            if (
                strip[0] < strip[2]
                and strip[1] < strip[3]
                and ImageStat.Stat(grayscale.crop(strip)).extrema[0][0] < 250
            ):
                raise ExteriorAnnotationError("SDXL_TARGET_ANNOTATION_CLEARANCE_NOT_WHITE")
    derivative = source.copy()
    drawing = ImageDraw.Draw(derivative)
    for left, top, right, bottom in masks:
        fill = 255 if derivative.mode == "L" else (255, 255, 255)
        drawing.rectangle((left, top, right - 1, bottom - 1), fill=fill)
    return derivative

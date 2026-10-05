"""One case-aware pixel owner for full and reviewed-region photo control."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartProbeCase
from eom_image_contracts.sdxl_photo_region_review import photo_source_box_to_canvas
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStylePlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
)
from PIL import Image

from eom_image_provider.sdxl_canny_pixels import retained_canny_conditioning_png
from eom_image_provider.sdxl_reference_pixels import SdxlReferenceConditioner


def photo_style_conditioner(
    plan: LocalImageSdxlPhotoStylePlan, *, canny: Callable[..., bytes]
) -> SdxlReferenceConditioner:
    """O(cases) immutable lookup; preserve original internal pixels in O(canvas)."""
    regions = MappingProxyType(
        {r.case_id: r for r in plan.region_reviews}
        if isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan)
        else {}
    )

    def condition(
        case: SdxlLineartProbeCase, canvas: Image.Image, *, policy: SdxlCannyPolicy
    ) -> bytes:
        if not regions:
            return canny(canvas, policy=policy)
        # A retained plan never falls back to a full-frame or latest case.
        review = regions[case.case_id]
        if review.reference_sha256 != case.reference_image.sha256:
            raise ValueError("photo conditioning source differs from reviewed region")
        control = canny(canvas, policy=policy)
        return retained_canny_conditioning_png(
            control,
            policy=policy,
            retained_box=photo_source_box_to_canvas(review.retained_box),
            protected_boxes=tuple(photo_source_box_to_canvas(p) for p in review.protected_boxes),
        )

    return condition

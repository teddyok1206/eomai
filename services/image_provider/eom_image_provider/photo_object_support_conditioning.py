"""Staged support verification and exact candidate reuse, before any model loading."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartProbeCase
from eom_image_contracts.sdxl_photo_object_support_lineage import (
    photo_object_support_pixel_members,
    validate_photo_object_support_lineage,
)
from eom_image_contracts.sdxl_photo_style import LocalImageSdxlPhotoObjectSupportPlan
from eom_image_contracts.sdxl_photo_style_execution import SdxlPhotoStyleExecutionSources
from eom_image_contracts.sdxl_photo_style_result import PhotoObjectSupportExecutionTrace
from PIL import Image

from eom_image_provider.photo_object_support_pixels import validate_photo_object_support_pixels
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_photo_conditioning import photo_style_conditioner
from eom_image_provider.sdxl_reference_pixels import SdxlReferenceConditioner
from eom_image_provider.staged_file_io import read_staged_member


@dataclass(frozen=True, slots=True)
class PreparedPhotoStyleConditioning:
    conditioner: SdxlReferenceConditioner
    object_support: PhotoObjectSupportExecutionTrace | None


def staged_photo_style_conditioning(
    root: int,
    sources: SdxlPhotoStyleExecutionSources,
    originals: Mapping[str, bytes],
    *,
    canny: Callable[..., bytes],
) -> PreparedPhotoStyleConditioning:
    """Read/verify support once at this input boundary; no model or canonical writes.

    The returned callback reconstructs prior control from the unchanged source
    before reusing the exact candidate bytes. Construction itself does no Canny
    transform, so terminal replay can validate pixels without rerunning transforms.
    """
    plan = sources.plan
    if not isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan):
        return PreparedPhotoStyleConditioning(photo_style_conditioner(plan, canny=canny), None)
    try:
        if sources.object_support is None:
            raise ValueError("object support metadata missing")
        lineage = validate_photo_object_support_lineage(plan, sources.object_support)
        review = lineage.review
        payloads = tuple(
            read_staged_member(root, path, maximum_bytes=16 * 1024**2, expected_sha256=pin.sha256)
            for path, pin in photo_object_support_pixel_members(review)
        )
        observation = validate_photo_object_support_pixels(
            review,
            source=originals[plan.cases[0].case.case_id],
            prior_control=payloads[0],
            support_mask=payloads[1],
            candidate_control=payloads[2],
        )
        trace = PhotoObjectSupportExecutionTrace(
            review_sha256=review.review_sha256,
            source_sha256=review.source.sha256,
            prior_control_sha256=review.prior_control.sha256,
            support_mask_sha256=review.support_mask.sha256,
            candidate_control_sha256=review.candidate_control.sha256,
            pixel_observation=observation,
        )
        prior_id = review.prior_control.member_path.removeprefix("conditionings/").removesuffix(
            ".png"
        )
        prior_cases = {entry.case.case_id: entry.case for entry in lineage.prior_plan.cases}
        prior_case = prior_cases[prior_id]
        prior_conditioner = photo_style_conditioner(lineage.prior_plan, canny=canny)
        candidate = payloads[2]

        def condition(
            case: SdxlLineartProbeCase, canvas: Image.Image, *, policy: SdxlCannyPolicy
        ) -> bytes:
            if case != plan.cases[0].case:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            reproduced = prior_conditioner(prior_case, canvas, policy=policy)
            if "sha256:" + hashlib.sha256(reproduced).hexdigest() != review.prior_control.sha256:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            return candidate

        return PreparedPhotoStyleConditioning(condition, trace)
    except (ValueError, KeyError, OSError, ProviderError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc

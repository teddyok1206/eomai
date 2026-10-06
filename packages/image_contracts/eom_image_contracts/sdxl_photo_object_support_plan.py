"""Bounded preparation parser and stable public names for object-support plans."""

from __future__ import annotations

import hashlib
import json

from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
)
from eom_image_contracts.photo_object_support import (
    PhotoObjectSupportParents as PhotoObjectSupportParents,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoObjectSupportPlan as LocalImageSdxlPhotoObjectSupportPlan,
)
from eom_image_contracts.sdxl_photo_style import (
    PhotoObjectSupportBudget as PhotoObjectSupportBudget,
)

PLAN_SCHEMA = "eom://schemas/image-provider/local-image-sdxl-photo-style-plan/1.6"


def parse_photo_object_support_plan(
    pointer: ImageEvaluationArtifactMember, raw: bytes
) -> LocalImageSdxlPhotoObjectSupportPlan:
    """Preparation metadata parser, intentionally not the execution plan codec."""
    from eom_image_contracts.validation import validate_contract

    if (
        pointer.schema_ref != PLAN_SCHEMA
        or pointer.member_path != "manifests/sdxl-photo-style-plan.json"
        or pointer.media_type != "application/json"
    ):
        raise ValueError("OBJECT_SUPPORT_PLAN_POINTER_KIND_INVALID")
    if (
        not 0 < len(raw) <= 256 * 1024
        or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
    ):
        raise ValueError("OBJECT_SUPPORT_PLAN_BOUND_HASH_INVALID")
    value = json.loads(raw)
    validate_contract("sdxl-photo-style-plan-v7", value)
    plan = LocalImageSdxlPhotoObjectSupportPlan.model_validate(value)
    if raw != content_json_bytes(plan.model_dump(mode="json")):
        raise ValueError("OBJECT_SUPPORT_PLAN_NONCANONICAL")
    return plan

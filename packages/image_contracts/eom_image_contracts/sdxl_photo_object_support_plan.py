"""Single-pair preparation only; runtime codecs remain closed until integration."""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    content_json_bytes,
)
from eom_image_contracts.photo_object_support import REVIEW_SCHEMA
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleFullDenoisingPlan,
    SdxlPhotoStyleBudget,
    SdxlPhotoStyleCase,
)

PLAN_SCHEMA = "eom://schemas/image-provider/local-image-sdxl-photo-style-plan/1.6"


class PhotoObjectSupportParents(FrozenModel):
    """Small immutable metadata pins, not loaded parent payloads or latest aliases."""

    review: ImageEvaluationArtifactMember
    prior_plan: ImageEvaluationArtifactMember
    prior_result: ImageEvaluationArtifactMember
    baseline_plan: ImageEvaluationArtifactMember
    baseline_result: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_kinds(self) -> Self:
        pins = (
            (self.review, REVIEW_SCHEMA, "photo-object-support-review"),
            *(
                (
                    pin,
                    "eom://schemas/image-provider/local-image-sdxl-photo-style-" + family + "/1.5",
                    "sdxl-photo-style-" + family,
                )
                for pin, family in (
                    (self.prior_plan, "plan"),
                    (self.prior_result, "result"),
                    (self.baseline_plan, "plan"),
                    (self.baseline_result, "result"),
                )
            ),
        )
        if any(
            pin.schema_ref != schema
            or pin.member_path != "manifests/" + filename + ".json"
            or pin.media_type != "application/json"
            for pin, schema, filename in pins
        ):
            raise ValueError("OBJECT_SUPPORT_PARENT_POINTER_KIND_INVALID")
        # The same parent can legitimately be both control provenance and baseline;
        # conflicting claims about one immutable member cannot.
        claims: dict[tuple[str, str, str], ImageEvaluationArtifactMember] = {}
        for pin, _, _ in pins:
            identity = (pin.artifact_id, pin.artifact_revision_id, pin.member_path)
            if identity in claims and claims[identity] != pin:
                raise ValueError("OBJECT_SUPPORT_PARENT_IDENTITY_CONFLICT")
            claims[identity] = pin
        return self


class PhotoObjectSupportBudget(SdxlPhotoStyleBudget):
    maximum_outputs: Literal[2] = 2  # type: ignore[assignment]


class LocalImageSdxlPhotoObjectSupportPlan(LocalImageSdxlPhotoStyleFullDenoisingPlan):
    """No inheritance of old retained/protected-interior semantics."""

    _configuration_schema_ref: ClassVar[str] = (
        "eom://schemas/image-provider/local-image-sdxl-canny-reference-command/1.3"
    )
    schema_version: Literal["local-image-sdxl-photo-style-plan/1.6"]  # type: ignore[assignment]
    cases: tuple[SdxlPhotoStyleCase, ...] = Field(min_length=1, max_length=1)
    budget: PhotoObjectSupportBudget
    control: SdxlCannyControlParameters
    support_parents: PhotoObjectSupportParents
    comparison_policy: Literal["CHANGE_OBJECT_SUPPORT_ONLY_REUSE_PINNED_BASELINE"]


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

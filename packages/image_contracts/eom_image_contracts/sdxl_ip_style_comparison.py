"""A proposed matched style matrix is neither dispatch authority nor source admission."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer

SDXL_IP_STYLE_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-ip-style-comparison-plan/1.0"
)


class SdxlIpStyleRouting(FrozenModel):
    policy: Literal["UP_BLOCK0_ATTN1_ONLY/1.0"] = "UP_BLOCK0_ATTN1_ONLY/1.0"
    off_scale: float = Field(default=0.0, ge=0.0, le=0.0, strict=True)
    on_scale: float = Field(default=1.0, ge=1.0, le=1.0, strict=True)
    other_ip_scales: float = Field(default=0.0, ge=0.0, le=0.0, strict=True)
    feature_subtraction: Literal[False] = False
    self_attention_policy: Literal["UNCHANGED"] = "UNCHANGED"
    embedding_reuse: Literal["SAME_ENCODER_AND_SOURCE_FOR_BOTH_ARMS"] = (
        "SAME_ENCODER_AND_SOURCE_FOR_BOTH_ARMS"
    )


class SdxlIpStyleComparisonBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=600_000, strict=True)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3, strict=True)
    maximum_outputs: Literal[4] = 4
    maximum_dispatches: Literal[1] = 1
    automatic_retry: Literal[False] = False


class SdxlIpStylePairSelection(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    conditioning_sha256: Sha256
    initialization_rgb_sha256: Sha256
    style_sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    style_rgb_sha256: Sha256


class LocalImageSdxlIpStyleComparisonPlan(FrozenModel):
    schema_version: Literal["local-image-sdxl-ip-style-comparison-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgsdxlipstyleplan_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_STYLE_REFERENCE"]
    dispatch_policy: Literal["PREPARATION_ONLY_NOT_A_WORKER_COMMAND"]
    activation_policy: Literal["FORBIDDEN"]
    comparison_policy: Literal["ONLY_IP_SCALE_0_VS_1_SAME_LORA_AND_STRUCTURE"]
    photo_command: ImageEvaluationArtifactMember
    photo_result: ImageEvaluationArtifactMember
    style_training_command: ImageEvaluationArtifactMember
    style_model: SdxlIpStyleModelPointer
    routing: SdxlIpStyleRouting
    cases: tuple[SdxlIpStylePairSelection, ...] = Field(min_length=2, max_length=2)
    budget: SdxlIpStyleComparisonBudget
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL_IP_STYLE_PLAN_TIMESTAMP_NOT_UTC")
        return value

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        for pointer, family in (
            (self.photo_command, "sdxl-photo-style-command/1.5"),
            (self.photo_result, "sdxl-photo-style-result/1.5"),
            (self.style_training_command, "sdxl-native-lora-command/1.3"),
        ):
            if (
                pointer.schema_ref != "eom://schemas/image-provider/local-image-" + family
                or pointer.member_path != "manifests/" + family.split("/")[0] + ".json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL_IP_STYLE_PLAN_SOURCE_FAMILY_INVALID")
        ids = tuple(row.case_id for row in self.cases)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("SDXL_IP_STYLE_PLAN_CASE_ORDER_OR_DUPLICATE")
        style_hashes: dict[str, str] = {}
        for row in self.cases:
            if (
                style_hashes.setdefault(row.style_sample_id, row.style_rgb_sha256)
                != row.style_rgb_sha256
            ):
                raise ValueError("SDXL_IP_STYLE_PLAN_SHARED_STYLE_HASH_CONFLICT")
        if (
            self.plan_id
            != "imgsdxlipstyleplan_"
            + content_sha256(self.model_dump(mode="json", exclude={"plan_id", "plan_sha256"}))[7:39]
        ):
            raise ValueError("SDXL_IP_STYLE_PLAN_ID_MISMATCH")
        if self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("SDXL_IP_STYLE_PLAN_HASH_MISMATCH")
        return self


def parse_sdxl_ip_style_comparison_plan(
    pointer: ImageEvaluationArtifactMember,
    raw: bytes,
) -> LocalImageSdxlIpStyleComparisonPlan:
    """Verify one bounded canonical plan document; do not infer its sources or authorization."""
    from eom_image_contracts.validation import validate_contract

    pointer = ImageEvaluationArtifactMember.model_validate(pointer.model_dump(mode="json"))
    if (
        pointer.schema_ref != SDXL_IP_STYLE_PLAN_SCHEMA_REF
        or pointer.member_path != "manifests/sdxl-ip-style-comparison-plan.json"
        or pointer.media_type != "application/json"
        or not 0 < len(raw) <= 64 * 1024
    ):
        raise ValueError("SDXL_IP_STYLE_PLAN_POINTER_OR_BOUND_INVALID")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256:
        raise ValueError("SDXL_IP_STYLE_PLAN_DOCUMENT_HASH_MISMATCH")
    validate_contract("sdxl-ip-style-comparison-plan", json.loads(raw))
    plan = LocalImageSdxlIpStyleComparisonPlan.model_validate_json(raw)
    if raw != content_json_bytes(plan.model_dump(mode="json")):
        raise ValueError("SDXL_IP_STYLE_PLAN_DOCUMENT_NONCANONICAL")
    return plan

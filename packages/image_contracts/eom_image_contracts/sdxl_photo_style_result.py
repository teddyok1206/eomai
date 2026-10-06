"""Immutable photo-result contracts; independent of command/source admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    LocalImageRuntime,
    Sha256,
    content_sha256,
)
from eom_image_contracts.photo_object_support import PhotoObjectSupportPixelObservation
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_canny_reference import SdxlCannyReferenceTrace
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_photo_style import (
    SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
    LocalImageSdxlPhotoObjectSupportPlan,
    LocalImageSdxlPhotoStyleControlWindowPlan,
    LocalImageSdxlPhotoStylePlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    SdxlPhotoStyleControlWindow,
    SdxlPhotoStyleFullDenoisingInitialization,
    SdxlPhotoStyleInitialization,
    SdxlPhotoStyleWhiteInitialization,
    photo_style_contract_name,
    photo_style_region_reviews_sha256,
    photo_style_version,
)
from eom_image_contracts.validation import validate_contract


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("photo execution timestamp must use UTC")
    return value


class LocalImageSdxlPhotoStyleResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlvalcmprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    plan_sha256: Sha256
    configuration_command_sha256: Sha256
    native_evaluation_command_sha256: Sha256
    native_adapter_manifest_sha256: Sha256
    case_relation: Literal["LICENSED_PHOTO_REFERENCES_NOT_CORPUS_HOLDOUT"]
    native_fit_policy: Literal["NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0"]
    initialization: SdxlPhotoStyleInitialization
    quality_acceptance: Literal["NOT_REVIEWED"]
    activation_policy: Literal["FORBIDDEN"]
    training_steps: Literal[0]
    holdout_binary_reads: Literal[0]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    inputs: tuple[SdxlCannyReferenceTrace, ...] = Field(min_length=1, max_length=6)
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=12)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    _timestamp_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        ids = tuple(row.case_id for row in self.inputs)
        keys = tuple((row.arm, row.case_id, row.seed) for row in self.outputs)
        if (
            ids != tuple(sorted(set(ids)))
            or keys != tuple(sorted(set(keys)))
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("photo result order/status/time/hash mismatch")
        if self.outputs and (
            self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(row.peak_gpu_memory_bytes for row in self.outputs)
        ):
            raise ValueError("photo result lacks measured runtime")
        return self


class LocalImageSdxlPhotoStyleWhiteResult(LocalImageSdxlPhotoStyleResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.1"]  # type: ignore[assignment]
    initialization: SdxlPhotoStyleWhiteInitialization

    @model_validator(mode="after")
    def exact_white_initializer(self) -> Self:
        if any(
            trace.initialization_rgb_sha256 != SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
            for trace in self.inputs
        ):
            raise ValueError("white photo result contains a nonwhite initializer")
        return self


class LocalImageSdxlPhotoStyleFullDenoisingResult(LocalImageSdxlPhotoStyleWhiteResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.2"]  # type: ignore[assignment]
    initialization: SdxlPhotoStyleFullDenoisingInitialization


class LocalImageSdxlPhotoStyleControlWindowResult(LocalImageSdxlPhotoStyleFullDenoisingResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.3"]  # type: ignore[assignment]
    control_window: SdxlPhotoStyleControlWindow


class LocalImageSdxlPhotoStyleRetainedRegionResult(LocalImageSdxlPhotoStyleFullDenoisingResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.4"]  # type: ignore[assignment]
    control: SdxlCannyControlParameters
    region_reviews_sha256: Sha256


class LocalImageSdxlPhotoStyleBalancedExposureResult(LocalImageSdxlPhotoStyleRetainedRegionResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.5"]  # type: ignore[assignment]


class PhotoObjectSupportExecutionTrace(FrozenModel):
    """Recomputed bounded observations, not a semantic/quality acceptance flag."""

    review_sha256: Sha256
    source_sha256: Sha256
    prior_control_sha256: Sha256
    support_mask_sha256: Sha256
    candidate_control_sha256: Sha256
    pixel_observation: PhotoObjectSupportPixelObservation


class LocalImageSdxlPhotoObjectSupportResult(LocalImageSdxlPhotoStyleFullDenoisingResult):
    schema_version: Literal["local-image-sdxl-photo-style-result/1.6"]  # type: ignore[assignment]
    control: SdxlCannyControlParameters
    support_parents_sha256: Sha256
    object_support: PhotoObjectSupportExecutionTrace
    inputs: tuple[SdxlCannyReferenceTrace, ...] = Field(min_length=1, max_length=1)
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=2)


def parse_photo_style_result(value: object) -> LocalImageSdxlPhotoStyleResult:
    if not isinstance(value, dict):
        raise ValueError("photo result object required")
    schema = value.get("schema_version")
    models: dict[str, type[LocalImageSdxlPhotoStyleResult]] = {
        "local-image-sdxl-photo-style-result/1.0": LocalImageSdxlPhotoStyleResult,
        "local-image-sdxl-photo-style-result/1.1": LocalImageSdxlPhotoStyleWhiteResult,
        "local-image-sdxl-photo-style-result/1.2": LocalImageSdxlPhotoStyleFullDenoisingResult,
        "local-image-sdxl-photo-style-result/1.3": LocalImageSdxlPhotoStyleControlWindowResult,
        "local-image-sdxl-photo-style-result/1.4": LocalImageSdxlPhotoStyleRetainedRegionResult,
        "local-image-sdxl-photo-style-result/1.5": LocalImageSdxlPhotoStyleBalancedExposureResult,
        "local-image-sdxl-photo-style-result/1.6": LocalImageSdxlPhotoObjectSupportResult,
    }
    if not isinstance(schema, str) or schema not in models:
        raise ValueError("unsupported photo result family")
    validate_contract(photo_style_contract_name(schema), value)
    return models[schema].model_validate(value)


def validate_photo_style_plan_result_relation(
    plan: LocalImageSdxlPhotoStylePlan, result: LocalImageSdxlPhotoStyleResult
) -> None:
    """One authority for small plan/result relation, not full execution-source admission."""
    expected = tuple(
        (arm, entry.case.case_id, plan.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for entry in plan.cases
    )
    observed = tuple((row.arm, row.case_id, row.seed) for row in result.outputs)
    traces = {row.case_id: row for row in result.inputs}
    if (
        photo_style_version(result.schema_version) != photo_style_version(plan.schema_version)
        or result.plan_sha256 != plan.plan_sha256
        or result.initialization != plan.initialization
        or result.started_at < plan.created_at
        or tuple(traces) != tuple(entry.case.case_id for entry in plan.cases)
        or observed != expected[: len(observed)]
        or any(
            traces[entry.case.case_id].source_sha256 != entry.case.reference_image.sha256
            for entry in plan.cases
        )
        or any(
            row.reference_sha256 != traces[row.case_id].source_sha256
            or row.conditioning_sha256 != traces[row.case_id].conditioning_sha256
            for row in result.outputs
        )
    ):
        raise ValueError("photo result differs from pinned plan/configuration/ordered prefix")
    if result.status == "SUCCEEDED" and (
        observed != expected
        or result.runtime is None
        or result.duration_ms > plan.budget.maximum_duration_ms
        or result.runtime.peak_gpu_memory_bytes > plan.budget.maximum_peak_gpu_memory_bytes
    ):
        raise ValueError("photo success coverage/resource budget mismatch")
    if isinstance(plan, LocalImageSdxlPhotoStyleControlWindowPlan) and (
        not isinstance(result, LocalImageSdxlPhotoStyleControlWindowResult)
        or result.control_window != plan.control_window
    ):
        raise ValueError("photo result differs from declared spatial-control window")
    if isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan) and (
        not isinstance(result, LocalImageSdxlPhotoStyleRetainedRegionResult)
        or result.control != plan.control
        or result.region_reviews_sha256 != photo_style_region_reviews_sha256(plan)
    ):
        raise ValueError("photo result differs from declared retained-region review/control")
    if isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan) and (
        not isinstance(result, LocalImageSdxlPhotoObjectSupportResult)
        or result.control != plan.control
        or result.support_parents_sha256
        != content_sha256(plan.support_parents.model_dump(mode="json"))
        or result.object_support.source_sha256 != plan.cases[0].case.reference_image.sha256
        or result.object_support.candidate_control_sha256 != result.inputs[0].conditioning_sha256
    ):
        raise ValueError("photo result differs from declared object support/control")

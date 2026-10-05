"""Thin execution pointer and measured evidence for a frozen licensed-photo plan."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_reference import (
    SdxlCannyReferenceTrace,
    validate_sdxl_canny_reference_sources,
)
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    SdxlNativeCannyReferenceSources,
)
from eom_image_contracts.sdxl_native_lora_sources import SdxlNativeLoraSources
from eom_image_contracts.sdxl_photo_style import (
    SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
    LocalImageSdxlPhotoStylePlan,
    SdxlPhotoStyleInitialization,
    SdxlPhotoStyleSource,
    SdxlPhotoStyleWhiteInitialization,
    parse_photo_style_plan_value,
    photo_style_contract_name,
    photo_style_training_image_hashes,
    photo_style_version,
    validate_photo_style_sources,
)
from eom_image_contracts.validation import validate_contract


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("photo execution timestamp must use UTC")
    return value


class LocalImageSdxlPhotoStyleCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlvalcmprun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE"]
    activation_policy: Literal["FORBIDDEN"]
    plan: ImageEvaluationArtifactMember
    plan_id: str = Field(pattern=r"^imgsdxlphotoplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if (
            self.plan.schema_ref
            != "eom://schemas/image-provider/local-image-sdxl-photo-style-plan/"
            + photo_style_version(self.schema_version)
            or self.plan.member_path != "manifests/sdxl-photo-style-plan.json"
            or self.plan.media_type != "application/json"
        ):
            raise ValueError("photo execution requires an explicit registered plan")
        if self.run_id != "imgsdxlvalcmprun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("photo execution command identity/hash mismatch")
        return self


class LocalImageSdxlPhotoStyleWhiteCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.1"]  # type: ignore[assignment]


def parse_photo_style_command(value: object) -> LocalImageSdxlPhotoStyleCommand:
    if not isinstance(value, dict):
        raise ValueError("photo execution command object required")
    schema = value.get("schema_version")
    if schema not in (
        "local-image-sdxl-photo-style-command/1.0",
        "local-image-sdxl-photo-style-command/1.1",
    ):
        raise ValueError("unsupported photo command family")
    validate_contract(photo_style_contract_name(schema), value)
    model = (
        LocalImageSdxlPhotoStyleWhiteCommand
        if schema.endswith("/1.1")
        else LocalImageSdxlPhotoStyleCommand
    )
    return model.model_validate(value)


def parse_photo_style_plan(
    command: LocalImageSdxlPhotoStyleCommand, raw: bytes
) -> LocalImageSdxlPhotoStylePlan:
    if not 0 < len(raw) <= 256 * 1024 or (
        "sha256:" + hashlib.sha256(raw).hexdigest() != command.plan.sha256
    ):
        raise ValueError("photo execution plan byte size/hash mismatch")
    value = json.loads(raw)
    plan = parse_photo_style_plan_value(value)
    if (
        photo_style_version(plan.schema_version) != photo_style_version(command.schema_version)
        or raw != content_json_bytes(plan.model_dump(mode="json"))
        or plan.plan_id != command.plan_id
        or plan.plan_sha256 != command.plan_sha256
        or command.created_at < plan.created_at
    ):
        raise ValueError("photo execution plan identity/semantic hash/time mismatch")
    return plan


@dataclass(frozen=True, slots=True)
class SdxlPhotoStyleExecutionSources:
    plan: LocalImageSdxlPhotoStylePlan
    configuration: LocalImageSdxlNativeCannyReferenceCommandV2
    configuration_sources: SdxlNativeCannyReferenceSources
    native_training_sources: SdxlNativeLoraSources
    photos: tuple[SdxlPhotoStyleSource, ...]


def validate_photo_style_execution_sources(
    command: LocalImageSdxlPhotoStyleCommand, sources: SdxlPhotoStyleExecutionSources
) -> None:
    plan = sources.plan
    parse_photo_style_plan(command, content_json_bytes(plan.model_dump(mode="json")))
    configuration = sources.configuration
    if (
        type(configuration) is not LocalImageSdxlNativeCannyReferenceCommandV2
        or "sha256:"
        + hashlib.sha256(content_json_bytes(configuration.model_dump(mode="json"))).hexdigest()
        != plan.configuration_anchor.sha256
        or plan.created_at < configuration.created_at
        or plan.seed != sources.configuration_sources.spatial_sources.parent.seed
    ):
        raise ValueError("photo execution configuration family/hash/seed/time mismatch")
    validate_sdxl_canny_reference_sources(configuration, sources.configuration_sources)
    validate_photo_style_sources(
        plan,
        sources.photos,
        training_image_hashes=photo_style_training_image_hashes(sources.native_training_sources),
    )


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


def parse_photo_style_result(value: object) -> LocalImageSdxlPhotoStyleResult:
    if not isinstance(value, dict):
        raise ValueError("photo result object required")
    schema = value.get("schema_version")
    if schema not in (
        "local-image-sdxl-photo-style-result/1.0",
        "local-image-sdxl-photo-style-result/1.1",
    ):
        raise ValueError("unsupported photo result family")
    validate_contract(photo_style_contract_name(schema), value)
    model = (
        LocalImageSdxlPhotoStyleWhiteResult
        if schema.endswith("/1.1")
        else LocalImageSdxlPhotoStyleResult
    )
    return model.model_validate(value)


def validate_photo_style_result(
    command: LocalImageSdxlPhotoStyleCommand,
    sources: SdxlPhotoStyleExecutionSources,
    result: LocalImageSdxlPhotoStyleResult,
) -> None:
    validate_photo_style_execution_sources(command, sources)
    plan = sources.plan
    expected = tuple(
        (arm, entry.case.case_id, plan.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for entry in plan.cases
    )
    observed = tuple((row.arm, row.case_id, row.seed) for row in result.outputs)
    traces = {row.case_id: row for row in result.inputs}
    native = sources.configuration_sources
    if (
        photo_style_version(result.schema_version) != photo_style_version(command.schema_version)
        or result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.plan_sha256 != command.plan_sha256
        or result.configuration_command_sha256 != sources.configuration.command_sha256
        or result.native_evaluation_command_sha256 != native.evaluation.command_sha256
        or result.native_adapter_manifest_sha256 != native.native.manifest.manifest_sha256
        or result.initialization != plan.initialization
        or result.started_at < command.created_at
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

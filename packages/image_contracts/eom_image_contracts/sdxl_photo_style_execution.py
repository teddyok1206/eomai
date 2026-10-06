"""Thin execution pointer and measured evidence for a frozen licensed-photo plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.photo_object_support import (
    PhotoBaselineReuseDocuments,
    PhotoObjectSupportParentDocuments,
)
from eom_image_contracts.sdxl_canny_reference import (
    validate_sdxl_canny_reference_sources,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    LocalImageSdxlNativeCannyReferenceCommandV3,
    LocalImageSdxlNativeCannyReferenceCommandV4,
    SdxlNativeCannyReferenceSources,
)
from eom_image_contracts.sdxl_native_lora_sources import SdxlNativeLoraSources
from eom_image_contracts.sdxl_photo_baseline_reuse import parse_reused_photo_baseline
from eom_image_contracts.sdxl_photo_object_support_lineage import (
    validate_photo_object_support_lineage,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoObjectSupportPlan,
    LocalImageSdxlPhotoReusedBaselinePlan,
    LocalImageSdxlPhotoStyleBalancedExposurePlan,
    LocalImageSdxlPhotoStylePlan,
    SdxlPhotoStyleSource,
    parse_photo_style_plan_value,
    photo_style_contract_name,
    photo_style_training_image_hashes,
    photo_style_version,
    validate_photo_style_sources,
)
from eom_image_contracts.sdxl_photo_style_result import (
    LocalImageSdxlPhotoObjectSupportResult,
    LocalImageSdxlPhotoStyleBalancedExposureResult,
    LocalImageSdxlPhotoStyleControlWindowResult,
    LocalImageSdxlPhotoStyleFullDenoisingResult,
    LocalImageSdxlPhotoStyleResult,
    LocalImageSdxlPhotoStyleRetainedRegionResult,
    LocalImageSdxlPhotoStyleWhiteResult,
    parse_photo_style_result,
    validate_photo_style_plan_result_relation,
)
from eom_image_contracts.validation import validate_contract

__all__ = (
    "LocalImageSdxlPhotoObjectSupportCommand",
    "LocalImageSdxlPhotoObjectSupportResult",
    "LocalImageSdxlPhotoReusedBaselineCommand",
    "LocalImageSdxlPhotoStyleBalancedExposureCommand",
    "LocalImageSdxlPhotoStyleBalancedExposureResult",
    "LocalImageSdxlPhotoStyleCommand",
    "LocalImageSdxlPhotoStyleControlWindowCommand",
    "LocalImageSdxlPhotoStyleControlWindowResult",
    "LocalImageSdxlPhotoStyleFullDenoisingCommand",
    "LocalImageSdxlPhotoStyleFullDenoisingResult",
    "LocalImageSdxlPhotoStyleResult",
    "LocalImageSdxlPhotoStyleRetainedRegionCommand",
    "LocalImageSdxlPhotoStyleRetainedRegionResult",
    "LocalImageSdxlPhotoStyleWhiteCommand",
    "LocalImageSdxlPhotoStyleWhiteResult",
    "SdxlPhotoStyleExecutionSources",
    "is_photo_style_command_schema",
    "parse_photo_style_command",
    "parse_photo_style_plan",
    "parse_photo_style_result",
    "validate_photo_style_execution_sources",
    "validate_photo_style_plan_result_relation",
    "validate_photo_style_result",
)


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


class LocalImageSdxlPhotoStyleFullDenoisingCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.2"]  # type: ignore[assignment]


class LocalImageSdxlPhotoStyleControlWindowCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.3"]  # type: ignore[assignment]


class LocalImageSdxlPhotoStyleRetainedRegionCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.4"]  # type: ignore[assignment]


class LocalImageSdxlPhotoStyleBalancedExposureCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.5"]  # type: ignore[assignment]


class LocalImageSdxlPhotoObjectSupportCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.6"]  # type: ignore[assignment]


class LocalImageSdxlPhotoReusedBaselineCommand(LocalImageSdxlPhotoStyleCommand):
    schema_version: Literal["local-image-sdxl-photo-style-command/1.7"]  # type: ignore[assignment]


_COMMAND_MODELS: Mapping[str, type[LocalImageSdxlPhotoStyleCommand]] = MappingProxyType(
    {
        "local-image-sdxl-photo-style-command/1.0": LocalImageSdxlPhotoStyleCommand,
        "local-image-sdxl-photo-style-command/1.1": LocalImageSdxlPhotoStyleWhiteCommand,
        "local-image-sdxl-photo-style-command/1.2": LocalImageSdxlPhotoStyleFullDenoisingCommand,
        "local-image-sdxl-photo-style-command/1.3": LocalImageSdxlPhotoStyleControlWindowCommand,
        "local-image-sdxl-photo-style-command/1.4": LocalImageSdxlPhotoStyleRetainedRegionCommand,
        "local-image-sdxl-photo-style-command/1.5": LocalImageSdxlPhotoStyleBalancedExposureCommand,
        "local-image-sdxl-photo-style-command/1.6": LocalImageSdxlPhotoObjectSupportCommand,
        "local-image-sdxl-photo-style-command/1.7": LocalImageSdxlPhotoReusedBaselineCommand,
    }
)


def is_photo_style_command_schema(value: object) -> bool:
    """File adapters select only families supported by the authoritative closed codec."""
    return isinstance(value, str) and value in _COMMAND_MODELS


def parse_photo_style_command(value: object) -> LocalImageSdxlPhotoStyleCommand:
    if not isinstance(value, dict):
        raise ValueError("photo execution command object required")
    schema = value.get("schema_version")
    if not isinstance(schema, str) or not is_photo_style_command_schema(schema):
        raise ValueError("unsupported photo command family")
    validate_contract(photo_style_contract_name(schema), value)
    return _COMMAND_MODELS[schema].model_validate(value)


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
    object_support: PhotoObjectSupportParentDocuments | None = None
    baseline_reuse: PhotoBaselineReuseDocuments | None = None


def validate_photo_style_execution_sources(
    command: LocalImageSdxlPhotoStyleCommand, sources: SdxlPhotoStyleExecutionSources
) -> None:
    plan = sources.plan
    parse_photo_style_plan(command, content_json_bytes(plan.model_dump(mode="json")))
    configuration = sources.configuration
    expected_model = (
        LocalImageSdxlNativeCannyReferenceCommandV4
        if isinstance(plan, LocalImageSdxlPhotoReusedBaselinePlan)
        else LocalImageSdxlNativeCannyReferenceCommandV3
        if isinstance(
            plan,
            (LocalImageSdxlPhotoStyleBalancedExposurePlan, LocalImageSdxlPhotoObjectSupportPlan),
        )
        else LocalImageSdxlNativeCannyReferenceCommandV2
    )
    if (
        type(configuration) is not expected_model
        or "sha256:"
        + hashlib.sha256(content_json_bytes(configuration.model_dump(mode="json"))).hexdigest()
        != plan.configuration_anchor.sha256
        or plan.created_at < configuration.created_at
        or plan.seed != sources.configuration_sources.spatial_sources.parent.seed
    ):
        raise ValueError("photo execution configuration family/hash/seed/time mismatch")
    validate_sdxl_canny_reference_sources(configuration, sources.configuration_sources)
    reused = None
    if isinstance(plan, LocalImageSdxlPhotoReusedBaselinePlan):
        if sources.baseline_reuse is None or not isinstance(
            configuration, LocalImageSdxlNativeCannyReferenceCommandV4
        ):
            raise ValueError("PHOTO_STYLE_BASELINE_REUSE_METADATA_MISSING")
        reused = parse_reused_photo_baseline(
            plan, configuration, sources.configuration_sources, sources.baseline_reuse
        )
    elif sources.baseline_reuse is not None:
        raise ValueError("PHOTO_STYLE_BASELINE_REUSE_UNDECLARED")
    validate_photo_style_sources(
        plan,
        sources.photos,
        training_image_hashes=photo_style_training_image_hashes(sources.native_training_sources),
    )
    if isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan):
        if sources.object_support is None:
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_METADATA_MISSING")
        lineage = validate_photo_object_support_lineage(plan, sources.object_support)
        native = sources.configuration_sources
        parent_configuration = (
            reused.configuration.command_sha256 if reused else configuration.command_sha256
        )
        parent_evaluation = (
            reused.geometry.command_sha256 if reused else native.evaluation.command_sha256
        )
        parent_adapter = (
            reused.geometry.evaluation.adapter_manifest_sha256
            if reused
            else native.native.manifest.manifest_sha256
        )
        if any(
            parent.configuration_command_sha256 != parent_configuration
            or parent.native_evaluation_command_sha256 != parent_evaluation
            or parent.native_adapter_manifest_sha256 != parent_adapter
            for parent in (lineage.prior_result, lineage.baseline_result)
        ):
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_NATIVE_PARENT_MISMATCH")
        if reused is not None:
            review, trace = lineage.review, reused.result.object_support
            if (
                trace.review_sha256 != review.review_sha256
                or trace.source_sha256 != review.source.sha256
                or trace.prior_control_sha256 != review.prior_control.sha256
                or trace.support_mask_sha256 != review.support_mask.sha256
                or trace.candidate_control_sha256 != review.candidate_control.sha256
                or trace.pixel_observation != review.pixel_observation
            ):
                raise ValueError("PHOTO_STYLE_BASELINE_REUSE_TRACE_MISMATCH")
    elif sources.object_support is not None:
        raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_UNDECLARED")


def validate_photo_style_result(
    command: LocalImageSdxlPhotoStyleCommand,
    sources: SdxlPhotoStyleExecutionSources,
    result: LocalImageSdxlPhotoStyleResult,
) -> None:
    validate_photo_style_execution_sources(command, sources)
    plan = sources.plan
    native = sources.configuration_sources
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.configuration_command_sha256 != sources.configuration.command_sha256
        or result.native_evaluation_command_sha256 != native.evaluation.command_sha256
        or result.native_adapter_manifest_sha256 != native.native.manifest.manifest_sha256
        or result.started_at < command.created_at
    ):
        raise ValueError("photo result differs from pinned plan/configuration/ordered prefix")
    validate_photo_style_plan_result_relation(plan, result)
    if isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan):
        if (
            not isinstance(result, LocalImageSdxlPhotoObjectSupportResult)
            or sources.object_support is None
        ):
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_RESULT_MISSING")
        review = validate_photo_object_support_lineage(plan, sources.object_support).review
        trace = result.object_support
        if (
            trace.review_sha256 != review.review_sha256
            or trace.source_sha256 != review.source.sha256
            or trace.prior_control_sha256 != review.prior_control.sha256
            or trace.support_mask_sha256 != review.support_mask.sha256
            or trace.candidate_control_sha256 != review.candidate_control.sha256
            or trace.pixel_observation != review.pixel_observation
        ):
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_RESULT_INVALID")

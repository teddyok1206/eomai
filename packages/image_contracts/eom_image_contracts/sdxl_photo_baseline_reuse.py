"""Authenticate the previous object-supported BASE without old weights or pixels."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.photo_object_support import PhotoBaselineReuseDocuments
from eom_image_contracts.sdxl_geometry_baseline_reuse import LocalImageSdxlReusedGeometryCommand
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_evaluation_metadata
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV3,
    LocalImageSdxlNativeCannyReferenceCommandV4,
    SdxlNativeCannyReferenceSources,
    parse_reference_command,
)
from eom_image_contracts.sdxl_native_geometry import LocalImageSdxlNativeGeometryCommandV3
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoObjectSupportPlan,
    LocalImageSdxlPhotoReusedBaselinePlan,
    parse_photo_style_plan_value,
)
from eom_image_contracts.sdxl_photo_style_result import (
    LocalImageSdxlPhotoObjectSupportResult,
    parse_photo_style_result,
    validate_photo_style_plan_result_relation,
)


def photo_baseline_reuse_metadata_members(
    plan: LocalImageSdxlPhotoReusedBaselinePlan,
) -> tuple[tuple[str, ImageEvaluationArtifactMember], ...]:
    """Only three additional metadata members; geometry was staged by native admission."""
    return tuple(
        ("inputs/photo-reuse/" + key.replace("_", "-") + ".json", pin)
        for key, pin in (
            ("prior_plan", plan.baseline_reuse.prior_plan),
            ("prior_result", plan.baseline_reuse.prior_result),
            ("prior_configuration", plan.baseline_reuse.prior_configuration),
        )
    )


def photo_baseline_reuse_documents(
    plan: LocalImageSdxlPhotoReusedBaselinePlan,
    metadata: Mapping[str, bytes],
) -> PhotoBaselineReuseDocuments:
    prior_plan, prior_result, prior_configuration = (
        metadata[path] for path, _ in photo_baseline_reuse_metadata_members(plan)
    )
    return PhotoBaselineReuseDocuments(
        prior_plan,
        prior_result,
        prior_configuration,
        metadata["inputs/native-reuse-command.json"],
    )


@dataclass(frozen=True, slots=True)
class ReusedPhotoBaseline:
    plan: LocalImageSdxlPhotoObjectSupportPlan
    result: LocalImageSdxlPhotoObjectSupportResult
    configuration: LocalImageSdxlNativeCannyReferenceCommandV3
    geometry: LocalImageSdxlNativeGeometryCommandV3

    @property
    def base_outputs(self) -> tuple[SdxlLearnedComparisonOutput, ...]:
        return tuple(row for row in self.result.outputs if row.arm == "BASE")


def parse_reused_photo_baseline(
    plan: LocalImageSdxlPhotoReusedBaselinePlan,
    configuration: LocalImageSdxlNativeCannyReferenceCommandV4,
    sources: SdxlNativeCannyReferenceSources,
    documents: PhotoBaselineReuseDocuments,
) -> ReusedPhotoBaseline:
    """Pure bounded metadata equivalence. Caller owns access/lifecycle resolution."""
    pins = plan.baseline_reuse
    if (
        type(configuration) is not LocalImageSdxlNativeCannyReferenceCommandV4
        or "sha256:"
        + hashlib.sha256(content_json_bytes(configuration.model_dump(mode="json"))).hexdigest()
        != plan.configuration_anchor.sha256
        or configuration.created_at > plan.created_at
    ):
        raise ValueError("PHOTO_BASELINE_REUSE_CONFIGURATION_INVALID")
    for pin, raw in (
        (pins.prior_plan, documents.prior_plan),
        (pins.prior_result, documents.prior_result),
        (pins.prior_configuration, documents.prior_configuration),
    ):
        if not 0 < len(raw) <= 256 * 1024 or (
            "sha256:" + hashlib.sha256(raw).hexdigest() != pin.sha256
        ):
            raise ValueError("PHOTO_BASELINE_REUSE_BOUND_HASH_INVALID")
    prior = parse_photo_style_plan_value(json.loads(documents.prior_plan))
    result = parse_photo_style_result(json.loads(documents.prior_result))
    old_configuration = parse_reference_command(json.loads(documents.prior_configuration))
    if (
        type(prior) is not LocalImageSdxlPhotoObjectSupportPlan
        or type(result) is not LocalImageSdxlPhotoObjectSupportResult
        or type(old_configuration) is not LocalImageSdxlNativeCannyReferenceCommandV3
    ):
        raise ValueError("PHOTO_BASELINE_REUSE_FAMILY_INVALID")
    for raw, model in (
        (documents.prior_plan, prior),
        (documents.prior_result, result),
        (documents.prior_configuration, old_configuration),
    ):
        if raw != content_json_bytes(model.model_dump(mode="json")):
            raise ValueError("PHOTO_BASELINE_REUSE_NONCANONICAL")
    validate_photo_style_plan_result_relation(prior, result)
    geometry = sources.evaluation
    if not isinstance(geometry, LocalImageSdxlReusedGeometryCommand):
        raise ValueError("PHOTO_BASELINE_REUSE_NATIVE_FAMILY_INVALID")
    old_geometry = parse_sdxl_evaluation_metadata(
        geometry.baseline_reuse.prior_command,
        documents.prior_geometry,
        "sdxl-lora-evaluation-command-v6",
        LocalImageSdxlNativeGeometryCommandV3,
    )
    if (
        result.status != "SUCCEEDED"
        or result.completed_at > plan.created_at
        or old_configuration.created_at > prior.created_at
        or prior.configuration_anchor != pins.prior_configuration
        or old_configuration.native_evaluation_command != geometry.baseline_reuse.prior_command
        or result.configuration_command_sha256 != old_configuration.command_sha256
        or result.native_evaluation_command_sha256 != old_geometry.command_sha256
        or result.native_adapter_manifest_sha256 != old_geometry.evaluation.adapter_manifest_sha256
        or old_geometry.evaluation.adapter_strength != geometry.evaluation.adapter_strength
        or geometry.evaluation.adapter_strength != 1.0
        or prior.cases != plan.cases
        or prior.seed != plan.seed
        or prior.initialization != plan.initialization
        or prior.control != plan.control
        or prior.support_parents != plan.support_parents
        or prior.budget.model_dump(exclude={"maximum_outputs"})
        != plan.budget.model_dump(exclude={"maximum_outputs"})
        or old_configuration.spatial_command != configuration.spatial_command
        or old_configuration.spatial_result != configuration.spatial_result
        or old_configuration.initialization != configuration.initialization
        or old_configuration.budget != configuration.budget
        or old_geometry.numerics != geometry.numerics
        or old_geometry.cases != geometry.cases
        or old_geometry.negative_prompt_sha256 != geometry.negative_prompt_sha256
        or old_geometry.conditioning_policy != geometry.conditioning_policy
        or old_geometry.case_relation != geometry.case_relation
        or old_geometry.evaluation.baseline_command != geometry.evaluation.baseline_command
    ):
        raise ValueError("PHOTO_BASELINE_REUSE_INPUT_MISMATCH")
    return ReusedPhotoBaseline(prior, result, old_configuration, old_geometry)

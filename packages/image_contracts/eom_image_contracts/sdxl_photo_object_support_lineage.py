"""Pure bounded metadata closure; permission, pixels and native admission stay separate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.photo_object_support import (
    PhotoObjectSupportReview,
    parse_photo_object_support_review,
)
from eom_image_contracts.sdxl_learned_comparison import (
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_photo_object_support_plan import LocalImageSdxlPhotoObjectSupportPlan
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleBalancedExposurePlan,
    parse_photo_style_plan_value,
    photo_style_artifact_pointer,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleBalancedExposureResult,
    parse_photo_style_result,
    validate_photo_style_plan_result_relation,
)


@dataclass(frozen=True, slots=True)
class PhotoObjectSupportParentDocuments:
    """One bounded input materialization; no binary PNG payloads in this value."""

    review: bytes
    prior_plan: bytes
    prior_result: bytes
    baseline_plan: bytes
    baseline_result: bytes


@dataclass(frozen=True, slots=True)
class PhotoObjectSupportLineage:
    review: PhotoObjectSupportReview
    prior_plan: LocalImageSdxlPhotoStyleBalancedExposurePlan
    prior_result: LocalImageSdxlPhotoStyleBalancedExposureResult
    baseline_plan: LocalImageSdxlPhotoStyleBalancedExposurePlan
    baseline_result: LocalImageSdxlPhotoStyleBalancedExposureResult
    baseline_outputs: tuple[SdxlLearnedComparisonOutput, ...]


def _parent_pair(
    plan_pin: ImageEvaluationArtifactMember,
    result_pin: ImageEvaluationArtifactMember,
    plan_raw: bytes,
    result_raw: bytes,
) -> tuple[
    LocalImageSdxlPhotoStyleBalancedExposurePlan, LocalImageSdxlPhotoStyleBalancedExposureResult
]:
    for pin, raw in ((plan_pin, plan_raw), (result_pin, result_raw)):
        if (
            not 0 < len(raw) <= 256 * 1024
            or "sha256:" + hashlib.sha256(raw).hexdigest() != pin.sha256
        ):
            raise ValueError("OBJECT_SUPPORT_PARENT_BOUND_HASH_INVALID")
    plan = parse_photo_style_plan_value(json.loads(plan_raw))
    result = parse_photo_style_result(json.loads(result_raw))
    if (
        type(plan) is not LocalImageSdxlPhotoStyleBalancedExposurePlan
        or type(result) is not LocalImageSdxlPhotoStyleBalancedExposureResult
        or plan_raw != content_json_bytes(plan.model_dump(mode="json"))
        or result_raw != content_json_bytes(result.model_dump(mode="json"))
    ):
        raise ValueError("OBJECT_SUPPORT_PARENT_FAMILY_CANONICAL_INVALID")
    if result.status != "SUCCEEDED":
        raise ValueError("OBJECT_SUPPORT_PARENT_PLAN_RESULT_INVALID")
    try:
        validate_photo_style_plan_result_relation(plan, result)
    except ValueError as exc:
        raise ValueError("OBJECT_SUPPORT_PARENT_PLAN_RESULT_INVALID") from exc
    return plan, result


def validate_photo_object_support_lineage(
    plan: LocalImageSdxlPhotoObjectSupportPlan, documents: PhotoObjectSupportParentDocuments
) -> PhotoObjectSupportLineage:
    """Verify pinned preparation lineage; no pointer I/O, dispatch or quality approval."""
    pins = plan.support_parents
    review = parse_photo_object_support_review(pins.review, documents.review)
    prior, prior_result = _parent_pair(
        pins.prior_plan, pins.prior_result, documents.prior_plan, documents.prior_result
    )
    baseline, baseline_result = _parent_pair(
        pins.baseline_plan,
        pins.baseline_result,
        documents.baseline_plan,
        documents.baseline_result,
    )
    entry = plan.cases[0]
    prior_cases = {row.case.case_id: row for row in prior.cases}
    prior_traces = {row.case_id: row for row in prior_result.inputs}
    baseline_cases = {row.case.case_id: row for row in baseline.cases}
    baseline_traces = {row.case_id: row for row in baseline_result.inputs}
    prior_id = review.prior_control.member_path.removeprefix("conditionings/").removesuffix(".png")
    prior_entry = prior_cases.get(prior_id)
    prior_trace = prior_traces.get(prior_id)
    baseline_entry = baseline_cases.get(entry.case.case_id)
    baseline_trace = baseline_traces.get(entry.case.case_id)
    if (
        prior_entry is None
        or prior_trace is None
        or baseline_entry is None
        or baseline_trace is None
    ):
        raise ValueError("OBJECT_SUPPORT_PARENT_CASE_MISSING")
    prior_regions = {row.case_id: row for row in prior.region_reviews}
    baseline_regions = {row.case_id: row for row in baseline.region_reviews}
    if (
        entry != baseline_entry
        or prior_entry.visual_reference != entry.visual_reference
        or review.source != photo_style_artifact_pointer(entry.visual_reference.reference_member)
        or (review.prior_control.artifact_id, review.prior_control.artifact_revision_id)
        != (pins.prior_result.artifact_id, pins.prior_result.artifact_revision_id)
        or review.prior_control.sha256 != prior_trace.conditioning_sha256
        or prior_trace.conditioning_sha256 != baseline_trace.conditioning_sha256
        or prior_trace.initialization_rgb_sha256 != baseline_trace.initialization_rgb_sha256
        or prior_regions[prior_id].context_policy != review.context_policy
        or baseline_regions[entry.case.case_id].context_policy != review.context_policy
        or prior.configuration_anchor != baseline.configuration_anchor
        or plan.configuration_anchor != baseline.configuration_anchor
        or prior.seed != baseline.seed
        or plan.seed != baseline.seed
        or prior.control != baseline.control
        or plan.control != baseline.control
        or prior.initialization != baseline.initialization
        or plan.initialization != baseline.initialization
        or prior_result.configuration_command_sha256 != baseline_result.configuration_command_sha256
        or prior_result.native_evaluation_command_sha256
        != baseline_result.native_evaluation_command_sha256
        or prior_result.native_adapter_manifest_sha256
        != baseline_result.native_adapter_manifest_sha256
        or prior_result.completed_at > review.reviewed_at
        or baseline_result.completed_at > plan.created_at
        or review.created_at > plan.created_at
    ):
        raise ValueError("OBJECT_SUPPORT_SINGLE_FACTOR_LINEAGE_INVALID")
    outputs = tuple(row for row in baseline_result.outputs if row.case_id == entry.case.case_id)
    return PhotoObjectSupportLineage(
        review, prior, prior_result, baseline, baseline_result, outputs
    )

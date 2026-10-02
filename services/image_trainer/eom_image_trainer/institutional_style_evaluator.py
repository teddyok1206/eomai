"""Pure evaluator for pinned institutional-style image comparison plans."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    InstitutionalStyleCaseResult,
    LocalImageInstitutionalStyleEvaluationPlan,
    LocalImageInstitutionalStyleEvaluationResult,
    content_sha256,
    validate_institutional_style_result,
)

from eom_image_trainer.institutional_style_metrics import (
    InstitutionalStyleMetricsError,
    institutional_style_metrics,
)

MemberResolver = Callable[[ImageEvaluationArtifactMember], bytes]


class InstitutionalStyleEvaluationError(ValueError):
    """Stable failure raised before an evaluation result can be accepted."""


def _resolve_exact(
    member: ImageEvaluationArtifactMember,
    *,
    resolve_member: MemberResolver,
) -> bytes:
    try:
        payload = resolve_member(member)
    except Exception as exc:
        raise InstitutionalStyleEvaluationError(
            "INSTITUTIONAL_STYLE_MEMBER_RESOLUTION_FAILED"
        ) from exc
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != member.sha256:
        raise InstitutionalStyleEvaluationError("INSTITUTIONAL_STYLE_MEMBER_HASH_MISMATCH")
    return payload


def evaluate_institutional_style(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    *,
    resolve_member: MemberResolver,
    completed_at: datetime,
) -> LocalImageInstitutionalStyleEvaluationResult:
    """Evaluate an exact plan in O(C*W*H), resolving each immutable member once."""

    if completed_at.tzinfo is None or completed_at.utcoffset() != UTC.utcoffset(completed_at):
        raise InstitutionalStyleEvaluationError("INSTITUTIONAL_STYLE_COMPLETION_TIME_INVALID")
    case_results: list[InstitutionalStyleCaseResult] = []
    try:
        for case in plan.cases:
            institutional = institutional_style_metrics(
                _resolve_exact(case.institutional_image, resolve_member=resolve_member)
            )
            generated = institutional_style_metrics(
                _resolve_exact(case.generated_image, resolve_member=resolve_member)
            )
            metric_fields = (
                "foreground_fraction_milli",
                "dark_fraction_milli",
                "mid_tone_fraction_milli",
                "edge_fraction_milli",
                "border_foreground_fraction_milli",
                "fine_detail_fraction_milli",
                "tiny_component_fraction_milli",
            )
            distance = sum(
                abs(getattr(institutional, field) - getattr(generated, field))
                for field in metric_fields
            )
            case_results.append(
                InstitutionalStyleCaseResult(
                    case_id=case.case_id,
                    institutional_metrics=institutional,
                    generated_metrics=generated,
                    metric_distance_milli=distance,
                )
            )
    except InstitutionalStyleMetricsError as exc:
        raise InstitutionalStyleEvaluationError("INSTITUTIONAL_STYLE_IMAGE_INVALID") from exc

    body = {
        "schema_version": "local-image-institutional-style-evaluation-result/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "status": "SUCCEEDED",
        "case_results": [result.model_dump(mode="json") for result in case_results],
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    result = LocalImageInstitutionalStyleEvaluationResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )
    validate_institutional_style_result(plan, result)
    return result

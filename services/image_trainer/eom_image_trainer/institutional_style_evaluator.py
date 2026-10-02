"""Pure evaluator for pinned institutional-style image comparison plans."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    InstitutionalStyleAnswerKeyEntry,
    InstitutionalStyleBlindPresentationMember,
    InstitutionalStyleCaseResult,
    InstitutionalStyleReviewPacketCase,
    LocalImageInstitutionalStyleAnswerKey,
    LocalImageInstitutionalStyleEvaluationPlan,
    LocalImageInstitutionalStyleEvaluationResult,
    LocalImageInstitutionalStyleReviewPacket,
    content_sha256,
    validate_contract,
    validate_institutional_style_result,
    validate_institutional_style_review_packet,
)

from eom_image_trainer.institutional_style_metrics import (
    InstitutionalStyleMetricsError,
    institutional_style_presentation_metrics,
    normalize_institutional_style_presentation,
)

MemberResolver = Callable[[ImageEvaluationArtifactMember], bytes]


class InstitutionalStyleEvaluationError(ValueError):
    """Stable failure raised before an evaluation result can be accepted."""


@dataclass(frozen=True)
class InstitutionalStyleReviewPacketBuild:
    packet: LocalImageInstitutionalStyleReviewPacket
    answer_key: LocalImageInstitutionalStyleAnswerKey
    members: tuple[tuple[str, bytes], ...]


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
            institutional = institutional_style_presentation_metrics(
                _resolve_exact(case.institutional_image, resolve_member=resolve_member)
            )
            generated = institutional_style_presentation_metrics(
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


def build_institutional_style_review_packet(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    *,
    resolve_member: MemberResolver,
) -> InstitutionalStyleReviewPacketBuild:
    """Build deterministic blind bytes without exposing source origins in the review packet."""

    packet_cases: list[InstitutionalStyleReviewPacketCase] = []
    answers: list[InstitutionalStyleAnswerKeyEntry] = []
    members: dict[str, bytes] = {}
    try:
        for case in plan.cases:
            institutional = normalize_institutional_style_presentation(
                _resolve_exact(case.institutional_image, resolve_member=resolve_member)
            )
            generated = normalize_institutional_style_presentation(
                _resolve_exact(case.generated_image, resolve_member=resolve_member)
            )
            left, right = (
                (generated, institutional)
                if case.left_origin == "GENERATED"
                else (institutional, generated)
            )
            left_member = _blind_member(left, members=members)
            right_member = _blind_member(right, members=members)
            packet_cases.append(
                InstitutionalStyleReviewPacketCase(
                    case_id=case.case_id,
                    subject_family=case.subject_family,
                    depiction_key=case.depiction_key,
                    presentation_token=case.presentation_token,
                    left_image=left_member,
                    right_image=right_member,
                )
            )
            answers.append(
                InstitutionalStyleAnswerKeyEntry(
                    case_id=case.case_id,
                    presentation_token=case.presentation_token,
                    left_origin=case.left_origin,
                )
            )
    except InstitutionalStyleMetricsError as exc:
        raise InstitutionalStyleEvaluationError("INSTITUTIONAL_STYLE_IMAGE_INVALID") from exc

    packet_body = {
        "schema_version": "local-image-institutional-style-review-packet/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "presentation_policy": plan.presentation_policy,
        "cases": [case.model_dump(mode="json") for case in packet_cases],
    }
    packet = LocalImageInstitutionalStyleReviewPacket.model_validate(
        {**packet_body, "packet_sha256": content_sha256(packet_body)}
    )
    answer_body = {
        "schema_version": "local-image-institutional-style-answer-key/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "entries": [entry.model_dump(mode="json") for entry in answers],
    }
    answer_key = LocalImageInstitutionalStyleAnswerKey.model_validate(
        {**answer_body, "answer_key_sha256": content_sha256(answer_body)}
    )
    validate_contract("institutional-style-review-packet", packet.model_dump(mode="json"))
    validate_contract("institutional-style-answer-key", answer_key.model_dump(mode="json"))
    validate_institutional_style_review_packet(plan, packet, answer_key)
    return InstitutionalStyleReviewPacketBuild(
        packet=packet,
        answer_key=answer_key,
        members=tuple(sorted(members.items())),
    )


def _blind_member(
    payload: bytes,
    *,
    members: dict[str, bytes],
) -> InstitutionalStyleBlindPresentationMember:
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    member_path = f"presentation/{digest.removeprefix('sha256:')}.png"
    existing = members.setdefault(member_path, payload)
    if existing != payload:
        raise InstitutionalStyleEvaluationError("INSTITUTIONAL_STYLE_MEMBER_HASH_COLLISION")
    return InstitutionalStyleBlindPresentationMember(
        member_path=member_path,
        size_bytes=len(payload),
        sha256=digest,
    )

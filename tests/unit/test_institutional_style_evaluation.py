from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime

import pytest
from eom_image_contracts import (
    GENERATED_RASTER_SCHEMA_REF,
    INSTITUTIONAL_CROP_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    InstitutionalStyleCaseResult,
    InstitutionalStyleCaseReview,
    InstitutionalStyleEvaluationCase,
    InstitutionalStyleImageMetrics,
    InstitutionalStyleSideReview,
    LocalImageInstitutionalStyleEvaluationPlan,
    LocalImageInstitutionalStyleEvaluationResult,
    LocalImageInstitutionalStyleEvaluationReview,
    content_sha256,
    validate_contract,
    validate_institutional_style_result,
    validate_institutional_style_review,
)
from eom_image_trainer.institutional_style_evaluator import (
    InstitutionalStyleEvaluationError,
    evaluate_institutional_style,
)
from eom_image_trainer.institutional_style_metrics import institutional_style_metrics
from PIL import Image, ImageDraw


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _member(index: int, *, institutional: bool) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=f"artifact_{index + (0 if institutional else 100):032x}",
        artifact_revision_id=f"rev_{index + (200 if institutional else 300):032x}",
        member_path=f"crops/{index:02d}.png" if institutional else "generated-raster.png",
        schema_ref=(
            INSTITUTIONAL_CROP_SCHEMA_REF if institutional else GENERATED_RASTER_SCHEMA_REF
        ),
        media_type="image/png",
        sha256=_sha(f"{'source' if institutional else 'generated'}-{index}"),
    )


def _case(index: int) -> InstitutionalStyleEvaluationCase:
    families = (
        "EARTH_SPACE",
        "LAB_APPARATUS",
        "LIVING_ORGANISM",
        "NATURAL_OBJECT",
        "PHYSICAL_OBJECT",
        "REAL_WORLD_SCENE",
    )
    body = {
        "subject_family": families[index % len(families)],
        "institutional_image": _member(index, institutional=True).model_dump(mode="json"),
        "generated_image": _member(index, institutional=False).model_dump(mode="json"),
        "generated_request_sha256": _sha(f"request-{index}"),
        "generated_receipt_sha256": _sha(f"receipt-{index}"),
    }
    identity = content_sha256(body).removeprefix("sha256:")[:32]
    case_id = f"imgstylecase_{identity}"
    left_origin = "GENERATED" if index % 2 else "INSTITUTIONAL"
    token = content_sha256({"case_id": case_id, "left_origin": left_origin}).removeprefix(
        "sha256:"
    )[:32]
    return InstitutionalStyleEvaluationCase.model_validate(
        {
            **body,
            "case_id": case_id,
            "left_origin": left_origin,
            "presentation_token": f"blind_{token}",
        }
    )


def _plan() -> LocalImageInstitutionalStyleEvaluationPlan:
    cases = tuple(sorted((_case(index) for index in range(12)), key=lambda value: value.case_id))
    identity_body = {
        "selection_method": "STRATIFIED_ORIGIN_BLIND_V1",
        "provider_binding_sha256": _sha("binding"),
        "maximum_generated_origin_identification_rate": 0.6,
        "minimum_mean_institutional_style_score": 4.0,
        "cases": [case.model_dump(mode="json") for case in cases],
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")[:32]
    body = {
        "schema_version": "local-image-institutional-style-evaluation-plan/1.0",
        "evaluation_id": f"imgstyleeval_{identity}",
        "created_at": "2026-10-02T18:00:00Z",
        **identity_body,
    }
    return LocalImageInstitutionalStyleEvaluationPlan.model_validate(
        {**body, "plan_sha256": content_sha256(body)}
    )


def _metrics(value: int) -> InstitutionalStyleImageMetrics:
    return InstitutionalStyleImageMetrics(
        foreground_fraction_milli=value,
        dark_fraction_milli=value,
        mid_tone_fraction_milli=value,
        edge_fraction_milli=value,
        border_foreground_fraction_milli=value,
        fine_detail_fraction_milli=value,
        tiny_component_fraction_milli=value,
        component_count=value,
    )


def _result(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
) -> LocalImageInstitutionalStyleEvaluationResult:
    case_results = tuple(
        InstitutionalStyleCaseResult(
            case_id=case.case_id,
            institutional_metrics=_metrics(20),
            generated_metrics=_metrics(21),
            metric_distance_milli=7,
        )
        for case in plan.cases
    )
    body = {
        "schema_version": "local-image-institutional-style-evaluation-result/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "status": "SUCCEEDED",
        "case_results": [value.model_dump(mode="json") for value in case_results],
        "completed_at": "2026-10-02T18:10:00Z",
    }
    return LocalImageInstitutionalStyleEvaluationResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )


def test_institutional_style_contracts_are_schema_and_model_valid() -> None:
    plan = _plan()
    result = _result(plan)
    validate_contract("institutional-style-evaluation-plan", plan.model_dump(mode="json"))
    validate_contract("institutional-style-evaluation-result", result.model_dump(mode="json"))
    validate_institutional_style_result(plan, result)

    clean = InstitutionalStyleSideReview(
        institutional_style_score=4,
        semantic_suitability_score=4,
        composition_score=4,
        usability="USABLE_AFTER_DETERMINISTIC_OVERLAY",
        defects=(),
    )
    reviews = tuple(
        InstitutionalStyleCaseReview(
            case_id=case.case_id,
            guessed_generated_side="UNSURE",
            confidence=1,
            left=clean,
            right=clean,
        )
        for case in plan.cases
    )
    body = {
        "schema_version": "local-image-institutional-style-evaluation-review/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "result_sha256": result.result_sha256,
        "reviewer_id": "operator_test",
        "reviews": [review.model_dump(mode="json") for review in reviews],
        "generated_origin_identification_rate": 0.0,
        "generated_mean_institutional_style_score": 4.0,
        "critical_generated_defect_count": 0,
        "verdict": "CANDIDATE_CANARY_ELIGIBLE",
        "reviewed_at": datetime(2026, 10, 2, 18, 20, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }
    review = LocalImageInstitutionalStyleEvaluationReview.model_validate(
        {**body, "review_sha256": content_sha256(body)}
    )
    validate_contract("institutional-style-evaluation-review", review.model_dump(mode="json"))
    validate_institutional_style_review(plan, result, review)


def test_institutional_style_plan_rejects_duplicate_source() -> None:
    plan = _plan().model_dump(mode="json", exclude={"plan_sha256"})
    plan["cases"][1]["institutional_image"] = plan["cases"][0]["institutional_image"]
    plan["plan_sha256"] = content_sha256(plan)
    with pytest.raises(ValueError, match=r"case ID mismatch|repeats an image"):
        LocalImageInstitutionalStyleEvaluationPlan.model_validate(plan)


def test_institutional_style_plan_rejects_unstratified_population() -> None:
    plan = _plan().model_dump(mode="json", exclude={"plan_sha256"})
    for case in plan["cases"]:
        case["subject_family"] = "PHYSICAL_OBJECT"
        body = {
            key: case[key]
            for key in (
                "subject_family",
                "institutional_image",
                "generated_image",
                "generated_request_sha256",
                "generated_receipt_sha256",
            )
        }
        case["case_id"] = "imgstylecase_" + content_sha256(body).removeprefix("sha256:")[:32]
        case["presentation_token"] = (
            "blind_"
            + content_sha256(
                {"case_id": case["case_id"], "left_origin": case["left_origin"]}
            ).removeprefix("sha256:")[:32]
        )
    plan["cases"] = sorted(plan["cases"], key=lambda value: value["case_id"])
    plan["plan_sha256"] = content_sha256(plan)

    with pytest.raises(ValueError, match="at least four subject families"):
        LocalImageInstitutionalStyleEvaluationPlan.model_validate(plan)


def _png(*, speckles: bool) -> bytes:
    image = Image.new("L", (96, 64), 255)
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((20, 12, 76, 52), outline=48, width=3)
    if speckles:
        for x in range(4, 92, 8):
            for y in range(4, 60, 8):
                drawing.point((x, y), fill=48)
    target = io.BytesIO()
    image.save(target, format="PNG")
    return target.getvalue()


def test_institutional_style_metrics_detect_tiny_detail() -> None:
    clean = institutional_style_metrics(_png(speckles=False))
    noisy = institutional_style_metrics(_png(speckles=True))
    assert noisy.component_count > clean.component_count
    assert noisy.tiny_component_fraction_milli > clean.tiny_component_fraction_milli
    assert noisy.fine_detail_fraction_milli > clean.fine_detail_fraction_milli


def _evaluation_payload(index: int, *, generated: bool) -> bytes:
    image = Image.new("L", (96, 64), 255)
    drawing = ImageDraw.Draw(image)
    offset = index
    tone = 64 if generated else 48
    drawing.ellipse((18 + offset, 10, 74 + offset, 52), outline=tone, width=3)
    drawing.line((24, 40 - offset, 70, 18 + offset), fill=tone, width=2)
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9)
    return target.getvalue()


def _material_plan() -> tuple[
    LocalImageInstitutionalStyleEvaluationPlan,
    dict[tuple[str, str, str], bytes],
]:
    cases: list[InstitutionalStyleEvaluationCase] = []
    members: dict[tuple[str, str, str], bytes] = {}
    families = (
        "EARTH_SPACE",
        "LAB_APPARATUS",
        "LIVING_ORGANISM",
        "NATURAL_OBJECT",
        "PHYSICAL_OBJECT",
        "REAL_WORLD_SCENE",
    )
    for index in range(12):
        institutional_payload = _evaluation_payload(index, generated=False)
        generated_payload = _evaluation_payload(index, generated=True)
        institutional = _member(index, institutional=True).model_copy(
            update={"sha256": "sha256:" + hashlib.sha256(institutional_payload).hexdigest()}
        )
        generated = _member(index, institutional=False).model_copy(
            update={"sha256": "sha256:" + hashlib.sha256(generated_payload).hexdigest()}
        )
        members[
            (
                institutional.artifact_id,
                institutional.artifact_revision_id,
                institutional.member_path,
            )
        ] = institutional_payload
        members[(generated.artifact_id, generated.artifact_revision_id, generated.member_path)] = (
            generated_payload
        )
        body = {
            "subject_family": families[index % len(families)],
            "institutional_image": institutional.model_dump(mode="json"),
            "generated_image": generated.model_dump(mode="json"),
            "generated_request_sha256": _sha(f"material-request-{index}"),
            "generated_receipt_sha256": _sha(f"material-receipt-{index}"),
        }
        case_id = "imgstylecase_" + content_sha256(body).removeprefix("sha256:")[:32]
        left_origin = "GENERATED" if index % 2 else "INSTITUTIONAL"
        token = content_sha256({"case_id": case_id, "left_origin": left_origin}).removeprefix(
            "sha256:"
        )[:32]
        cases.append(
            InstitutionalStyleEvaluationCase.model_validate(
                {
                    **body,
                    "case_id": case_id,
                    "left_origin": left_origin,
                    "presentation_token": "blind_" + token,
                }
            )
        )
    cases.sort(key=lambda value: value.case_id)
    identity_body = {
        "selection_method": "STRATIFIED_ORIGIN_BLIND_V1",
        "provider_binding_sha256": _sha("material-binding"),
        "maximum_generated_origin_identification_rate": 0.6,
        "minimum_mean_institutional_style_score": 4.0,
        "cases": [case.model_dump(mode="json") for case in cases],
    }
    evaluation_id = "imgstyleeval_" + content_sha256(identity_body).removeprefix("sha256:")[:32]
    plan_body = {
        "schema_version": "local-image-institutional-style-evaluation-plan/1.0",
        "evaluation_id": evaluation_id,
        "created_at": "2026-10-02T18:00:00Z",
        **identity_body,
    }
    return (
        LocalImageInstitutionalStyleEvaluationPlan.model_validate(
            {**plan_body, "plan_sha256": content_sha256(plan_body)}
        ),
        members,
    )


def test_institutional_style_evaluator_resolves_each_exact_member() -> None:
    plan, members = _material_plan()
    calls: list[tuple[str, str, str]] = []

    def resolve(member: ImageEvaluationArtifactMember) -> bytes:
        key = (member.artifact_id, member.artifact_revision_id, member.member_path)
        calls.append(key)
        return members[key]

    result = evaluate_institutional_style(
        plan,
        resolve_member=resolve,
        completed_at=datetime(2026, 10, 2, 18, 30, tzinfo=UTC),
    )

    validate_contract("institutional-style-evaluation-result", result.model_dump(mode="json"))
    assert len(result.case_results) == 12
    assert len(calls) == 24
    assert len(set(calls)) == 24


def test_institutional_style_evaluator_rejects_member_hash_drift() -> None:
    plan, members = _material_plan()
    first = plan.cases[0].institutional_image
    members[(first.artifact_id, first.artifact_revision_id, first.member_path)] += b"drift"

    with pytest.raises(
        InstitutionalStyleEvaluationError,
        match="INSTITUTIONAL_STYLE_MEMBER_HASH_MISMATCH",
    ):
        evaluate_institutional_style(
            plan,
            resolve_member=lambda member: members[
                (member.artifact_id, member.artifact_revision_id, member.member_path)
            ],
            completed_at=datetime(2026, 10, 2, 18, 30, tzinfo=UTC),
        )

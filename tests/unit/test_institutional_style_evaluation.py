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
    LocalImageInstitutionalStyleReviewPacket,
    content_sha256,
    validate_contract,
    validate_institutional_style_result,
    validate_institutional_style_review,
    validate_institutional_style_review_packet,
)
from eom_image_trainer.institutional_style_evaluator import (
    InstitutionalStyleEvaluationError,
    build_institutional_style_review_packet,
    evaluate_institutional_style,
)
from eom_image_trainer.institutional_style_metrics import (
    institutional_style_metrics,
    institutional_style_presentation_metrics,
    normalize_institutional_style_presentation,
)
from jsonschema import ValidationError as JsonSchemaValidationError
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
        "depiction_key": f"SUBJECT_{index:02d}",
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
        "selection_method": "SUBJECT_MATCHED_SINGLE_TRACK_ORIGIN_BLIND_V1",
        "style_track": "OBJECT_LINE_ART",
        "presentation_policy": "FOREGROUND_BBOX_FIT_800X500_V1",
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


def test_institutional_style_plan_rejects_repeated_depiction_key() -> None:
    plan = _plan().model_dump(mode="json", exclude={"plan_sha256"})
    changed = plan["cases"][1]
    changed["depiction_key"] = plan["cases"][0]["depiction_key"]
    identity_body = {
        key: changed[key]
        for key in (
            "subject_family",
            "depiction_key",
            "institutional_image",
            "generated_image",
            "generated_request_sha256",
            "generated_receipt_sha256",
        )
    }
    changed["case_id"] = (
        "imgstylecase_" + content_sha256(identity_body).removeprefix("sha256:")[:32]
    )
    changed["presentation_token"] = (
        "blind_"
        + content_sha256(
            {"case_id": changed["case_id"], "left_origin": changed["left_origin"]}
        ).removeprefix("sha256:")[:32]
    )
    plan["cases"] = sorted(plan["cases"], key=lambda value: value["case_id"])
    plan["plan_sha256"] = content_sha256(plan)

    with pytest.raises(ValueError, match="repeats a depiction key"):
        LocalImageInstitutionalStyleEvaluationPlan.model_validate(plan)


def test_institutional_style_plan_rejects_unstratified_population() -> None:
    plan = _plan().model_dump(mode="json", exclude={"plan_sha256"})
    for case in plan["cases"]:
        case["subject_family"] = "PHYSICAL_OBJECT"
        body = {
            key: case[key]
            for key in (
                "subject_family",
                "depiction_key",
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


def test_institutional_style_presentation_normalizes_crop_whitespace() -> None:
    subject = Image.new("L", (96, 64), 255)
    drawing = ImageDraw.Draw(subject)
    drawing.ellipse((20, 12, 76, 52), outline=48, width=3)
    tight = io.BytesIO()
    subject.save(tight, format="PNG")

    padded = Image.new("L", (320, 240), 255)
    padded.paste(subject, (111, 83))
    padded_payload = io.BytesIO()
    padded.save(padded_payload, format="PNG")

    tight_normalized = normalize_institutional_style_presentation(tight.getvalue())
    padded_normalized = normalize_institutional_style_presentation(padded_payload.getvalue())
    assert tight_normalized == padded_normalized
    tight_metrics = institutional_style_presentation_metrics(tight.getvalue())
    assert tight_metrics == institutional_style_presentation_metrics(padded_payload.getvalue())
    assert tight_metrics.foreground_fraction_milli > 100


def _review_with_generated_side(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    result: LocalImageInstitutionalStyleEvaluationResult,
    *,
    generated_override: InstitutionalStyleSideReview,
    claimed_critical_count: int,
    claimed_verdict: str,
) -> LocalImageInstitutionalStyleEvaluationReview:
    clean = InstitutionalStyleSideReview(
        institutional_style_score=4,
        semantic_suitability_score=4,
        composition_score=4,
        usability="USABLE_AS_IS",
        defects=(),
    )
    reviews: list[InstitutionalStyleCaseReview] = []
    for index, case in enumerate(plan.cases):
        generated = generated_override if index == 0 else clean
        reviews.append(
            InstitutionalStyleCaseReview(
                case_id=case.case_id,
                guessed_generated_side="UNSURE",
                confidence=1,
                left=generated if case.left_origin == "GENERATED" else clean,
                right=generated if case.left_origin == "INSTITUTIONAL" else clean,
            )
        )
    body = {
        "schema_version": "local-image-institutional-style-evaluation-review/1.0",
        "evaluation_id": plan.evaluation_id,
        "plan_sha256": plan.plan_sha256,
        "result_sha256": result.result_sha256,
        "reviewer_id": "operator_negative_test",
        "reviews": [review.model_dump(mode="json") for review in reviews],
        "generated_origin_identification_rate": 0.0,
        "generated_mean_institutional_style_score": 4.0,
        "critical_generated_defect_count": claimed_critical_count,
        "verdict": claimed_verdict,
        "reviewed_at": "2026-10-02T18:20:00Z",
    }
    return LocalImageInstitutionalStyleEvaluationReview.model_validate(
        {**body, "review_sha256": content_sha256(body)}
    )


def test_institutional_style_review_treats_pseudotext_as_critical() -> None:
    plan = _plan()
    result = _result(plan)
    pseudotext = InstitutionalStyleSideReview(
        institutional_style_score=4,
        semantic_suitability_score=4,
        composition_score=4,
        usability="REJECT",
        defects=("PSEUDOTEXT",),
    )
    review = _review_with_generated_side(
        plan,
        result,
        generated_override=pseudotext,
        claimed_critical_count=0,
        claimed_verdict="CANDIDATE_CANARY_ELIGIBLE",
    )

    with pytest.raises(ValueError, match="review aggregates mismatch"):
        validate_institutional_style_review(plan, result, review)


def test_institutional_style_review_rejects_rejected_generated_side() -> None:
    plan = _plan()
    result = _result(plan)
    rejected = InstitutionalStyleSideReview(
        institutional_style_score=4,
        semantic_suitability_score=4,
        composition_score=4,
        usability="REJECT",
        defects=(),
    )
    review = _review_with_generated_side(
        plan,
        result,
        generated_override=rejected,
        claimed_critical_count=0,
        claimed_verdict="CANDIDATE_CANARY_ELIGIBLE",
    )

    with pytest.raises(ValueError, match="verdict mismatch"):
        validate_institutional_style_review(plan, result, review)


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
            "depiction_key": f"MATERIAL_{index:02d}",
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
        "selection_method": "SUBJECT_MATCHED_SINGLE_TRACK_ORIGIN_BLIND_V1",
        "style_track": "OBJECT_LINE_ART",
        "presentation_policy": "FOREGROUND_BBOX_FIT_800X500_V1",
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


def test_blind_review_packet_separates_origin_key_and_normalizes_members() -> None:
    plan, members = _material_plan()
    calls: list[tuple[str, str, str]] = []

    def resolve(member: ImageEvaluationArtifactMember) -> bytes:
        key = (member.artifact_id, member.artifact_revision_id, member.member_path)
        calls.append(key)
        return members[key]

    built = build_institutional_style_review_packet(plan, resolve_member=resolve)

    validate_contract("institutional-style-review-packet", built.packet.model_dump(mode="json"))
    validate_contract("institutional-style-answer-key", built.answer_key.model_dump(mode="json"))
    validate_institutional_style_review_packet(plan, built.packet, built.answer_key)
    assert len(calls) == 24
    assert len(set(calls)) == 24
    packet_value = built.packet.model_dump(mode="json")
    assert "left_origin" not in repr(packet_value)
    assert set(path for path, _payload in built.members) == {
        case.left_image.member_path for case in built.packet.cases
    } | {case.right_image.member_path for case in built.packet.cases}
    assert all(
        member.member_path == f"presentation/{member.sha256.removeprefix('sha256:')}.png"
        for case in built.packet.cases
        for member in (case.left_image, case.right_image)
    )

    first_plan = plan.cases[0]
    first_packet = built.packet.cases[0]
    first_source = (
        first_plan.generated_image
        if first_plan.left_origin == "GENERATED"
        else first_plan.institutional_image
    )
    expected_left = normalize_institutional_style_presentation(
        members[
            (
                first_source.artifact_id,
                first_source.artifact_revision_id,
                first_source.member_path,
            )
        ]
    )
    output_by_path = dict(built.members)
    assert output_by_path[first_packet.left_image.member_path] == expected_left


def test_blind_review_packet_rejects_answer_key_drift() -> None:
    plan, members = _material_plan()
    built = build_institutional_style_review_packet(
        plan,
        resolve_member=lambda member: members[
            (member.artifact_id, member.artifact_revision_id, member.member_path)
        ],
    )
    value = built.answer_key.model_dump(mode="json", exclude={"answer_key_sha256"})
    value["entries"][0]["left_origin"] = (
        "INSTITUTIONAL" if value["entries"][0]["left_origin"] == "GENERATED" else "GENERATED"
    )
    changed = built.answer_key.model_validate({**value, "answer_key_sha256": content_sha256(value)})

    with pytest.raises(ValueError, match="review packet case mismatch"):
        validate_institutional_style_review_packet(plan, built.packet, changed)


def test_blind_review_packet_schema_rejects_origin_leak() -> None:
    plan, members = _material_plan()
    built = build_institutional_style_review_packet(
        plan,
        resolve_member=lambda member: members[
            (member.artifact_id, member.artifact_revision_id, member.member_path)
        ],
    )
    leaked = built.packet.model_dump(mode="json")
    leaked["cases"][0]["left_origin"] = "GENERATED"

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("institutional-style-review-packet", leaked)


def test_blind_review_packet_rejects_packet_hash_drift() -> None:
    plan, members = _material_plan()
    built = build_institutional_style_review_packet(
        plan,
        resolve_member=lambda member: members[
            (member.artifact_id, member.artifact_revision_id, member.member_path)
        ],
    )
    value = built.packet.model_dump(mode="json")
    value["packet_sha256"] = _sha("wrong-packet")

    with pytest.raises(ValueError, match="packet hash mismatch"):
        LocalImageInstitutionalStyleReviewPacket.model_validate(value)

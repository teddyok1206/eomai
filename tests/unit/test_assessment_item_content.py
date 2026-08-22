from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_catalog_contracts import AssessmentItemContent, validate_contract
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.question_template import project_question_template
from eom_hwpx_manager.question_template_service import QuestionTemplateSnapshot
from jsonschema import Draft202012Validator
from pydantic import ValidationError


def item_content() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "locale": "ko-KR",
        "title": "삼각함수 문항",
        "body": [
            {
                "block_id": "block_stem",
                "type": "paragraph",
                "purpose": "stem",
                "text": "다음 자료를 보고 물음에 답하시오.",
            },
            {
                "block_id": "block_data",
                "type": "table",
                "purpose": "data",
                "caption": None,
                "headers": ["각", "사인", "코사인"],
                "rows": [["30", "1/2", "sqrt(3)/2"]],
            },
            {
                "block_id": "block_image",
                "type": "image",
                "purpose": "stimulus",
                "artifact": {
                    "artifact_id": "artifact_" + "1" * 32,
                    "artifact_revision_id": "rev_" + "2" * 32,
                    "artifact_member": "diagram.png",
                    "sha256": "sha256:" + "3" * 64,
                    "media_type": "image/png",
                },
                "alt_text": "삼각형 도식",
                "width_px": 800,
                "height_px": 500,
            },
            {
                "block_id": "block_equation",
                "type": "equation",
                "purpose": "stimulus",
                "notation": "hancom-equation-script",
                "source": "a^2+b^2=c^2",
            },
            {
                "block_id": "block_prompt",
                "type": "paragraph",
                "purpose": "prompt",
                "text": "옳은 것만을 고른 것은?",
            },
            {
                "block_id": "block_claims",
                "type": "statement_set",
                "purpose": "claims",
                "statements": [
                    {"statement_id": "statement_g", "label": "ㄱ", "text": "ㄱ 설명"},
                    {"statement_id": "statement_n", "label": "ㄴ", "text": "ㄴ 설명"},
                    {"statement_id": "statement_d", "label": "ㄷ", "text": "ㄷ 설명"},
                ],
            },
        ],
        "interaction": {
            "type": "single_choice",
            "choices": [
                {"choice_id": f"choice_{index}", "label": str(index), "text": f"선택지 {index}"}
                for index in range(1, 6)
            ],
        },
        "solution": {
            "correct_choice_ids": ["choice_3"],
            "accepted_answers": [],
            "explanation": "정답 해설",
            "authoring_intent": "삼각함수의 기본 관계를 평가한다.",
            "statement_explanations": [
                {"statement_id": "statement_g", "text": "ㄱ 해설"},
                {"statement_id": "statement_n", "text": "ㄴ 해설"},
                {"statement_id": "statement_d", "text": "ㄷ 해설"},
            ],
        },
        "score": {"points": 3},
    }


def test_assessment_item_schema_and_typed_model_agree() -> None:
    value = item_content()
    schema = json.loads(
        Path("schemas/item-registry/assessment-item-content-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(value))
    validate_contract("assessment-item-content", value)
    parsed = AssessmentItemContent.model_validate(value)
    assert parsed.body[0].block_id == "block_stem"


def test_assessment_item_rejects_duplicate_or_dangling_references() -> None:
    duplicate = item_content()
    body = duplicate["body"]
    assert isinstance(body, list)
    assert isinstance(body[1], dict)
    body[1]["block_id"] = "block_stem"
    with pytest.raises(ValidationError, match="block IDs must be unique"):
        AssessmentItemContent.model_validate(duplicate)

    dangling = item_content()
    solution = dangling["solution"]
    assert isinstance(solution, dict)
    solution["correct_choice_ids"] = ["choice_missing"]
    with pytest.raises(ValidationError, match="correct choice pointer does not resolve"):
        AssessmentItemContent.model_validate(dangling)


@pytest.mark.parametrize(
    "member",
    (
        "/diagram.png",
        ".",
        "source/./diagram.png",
        "../diagram.png",
        "source/../diagram.png",
        "source\\diagram.png",
        "a//b",
    ),
)
def test_assessment_item_rejects_unsafe_media_member(member: str) -> None:
    value = item_content()
    body = value["body"]
    assert isinstance(body, list) and isinstance(body[2], dict)
    artifact = body[2]["artifact"]
    assert isinstance(artifact, dict)
    artifact["artifact_member"] = member

    schema = json.loads(
        Path("schemas/item-registry/assessment-item-content-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(value))
    with pytest.raises(ValidationError, match="artifact member"):
        AssessmentItemContent.model_validate(value)


def test_question_template_projection_is_explicit_and_deterministic() -> None:
    content = AssessmentItemContent.model_validate(item_content())
    projection = project_question_template(
        content, item_revision_id="itemrev_" + "4" * 32, item_number=7
    )
    assert projection.document.item.item_number == "7"
    assert projection.document.item.table.rows == (
        ("각", "사인", "코사인"),
        ("30", "1/2", "sqrt(3)/2"),
    )
    assert projection.document.item.choices == tuple(f"선택지 {index}" for index in range(1, 6))
    assert projection.document.solution.answer == "3"
    assert projection.image.artifact.artifact_revision_id == "rev_" + "2" * 32


def test_question_template_rejects_incompatible_content_without_fallback() -> None:
    value = item_content()
    interaction = value["interaction"]
    assert isinstance(interaction, dict)
    choices = interaction["choices"]
    assert isinstance(choices, list)
    choices.pop()
    content = AssessmentItemContent.model_validate(value)
    with pytest.raises(HwpxManagerError) as raised:
        project_question_template(content, item_revision_id="itemrev_" + "4" * 32)
    assert raised.value.code is HwpxManagerErrorCode.HWPX_TEMPLATE_CONTENT_INCOMPATIBLE


def test_question_template_release_snapshot_round_trips_application_options() -> None:
    snapshot = QuestionTemplateSnapshot(
        profile="eom-question-template-v1",
        template_id="hwpxtpl_" + "1" * 32,
        template_revision_id="hwpxrev_" + "2" * 32,
        template_artifact_id="artifact_" + "3" * 32,
        template_artifact_revision_id="rev_" + "4" * 32,
        template_source_sha256="sha256:" + "5" * 64,
        binding_manifest_sha256="sha256:" + "6" * 64,
    )
    assert QuestionTemplateSnapshot.from_request_options(snapshot.request_identity()) == snapshot

    incomplete = snapshot.request_identity()
    del incomplete["template_artifact_revision_id"]
    with pytest.raises(HwpxManagerError) as raised:
        QuestionTemplateSnapshot.from_request_options(incomplete)
    assert raised.value.code is HwpxManagerErrorCode.HWPX_REFERENCE_MISSING

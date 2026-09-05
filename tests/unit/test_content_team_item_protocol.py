from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts import (
    AssessmentItemContentV2,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    ReviewedItemContentImportCommand,
    resolve_integrated_science_curriculum_scope,
    validate_contract,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_hwpx_contracts import (
    ContentTeamImageSlot,
    ContentTeamInquiry,
    ContentTeamTable,
    derive_content_team_equation_sources,
    normalize_content_team_bottom_stem,
    normalize_content_team_stem,
)
from eom_hwpx_contracts.content_team_markdown import (
    parse_content_team_markdown,
    serialize_content_team_markdown,
)
from eom_workflow.compiler import compile_definition
from eom_workflow.models import (
    ArtifactSpec,
    ContentTeamAuthoringRoleResultV7,
    ContentTeamItemBrief,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    load_codex_result_schema,
    load_knowledge_item_brief_v3_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_result,
    validate_schema_message,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

ROOT = Path(__file__).resolve().parents[2]
ROLES = {"authoring", "image", "review", "item_management"}


def _content(
    *,
    visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...] = (),
    visual_layout: str = "NONE",
    equations: tuple[str, ...] = (),
    inquiry: ContentTeamInquiry | None = None,
    stem: str = "제시된 정보를 해석하여 물음에 답하시오.",
) -> AssessmentItemContentV2:
    return AssessmentItemContentV2.model_validate(
        {
            "item_number": 11,
            "score_display": "2.5",
            "stem": stem,
            "bottom_stem": "옳은 것만을 <보기>에서 있는 대로 고른 것은?",
            "inquiry": inquiry.model_dump(mode="json") if inquiry is not None else None,
            "labeled_blocks": [],
            "visuals": [value.model_dump(mode="json") for value in visuals],
            "visual_layout": visual_layout,
            "statements": [
                {"label": "ㄱ", "text": "첫째 진술은 자료와 일치한다."},
                {"label": "ㄴ", "text": "둘째 진술은 자료와 일치하지 않는다."},
                {"label": "ㄷ", "text": "셋째 진술은 자료와 일치한다."},
            ],
            "choices": [
                {"number": "①", "text": "ㄱ"},
                {"number": "②", "text": "ㄴ"},
                {"number": "③", "text": "ㄱ, ㄷ"},
                {"number": "④", "text": "ㄴ, ㄷ"},
                {"number": "⑤", "text": "ㄱ, ㄴ, ㄷ"},
            ],
            "answer": {
                "answer_kind": "STATEMENT_COMBINATION",
                "number": "③",
                "statement_labels": ["ㄱ", "ㄷ"],
                "answer_content": "ㄱ, ㄷ",
                "raw_line": "정답 : ③ (ㄱ, ㄷ)",
            },
            "explanations": {
                "authoring_intent": "제시된 정보의 관계를 해석한다.",
                "concept_source": "요청에 고정된 교육과정 근거를 사용한다.",
                "correct_answer": ("ㄱ. 제시된 정보와 일치한다.\nㄷ. 제시된 정보와 일치한다."),
                "wrong_answer": "ㄴ. 제시된 정보와 일치하지 않는다.",
            },
            "equation_sources": list(equations),
        }
    )


@pytest.mark.parametrize(
    ("visuals", "layout", "equations"),
    [
        ((), "NONE", ()),
        ((ContentTeamImageSlot(),), "IMAGE_ONLY", ()),
        (
            (
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "$x$"), ("B", "$x^{2}$")),
                    alignments=("default", "right"),
                ),
            ),
            "TABLE_ONLY",
            ("x", "x^{2}"),
        ),
        (
            (
                ContentTeamImageSlot(),
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
            ),
            "IMAGE_TABLE",
            (),
        ),
        (
            (
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
                ContentTeamImageSlot(),
            ),
            "TABLE_IMAGE",
            (),
        ),
        (
            (
                ContentTeamImageSlot(label="(가)"),
                ContentTeamImageSlot(label="(나)"),
            ),
            "IMAGE_IMAGE",
            (),
        ),
        (
            (
                ContentTeamTable(
                    label="(가)",
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
                ContentTeamTable(
                    label="(나)",
                    headers=("구분", "값"),
                    rows=(("B", "2"),),
                    alignments=("default", "right"),
                ),
            ),
            "TABLE_TABLE",
            (),
        ),
    ],
)
def test_content_v2_preserves_program_shapes_without_fixed_asset_counts(
    visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...],
    layout: str,
    equations: tuple[str, ...],
) -> None:
    content = _content(visuals=visuals, visual_layout=layout, equations=equations)
    value = content.model_dump(mode="json")

    validate_contract("assessment-item-content-v2", value)
    assert value["score_display"] == "2.5"
    assert len(value["visuals"]) == len(visuals)
    assert value["equation_sources"] == list(equations)
    materialized = serialize_content_team_markdown(content)
    assert parse_content_team_markdown(materialized).visual_layout == layout


@pytest.mark.parametrize("column_count", [2, 3, 4, 5])
def test_content_team_table_width_follows_program_contract(column_count: int) -> None:
    headers = tuple(f"열 {index}" for index in range(1, column_count + 1))
    table = ContentTeamTable(
        headers=headers,
        rows=(tuple(str(index) for index in range(1, column_count + 1)),),
        alignments=tuple("default" for _ in range(column_count)),
    )
    content = _content(visuals=(table,), visual_layout="TABLE_ONLY")

    assert len(content.visuals[0].headers) == column_count
    assert (
        parse_content_team_markdown(serialize_content_team_markdown(content)).visual_layout
        == "TABLE_ONLY"
    )


def test_content_team_inquiry_box_round_trips_without_general_visuals() -> None:
    inquiry = ContentTeamInquiry(
        kind="탐구",
        goal=None,
        procedure="(가) 첫 과정을 수행한다.\n(나) 다음 과정을 수행한다.\n(다) 결과를 관찰한다.",
        result="관찰 결과를 정리한다.",
    )
    content = _content(visual_layout="INQUIRY_BOX", inquiry=inquiry)

    reparsed = parse_content_team_markdown(serialize_content_team_markdown(content))
    assert reparsed.inquiry is not None
    assert reparsed.inquiry.kind == "탐구"
    assert reparsed.visuals == ()


def test_content_team_inquiry_requires_the_programs_ordered_procedure_steps() -> None:
    with pytest.raises(ValueError, match="three ordered steps"):
        ContentTeamInquiry(
            kind="실험",
            procedure="(가) 첫 과정을 수행한다.\n(다) 다음 과정을 수행한다.",
            result="결과를 정리한다.",
        )


def test_multiple_equations_round_trip_without_a_fixed_count() -> None:
    equations = ("x", "x_{0}", "x^{2}")
    content = _content(
        stem="관계 $x$, $x_{0}$, $x^{2}$을 해석하여 물음에 답하시오.",
        equations=equations,
    )

    reparsed = parse_content_team_markdown(serialize_content_team_markdown(content))
    assert reparsed.equation_sources == equations


def test_content_v2_rejects_explanations_that_do_not_partition_answer_labels() -> None:
    value = _content().model_dump(mode="json")
    value["explanations"]["correct_answer"] = "ㄱ. 제시된 정보와 일치한다."
    value["explanations"]["wrong_answer"] = (
        "ㄴ. 제시된 정보와 일치하지 않는다.\nㄷ. 제시된 정보와 일치하지 않는다."
    )

    with pytest.raises(ValueError, match="explanation labels must partition"):
        AssessmentItemContentV2.model_validate(value)


def test_all_correct_item_round_trips_with_an_empty_wrong_answer_section() -> None:
    value = _content().model_dump(mode="json")
    value["answer"] = {
        "answer_kind": "STATEMENT_COMBINATION",
        "number": "⑤",
        "statement_labels": ["ㄱ", "ㄴ", "ㄷ"],
        "answer_content": "ㄱ, ㄴ, ㄷ",
        "raw_line": "정답 : ⑤ (ㄱ, ㄴ, ㄷ)",
    }
    value["explanations"] = {
        **value["explanations"],
        "correct_answer": (
            "ㄱ. 제시된 정보와 일치한다.\nㄴ. 제시된 정보와 일치한다.\nㄷ. 제시된 정보와 일치한다."
        ),
        "wrong_answer": "",
    }
    content = AssessmentItemContentV2.model_validate(value)

    reparsed = parse_content_team_markdown(serialize_content_team_markdown(content))
    assert reparsed.answer.statement_labels == ("ㄱ", "ㄴ", "ㄷ")
    assert reparsed.explanations.wrong_answer == ""


def test_direct_choice_item_is_a_first_class_v2_contract() -> None:
    value = _content().model_dump(mode="json")
    value["statements"] = []
    value["answer"] = {
        "answer_kind": "DIRECT_CHOICE",
        "number": "②",
        "statement_labels": [],
        "answer_content": "두 번째 설명",
        "raw_line": "정답 : ② (두 번째 설명)",
    }
    value["explanations"] = {
        **value["explanations"],
        "correct_answer": "두 번째 설명이 요청의 판단 기준과 일치한다.",
        "wrong_answer": "나머지 설명은 요청의 판단 기준과 일치하지 않는다.",
    }

    content = AssessmentItemContentV2.model_validate(value)
    validate_contract("assessment-item-content-v2", content.model_dump(mode="json"))
    reparsed = parse_content_team_markdown(serialize_content_team_markdown(content))

    assert reparsed.answer.answer_kind == "DIRECT_CHOICE"
    assert reparsed.statements == ()
    assert reparsed.answer.answer_content == "두 번째 설명"


def test_v2_json_schema_rejects_a_partial_statement_block() -> None:
    value = _content().model_dump(mode="json")
    value["statements"] = value["statements"][:2]

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("assessment-item-content-v2", value)


def test_v7_authoring_result_is_schema_first_and_codex_compatible() -> None:
    result = ContentTeamAuthoringRoleResultV7(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="authoring",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 3, tzinfo=UTC),
        output={
            "draft": _content(
                stem="관계 $x$와 $x^{2}$을 해석하여 물음에 답하시오.",
                equations=("x", "x^{2}"),
            ),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    )
    value = result.model_dump(mode="json")

    assert isinstance(
        validate_role_result(value, "authoring", "authoring-result@7.0"),
        ContentTeamAuthoringRoleResultV7,
    )
    Draft202012Validator(load_role_result_schema("authoring-result@7.0")).validate(value)
    codex_schema = load_codex_result_schema("authoring-result@7.0")
    projected = json.loads(json.dumps(value))
    del projected["output"]["draft"]["visual_layout"]
    Draft202012Validator(codex_schema).validate(projected)
    rehydrated = validate_role_result(projected, "authoring", "authoring-result@7.0")
    assert isinstance(rehydrated, ContentTeamAuthoringRoleResultV7)
    assert rehydrated.output.draft.visual_layout == "NONE"
    draft_schema = codex_schema["$defs"]["AssessmentItemContentV2"]
    assert "visual_layout" not in draft_schema["properties"]
    assert "visual_layout" not in draft_schema["required"]
    assert "actual headers and rows" in draft_schema["properties"]["visuals"]["description"]
    encoded = json.dumps(codex_schema, ensure_ascii=False, sort_keys=True)
    assert "prefixItems" not in encoded
    assert all(name not in encoded for name in ('"data_table"', '"image_brief"', '"equation"'))
    assert role_schema_bundle_hash("workflow-role/1.15.0") == (
        "sha256:bbdc8f4d62bbd5fbe576a55ee418b6477c8a6e5b03c10a0d517aa35b11f79144"
    )


def test_content_team_stem_normalizes_only_its_duplicate_item_marker() -> None:
    assert normalize_content_team_stem(11, "11. 문항의 발문") == "문항의 발문"
    assert normalize_content_team_stem(11, "12. 비교 대상의 번호") == "12. 비교 대상의 번호"
    assert normalize_content_team_stem(11, "11.문항의 발문") == "11.문항의 발문"
    with pytest.raises(ValueError, match="empty after item marker"):
        normalize_content_team_stem(11, "11. ")


def test_content_team_bottom_stem_separates_matching_source_score_markers() -> None:
    assert (
        normalize_content_team_bottom_stem("2.5", "옳은 것을 고른 것은? [2.5점]")
        == "옳은 것을 고른 것은?"
    )
    assert (
        normalize_content_team_bottom_stem("2.5", "옳은 것을 고른 것은? [2.5점] [2.5점]")
        == "옳은 것을 고른 것은?"
    )
    assert normalize_content_team_bottom_stem("2.5", "옳은 것을 고른 것은?") == (
        "옳은 것을 고른 것은?"
    )
    with pytest.raises(ValueError, match="differs from score_display"):
        normalize_content_team_bottom_stem("2.5", "옳은 것을 고른 것은? [3점]")


def test_content_team_serializer_rejects_noncanonical_embedded_score() -> None:
    value = _content().model_dump(mode="json")
    value["bottom_stem"] += " [2.5점]"

    with pytest.raises(ValueError, match="score only in score_display"):
        serialize_content_team_markdown(AssessmentItemContentV2.model_validate(value))


def test_content_team_equation_sources_are_an_ordered_derived_occurrence_index() -> None:
    content = _content(
        stem="첫 $x$를 해석한다.",
        equations=("x", "x"),
    )
    value = content.model_dump(mode="json")
    value["explanations"]["concept_source"] = "두 번째 $x$를 확인한다."
    content = AssessmentItemContentV2.model_validate(value)

    assert derive_content_team_equation_sources(content) == ("x", "x")

    value["equation_sources"] = ["$x$"]
    with pytest.raises(ValueError, match="index differs"):
        serialize_content_team_markdown(AssessmentItemContentV2.model_validate(value))


def test_v7_projected_authoring_derives_markdown_representation_fields() -> None:
    result = ContentTeamAuthoringRoleResultV7(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="authoring",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 3, tzinfo=UTC),
        output={
            "draft": _content(
                stem="관계 $x$를 해석하여 물음에 답하시오.",
                equations=("$x$",),
            ),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    )
    projected = result.model_dump(mode="json")
    draft = projected["output"]["draft"]
    del draft["visual_layout"]
    draft["stem"] = f"{draft['item_number']}. {draft['stem']}"

    parsed = validate_role_result(projected, "authoring", "authoring-result@7.0")

    assert isinstance(parsed, ContentTeamAuthoringRoleResultV7)
    assert parsed.output.draft.stem == "관계 $x$를 해석하여 물음에 답하시오."
    assert parsed.output.draft.equation_sources == ("x",)
    serialize_content_team_markdown(parsed.output.draft)


def test_v7_projected_authoring_canonicalizes_source_score_before_commit() -> None:
    result = ContentTeamAuthoringRoleResultV7(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="authoring",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 3, tzinfo=UTC),
        output={
            "draft": _content(),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    )
    projected = result.model_dump(mode="json")
    draft = projected["output"]["draft"]
    del draft["visual_layout"]
    draft["bottom_stem"] += " [2.5점] [2.5점]"

    parsed = validate_role_result(projected, "authoring", "authoring-result@7.0")

    assert isinstance(parsed, ContentTeamAuthoringRoleResultV7)
    assert parsed.output.draft.bottom_stem == "옳은 것만을 <보기>에서 있는 대로 고른 것은?"
    rendered = serialize_content_team_markdown(parsed.output.draft).decode("utf-8")
    assert rendered.count("[2.5점]") == 1
    projected_schema = load_codex_result_schema("authoring-result@7.0")
    bottom = projected_schema["$defs"]["AssessmentItemContentV2"]["properties"]["bottom_stem"]
    assert "must omit" in bottom["description"]


def test_v7_projected_authoring_rejects_unrenderable_equations_early() -> None:
    result = ContentTeamAuthoringRoleResultV7(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="authoring",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 3, tzinfo=UTC),
        output={
            "draft": _content(
                stem=r"관계 $\sqrt{2}$를 해석하여 물음에 답하시오.",
                equations=(r"\sqrt{2}",),
            ),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    )
    projected = result.model_dump(mode="json")
    del projected["output"]["draft"]["visual_layout"]

    with pytest.raises(ValueError, match="cannot be materialized"):
        validate_role_result(projected, "authoring", "authoring-result@7.0")


@pytest.mark.parametrize(
    ("visuals", "layout", "inquiry"),
    [
        ((), "NONE", None),
        ((ContentTeamImageSlot(),), "IMAGE_ONLY", None),
        (
            (
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
            ),
            "TABLE_ONLY",
            None,
        ),
        (
            (ContentTeamImageSlot(label="(가)"), ContentTeamImageSlot(label="(나)")),
            "IMAGE_IMAGE",
            None,
        ),
        (
            (
                ContentTeamImageSlot(),
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
            ),
            "IMAGE_TABLE",
            None,
        ),
        (
            (
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
                ContentTeamImageSlot(),
            ),
            "TABLE_IMAGE",
            None,
        ),
        (
            (
                ContentTeamTable(
                    label="(가)",
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
                ContentTeamTable(
                    label="(나)",
                    headers=("구분", "값"),
                    rows=(("B", "2"),),
                    alignments=("default", "right"),
                ),
            ),
            "TABLE_TABLE",
            None,
        ),
        (
            (),
            "INQUIRY_BOX",
            ContentTeamInquiry(
                kind="실험",
                procedure=(
                    "(가) 첫 과정을 수행한다.\n(나) 다음 과정을 수행한다.\n(다) 결과를 관찰한다."
                ),
                result="관찰 결과를 정리한다.",
            ),
        ),
    ],
)
def test_v7_projected_authoring_derives_one_canonical_visual_layout(
    visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...],
    layout: str,
    inquiry: ContentTeamInquiry | None,
) -> None:
    result = ContentTeamAuthoringRoleResultV7(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="authoring",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 3, tzinfo=UTC),
        output={
            "draft": _content(
                visuals=visuals,
                visual_layout=layout,
                inquiry=inquiry,
            ),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    )
    projected = result.model_dump(mode="json")
    del projected["output"]["draft"]["visual_layout"]
    projected["output"]["draft"]["stem"] = f"{result.output.draft.item_number}. " + str(
        projected["output"]["draft"]["stem"]
    )

    parsed = validate_role_result(projected, "authoring", "authoring-result@7.0")

    assert isinstance(parsed, ContentTeamAuthoringRoleResultV7)
    assert parsed.output.draft.visual_layout == layout
    assert parsed.output.draft.stem == result.output.draft.stem


def test_v7_explicit_canonical_layout_is_never_rewritten() -> None:
    content = _content(
        visuals=(
            ContentTeamTable(
                headers=("구분", "값"),
                rows=(("A", "1"),),
                alignments=("default", "right"),
            ),
        ),
        visual_layout="TABLE_ONLY",
    ).model_dump(mode="json")
    content["visual_layout"] = "IMAGE_ONLY"
    value = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.15.0",
        "job_id": "job_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "step_run_id": "steprun_" + "3" * 32,
        "role": "authoring",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "4" * 32,
            "revision_id": "rev_" + "5" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": "2026-09-03T00:00:00Z",
        "output": {
            "draft": content,
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
    }

    with pytest.raises(ValueError, match="typed validation"):
        validate_role_result(value, "authoring", "authoring-result@7.0")


def test_v7_workflow_has_no_mandatory_image_step_and_one_protocol() -> None:
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.7.yaml",
        ROLES,
    )

    assert compiled.definition.definition_version == "1.7.0"
    assert [step.key for step in compiled.definition.steps] == [
        "authoring",
        "review",
        "human_approval",
        "registration",
        "complete",
    ]
    assert [
        step.result_schema for step in compiled.definition.steps if hasattr(step, "result_schema")
    ] == ["authoring-result@7.0", "review-result@7.0", "registration-result@7.0"]


def test_content_team_pack_uses_unconstrained_brief_and_no_image_role() -> None:
    pack_root = ROOT / "content/packs/generated-knowledge-item/1.12.0"
    compiled = compile_pack(pack_root)
    request = WorkflowRequest.model_validate_json(
        (pack_root / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )

    assert compiled.manifest.pack.version == "1.12.0"
    assert compiled.source_tree_sha256 == (
        "sha256:f75b0416e117e8c5b768c326ef438f3400446c0cb1488637c4a6361e7177b975"
    )
    assert compiled.manifest.compatibility.protocol.minimum == "1.15.0"
    assert compiled.manifest.compatibility.required_worker_roles == (
        "authoring",
        "review",
        "item_management",
    )
    assert request.image_mode == "skip"
    assert request.profiles is not None and request.profiles.image is None
    assert isinstance(request.item_brief, ContentTeamItemBrief)
    brief = request.item_brief.model_dump(mode="json")
    validate_schema_message(load_knowledge_item_brief_v3_schema(), brief, "content-team-brief")
    assert {"choice_count", "equation_required", "image_required", "quality_profile"}.isdisjoint(
        brief
    )
    authoring_prompt = (pack_root / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    assert "처음부터 끝까지 그대로 읽고" in authoring_prompt
    assert "별도의 내용 규칙을 추가하지 마라" in authoring_prompt


def test_api_v3_resolves_content_team_curriculum_without_adding_shape_defaults() -> None:
    scope = resolve_integrated_science_curriculum_scope("eom.is.middle.3-2")
    guidance = " > ".join(scope.breadcrumb)
    request = WorkflowStartRequest.model_validate(
        {
            "definition_key": "generic-item-development",
            "definition_version": "1.7.0",
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "skip",
            "pack_key": "generated-knowledge-item",
            "execution_preset_key": "standard-item",
            "item_brief": {
                "schema_version": "3.0",
                "subject": "통합과학",
                "topic": scope.breadcrumb[-1],
                "task_type": "문항 출제",
                "difficulty": "중",
                "authoring_guidance": guidance,
                "authoring_guidance_sha256": (
                    "sha256:" + hashlib.sha256(guidance.encode("utf-8")).hexdigest()
                ),
                "curriculum_selected_unit_key": scope.selected_unit_key,
                "original_request_sha256": "0" * 64,
            },
        }
    )

    internal = _workflow_request_from_api(request)

    assert isinstance(internal.item_brief, ContentTeamItemBrief)
    assert internal.item_brief.curriculum_scope == scope
    assert internal.image_mode == "skip"
    assert internal.profiles is not None and internal.profiles.image is None
    dumped = internal.item_brief.model_dump(mode="json")
    assert {"choice_count", "equation_required", "image_required", "quality_profile"}.isdisjoint(
        dumped
    )


def test_catalog_v10_carries_v1_or_v2_without_rewriting_old_protocol() -> None:
    content = _content()
    request = CatalogApplicationRequest(
        root=ReviewedItemContentImportCommand(
            base_revision_id="itemrev_" + "6" * 32,
            expected_version=1,
            reviewed_by="operator_test_admin",
            review_reason="콘텐츠팀 형식과 검토 결과를 승인합니다.",
            content=content,
        )
    ).model_dump(mode="json")
    response_model = CatalogApplicationResponse(
        status="OK",
        operation="GET_ITEM_CONTENT",
        content=content,
    )
    response = {
        key: value
        for key, value in response_model.model_dump(mode="json").items()
        if value is not None
    }

    validate_contract("catalog-application-request-v10", request)
    validate_contract("catalog-application-response-v10", response)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("catalog-application-request", request)


def test_generated_protocol_pins_identity_without_content_shape_defaults() -> None:
    content_path = ROOT / "schemas/item-registry/assessment-item-content-v2.schema.json"
    brief_path = ROOT / "schemas/workflow/knowledge-item-brief-v3.schema.json"
    content_schema = json.loads(content_path.read_text(encoding="utf-8"))
    brief_schema = json.loads(brief_path.read_text(encoding="utf-8"))

    content_properties = content_schema["properties"]
    assert "minItems" not in content_properties["visuals"]
    assert "minItems" not in content_properties["equation_sources"]
    for field in ("subject", "topic", "task_type", "difficulty", "authoring_guidance"):
        assert {"const", "enum", "default"}.isdisjoint(brief_schema["properties"][field])
    assert hashlib.sha256(content_path.read_bytes()).hexdigest() == (
        "2136413f5059905be0c066c8fd657cbfc5238ba47e36ac3502be669ae130b9a8"
    )


def test_content_team_contract_keeps_service_dependency_direction() -> None:
    contract_modules = (
        ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/content_team_equations.py",
        ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/content_team_markdown.py",
        ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/models.py",
    )
    forbidden_roots = {
        "eom_catalog_service",
        "eom_hwpx_builder",
        "eom_hwpx_manager",
        "eom_orchestrator",
        "sqlalchemy",
        "subprocess",
    }
    imported: set[str] = set()
    for path in contract_modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden_roots)

    for relative in (
        "services/catalog_service/eom_catalog_service/item_content_import.py",
        "services/catalog_service/eom_catalog_service/workflow_catalog.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "eom_hwpx_manager" not in source
        assert "eom_hwpx_builder" not in source

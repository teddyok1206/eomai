"""Synthetic pure projections: no database, Artifact reads, runtime activation or model use."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.assessment_item import (
    AssessmentItemContent,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile
from eom_catalog_contracts.knowledge import (
    KnowledgeAnalysisSolutionReport,
    KnowledgeAnalysisSourceArtifactMemberV2,
)
from eom_catalog_service.inference_transfer_item_projection import (
    IMAGE_ACCESS_LIMITATION,
    INLINE_FORMULA_METADATA_LIMITATION,
    PATTERN_SUMMARY_LIMITATION,
    STRUCTURAL_METADATA_LIMITATION,
    ItemProjectionUnavailable,
    extract_evidence_bound_item_metadata,
    extract_original_item_metadata,
    project_staged_item_entry,
    render_no_solution_item_text,
)
from eom_identifiers import canonical_json_bytes, content_sha256

from tests.unit.inference_transfer_fixtures import profile, report, sha


def _recipe() -> ExperimentViewRecipe:
    body = ExperimentViewRecipe.model_construct(recipe_sha256=sha()).model_dump(
        mode="json", exclude={"recipe_sha256"}
    )
    return ExperimentViewRecipe.model_validate(body | {"recipe_sha256": content_sha256(body)})


def _item_v1() -> AssessmentItemContent:
    return AssessmentItemContent.model_validate(
        {
            "schema_version": "1.0",
            "locale": "ko-KR",
            "title": "TITLE_INTERNAL_ONLY",
            "body": [
                {
                    "block_id": "block_stem",
                    "type": "paragraph",
                    "purpose": "stem",
                    "text": "마찰이 없고 속력은 -36 km/h이다. 에너지가 보존되지 않는 경우는?",
                },
                {
                    "block_id": "block_table",
                    "type": "table",
                    "purpose": "data",
                    "caption": "질량과 속력의 측정 결과",
                    "headers": ["질량 (kg)", "속력 (m/s)"],
                    "rows": [["2", "-10"], ["4 | 5", "0\t또는\n-3"]],
                },
                {
                    "block_id": "block_equation",
                    "type": "equation",
                    "purpose": "stimulus",
                    "notation": "latex",
                    "source": r"E_k=\frac{1}{2}mv^2",
                },
                {
                    "block_id": "block_image",
                    "type": "image",
                    "purpose": "stimulus",
                    "alt_text": "경사면을 내려오는 물체",
                    "width_px": 400,
                    "height_px": 300,
                    "artifact": {
                        "artifact_id": "artifact_" + "a" * 32,
                        "artifact_revision_id": "rev_" + "b" * 32,
                        "artifact_member": "PRIVATE_IMAGE_PATH.png",
                        "sha256": sha("c"),
                        "media_type": "image/png",
                    },
                },
                {
                    "block_id": "block_statements",
                    "type": "statement_set",
                    "purpose": "claims",
                    "statements": [
                        {"statement_id": "statement_g", "label": "ㄱ", "text": "외력은 0 N이다."},
                        {
                            "statement_id": "statement_n",
                            "label": "ㄴ",
                            "text": "속력은 음수가 아니다.",
                        },
                    ],
                },
            ],
            "interaction": {
                "type": "single_choice",
                "choices": [
                    {"choice_id": f"choice_{i}", "label": str(i), "text": f"선택지 {i}"}
                    for i in range(1, 6)
                ],
            },
            "solution": {
                "correct_choice_ids": ["choice_2"],
                "accepted_answers": [],
                "explanation": "SOLUTION_ONLY",
                "authoring_intent": "AUTHOR_INTENT_ONLY",
                "statement_explanations": [
                    {"statement_id": "statement_g", "text": "STATEMENT_EXPLANATION_ONLY"},
                    {"statement_id": "statement_n", "text": "STATEMENT_EXPLANATION_ONLY"},
                ],
            },
            "score": {"points": 3},
        }
    )


def _item_content_team(version: int = 2) -> AssessmentItemContentV2 | AssessmentItemContentV3:
    body = {
        "schema_version": f"{version}.0",
        "item_number": 57,
        "score_display": "2" if version == 2 else "1.5",
        "stem": "다음은 에너지에 대한 설명이다. $E=mc^2$이며 질량은 2 kg이다.",
        "bottom_stem": "이에 대한 설명으로 옳지 않은 것은?",
        "inquiry": None,
        "labeled_blocks": [{"kind": "DATA", "content": "외력이 한 일은 0 J이다."}],
        "visuals": [
            {"kind": "IMAGE", "label": ""},
            {
                "kind": "TABLE",
                "label": "",
                "headers": ["물체", "속력 (m/s)"],
                "rows": [["A", "-2"], ["B", "0"]],
                "alignments": ["left", "right"],
            },
        ],
        "visual_layout": "IMAGE_TABLE",
        "statements": [],
        "choices": [{"number": label, "text": f"선택지 {i}"} for i, label in enumerate("①②③④⑤", 1)],
        "answer": {
            "answer_kind": "DIRECT_CHOICE",
            "number": "②",
            "answer_content": "ANSWER_CONTENT_ONLY",
            "raw_line": "정답 : ② (ANSWER_CONTENT_ONLY)",
            "statement_labels": [],
        },
        "explanations": {
            "authoring_intent": "AUTHOR_INTENT_ONLY",
            "concept_source": "CONCEPT_SOURCE_ONLY",
            "correct_answer": "CORRECT_EXPLANATION_ONLY",
            "wrong_answer": "WRONG_EXPLANATION_ONLY",
        },
        "equation_sources": ["AGGREGATE_ANSWER_EQUATION_ONLY"],
    }
    model = AssessmentItemContentV2 if version == 2 else AssessmentItemContentV3
    return model.model_validate(body)


def _source(
    item: AssessmentItemContentContract, *, schema: str | None = None
) -> KnowledgeAnalysisSourceArtifactMemberV2:
    body = profile().source_basis.source.artifact_member.model_dump(mode="json")
    body.update(
        schema_ref=schema or f"eom.assessment.item-content/{item.schema_version}",
        sha256=content_sha256(item.model_dump(mode="json")),
        bytes=len(canonical_json_bytes(item)),
    )
    return KnowledgeAnalysisSourceArtifactMemberV2.model_validate(body)


def _accepted_report(
    *, summary: str = "보존 조건으로 에너지 관계를 적용하는 패턴"
) -> KnowledgeAnalysisSolutionReport:
    body = report().model_dump(mode="json")
    body["concept_assessment_links"][1].update(
        assessment_pattern_node_ids=["knode_assessment_pattern_energy_conservation"],
        summary=summary,
    )
    return KnowledgeAnalysisSolutionReport.model_validate(body)


def _bound_profile(
    item: AssessmentItemContentContract, accepted: KnowledgeAnalysisSolutionReport
) -> InferenceTransferProfile:
    body = profile().model_dump(mode="json", exclude={"profile_sha256"})
    body["source_basis"]["source"]["artifact_member"] = _source(item).model_dump(mode="json")
    pointer = body["source_basis"]["solution_evidence"]
    pointer["solution_report"]["sha256"] = content_sha256(accepted.model_dump(mode="json"))
    pointer["pointer_sha256"] = content_sha256(
        {key: value for key, value in pointer.items() if key != "pointer_sha256"}
    )
    return InferenceTransferProfile.model_validate(body | {"profile_sha256": content_sha256(body)})


@pytest.mark.parametrize("version", (1, 2, 3))
def test_all_canonical_versions_are_complete_repeatable_and_question_only(version: int) -> None:
    item = _item_v1() if version == 1 else _item_content_team(version)
    before = canonical_json_bytes(item)
    original = _source(item)
    first = render_no_solution_item_text(item=item, original_source=original, recipe=_recipe())
    second = render_no_solution_item_text(item=item, original_source=original, recipe=_recipe())
    assert first == second and first.original_source == original
    assert first.text_sha256 == content_sha256(first.text)
    assert canonical_json_bytes(item) == before
    for forbidden in (
        "TITLE_INTERNAL_ONLY",
        "SOLUTION_ONLY",
        "AUTHOR_INTENT_ONLY",
        "ACCEPTED_ANSWER_ONLY",
        "STATEMENT_EXPLANATION_ONLY",
        "ANSWER_CONTENT_ONLY",
        "CORRECT_EXPLANATION_ONLY",
        "CONCEPT_SOURCE_ONLY",
        "WRONG_EXPLANATION_ONLY",
        "AGGREGATE_ANSWER_EQUATION_ONLY",
        "artifact_",
        "rev_",
        "sha256:",
        "block_stem",
        "choice_",
        "PRIVATE_IMAGE_PATH",
        "authoring_prompt_sha256",
        "handoff_archive_sha256",
        "score_display",
    ):
        assert forbidden not in first.text
    assert "kg" in first.text and ("경우는?" in first.text or "옳지 않은" in first.text)


def test_v1_body_order_caption_table_boundaries_units_and_negation_are_preserved() -> None:
    item = _item_v1()
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    expected = (
        "-36 km/h",
        "질량과 속력의 측정 결과",
        r"E_k=\frac{1}{2}mv^2",
        "경사면을 내려오는 물체",
        "ㄱ 외력은 0 N이다.",
        "ㄴ 속력은 음수가 아니다.",
        "1 선택지 1",
    )
    assert [result.text.index(value) for value in expected] == sorted(
        result.text.index(value) for value in expected
    )
    rows = [json.loads(line) for line in result.text.splitlines() if line.startswith("[")]
    assert rows == [["질량 (kg)", "속력 (m/s)"], ["2", "-10"], ["4 | 5", "0\t또는\n-3"]]
    assert "보존되지 않는" in result.text


@pytest.mark.parametrize(
    "layout,kinds", (("IMAGE_TABLE", ("IMAGE", "TABLE")), ("TABLE_IMAGE", ("TABLE", "IMAGE")))
)
def test_mixed_native_visual_order_is_not_reinterpreted(
    layout: str, kinds: tuple[str, str]
) -> None:
    body = _item_content_team().model_dump(mode="json")
    by_kind = {visual["kind"]: visual for visual in body["visuals"]}
    body.update(visual_layout=layout, visuals=[by_kind[kind] for kind in kinds])
    item = AssessmentItemContentV2.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    indices = [result.text.index("[그림]"), result.text.index('["물체","속력 (m/s)"]')]
    assert (indices[0] < indices[1]) == (kinds[0] == "IMAGE")
    assert result.text.index("0 J") < min(indices) < result.text.index(item.bottom_stem)
    assert "$E=mc^2$" in result.text and "옳지 않은" in result.text


def test_inquiry_goal_procedure_result_are_candidate_fields_and_stay_ordered() -> None:
    body = _item_content_team(3).model_dump(mode="json")
    body.update(
        visuals=[],
        visual_layout="INQUIRY_BOX",
        inquiry={
            "kind": "실험",
            "goal": "질량의 영향 확인",
            "procedure": "(가) 준비한다.\n(나) 측정한다.\n(다) 비교한다.",
            "result": "시간은 2 s이며 증가하지 않는다.",
        },
    )
    item = AssessmentItemContentV3.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    assert (
        result.text.index("질량의 영향")
        < result.text.index("(가) 준비")
        < result.text.index("2 s")
        < result.text.index(item.bottom_stem)
    )


def test_inquiry_kind_is_exact_structural_metadata_not_added_content_prose() -> None:
    body = _item_content_team(3).model_dump(mode="json")
    body.update(
        visuals=[],
        visual_layout="INQUIRY_BOX",
        inquiry={
            "kind": "실험",
            "goal": "질량의 영향 확인",
            "procedure": "(가) 준비한다.\n(나) 측정한다.\n(다) 비교한다.",
            "result": "시간은 2 s이다.",
        },
    )
    accepted = _accepted_report()
    entries = []
    for kind in ("실험", "탐구"):
        body["inquiry"]["kind"] = kind
        item = AssessmentItemContentV3.model_validate(body)
        entries.append(
            project_staged_item_entry(
                profile=_bound_profile(item, accepted),
                item=item,
                accepted_report=accepted,
                recipe=_recipe(),
            )
        )
    assert entries[0].content is not None and entries[1].content is not None
    assert entries[0].content.text == entries[1].content.text
    for entry, kind in zip(entries, ("실험", "탐구"), strict=True):
        assert entry.content is not None and kind not in entry.content.text
        assert any(
            field.key == "MATERIAL_FORM" and field.value == kind and field.basis == "ORIGINAL_ITEM"
            for field in entry.metadata
        )
        assert INLINE_FORMULA_METADATA_LIMITATION in entry.limitations


def test_constructed_response_includes_only_original_response_format() -> None:
    body = _item_v1().model_dump(mode="json")
    body["interaction"] = {"type": "constructed_response", "response_format": "numeric"}
    body["solution"]["correct_choice_ids"] = []
    body["solution"]["accepted_answers"] = ["ACCEPTED_ANSWER_ONLY"]
    item = AssessmentItemContent.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    assert "응답 형식: numeric" in result.text and "ACCEPTED_ANSWER_ONLY" not in result.text


def test_hancom_equation_source_is_preserved_without_notation_conversion() -> None:
    body = _item_v1().model_dump(mode="json")
    body["body"][2].update(notation="hancom-equation-script", source="E_k = {1} over {2} m v^2")
    item = AssessmentItemContent.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    assert "E_k = {1} over {2} m v^2" in result.text


def test_content_team_statement_combination_keeps_question_order_not_explanations() -> None:
    body = _item_content_team(3).model_dump(mode="json")
    body["statements"] = [
        {"label": label, "text": f"{label}의 조건에서 보존되지 않는다."} for label in "ㄱㄴㄷ"
    ]
    for choice, text in zip(
        body["choices"], ("ㄱ", "ㄴ", "ㄱ, ㄴ", "ㄴ, ㄷ", "ㄱ, ㄴ, ㄷ"), strict=True
    ):
        choice["text"] = text
    body["answer"].update(
        answer_kind="STATEMENT_COMBINATION",
        answer_content="ㄴ",
        raw_line="정답 : ② (ㄴ)",
        statement_labels=["ㄴ"],
    )
    body["explanations"].update(
        correct_answer="ㄴ. CORRECT_EXPLANATION_ONLY",
        wrong_answer="ㄱ. WRONG_EXPLANATION_ONLY\nㄷ. WRONG_EXPLANATION_ONLY",
    )
    item = AssessmentItemContentV3.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    assert result.text.index(item.bottom_stem) < result.text.index("ㄱ ㄱ의 조건")
    assert result.text.index("ㄷ ㄷ의 조건") < result.text.index("① ㄱ")
    assert "정답 :" not in result.text and "EXPLANATION_ONLY" not in result.text


@pytest.mark.parametrize("kind,layout", (("IMAGE", "IMAGE_IMAGE"), ("TABLE", "TABLE_TABLE")))
def test_two_visual_labels_remain_exact_ordered_candidate_text(kind: str, layout: str) -> None:
    body = _item_content_team(3).model_dump(mode="json")
    visual = next(value for value in body["visuals"] if value["kind"] == kind)
    body.update(
        visuals=[visual | {"label": "(가)"}, visual | {"label": "(나)"}],
        visual_layout=layout,
    )
    item = AssessmentItemContentV3.model_validate(body)
    result = render_no_solution_item_text(
        item=item, original_source=_source(item), recipe=_recipe()
    )
    assert (
        result.text.index("(가)") < result.text.index("(나)") < result.text.index(item.bottom_stem)
    )
    assert result.text.count("[그림]" if kind == "IMAGE" else '["물체","속력 (m/s)"]') == 2


@pytest.mark.parametrize("version", (1, 2, 3))
def test_supported_schema_aliases_use_the_one_authoritative_alias_map(version: int) -> None:
    item = _item_v1() if version == 1 else _item_content_team(version)
    source = _source(item, schema=f"eom://schemas/item-registry/assessment-item-content-v{version}")
    assert (
        render_no_solution_item_text(
            item=item, original_source=source, recipe=_recipe()
        ).original_source
        == source
    )


@pytest.mark.parametrize(
    "update,code",
    (
        (
            {"schema_ref": "eom.assessment.item-content/99.0"},
            "INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE",
        ),
        ({"schema_ref": None}, "INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE"),
        ({"schema_ref": "eom.assessment.item-content/2.0"}, "INFERENCE_ITEM_CONTENT_TYPE_MISMATCH"),
        ({"media_type": "application/pdf"}, "INFERENCE_ITEM_CONTENT_MEDIA_TYPE_UNAVAILABLE"),
    ),
)
def test_unsupported_schema_media_or_wrong_typed_version_never_falls_back(
    update: dict[str, Any], code: str
) -> None:
    item = _item_v1()
    source = _source(item).model_copy(update=update)
    with pytest.raises(ItemProjectionUnavailable) as caught:
        render_no_solution_item_text(item=item, original_source=source, recipe=_recipe())
    assert caught.value.code == code


def test_utf8_byte_bound_rejects_whole_view_without_cutting_terminal_negation() -> None:
    body = _item_v1().model_dump(mode="json")
    body["body"] = [
        {
            "block_id": f"block_long_{i}",
            "type": "paragraph",
            "purpose": "context",
            "text": "가" * 19000 + "끝에서도 보존되지 않는다.",
        }
        for i in range(5)
    ]
    body["solution"]["statement_explanations"] = []
    item = AssessmentItemContent.model_validate(body)
    with pytest.raises(ItemProjectionUnavailable, match="INFERENCE_ITEM_TEXT_TOO_LARGE"):
        render_no_solution_item_text(item=item, original_source=_source(item), recipe=_recipe())
    accepted = _accepted_report()
    result = project_staged_item_entry(
        profile=_bound_profile(item, accepted),
        item=item,
        accepted_report=accepted,
        recipe=_recipe(),
    )
    assert result.content is None and "INFERENCE_ITEM_TEXT_TOO_LARGE" in result.limitations
    assert result.metadata


def test_structural_and_exact_report_metadata_have_distinct_evidence_hashes() -> None:
    item, accepted = _item_v1(), _accepted_report()
    bound = _bound_profile(item, accepted)
    result = extract_evidence_bound_item_metadata(
        item=item,
        original_source=bound.source_basis.source.artifact_member,
        accepted_report=accepted,
        solution_evidence=bound.source_basis.solution_evidence,
    )
    assert result.fields == tuple(
        sorted(result.fields, key=lambda field: (field.key, field.value, field.basis))
    )
    assert {field.key for field in result.fields} == {
        "MATERIAL_FORM",
        "FORMULA",
        "ASSESSMENT_PATTERN",
    }
    for field in result.fields:
        assert field.source_sha256 == (
            bound.source_basis.source.artifact_member.sha256
            if field.basis == "ORIGINAL_ITEM"
            else bound.source_basis.solution_evidence.solution_report.sha256
        )
        assert "knode_" not in field.value and "solutionstep_" not in field.value
    accepted_fields = tuple(field for field in result.fields if field.basis == "ACCEPTED_SOLUTION")
    assert tuple(field.value for field in accepted_fields) == (
        accepted.concept_assessment_links[1].summary,
    )
    assert PATTERN_SUMMARY_LIMITATION in result.limitations
    assert STRUCTURAL_METADATA_LIMITATION in result.limitations


def test_report_without_pattern_link_has_explicit_limitation_not_invented_label() -> None:
    item, accepted = _item_v1(), report()
    result = extract_evidence_bound_item_metadata(
        item=item,
        original_source=_source(item),
        accepted_report=accepted,
        solution_evidence=profile().source_basis.solution_evidence,
    )
    assert all(field.basis != "ACCEPTED_SOLUTION" for field in result.fields)
    assert any("summary is unavailable" in limitation for limitation in result.limitations)


def test_long_report_summary_and_formula_are_wholly_omitted_not_sliced() -> None:
    body = _item_v1().model_dump(mode="json")
    formula = "x=" + "1+" * 260 + "0"
    body["body"][2]["source"] = formula
    item = AssessmentItemContent.model_validate(body)
    summary = "관계 " * 170 + "에너지는 보존되지 않는다."
    accepted = _accepted_report(summary=summary)
    result = extract_evidence_bound_item_metadata(
        item=item,
        original_source=_source(item),
        accepted_report=accepted,
        solution_evidence=profile().source_basis.solution_evidence,
    )
    assert all(
        field.key != "FORMULA" and field.basis != "ACCEPTED_SOLUTION" for field in result.fields
    )
    assert (
        len(
            tuple(limitation for limitation in result.limitations if "wholly omitted" in limitation)
        )
        == 2
    )
    assert PATTERN_SUMMARY_LIMITATION in result.limitations


def test_equal_evidence_values_deduplicate_without_mutating_report_or_changing_hash_origin() -> (
    None
):
    item = _item_v1()
    body = _accepted_report().model_dump(mode="json")
    body["concept_assessment_links"][0].update(
        assessment_pattern_node_ids=["knode_assessment_pattern_energy_conservation"],
        summary=body["concept_assessment_links"][1]["summary"],
    )
    accepted = KnowledgeAnalysisSolutionReport.model_validate(body)
    before = canonical_json_bytes(accepted)
    bound = _bound_profile(item, accepted)
    result = extract_evidence_bound_item_metadata(
        item=item,
        original_source=bound.source_basis.source.artifact_member,
        accepted_report=accepted,
        solution_evidence=bound.source_basis.solution_evidence,
    )
    fields = tuple(field for field in result.fields if field.basis == "ACCEPTED_SOLUTION")
    assert len(fields) == 1 and canonical_json_bytes(accepted) == before
    assert fields[0].source_sha256 == bound.source_basis.solution_evidence.solution_report.sha256


def test_metadata_budget_overflow_marks_entire_view_unavailable_not_first_32_fields() -> None:
    body = _item_v1().model_dump(mode="json")
    body["body"] = [
        {
            "block_id": f"block_eq_{i}",
            "type": "equation",
            "purpose": "stimulus",
            "notation": "latex",
            "source": f"F={i}ma",
        }
        for i in range(33)
    ]
    body["solution"]["statement_explanations"] = []
    item, accepted = AssessmentItemContent.model_validate(body), _accepted_report()
    result = extract_evidence_bound_item_metadata(
        item=item,
        original_source=_source(item),
        accepted_report=accepted,
        solution_evidence=profile().source_basis.solution_evidence,
    )
    assert result.fields == () and any(
        "entire metadata view is unavailable" in limitation for limitation in result.limitations
    )


def test_staged_entry_records_pixel_limitation_and_exact_source_closure() -> None:
    item, accepted = _item_content_team(3), _accepted_report()
    bound = _bound_profile(item, accepted)
    result = project_staged_item_entry(
        profile=bound, item=item, accepted_report=accepted, recipe=_recipe()
    )
    assert result.profile == bound and result.content is not None
    assert result.content.original_source == bound.source_basis.source.artifact_member
    assert IMAGE_ACCESS_LIMITATION in result.limitations
    assert INLINE_FORMULA_METADATA_LIMITATION in result.limitations
    assert all(field.key != "FORMULA" for field in result.metadata)


def test_unsupported_source_is_explicit_unavailable_entry_not_fake_authorized_content() -> None:
    item, accepted = _item_v1(), _accepted_report()
    body = _bound_profile(item, accepted).model_dump(mode="json", exclude={"profile_sha256"})
    body["source_basis"]["source"]["artifact_member"]["schema_ref"] = (
        "eom.assessment.item-content/99.0"
    )
    bound = InferenceTransferProfile.model_validate(body | {"profile_sha256": content_sha256(body)})
    result = project_staged_item_entry(
        profile=bound, item=item, accepted_report=accepted, recipe=_recipe()
    )
    assert result.content is None and result.metadata == ()
    assert "INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE" in result.limitations


def test_forged_frozen_item_report_recipe_and_evidence_are_revalidated() -> None:
    item = _item_content_team()
    forged_choice = item.choices[0].model_copy(update={"text": "x" * 2001})
    forged_item = item.model_copy(update={"choices": (forged_choice, *item.choices[1:])})
    with pytest.raises(ValueError):
        render_no_solution_item_text(
            item=forged_item, original_source=_source(item), recipe=_recipe()
        )
    with pytest.raises(ValueError, match="recipe_sha256"):
        render_no_solution_item_text(
            item=item,
            original_source=_source(item),
            recipe=_recipe().model_copy(update={"recipe_sha256": sha("0")}),
        )
    accepted = _accepted_report()
    evidence = profile().source_basis.solution_evidence
    with pytest.raises(ValueError, match="pointer hash"):
        extract_evidence_bound_item_metadata(
            item=item,
            original_source=_source(item),
            accepted_report=accepted,
            solution_evidence=evidence.model_copy(update={"pointer_sha256": sha("0")}),
        )
    changed = accepted.model_copy(
        update={"base_analysis_result_id": "knowledgeanalysisresult_" + "e" * 32}
    )
    with pytest.raises(ValueError, match="REPORT_BASE_MISMATCH"):
        extract_evidence_bound_item_metadata(
            item=item,
            original_source=_source(item),
            accepted_report=changed,
            solution_evidence=evidence,
        )


def test_source_file_hash_is_not_falsely_recomputed_from_normalized_model_json() -> None:
    item = _item_v1()
    # An owner-validated original file may have different whitespace than model JSON.
    source = _source(item).model_copy(update={"sha256": sha("d")})
    result = render_no_solution_item_text(item=item, original_source=source, recipe=_recipe())
    assert result.original_source.sha256 == sha("d")
    assert result.text_sha256 == content_sha256(result.text) != source.sha256


@pytest.mark.parametrize("version", [1, 2, 3])
def test_original_only_metadata_reuses_exact_legacy_structural_fields(version: int) -> None:
    item = _item_v1() if version == 1 else _item_content_team(version)
    source = _source(item)
    original = extract_original_item_metadata(item=item, original_source=source)
    legacy = extract_evidence_bound_item_metadata(
        item=item,
        original_source=source,
        accepted_report=_accepted_report(),
        solution_evidence=profile().source_basis.solution_evidence,
    )
    assert original.fields == tuple(
        field for field in legacy.fields if field.basis == "ORIGINAL_ITEM"
    )
    assert all(field.source_sha256 == source.sha256 for field in original.fields)
    assert PATTERN_SUMMARY_LIMITATION not in original.limitations
    assert not any("Accepted assessment-pattern" in row for row in original.limitations)


def test_original_only_metadata_rejects_undeclared_frozen_extras() -> None:
    item = _item_content_team(3)
    forged = item.model_copy(update={"invented_dag": []})
    with pytest.raises(ValueError, match="undeclared"):
        extract_original_item_metadata(item=forged, original_source=_source(item))


def test_projection_module_has_no_filesystem_sql_worker_or_runtime_imports() -> None:
    source = Path(
        "services/catalog_service/eom_catalog_service/inference_transfer_item_projection.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module.startswith(
            (
                "sqlalchemy",
                "pathlib",
                "os",
                "subprocess",
                "eom_orchestrator",
                "eom_identity_service",
            )
        )
        for module in imports
    )
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not calls & {"open", "eval", "exec"}

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts.assessment_assembly import (
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.assessment_item import AssessmentItemContentV2
from eom_catalog_contracts.curriculum import load_integrated_science_editorial_outline
from eom_catalog_contracts.mock_exam_production_plan import (
    CONTENT_TEAM_ITEM_GUIDANCE,
    CONTENT_TEAM_ITEM_GUIDANCE_SHA256,
    CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256,
    CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256,
    MockExamProductionPlanError,
    MockExamProductionPlanV1,
    build_integrated_science_mock_exam_production_plan,
    classify_content_team_mock_exam_material_profile,
    validate_content_team_mock_exam_slot_output,
)
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow import ContentTeamItemBrief
from eom_workflow.schemas import (
    load_knowledge_item_brief_v3_schema,
    validate_schema_message,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _plan() -> MockExamProductionPlanV1:
    return build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


def test_production_plan_schema_is_2020_12_and_packaged_verbatim() -> None:
    canonical_path = ROOT / "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json"
    packaged_path = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
        / "mock-exam-production-plan-v1.schema.json"
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    schema = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_plan().model_dump(mode="json"))


def test_plan_is_exactly_25_unique_new_one_item_workflow_calls() -> None:
    plan = _plan()
    assert plan.item_count == len(plan.workflow_calls) == 25
    slots = tuple(row.item_brief.mock_exam_slot for row in plan.workflow_calls)
    assert tuple(row.position for row in slots) == tuple(range(1, 26))
    assert len({row.workflow_call_id for row in plan.workflow_calls}) == 25
    assert len({row.item_brief.original_request_sha256 for row in plan.workflow_calls}) == 25
    assert len({row.curriculum_selected_unit_key for row in slots}) < 25
    assert all(
        row.generation_block_sha256 == CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256
        for row in plan.workflow_calls
    )

    serialized = plan.model_dump(mode="json")
    forbidden_keys = {
        "item_id",
        "item_revision_id",
        "base_revision_id",
        "candidate_item_id",
        "candidate_item_revision_id",
    }
    assert forbidden_keys.isdisjoint(_nested_keys(serialized))
    assert "APPROVED" not in json.dumps(serialized, ensure_ascii=False)


def test_plan_preserves_50_points_and_released_score_distribution() -> None:
    plan = _plan()
    policy = load_integrated_science_mock_exam_policy()
    slots = tuple(row.item_brief.mock_exam_slot for row in plan.workflow_calls)
    observed = Counter(row.points_milli for row in slots)
    expected = Counter({row.points_milli: row.count for row in policy.score_distribution})
    assert observed == expected == Counter({1500: 8, 2000: 9, 2500: 8})
    assert sum(row.points_milli for row in slots) == 50_000


def test_plan_satisfies_exact_runtime_coverage_and_four_inquiries() -> None:
    plan = _plan()
    policy = load_integrated_science_mock_exam_policy()
    resolver = load_integrated_science_editorial_outline()
    unit_by_key = {unit.key: unit for unit in resolver.units}
    required_by_id: dict[str, list[str]] = defaultdict(list)
    for call in plan.workflow_calls:
        slot = call.item_brief.mock_exam_slot
        unit = unit_by_key[slot.curriculum_selected_unit_key]
        assert unit.parent_key == slot.large_unit_key
        if slot.coverage_role == "REQUIRED":
            assert slot.coverage_requirement_id is not None
            required_by_id[slot.coverage_requirement_id].append(slot.curriculum_selected_unit_key)
        else:
            assert slot.balance_large_unit_key == slot.large_unit_key

    assert sum(row.item_brief.mock_exam_slot.inquiry_required for row in plan.workflow_calls) == 4
    assert set(required_by_id) == {row.requirement_id for row in policy.coverage_requirements}
    for requirement in policy.coverage_requirements:
        selected = required_by_id[requirement.requirement_id]
        assert len(selected) == requirement.selection_count
        assert set(selected).issubset(requirement.allowed_unit_keys)
        if requirement.distinct_units:
            assert len(set(selected)) == requirement.selection_count


def test_each_v3_brief_is_derived_only_from_slot_outline_and_canonical_guidance() -> None:
    plan = _plan()
    layout = load_integrated_science_mock_exam_layout_policy()
    outline = load_integrated_science_editorial_outline()
    unit_by_key = {unit.key: unit for unit in outline.units}
    fixture = json.loads(
        (
            ROOT / "content/packs/generated-knowledge-item/1.13.0/fixtures/smoke-request.json"
        ).read_text(encoding="utf-8")
    )
    fixture_brief = fixture["item_brief"]
    assert fixture_brief["authoring_guidance"] == CONTENT_TEAM_ITEM_GUIDANCE
    assert fixture_brief["authoring_guidance_sha256"] == CONTENT_TEAM_ITEM_GUIDANCE_SHA256
    assert (
        plan.one_item_generation_block.content_pack_source_tree_sha256
        == CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256
    )

    for slot, call in zip(layout.slots, plan.workflow_calls, strict=True):
        brief = call.item_brief
        intent = brief.mock_exam_slot
        unit = unit_by_key[intent.curriculum_selected_unit_key]
        assert brief.subject == outline.subject_label
        assert brief.topic == unit.label
        assert brief.task_type == slot.preferred_material_profiles[0]
        assert brief.difficulty == slot.preferred_difficulty
        assert brief.curriculum_selected_unit_key == unit.key
        assert intent.slot_id == slot.slot_id
        assert intent.position == slot.position
        assert intent.points_milli == slot.points_milli
        assert intent.coverage_role == slot.coverage_role
        assert intent.coverage_requirement_id == slot.coverage_requirement_id
        assert intent.balance_large_unit_key == slot.balance_large_unit_key
        assert intent.inquiry_required == slot.inquiry_required
        assert intent.preferred_difficulty == slot.preferred_difficulty
        assert intent.preferred_material_profiles == slot.preferred_material_profiles
        assert (
            content_sha256(intent.model_dump(mode="json", exclude={"slot_sha256"}))
            == intent.slot_sha256
        )
        assert brief.authoring_guidance == CONTENT_TEAM_ITEM_GUIDANCE
        assert brief.authoring_guidance_sha256 == CONTENT_TEAM_ITEM_GUIDANCE_SHA256
        assert {
            "choice_count",
            "equation_required",
            "image_required",
            "quality_profile",
        }.isdisjoint(brief.model_fields_set)


def test_typed_slot_survives_api_to_domain_v3_mapping_without_a_prompt_rewrite() -> None:
    plan = _plan()
    block = plan.one_item_generation_block
    planned = plan.workflow_calls[0]
    request = WorkflowStartRequest.model_validate(
        {
            "definition_key": block.workflow_definition_key,
            "definition_version": block.workflow_definition_version,
            "request_name": block.request_name,
            "image_mode": block.image_mode,
            "pack_key": block.content_pack_key,
            "environment": "development",
            "registry_mode": block.registry_mode,
            "execution_preset_key": block.execution_preset_key,
            "item_brief": planned.item_brief.model_dump(mode="json"),
            "educational_retrieval": {
                "schema_version": "educational-retrieval-requirement/1.0",
                "corpus_key": "integrated-science-textbooks",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": None,
                "topic_keys": [],
                "required_item_elements": ["choice", "paragraph"],
                "source_classes": ["APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"],
            },
        }
    )
    internal = _workflow_request_from_api(request)
    assert isinstance(internal.item_brief, ContentTeamItemBrief)
    assert internal.item_brief.mock_exam_slot == planned.item_brief.mock_exam_slot
    assert internal.item_brief.curriculum_scope is not None
    assert internal.educational_retrieval is not None
    assert (
        internal.educational_retrieval.curriculum_root_key
        == internal.item_brief.curriculum_scope.graph_root_stable_key
    )
    assert (
        internal.item_brief.curriculum_scope.selected_unit_key
        == planned.item_brief.curriculum_selected_unit_key
    )
    validate_schema_message(
        load_knowledge_item_brief_v3_schema(),
        internal.item_brief.model_dump(mode="json"),
        "mock-exam-content-team-v3",
    )

    service = object.__new__(WorkflowCatalogService)
    prompt_context = service._prompt_context(
        SimpleNamespace(workflow_id="workflow_" + "1" * 32, runtime_context={}),
        SimpleNamespace(step_key="authoring"),
        internal,
        (),
        "packrel_" + "2" * 32,
    )
    reviewed_brief = json.loads(prompt_context["brief"]["reviewed_item_brief_json"])
    assert reviewed_brief["mock_exam_slot"] == planned.item_brief.mock_exam_slot.model_dump(
        mode="json"
    )
    provenance = service._brief_provenance_metadata(internal)
    assert provenance["mock_exam_slot"] == reviewed_brief["mock_exam_slot"]


def test_registration_slot_validation_is_fail_closed_but_does_not_bind_item_score() -> None:
    plan = _plan()
    text_slot = plan.workflow_calls[0].item_brief.mock_exam_slot
    text_content = _content(score_display="3")
    assert (
        validate_content_team_mock_exam_slot_output(
            slot=text_slot,
            content=text_content,
            authoring_difficulty="easy",
        )
        == "TEXT"
    )

    inquiry_slot = plan.workflow_calls[2].item_brief.mock_exam_slot
    with pytest.raises(MockExamProductionPlanError) as missing_inquiry:
        validate_content_team_mock_exam_slot_output(
            slot=inquiry_slot,
            content=text_content,
            authoring_difficulty="medium",
        )
    assert missing_inquiry.value.code == "PRODUCTION_AUTHORING_INQUIRY_MISMATCH"

    with pytest.raises(MockExamProductionPlanError) as wrong_difficulty:
        validate_content_team_mock_exam_slot_output(
            slot=text_slot,
            content=text_content,
            authoring_difficulty="hard",
        )
    assert wrong_difficulty.value.code == "PRODUCTION_AUTHORING_DIFFICULTY_MISMATCH"

    inquiry_content = _content(
        inquiry={
            "kind": "탐구",
            "goal": "변인 사이의 관계를 확인한다.",
            "procedure": "(가) 조건을 정한다.\n(나) 값을 측정한다.\n(다) 결과를 비교한다.",
            "result": "측정 결과를 표로 정리하였다.",
        }
    )
    assert (
        validate_content_team_mock_exam_slot_output(
            slot=inquiry_slot,
            content=inquiry_content,
            authoring_difficulty="medium",
        )
        == "INQUIRY"
    )

    with pytest.raises(MockExamProductionPlanError) as unexpected_inquiry:
        validate_content_team_mock_exam_slot_output(
            slot=text_slot,
            content=inquiry_content,
            authoring_difficulty="easy",
        )
    assert unexpected_inquiry.value.code == "PRODUCTION_AUTHORING_INQUIRY_MISMATCH"


def test_material_profile_has_one_public_domain_classifier() -> None:
    assert classify_content_team_mock_exam_material_profile(_content()) == "TEXT"
    assert (
        classify_content_team_mock_exam_material_profile(
            _content(labeled_blocks=({"kind": "DATA", "content": "측정값"},))
        )
        == "DATA"
    )
    table = {
        "kind": "TABLE",
        "label": "",
        "headers": ["구분", "값"],
        "rows": [["A", "1"]],
        "alignments": ["default", "default"],
    }
    assert classify_content_team_mock_exam_material_profile(_content(visuals=(table,))) == "TABLE"
    image = {"kind": "IMAGE", "label": ""}
    assert classify_content_team_mock_exam_material_profile(_content(visuals=(image,))) == "IMAGE"
    assert (
        classify_content_team_mock_exam_material_profile(
            _content(
                labeled_blocks=({"kind": "DATA", "content": "측정값"},),
                visuals=(image,),
            )
        )
        == "MIXED"
    )
    assert (
        classify_content_team_mock_exam_material_profile(
            _content(
                inquiry={
                    "kind": "탐구",
                    "goal": "변인 사이의 관계를 확인한다.",
                    "procedure": (
                        "(가) 조건을 정한다.\n(나) 값을 측정한다.\n(다) 결과를 비교한다."
                    ),
                    "result": "측정 결과를 표로 정리하였다.",
                }
            )
        )
        == "INQUIRY"
    )


def test_production_plan_replay_and_canonical_serialization_are_deterministic() -> None:
    first = _plan()
    second = _plan()
    assert first == second
    assert first.production_plan_id == second.production_plan_id
    assert first.plan_sha256 == second.plan_sha256
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )
    identity_body = first.model_dump(
        mode="json",
        exclude={"production_plan_id", "plan_sha256"},
    )
    assert content_sha256(identity_body) == first.plan_sha256
    restored = MockExamProductionPlanV1.model_validate_json(
        canonical_json_bytes(first.model_dump(mode="json"))
    )
    assert restored == first


def test_stale_hashes_are_explicitly_rejected() -> None:
    payload = _plan().model_dump(mode="json")
    payload["plan_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="production plan identity"):
        MockExamProductionPlanV1.model_validate(payload)

    payload = _plan().model_dump(mode="json")
    payload["workflow_calls"][0]["item_brief"]["original_request_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="original request hash"):
        MockExamProductionPlanV1.model_validate(payload)


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(member) for member in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_nested_keys(member) for member in value), set())
    return set()


def _content(
    *,
    score_display: str = "2.5",
    inquiry: dict[str, object] | None = None,
    labeled_blocks: tuple[dict[str, object], ...] = (),
    visuals: tuple[dict[str, object], ...] = (),
) -> AssessmentItemContentV2:
    visual_kinds = tuple(value["kind"] for value in visuals)
    visual_layout = {
        (): "NONE",
        ("IMAGE",): "IMAGE_ONLY",
        ("TABLE",): "TABLE_ONLY",
    }[visual_kinds]
    return AssessmentItemContentV2.model_validate(
        {
            "item_number": 11,
            "score_display": score_display,
            "stem": "제시된 정보를 해석하여 물음에 답하시오.",
            "bottom_stem": "옳은 것만을 <보기>에서 있는 대로 고른 것은?",
            "inquiry": inquiry,
            "labeled_blocks": labeled_blocks,
            "visuals": visuals,
            "visual_layout": "INQUIRY_BOX" if inquiry is not None else visual_layout,
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
                "correct_answer": "ㄱ. 제시된 정보와 일치한다.\nㄷ. 제시된 정보와 일치한다.",
                "wrong_answer": "ㄴ. 제시된 정보와 일치하지 않는다.",
            },
            "equation_sources": [],
        }
    )

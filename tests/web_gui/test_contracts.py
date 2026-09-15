from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eom_web_gui.contracts import (
    CurriculumEditorialOutline,
    ExplorerQuery,
    ItemPreview,
    ItemPreviewV2,
    PreviewChoice,
    PreviewLabeledTextBlock,
    PreviewParagraphBlock,
    PreviewParagraphBlockV3,
    PreviewTableBlockV3,
    RequestDraftInput,
    RequestDraftUpdate,
    StudioProblem,
    WorkflowApproval,
)
from eom_web_gui.request_drafts import DEMO_REQUEST, normalize_request, update_draft
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "web-gui"


def test_web_gui_schemas_are_valid_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert len(schemas) == 14
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_studio_problem_matches_web_schema_and_rejects_extra_data() -> None:
    value = StudioProblem(
        error_code="APPLICATION_API_UNAVAILABLE",
        message="request could not be completed",
        request_id="webreq_" + "a" * 24,
    )
    schema = json.loads((SCHEMA_ROOT / "studio-problem-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value.model_dump(mode="json") | {"detail": "x"})


def _curriculum_outline_projection() -> dict[str, object]:
    source = json.loads(
        (
            SCHEMA_ROOT.parents[1]
            / "content/curriculum/eom-integrated-science-editorial-outline-v1.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "schema_version": source["schema_version"],
        "outline_key": source["outline_key"],
        "outline_revision": source["outline_revision"],
        "subject_key": source["subject_key"],
        "subject_label": source["subject_label"],
        "graph_mapping_status": source["graph_mapping_status"],
        "graph_grounding_available": False,
        "supported_product_levels": source["supported_product_levels"],
        "unsupported_product_levels": source["unsupported_product_levels"],
        "units": [
            {key: unit[key] for key in ("key", "level", "code", "label", "parent_key", "ordinal")}
            for unit in source["units"]
        ],
    }


def test_curriculum_outline_projection_matches_web_schema() -> None:
    value = CurriculumEditorialOutline.model_validate(_curriculum_outline_projection())
    schema = json.loads(
        (SCHEMA_ROOT / "curriculum-editorial-outline-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


def test_item_preview_v2_metadata_projection_matches_web_schema() -> None:
    value = ItemPreviewV2(
        preview_state="METADATA_ONLY",
        workflow_id="workflow_test0001",
        item_id="item_test0001",
        item_revision_id="itemrev_test0001",
        revision_etag='"v1"',
        revision_state="APPROVED",
        content_pack_release_id="packrel_test0001",
    )
    schema = json.loads((SCHEMA_ROOT / "item-preview-v2.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


def test_item_preview_v2_fails_closed_on_dangling_answer() -> None:
    with pytest.raises(ValueError, match="answer must resolve"):
        ItemPreviewV2(
            preview_state="AVAILABLE",
            workflow_id="workflow_test0001",
            item_id="item_test0001",
            item_revision_id="itemrev_test0001",
            revision_etag='"v1"',
            revision_state="APPROVED",
            content_pack_release_id="packrel_test0001",
            locale="ko-KR",
            title="검증 문항",
            score_points=2,
            blocks=(
                PreviewParagraphBlock(
                    block_id="block_stem", purpose="stem", text="다음 질문에 답하시오."
                ),
            ),
            choices=(PreviewChoice(choice_id="choice_1", label="1", text="선택지"),),
            answer="2",
            explanation="검증 해설",
        )


def test_item_preview_v2_schema_rejects_content_in_metadata_only_projection() -> None:
    value = ItemPreviewV2(
        preview_state="METADATA_ONLY",
        workflow_id="workflow_test0001",
        item_id="item_test0001",
        item_revision_id="itemrev_test0001",
        revision_etag='"v1"',
        revision_state="APPROVED",
        content_pack_release_id="packrel_test0001",
    ).model_dump(mode="json")
    value["title"] = "허용되지 않는 본문"
    schema = json.loads((SCHEMA_ROOT / "item-preview-v2.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


def _item_preview_v3_table_only() -> ItemPreview:
    return ItemPreview(
        preview_state="AVAILABLE",
        workflow_id="workflow_test0001",
        item_id="item_test0001",
        item_revision_id="itemrev_test0001",
        revision_etag='"v1"',
        revision_state="APPROVED",
        content_pack_release_id="packrel_test0001",
        content_schema_ref="eom.assessment.item-content/3.0",
        content_profile="CONTENT_TEAM_V3",
        template_delivery_available=True,
        locale="ko-KR",
        item_number=1,
        score_display="2.5",
        blocks=(
            PreviewParagraphBlockV3(
                block_id="block_stem", purpose="stem", text="다음 자료를 보시오."
            ),
            PreviewLabeledTextBlock(
                block_id="block_labeled_0",
                kind="DATA",
                label="<자료>",
                text="측정 결과이다.",
            ),
            PreviewTableBlockV3(
                block_id="block_visual_0",
                purpose="data",
                headers=("구분", "값"),
                rows=(("A", "1"),),
            ),
            PreviewParagraphBlockV3(
                block_id="block_bottom_stem", purpose="prompt", text="옳은 것을 고르시오."
            ),
        ),
        choices=tuple(
            PreviewChoice(choice_id=f"choice_{index}", label=label, text=f"선택지 {index}")
            for index, label in enumerate(("①", "②", "③", "④", "⑤"), start=1)
        ),
        answer="①",
        explanation="정답 해설",
        concept_source="통합과학 개념",
        authoring_intent="자료 해석 평가",
    )


def test_item_preview_v3_table_only_projection_matches_web_schema() -> None:
    value = _item_preview_v3_table_only()
    schema = json.loads((SCHEMA_ROOT / "item-preview-v3.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


def test_item_preview_v3_schema_rejects_labeled_text_kind_label_drift() -> None:
    schema = json.loads((SCHEMA_ROOT / "item-preview-v3.schema.json").read_text(encoding="utf-8"))
    value = _item_preview_v3_table_only().model_dump(mode="json")
    value["blocks"][1]["label"] = "<조건>"

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("workflow_id", "unknown"),
        ("item_id", "item"),
        ("item_revision_id", "latest"),
        ("content_pack_release_id", "unknown"),
        ("revision_state", "DRAFT"),
    ),
)
def test_item_preview_v3_rejects_invented_or_mutable_provenance(field: str, invalid: str) -> None:
    schema = json.loads((SCHEMA_ROOT / "item-preview-v3.schema.json").read_text(encoding="utf-8"))
    value = _item_preview_v3_table_only().model_dump(mode="json")
    value[field] = invalid

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)
    with pytest.raises(ValueError):
        ItemPreview.model_validate(value)


def test_item_preview_v3_unsupported_variant_is_not_processing_state() -> None:
    value = ItemPreview(
        preview_state="UNSUPPORTED",
        unavailable_reason="UNSUPPORTED_CONTENT_SCHEMA",
        workflow_id="workflow_test0001",
        item_id="item_test0001",
        item_revision_id="itemrev_test0001",
        revision_etag='"v1"',
        revision_state="APPROVED",
        content_pack_release_id="packrel_test0001",
        content_schema_ref="eom.assessment.item-content/99.0",
    )
    schema = json.loads((SCHEMA_ROOT / "item-preview-v3.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


def test_curriculum_outline_ready_capability_pair_matches_web_schema() -> None:
    projection = _curriculum_outline_projection()
    projection["graph_mapping_status"] = "PUBLISHED_CURRICULUM_GRAPH_VERIFIED"
    projection["graph_grounding_available"] = True
    value = CurriculumEditorialOutline.model_validate(projection)
    schema = json.loads(
        (SCHEMA_ROOT / "curriculum-editorial-outline-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


@pytest.mark.parametrize("defect", ("parent", "code", "order"))
def test_curriculum_outline_projection_fails_closed_on_hierarchy_drift(defect: str) -> None:
    value = _curriculum_outline_projection()
    units = value["units"]
    assert isinstance(units, list)
    if defect == "parent":
        units[14]["parent_key"] = "eom.is.large.4"
    elif defect == "code":
        units[14]["code"] = "3-(7)"
    else:
        units[13], units[14] = units[14], units[13]
    with pytest.raises(ValueError):
        CurriculumEditorialOutline.model_validate(value)


def _request_draft_v4_validator() -> Draft202012Validator:
    schema = json.loads((SCHEMA_ROOT / "request-draft-v4.schema.json").read_text(encoding="utf-8"))
    material = json.loads(
        (
            SCHEMA_ROOT.parents[0] / "workflow/content-team-material-requirement-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(material["$id"], Resource.from_contents(material))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def test_request_draft_matches_canonical_schema() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    _request_draft_v4_validator().validate(draft.model_dump(mode="json"))


def test_request_draft_v1_contract_remains_immutable() -> None:
    payload = (SCHEMA_ROOT / "request-draft-v1.schema.json").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        "1fc60c96d6edb9946a6604fde7aff1e41548c9c2cb7135bb017eabcc11313f0d"
    )


def test_request_draft_v2_contract_remains_immutable() -> None:
    payload = (SCHEMA_ROOT / "request-draft-v2.schema.json").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        "03e36ad460fc5f56f64c10513f525af35d3d822940e8b542efb2b463579362d8"
    )


def test_request_draft_v3_contract_remains_immutable() -> None:
    payload = (SCHEMA_ROOT / "request-draft-v3.schema.json").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        "d5ab298e798d0148d958701f2574aeef62936dd5c92e28b044f6e4f87cdcc9bf"
    )


def test_grounded_request_draft_matches_v4_schema() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    grounded = update_draft(
        draft,
        RequestDraftUpdate(
            subject=draft.subject,
            topic=draft.topic,
            task_type=draft.task_type,
            difficulty=draft.difficulty,
            material_requirement=draft.material_requirement,
            quality_profile=draft.quality_profile,
            authoring_guidance=draft.authoring_guidance,
            knowledge_grounding=True,
            curriculum_selected_unit_key="eom.is.middle.3-2",
        ),
        now=draft.updated_at,
    )
    _request_draft_v4_validator().validate(grounded.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("knowledge_grounding", "curriculum_selected_unit_key"),
    ((True, None),),
)
def test_request_draft_v4_schema_rejects_incoherent_grounding_scope(
    knowledge_grounding: bool, curriculum_selected_unit_key: None
) -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    value = draft.model_dump(mode="json") | {
        "knowledge_grounding": knowledge_grounding,
        "curriculum_selected_unit_key": curriculum_selected_unit_key,
    }
    with pytest.raises(ValidationError):
        _request_draft_v4_validator().validate(value)


def test_schema_rejects_unknown_request_field() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    value = draft.model_dump(mode="json")
    value["raw_model_name"] = "forbidden"
    with pytest.raises(ValidationError):
        _request_draft_v4_validator().validate(value)


def test_explorer_query_rejects_raw_sql_and_arbitrary_entity() -> None:
    with pytest.raises(ValueError):
        ExplorerQuery.model_validate({"entity": "raw_sql", "sql": "SELECT 1"})


def test_workflow_approval_accepts_the_application_api_strong_etag_contract() -> None:
    value = {
        "etag": '"v4"',
        "idempotency_key": "studio:test-approval-0001",
        "reason": None,
    }
    assert WorkflowApproval.model_validate(value).etag == '"v4"'
    with pytest.raises(ValueError):
        WorkflowApproval.model_validate({**value, "etag": '"4"'})


def test_scientific_studio_design_tokens_are_role_based() -> None:
    css = Path("apps/web_gui/eom_web_gui/static/styles.css").read_text(encoding="utf-8")
    for token in (
        "--eom-background",
        "--eom-surface",
        "--eom-document",
        "--eom-sidebar",
        "--eom-text",
        "--eom-text-muted",
        "--eom-primary",
        "--eom-teal",
        "--eom-warning",
        "--eom-danger",
        "--eom-border",
        "--eom-focus",
    ):
        assert token in css
    assert "border-radius: 16px" not in css
    assert "border-radius: 24px" not in css

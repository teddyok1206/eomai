from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eom_web_gui.contracts import (
    CurriculumEditorialOutline,
    ExplorerQuery,
    RequestDraftInput,
    RequestDraftUpdate,
    WorkflowApproval,
)
from eom_web_gui.request_drafts import DEMO_REQUEST, normalize_request, update_draft
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "web-gui"


def test_web_gui_schemas_are_valid_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert len(schemas) == 10
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


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


def test_request_draft_matches_canonical_schema() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    schema = json.loads((SCHEMA_ROOT / "request-draft-v3.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        draft.model_dump(mode="json")
    )


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


def test_grounded_request_draft_matches_v3_schema() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    grounded = update_draft(
        draft,
        RequestDraftUpdate(
            subject=draft.subject,
            topic=draft.topic,
            task_type=draft.task_type,
            difficulty=draft.difficulty,
            quality_profile=draft.quality_profile,
            authoring_guidance=draft.authoring_guidance,
            knowledge_grounding=True,
            curriculum_selected_unit_key="eom.is.middle.3-2",
        ),
        now=draft.updated_at,
    )
    schema = json.loads((SCHEMA_ROOT / "request-draft-v3.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        grounded.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    ("knowledge_grounding", "curriculum_selected_unit_key"),
    ((True, None),),
)
def test_request_draft_v3_schema_rejects_incoherent_grounding_scope(
    knowledge_grounding: bool, curriculum_selected_unit_key: None
) -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    value = draft.model_dump(mode="json") | {
        "knowledge_grounding": knowledge_grounding,
        "curriculum_selected_unit_key": curriculum_selected_unit_key,
    }
    schema = json.loads((SCHEMA_ROOT / "request-draft-v3.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


def test_schema_rejects_unknown_request_field() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    value = draft.model_dump(mode="json")
    value["raw_model_name"] = "forbidden"
    schema = json.loads((SCHEMA_ROOT / "request-draft-v3.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


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

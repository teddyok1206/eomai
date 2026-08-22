from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_web_gui.contracts import ExplorerQuery, RequestDraftInput, WorkflowApproval
from eom_web_gui.request_drafts import DEMO_REQUEST, normalize_request
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "web-gui"


def test_web_gui_schemas_are_valid_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert len(schemas) == 5
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_request_draft_matches_canonical_schema() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    schema = json.loads((SCHEMA_ROOT / "request-draft-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        draft.model_dump(mode="json")
    )


def test_schema_rejects_unknown_request_field() -> None:
    draft = normalize_request(RequestDraftInput(original_request_text=DEMO_REQUEST), token="0" * 32)
    value = draft.model_dump(mode="json")
    value["raw_model_name"] = "forbidden"
    schema = json.loads((SCHEMA_ROOT / "request-draft-v1.schema.json").read_text(encoding="utf-8"))
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

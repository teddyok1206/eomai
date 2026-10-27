"""The new support role protocol is schema-first and distinct from past-exam extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_catalog_contracts.validation import catalog_schema_registry
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from tests.unit.test_external_item_learning_result_contract import _result
from tests.unit.test_external_item_learning_work_contract import _work

ROOT = Path(__file__).resolve().parents[2]
ROLE_PATH = "schemas/workflow/roles"
RESOURCE_PATH = "packages/workflow/eom_workflow/resources/roles"


def _schema(kind: str) -> dict[str, object]:
    filename = f"external-item-learning-{kind}-v1.schema.json"
    canonical = (ROOT / ROLE_PATH / filename).read_bytes()
    assert canonical == (ROOT / RESOURCE_PATH / filename).read_bytes()
    value = json.loads(canonical)
    Draft202012Validator.check_schema(value)
    return value


def _validate(kind: str, value: object) -> None:
    Draft202012Validator(
        _schema(kind), registry=catalog_schema_registry(), format_checker=FormatChecker()
    ).validate(value)


def _artifact() -> dict[str, str]:
    return {
        "logical_artifact_id": "artifact_" + "a" * 32,
        "revision_id": "rev_" + "b" * 32,
        "file_name": "result.json",
        "media_type": "application/json",
    }


def _input() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.33.0",
        "job_id": "job_" + "c" * 32,
        "workflow_id": "workflow_" + "d" * 32,
        "step_run_id": "steprun_" + "e" * 32,
        "attempt": 1,
        "role": "support",
        "request": {
            "request_name": "EXTERNAL_ITEM_LEARNING_REQUEST",
            "work_input": _work(),
        },
        "upstream_artifacts": [],
        "artifact": _artifact(),
    }


def test_creative_role_input_and_result_schemas_accept_exact_messages() -> None:
    _validate("input", _input())
    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.33.0",
        "job_id": "job_" + "c" * 32,
        "workflow_id": "workflow_" + "d" * 32,
        "step_run_id": "steprun_" + "e" * 32,
        "status": "ok",
        "artifact": _artifact(),
        "completed_at": "2026-10-27T10:00:00Z",
        "role": "support",
        "output": {"learning_result": _result()},
    }
    _validate("result", result)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("protocol_version", "workflow-role/1.14.0"),
        ("role", "authoring"),
        ("upstream_artifacts", [{"unauthorized": True}]),
    ],
)
def test_creative_role_input_rejects_cross_workflow_shape(field: str, replacement: object) -> None:
    value = _input()
    value[field] = replacement
    with pytest.raises(ValidationError):
        _validate("input", value)


def test_creative_role_input_rejects_legacy_extraction_request() -> None:
    value = _input()
    value["request"] = {
        "request_name": "LEGACY_ITEM_EXTRACTION_REQUEST",
        "extraction_request": {},
    }
    with pytest.raises(ValidationError):
        _validate("input", value)

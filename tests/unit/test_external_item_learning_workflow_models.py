"""Creative workflow values cannot be interpreted as past-exam extraction."""

from __future__ import annotations

import pytest
from eom_workflow.models import (
    ExternalItemLearningRoleResult,
    ExternalItemLearningWorkerRequest,
    RoleWorkerInput,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    load_role_input_schema,
    load_role_result_schema,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_external_item_learning_result_contract import _result
from tests.unit.test_external_item_learning_role_schemas import _input
from tests.unit.test_external_item_learning_work_contract import _work


def _references(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            item
            for key, raw in value.items()
            for item in ((raw,) if key == "$ref" and isinstance(raw, str) else _references(raw))
        )
    if isinstance(value, list):
        return tuple(item for raw in value for item in _references(raw))
    return ()


def test_creative_workflow_request_and_role_input_are_exact() -> None:
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="external-item-learning",
        external_item_learning_work=_work(),
    )
    worker_request = request.worker_request()
    assert isinstance(worker_request, ExternalItemLearningWorkerRequest)
    assert worker_request.work_input.source.external_number == "12345"
    parsed = RoleWorkerInput.model_validate(_input())
    assert isinstance(parsed.request, ExternalItemLearningWorkerRequest)
    admitted = validate_role_input(_input(), "support", "workflow-role/1.33.0")
    assert isinstance(admitted.request, ExternalItemLearningWorkerRequest)
    assert all(
        reference.startswith("#/$defs/")
        for reference in _references(load_role_input_schema("support", "workflow-role/1.33.0"))
    )


def test_creative_request_rejects_missing_work_and_wrong_workflow_identity() -> None:
    with pytest.raises(ValidationError, match="requires only its pinned work input"):
        WorkflowRequest(
            request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
            image_mode="skip",
            execution_preset_key="external-item-learning",
        )
    with pytest.raises(ValidationError, match="requires only its pinned work input"):
        WorkflowRequest(
            request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
            image_mode="required",
            execution_preset_key="external-item-learning",
            external_item_learning_work=_work(),
        )
    with pytest.raises(ValidationError, match="only creative learning"):
        WorkflowRequest(
            request_name="PLACEHOLDER_REQUEST",
            image_mode="skip",
            external_item_learning_work=_work(),
        )


def test_creative_role_result_is_separate_typed_proposal() -> None:
    role_result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.33.0",
        "job_id": "job_" + "c" * 32,
        "workflow_id": "workflow_" + "d" * 32,
        "step_run_id": "steprun_" + "e" * 32,
        "status": "ok",
        "artifact": _input()["artifact"],
        "completed_at": "2026-10-27T10:00:00Z",
        "role": "support",
        "output": {"learning_result": _result()},
    }
    parsed = ExternalItemLearningRoleResult.model_validate(role_result)
    assert parsed.output.learning_result.status == "PROPOSED"
    assert parsed.output.learning_result.proposal is not None
    admitted = validate_role_result(role_result, "support", "external-item-learning-result@1.0")
    assert isinstance(admitted, ExternalItemLearningRoleResult)
    assert all(
        reference.startswith("#/$defs/")
        for reference in _references(load_role_result_schema("external-item-learning-result@1.0"))
    )


def test_creative_generation_schema_binds_pinned_source_and_page_count() -> None:
    projected = load_codex_result_schema("external-item-learning-result@1.0")
    Draft202012Validator.check_schema(projected)
    worker_input = RoleWorkerInput.model_validate(_input())
    constrained = constrained_result_schema("external-item-learning-result@1.0", worker_input)
    definitions = constrained["$defs"]
    result = definitions["ExternalItemLearningResult"]
    fields = result["properties"]
    work = worker_input.request.work_input
    assert "result_sha256" not in fields
    assert fields["input_sha256"]["const"] == work.source.input_sha256
    assert fields["source_id"]["const"] == work.source.source_id
    assert fields["source_revision_id"]["const"] == work.source.source_revision_id
    assert fields["external_number"]["const"] == work.source.external_number
    assert definitions["ExternalItemLearningResult_region"]["properties"]["physical_page"][
        "maximum"
    ] == len(work.page_set.pages)


def test_creative_result_hash_is_derived_only_if_omitted() -> None:
    role_result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.33.0",
        "job_id": "job_" + "c" * 32,
        "workflow_id": "workflow_" + "d" * 32,
        "step_run_id": "steprun_" + "e" * 32,
        "status": "ok",
        "artifact": _input()["artifact"],
        "completed_at": "2026-10-27T10:00:00Z",
        "role": "support",
        "output": {"learning_result": _result()},
    }
    learning_result = role_result["output"]["learning_result"]
    original_hash = learning_result.pop("result_sha256")
    admitted = validate_role_result(role_result, "support", "external-item-learning-result@1.0")
    assert admitted.output.learning_result.result_sha256 == original_hash
    learning_result["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValidationError, ValueError), match="hash differs"):
        validate_role_result(role_result, "support", "external-item-learning-result@1.0")

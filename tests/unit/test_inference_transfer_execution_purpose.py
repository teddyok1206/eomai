"""Source-only dedicated purpose invariants; no worker, DB, runtime or model calls."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_workflow.admission import workflow_admission
from eom_workflow.compiler import compile_definition
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.inference_transfer_control import (
    ResolvedExecutionPlanV21,
    validate_inference_transfer_plan_context,
    validate_inference_transfer_rubric_instruction,
)
from eom_workflow.models import AgentStep, WorkflowRequest
from eom_workflow.schemas import result_schema_protocol
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.state_machine import STAGE_TRANSITIONS, WorkflowStage
from jsonschema import ValidationError as SchemaValidationError
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, Table

from tests.unit.inference_transfer_execution_fixtures import transfer_instruction, transfer_plan
from tests.unit.inference_transfer_fixtures import profile, request, sha


def _assert_context(plan: ResolvedExecutionPlanV21) -> None:
    validate_inference_transfer_plan_context(
        plan,
        comparison=request(),
        left_profile=profile("a"),
        right_profile=profile("b"),
        workflow_id="workflow_" + "1" * 32,
        core_prompt_sha256=sha("5"),
        prompt_sha256=sha("6"),
    )


def test_v21_schema_model_and_exact_context_round_trip_without_fake_pack() -> None:
    plan = transfer_plan()
    document = plan.model_dump(mode="json")
    validate_control_contract("resolved-execution-plan-v21", document)
    assert ResolvedExecutionPlanV21.model_validate(document) == plan
    assert "content_pack_release_id" not in document
    assert "requester_permissions" not in document
    assert plan.steps[0].model == "gpt-6.1-sol"
    assert plan.core_prompt_sha256 != plan.prompt_sha256
    _assert_context(plan)
    validate_inference_transfer_rubric_instruction(plan, transfer_instruction())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_definition_key", "customer-support"),
        ("workflow_definition_version", "1.1.0"),
        ("schema_version", "resolved-execution-plan/1.0"),
        ("resolver_version", "1.0.0"),
        ("workload_class", "LOCAL_GPU"),
    ],
)
def test_v21_rejects_unsupported_semantics_in_schema_and_model(field: str, value: str) -> None:
    document = transfer_plan().model_dump(mode="json")
    document[field] = value
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    with pytest.raises(SchemaValidationError):
        validate_control_contract("resolved-execution-plan-v21", document)
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV21.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "authoring"),
        ("step_key", "diagnose"),
        ("worker_pool_key", "default"),
        ("network", "enabled"),
        ("sandbox", "workspace-write"),
        ("timeout_seconds", 901),
        ("general_knowledge_mode", "ALLOWED_WITH_PROVENANCE"),
    ],
)
def test_v21_rejects_unbounded_or_unrelated_step(field: str, value: str | int) -> None:
    document = transfer_plan().model_dump(mode="json")
    document["steps"][0][field] = value
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    with pytest.raises(SchemaValidationError):
        validate_control_contract("resolved-execution-plan-v21", document)
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV21.model_validate(document)


def test_v21_hash_tampering_and_copied_frozen_value_cannot_bypass_validation() -> None:
    plan = transfer_plan()
    copied = plan.model_copy(update={"access_policy_sha256": sha("f")})
    with pytest.raises(ValidationError, match="plan hash differs"):
        _assert_context(copied)
    document = plan.model_dump(mode="json")
    document["plan_sha256"] = sha("f")
    with pytest.raises(ValidationError, match="plan hash differs"):
        ResolvedExecutionPlanV21.model_validate(document)


@pytest.mark.parametrize(
    "field", ["comparison_request_sha256", "core_prompt_sha256", "prompt_sha256"]
)
def test_v21_context_rejects_rehashed_foreign_request_or_prompt(field: str) -> None:
    document = transfer_plan().model_dump(mode="json")
    document[field] = sha("f")
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanV21.model_validate(document)
    with pytest.raises(ValueError, match="context differs"):
        _assert_context(plan)


def test_v21_context_rejects_same_graph_revision_with_foreign_manifest_hash() -> None:
    document = transfer_plan().model_dump(mode="json")
    document["graph_snapshot"]["manifest_sha256"] = sha("f")
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanV21.model_validate(document)
    with pytest.raises(ValueError, match="context differs"):
        _assert_context(plan)


def test_v21_requires_distinct_profile_pins_and_matching_rubric_artifact() -> None:
    document = transfer_plan().model_dump(mode="json")
    document["right_profile"] = document["left_profile"]
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="profiles must be distinct"):
        ResolvedExecutionPlanV21.model_validate(document)
    document = transfer_plan().model_dump(mode="json")
    document["rubric_artifact"]["sha256"] = sha("f")
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="rubric Artifact pin differs"):
        ResolvedExecutionPlanV21.model_validate(document)


def test_v21_rubric_must_be_exact_released_role_component() -> None:
    plan = transfer_plan()
    instruction = transfer_instruction()
    with pytest.raises(ValueError, match="instruction bundle differs"):
        validate_inference_transfer_rubric_instruction(
            plan, instruction.model_copy(update={"state": "DRAFT"})
        )
    document = instruction.model_dump(mode="json")
    document["components"][1]["layer"] = "PLATFORM"
    document["content_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "content_sha256"}
    )
    changed = type(instruction).model_validate(document)
    with pytest.raises(ValueError, match="rubric is absent"):
        validate_inference_transfer_rubric_instruction(plan, changed)


def test_dedicated_definition_admission_is_exact_and_workflow_wrapper_still_unsupported() -> None:
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1.yaml"), {"support"}
    )
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1
    step = compiled.steps_by_key["compare_pair"]
    assert isinstance(step, AgentStep)
    assert step.worker_role == "support"
    assert result_schema_protocol(step.result_schema) == "workflow-role/1.29.0"
    admission = workflow_admission("item-inference-transfer-comparison", "1.0.0")
    assert admission is not None
    assert admission.role_protocol_version == "workflow-role/1.29.0"
    successor = workflow_admission("item-inference-transfer-comparison", "1.1.0")
    assert successor is not None
    assert successor.role_protocol_version == "workflow-role/1.30.0"
    assert workflow_admission("item-inference-transfer-comparison", "1.2.0") is None
    with pytest.raises(ValidationError):
        WorkflowRequest.model_validate({"request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"})


def test_inference_transfer_stage_is_dedicated_and_has_only_terminal_targets() -> None:
    assert STAGE_TRANSITIONS[WorkflowStage.INFERENCE_TRANSFER] == frozenset(
        {WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    )
    table = WorkflowInstanceRecord.__table__
    assert isinstance(table, Table)
    stage_constraint = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "ck_workflow_instances_stage"
    )
    assert isinstance(stage_constraint, CheckConstraint)
    assert "'INFERENCE_TRANSFER'" in str(stage_constraint.sqltext)


def test_stage_migration_changes_only_existing_check_and_downgrade_never_rewrites_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path("migrations/versions/20261010_0051_inference_transfer_stage.py")
    spec = importlib.util.spec_from_file_location("inference_transfer_stage_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "20261009_0050"
    owner = Mock()
    monkeypatch.setattr(module, "op", owner)
    module.upgrade()
    assert owner.method_calls[0][0] == "drop_constraint"
    assert owner.method_calls[1][0] == "create_check_constraint"
    assert "'INFERENCE_TRANSFER'" in owner.method_calls[1].args[2]
    owner.reset_mock()
    module.downgrade()
    assert [call[0] for call in owner.method_calls] == [
        "drop_constraint",
        "create_check_constraint",
    ]
    assert "INFERENCE_TRANSFER" not in owner.method_calls[1].args[2]

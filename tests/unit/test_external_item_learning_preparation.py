"""Preparation stays before the model boundary; persistence ports are synthetic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ResolvedExecutionPlanV27
from eom_workflow_runner import external_item_learning_preparation as preparation
from eom_workflow_runner.errors import WorkflowError
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_workflow_admission import OPERATOR, _definition


def _case(monkeypatch):
    definition = _definition()
    raw = _plan()
    raw["workflow_definition_sha256"] = definition.definition_hash
    raw["plan_sha256"] = content_sha256(
        {key: value for key, value in raw.items() if key != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanV27.model_validate(raw)
    workflow = SimpleNamespace(
        workflow_id=plan.workflow_id,
        state="REQUESTED",
        stage="KNOWLEDGE_ANALYSIS",
        current_step_key="extract",
        role_schema_version="workflow-role/1.33.0",
        runtime_context={"artifact_pointers": []},
    )
    step = SimpleNamespace(
        step_run_id="steprun_" + "9" * 32,
        step_key="extract",
        attempt=1,
        state="READY",
        step_type="agent",
        worker_role="support",
        result_schema="external-item-learning-result@1.0",
        platform_job_id=None,
        input_pointer_manifest={"upstream_artifacts": []},
        output_pointer_manifest=None,
        started_at=None,
        finished_at=None,
        error_code=None,
        superseded_by_step_run_id=None,
    )
    session = Mock(spec=Session)
    session.in_transaction.return_value = True
    session.scalar.side_effect = [workflow, None]
    session.scalars.return_value = ()
    owner = Mock()
    owner.reauthorize.return_value = plan.work_input.source
    page_read = Mock()
    create = Mock(return_value=(workflow, True))
    resolve = Mock(return_value=plan)
    new_step = Mock(return_value=step)
    event = Mock()
    monkeypatch.setattr(preparation, "read_external_item_learning_page_artifact", page_read)
    monkeypatch.setattr(preparation, "create_workflow_instance", create)
    monkeypatch.setattr(preparation, "resolve_external_item_learning_plan", resolve)
    monkeypatch.setattr(preparation, "create_step_run", new_step)
    monkeypatch.setattr(preparation, "record_workflow_event", event)
    args = dict(
        definition=definition,
        work=plan.work_input,
        operator_id=OPERATOR,
        idempotency_key="synthetic-creative-prepare",
        source_authorizer=owner,
        page_publisher=Mock(),
    )
    return SimpleNamespace(**locals())


def test_prepare_saves_exact_plan_and_ready_role_without_start(monkeypatch):
    value = _case(monkeypatch)
    prepared = preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    assert prepared.workflow_created and prepared.step_created
    assert prepared.selection.workflow_id == value.workflow.workflow_id
    assert prepared.selection.step_run_id == value.step.step_run_id
    assert prepared.selection.work_input_sha256 == value.plan.work_input.request_sha256
    assert value.workflow.state == "REQUESTED"
    assert value.step.state == "READY" and value.step.platform_job_id is None
    assert value.new_step.call_args.kwargs["max_attempts"] == 1
    assert value.event.call_args.args[2] == "STEP_READY"
    assert value.event.call_args.kwargs["command_id"] is None
    value.session.commit.assert_not_called()
    value.session.rollback.assert_not_called()
    assert value.owner.reauthorize.call_count == 2


def test_prepare_replay_rechecks_source_but_does_not_add_step_or_event(monkeypatch):
    value = _case(monkeypatch)
    first = preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.session.scalar.side_effect = [value.workflow, None]
    value.session.scalars.return_value = (value.step,)
    value.create.return_value = (value.workflow, False)
    second = preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    assert first.selection == second.selection
    assert not second.workflow_created and not second.step_created
    assert value.new_step.call_count == value.event.call_count == 1
    assert value.page_read.call_count == 2
    assert value.owner.reauthorize.call_count == 4


@pytest.mark.parametrize("fault", ["state", "command", "step", "attempt", "job", "extra"])
def test_prepare_cannot_reset_or_reinterpret_existing_history(monkeypatch, fault):
    value = _case(monkeypatch)
    value.session.scalars.return_value = (value.step,)
    if fault == "state":
        value.workflow.state = "FAILED"
    elif fault == "command":
        value.session.scalar.side_effect = [value.workflow, "command_already_exists"]
    elif fault == "step":
        value.step.state = "FAILED"
    elif fault == "attempt":
        value.step.attempt = 2
    elif fault == "job":
        value.step.platform_job_id = "job_" + "8" * 32
    else:
        value.session.scalars.return_value = (value.step, value.step)
    with pytest.raises((WorkflowError, ValueError)):
        preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.session.rollback.assert_called_once()
    value.new_step.assert_not_called()
    value.event.assert_not_called()


@pytest.mark.parametrize("late", [False, True])
def test_revoked_source_rolls_back_and_is_not_persisted_as_success(monkeypatch, late):
    value = _case(monkeypatch)
    error = ValueError("synthetic source revocation")
    value.owner.reauthorize.side_effect = [value.plan.work_input.source, error] if late else error
    with pytest.raises(WorkflowError):
        preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.session.rollback.assert_called_once()
    if not late:
        value.page_read.assert_not_called()
        value.create.assert_not_called()


def test_unapproved_page_artifact_is_rejected_before_workflow_creation(monkeypatch):
    value = _case(monkeypatch)
    value.page_read.side_effect = ControlPlaneError("CONTROL_POINTER_INVALID", "synthetic")
    with pytest.raises(ControlPlaneError):
        preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.create.assert_not_called()
    value.session.rollback.assert_called_once()


def test_preparation_requires_caller_root_transaction(monkeypatch):
    value = _case(monkeypatch)
    value.session.in_transaction.return_value = False
    with pytest.raises(ValueError, match="caller-owned root"):
        preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.owner.reauthorize.assert_not_called()
    value.page_read.assert_not_called()


def test_existing_plan_pointer_cannot_be_silently_replaced(monkeypatch):
    value = _case(monkeypatch)
    value.workflow.runtime_context["execution_plan"] = {"plan_id": "different"}
    with pytest.raises(ValueError, match="plan pointer differs"):
        preparation.prepare_external_item_learning_workflow(value.session, **value.args)
    value.new_step.assert_not_called()
    value.session.rollback.assert_called_once()

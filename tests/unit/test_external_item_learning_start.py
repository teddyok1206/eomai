"""Starting a prepared creative role preserves source, ownership and exact replay."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_identifiers import content_sha256
from eom_workflow.control_plane import ResolvedExecutionPlanV27
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner import external_item_learning_start as start
from eom_workflow_runner.errors import WorkflowError
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_workflow_admission import OPERATOR, _definition


def _case(monkeypatch):
    definition = _definition()
    raw = _plan()
    raw["workflow_definition_sha256"] = definition.definition_hash
    raw["plan_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "plan_sha256"})
    plan = ResolvedExecutionPlanV27.model_validate(raw)
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="external-item-learning",
        external_item_learning_work=plan.work_input,
    )
    workflow = SimpleNamespace(
        workflow_id=plan.workflow_id,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        state="REQUESTED",
        stage="KNOWLEDGE_ANALYSIS",
        current_step_key="extract",
        role_schema_version="workflow-role/1.33.0",
        created_actor_type="human",
        created_actor_id=OPERATOR,
        initial_request=request.model_dump(mode="json", exclude_none=True),
        request_payload=request.model_dump(mode="json", exclude_none=True),
        runtime_context={
            "execution_plan": {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "preset_id": plan.preset_id,
                "preset_revision_id": plan.preset_revision_id,
            }
        },
    )
    step = SimpleNamespace(
        workflow_id=plan.workflow_id,
        step_key="extract",
        step_type="agent",
        worker_role="support",
        result_schema="external-item-learning-result@1.0",
        attempt=1,
        state="READY",
        platform_job_id=None,
        input_pointer_manifest={"upstream_artifacts": []},
        output_pointer_manifest=None,
        started_at=None,
        finished_at=None,
        error_code=None,
        superseded_by_step_run_id=None,
    )
    selection = ExternalItemLearningRoleSelection(
        workflow_id=workflow.workflow_id,
        step_run_id="steprun_" + "9" * 32,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        work_input_sha256=plan.work_input.request_sha256,
    )
    session = Mock(spec=Session)
    session.in_transaction.return_value = True
    session.scalar.return_value = workflow
    session.get.side_effect = [definition, step, object()]
    session.scalars.return_value = ()
    owner = Mock()
    owner.reauthorize.return_value = plan.work_input.source
    command = SimpleNamespace(command_id="wfcmd_" + "8" * 32, state="PENDING")
    enqueue = Mock(return_value=(command, True))
    page = Mock()
    monkeypatch.setattr(start, "enqueue_command", enqueue)
    monkeypatch.setattr(start, "read_external_item_learning_page_artifact", page)
    monkeypatch.setattr(
        start, "validate_external_item_learning_execution_plan", lambda *_a, **_k: plan
    )
    args = dict(
        selection=selection,
        operator_id=OPERATOR,
        source_authorizer=owner,
        page_publisher=Mock(),
    )
    return SimpleNamespace(**locals())


def test_start_uses_existing_queue_without_creating_workflow_step_or_plan(monkeypatch):
    value = _case(monkeypatch)
    result = start.start_prepared_external_item_learning(value.session, **value.args)
    assert result.command_created and result.command_state == "PENDING"
    assert result.selection == value.selection
    assert value.owner.reauthorize.call_count == 2
    assert value.page.call_count == 1
    arguments = value.enqueue.call_args.kwargs
    assert arguments["actor_id"] == OPERATOR and arguments["payload"] == {}
    assert arguments["command_type"] == start.CommandType.START_WORKFLOW
    assert arguments["idempotency_key"].startswith("creative-start:")
    value.session.add.assert_not_called()
    value.session.commit.assert_not_called()
    value.session.rollback.assert_not_called()


@pytest.mark.parametrize("field", ["owner", "state", "definition", "role", "work", "plan", "step"])
def test_start_rejects_wrong_owner_or_pins_before_enqueue(monkeypatch, field):
    value = _case(monkeypatch)
    if field == "owner":
        value.args["operator_id"] = "operator_" + "f" * 32
    elif field == "state":
        value.workflow.state = "FAILED"
    elif field == "definition":
        value.definition.active = False
    elif field == "role":
        value.workflow.role_schema_version = "workflow-role/1.32.0"
    elif field == "work":
        value.args["selection"] = value.selection.model_copy(
            update={"work_input_sha256": "sha256:" + "0" * 64}
        )
    elif field == "plan":
        value.workflow.runtime_context["execution_plan"]["plan_sha256"] = "sha256:" + "0" * 64
    else:
        value.step.workflow_id = "workflow_" + "0" * 32
    with pytest.raises((ValueError, WorkflowError)):
        start.start_prepared_external_item_learning(value.session, **value.args)
    value.enqueue.assert_not_called()


@pytest.mark.parametrize("late", [False, True])
def test_start_source_reauthorization_denial_leaves_commit_to_caller(monkeypatch, late):
    value = _case(monkeypatch)
    value.owner.reauthorize.side_effect = (
        [value.plan.work_input.source, ValueError("revoked")] if late else ValueError("revoked")
    )
    with pytest.raises(WorkflowError, match="creative learning source authorization failed"):
        start.start_prepared_external_item_learning(value.session, **value.args)
    assert value.enqueue.call_count == int(late)
    value.session.commit.assert_not_called()


@pytest.mark.parametrize("workflow_state", ["REQUESTED", "RUNNING", "COMPLETED"])
def test_exact_start_replay_preserves_original_command_state(monkeypatch, workflow_state):
    value = _case(monkeypatch)
    start.start_prepared_external_item_learning(value.session, **value.args)
    key = value.enqueue.call_args.kwargs["idempotency_key"]
    value.session.get.side_effect = [value.definition, value.step, object()]
    value.workflow.state = workflow_state
    existing = SimpleNamespace(
        idempotency_key=key,
        command_type="START_WORKFLOW",
        actor_type="human",
        actor_id=OPERATOR,
        source="creative_item_learning",
        payload={},
    )
    value.session.scalars.return_value = (existing,)
    value.command.state = "SUCCEEDED" if workflow_state == "COMPLETED" else "PROCESSING"
    value.enqueue.return_value = value.command, False
    replay = start.start_prepared_external_item_learning(value.session, **value.args)
    assert not replay.command_created
    assert replay.command_id == value.command.command_id
    assert replay.command_state == value.command.state


def test_start_cannot_adopt_another_start_or_reset_a_used_role(monkeypatch):
    value = _case(monkeypatch)
    value.step.platform_job_id = "job_" + "1" * 32
    with pytest.raises(ValueError, match="untouched"):
        start.start_prepared_external_item_learning(value.session, **value.args)
    value.enqueue.assert_not_called()


def test_start_requires_caller_owned_transaction(monkeypatch):
    value = _case(monkeypatch)
    value.session.in_transaction.return_value = False
    with pytest.raises(ValueError, match="caller-owned"):
        start.start_prepared_external_item_learning(value.session, **value.args)
    value.session.scalar.assert_not_called()

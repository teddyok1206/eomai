"""Synthetic Session/Workflow terminal shapes; not DB/claim/source authorization proof."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow_runner import native_step_completion as terminal_module
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy.orm import Session

from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def private_terminal(completed, monkeypatch):
    value = completed
    origin = value.expected["origin"]
    context = build_private_chat_query_submission_context(value.request, origin)
    workflow = WorkflowInstanceRecord(
        workflow_id=value.output.workflow_id,
        state="RUNNING",
        stage="LOCAL_EMBEDDING",
        current_step_key="complete",
        initial_request=value.request.model_dump(mode="json"),
        runtime_context=context.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=origin.actor_id,
        definition_key=value.request.workflow_definition_key,
        definition_version=value.request.workflow_definition_version,
        definition_hash=value.request.workflow_definition_sha256,
        lock_version=1,
    )
    step = WorkflowStepRunRecord(
        workflow_id=workflow.workflow_id,
        step_run_id=value.output.step_run_id,
        step_key="encode_private_chat_query",
        attempt=1,
        step_type="application",
        state="SUCCEEDED",
        worker_role=None,
        result_schema="embedding-private-chat-query-result@1.0",
        platform_job_id=value.output.receipt_owner_job_id,
        input_pointer_manifest={"workflow_request_sha256": value.request.request_sha256},
        output_pointer_manifest=value.output.model_dump(mode="json"),
    )
    session = Mock(spec=Session)
    session.get.return_value = workflow
    session.execute.return_value.scalar_one_or_none.return_value = workflow
    case = SimpleNamespace(
        workflow=workflow,
        step=step,
        output=value.output,
        session=session,
        terminal=None,
        validate=Mock(return_value=value.output),
    )

    def scalar(statement, **_kwargs):
        entity = statement.column_descriptions[0]["entity"]
        return case.terminal if entity is WorkflowStepRunRecord else 1

    def create(_session, **kwargs):
        assert case.terminal is None
        assert kwargs.pop("max_attempts") == 1
        case.terminal = WorkflowStepRunRecord(
            **kwargs, state="READY", attempt=1, output_pointer_manifest=None, platform_job_id=None
        )
        return case.terminal

    session.scalar.side_effect = scalar
    monkeypatch.setattr(terminal_module, "native_application_step", lambda *_args: step)
    monkeypatch.setattr(terminal_module, "create_step_run", create)

    @contextmanager
    def root():
        yield session

    def complete():
        terminal_module.complete_native_terminal(
            workflow_id=workflow.workflow_id,
            step_key="encode_private_chat_query",
            lease=CommandLeaseIdentity("wfcmd_" + "a" * 32, "synthetic", "lease", 1),
            validate_completion=case.validate,
            fenced_transaction=root,
            actor_type="human",
            actor_id=origin.actor_id,
        )

    case.complete = complete
    return case


def test_private_terminal_preserves_exact_original_context_and_revalidates_replay(private_terminal):
    value = private_terminal
    before = canonical_json_bytes(value.workflow.runtime_context)
    value.complete()
    assert value.workflow.state == "COMPLETED" and value.workflow.stage == "COMPLETED"
    assert value.terminal.state == "SUCCEEDED" and value.terminal.input_pointer_manifest == {}
    assert value.step.output_pointer_manifest == value.output.model_dump(mode="json")
    assert canonical_json_bytes(value.workflow.runtime_context) == before
    assert "final_pointer_manifest" not in value.workflow.runtime_context
    events = value.session.add.call_count
    value.complete()
    assert value.validate.call_count == 2 and value.session.add.call_count == events
    assert canonical_json_bytes(value.workflow.runtime_context) == before


@pytest.mark.parametrize("fault", ["extra_final", "missing_origin", "actor", "request"])
def test_private_terminal_refuses_bad_original_context_before_transition(private_terminal, fault):
    value = private_terminal
    if fault == "extra_final":
        value.workflow.runtime_context = value.workflow.runtime_context | {
            "final_pointer_manifest": {}
        }
    elif fault == "missing_origin":
        value.workflow.runtime_context = {}
    elif fault == "actor":
        value.workflow.created_actor_id = "operator_" + "f" * 32
    else:
        value.workflow.initial_request = {}
    before = deepcopy(value.workflow.runtime_context)
    with pytest.raises(WorkflowError):
        value.complete()
    assert value.workflow.state == "RUNNING" and value.workflow.stage == "LOCAL_EMBEDDING"
    assert value.workflow.runtime_context == before and value.terminal is None
    value.session.add.assert_not_called()


def test_private_terminal_requires_current_completion_owner_even_for_replay(private_terminal):
    value = private_terminal
    value.complete()
    events = value.session.add.call_count
    value.validate.side_effect = ValueError("current source revoked")
    with pytest.raises(WorkflowError):
        value.complete()
    assert value.session.add.call_count == events


def test_private_completed_replay_requires_exact_successful_terminal_shape(private_terminal):
    value = private_terminal
    value.complete()
    value.terminal.platform_job_id = "job_" + "f" * 32
    with pytest.raises(WorkflowError):
        value.complete()

from __future__ import annotations

from itertools import pairwise

import pytest
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowStepRunRecord
from eom_workflow_runner.state_machine import (
    COMMAND_TRANSITIONS,
    STEP_TRANSITIONS,
    WORKFLOW_TRANSITIONS,
    CommandState,
    StepState,
    WorkflowState,
    WorkflowStateCategory,
    classify_workflow_state,
    require_transition,
    transition_command,
    transition_step,
)


def test_workflow_happy_path_transitions_are_explicit() -> None:
    path = (
        WorkflowState.REQUESTED,
        WorkflowState.RUNNING,
        WorkflowState.AWAITING_HUMAN_APPROVAL,
        WorkflowState.APPROVED,
        WorkflowState.REGISTERING,
        WorkflowState.COMPLETED,
    )
    for current, target in pairwise(path):
        require_transition(current, target, WORKFLOW_TRANSITIONS)


def test_workflow_rework_path_is_explicit() -> None:
    path = (
        WorkflowState.AWAITING_HUMAN_APPROVAL,
        WorkflowState.REWORK_REQUESTED,
        WorkflowState.RUNNING,
    )
    for current, target in pairwise(path):
        require_transition(current, target, WORKFLOW_TRANSITIONS)


def test_invalid_workflow_transition_is_rejected() -> None:
    with pytest.raises(WorkflowError, match="invalid transition"):
        require_transition(WorkflowState.COMPLETED, WorkflowState.RUNNING, WORKFLOW_TRANSITIONS)


def test_terminal_workflow_states_have_no_outgoing_transition() -> None:
    for state in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED):
        assert WORKFLOW_TRANSITIONS[state] == frozenset()


@pytest.mark.parametrize(
    "state",
    (
        WorkflowState.REQUESTED,
        WorkflowState.RUNNING,
        WorkflowState.AWAITING_HUMAN_APPROVAL,
        WorkflowState.REWORK_REQUESTED,
        WorkflowState.APPROVED,
        WorkflowState.REGISTERING,
    ),
)
def test_nonterminal_workflow_states_are_active(state: WorkflowState) -> None:
    assert classify_workflow_state(state) is WorkflowStateCategory.ACTIVE


def test_terminal_workflow_submission_categories_are_explicit() -> None:
    assert (
        classify_workflow_state(WorkflowState.COMPLETED)
        is WorkflowStateCategory.SUCCESSFUL_TERMINAL
    )
    for state in (WorkflowState.FAILED, WorkflowState.CANCELLED):
        assert classify_workflow_state(state) is WorkflowStateCategory.UNSUCCESSFUL_TERMINAL
    assert {classify_workflow_state(state) for state in WorkflowState} == set(WorkflowStateCategory)


def test_step_attempt_state_can_be_superseded_but_not_restarted() -> None:
    step = WorkflowStepRunRecord(
        step_run_id="steprun_0123456789abcdef0123456789abcdef",
        workflow_id="workflow_0123456789abcdef0123456789abcdef",
        step_key="authoring",
        attempt=1,
        step_type="agent",
        worker_role="authoring",
        result_schema="authoring-result@1.0",
        state=StepState.PENDING.value,
        input_pointer_manifest={},
    )
    for state in (StepState.READY, StepState.RUNNING, StepState.SUCCEEDED):
        transition_step(step, state)
    original_finished_at = step.finished_at
    transition_step(step, StepState.SUPERSEDED)
    assert step.finished_at == original_finished_at
    with pytest.raises(WorkflowError):
        transition_step(step, StepState.RUNNING)


def test_command_lease_processing_path_is_explicit() -> None:
    command = WorkflowCommandRecord(
        command_id="wfcmd_0123456789abcdef0123456789abcdef",
        workflow_id="workflow_0123456789abcdef0123456789abcdef",
        command_type="START_WORKFLOW",
        payload={},
        actor_type="human",
        actor_id="requester_01",
        source="eomctl",
        idempotency_key="command-1",
        request_hash="sha256:" + "a" * 64,
        state=CommandState.PENDING.value,
        attempts=0,
    )
    for state in (CommandState.LEASED, CommandState.PROCESSING, CommandState.SUCCEEDED):
        transition_command(command, state)
    assert command.state == CommandState.SUCCEEDED.value
    assert COMMAND_TRANSITIONS[CommandState.SUCCEEDED] == frozenset()
    assert STEP_TRANSITIONS[StepState.SUPERSEDED] == frozenset()

"""Explicit transition tables for all workflow-owned state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)


class WorkflowState(StrEnum):
    REQUESTED = "REQUESTED"
    RUNNING = "RUNNING"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    APPROVED = "APPROVED"
    REGISTERING = "REGISTERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStateCategory(StrEnum):
    ACTIVE = "ACTIVE"
    SUCCESSFUL_TERMINAL = "SUCCESSFUL_TERMINAL"
    UNSUCCESSFUL_TERMINAL = "UNSUCCESSFUL_TERMINAL"


ACTIVE_WORKFLOW_STATES = frozenset(
    {
        WorkflowState.REQUESTED,
        WorkflowState.RUNNING,
        WorkflowState.AWAITING_HUMAN_APPROVAL,
        WorkflowState.REWORK_REQUESTED,
        WorkflowState.APPROVED,
        WorkflowState.REGISTERING,
    }
)
SUCCESSFUL_TERMINAL_WORKFLOW_STATES = frozenset({WorkflowState.COMPLETED})
UNSUCCESSFUL_TERMINAL_WORKFLOW_STATES = frozenset({WorkflowState.FAILED, WorkflowState.CANCELLED})


def classify_workflow_state(state: WorkflowState) -> WorkflowStateCategory:
    if state in ACTIVE_WORKFLOW_STATES:
        return WorkflowStateCategory.ACTIVE
    if state in SUCCESSFUL_TERMINAL_WORKFLOW_STATES:
        return WorkflowStateCategory.SUCCESSFUL_TERMINAL
    if state in UNSUCCESSFUL_TERMINAL_WORKFLOW_STATES:
        return WorkflowStateCategory.UNSUCCESSFUL_TERMINAL
    raise ValueError(f"unclassified workflow state: {state}")


class WorkflowStage(StrEnum):
    AUTHORING = "AUTHORING"
    IMAGE_REQUIRED = "IMAGE_REQUIRED"
    IMAGE_SKIPPED = "IMAGE_SKIPPED"
    REVIEWING = "REVIEWING"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    REGISTERING = "REGISTERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SKIPPED = "SKIPPED"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class CommandState(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.REQUESTED: frozenset(
        {WorkflowState.RUNNING, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.RUNNING: frozenset(
        {WorkflowState.AWAITING_HUMAN_APPROVAL, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.AWAITING_HUMAN_APPROVAL: frozenset(
        {WorkflowState.APPROVED, WorkflowState.REWORK_REQUESTED, WorkflowState.CANCELLED}
    ),
    WorkflowState.REWORK_REQUESTED: frozenset(
        {WorkflowState.RUNNING, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.APPROVED: frozenset(
        {WorkflowState.REGISTERING, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.REGISTERING: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
}

STAGE_TRANSITIONS: dict[WorkflowStage, frozenset[WorkflowStage]] = {
    WorkflowStage.AUTHORING: frozenset(
        {
            WorkflowStage.IMAGE_REQUIRED,
            WorkflowStage.IMAGE_SKIPPED,
            WorkflowStage.FAILED,
            WorkflowStage.CANCELLED,
        }
    ),
    WorkflowStage.IMAGE_REQUIRED: frozenset(
        {WorkflowStage.REVIEWING, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    ),
    WorkflowStage.IMAGE_SKIPPED: frozenset(
        {WorkflowStage.REVIEWING, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    ),
    WorkflowStage.REVIEWING: frozenset(
        {
            WorkflowStage.AWAITING_HUMAN_APPROVAL,
            WorkflowStage.FAILED,
            WorkflowStage.CANCELLED,
        }
    ),
    WorkflowStage.AWAITING_HUMAN_APPROVAL: frozenset(
        {
            WorkflowStage.AUTHORING,
            WorkflowStage.IMAGE_REQUIRED,
            WorkflowStage.REVIEWING,
            WorkflowStage.REGISTERING,
            WorkflowStage.FAILED,
            WorkflowStage.CANCELLED,
        }
    ),
    WorkflowStage.REGISTERING: frozenset(
        {WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    ),
    WorkflowStage.COMPLETED: frozenset(),
    WorkflowStage.FAILED: frozenset(),
    WorkflowStage.CANCELLED: frozenset(),
}

STEP_TRANSITIONS: dict[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset({StepState.READY, StepState.CANCELLED}),
    StepState.READY: frozenset(
        {StepState.RUNNING, StepState.SKIPPED, StepState.WAITING_FOR_HUMAN, StepState.CANCELLED}
    ),
    StepState.RUNNING: frozenset({StepState.SUCCEEDED, StepState.FAILED, StepState.CANCELLED}),
    StepState.SUCCEEDED: frozenset({StepState.SUPERSEDED}),
    StepState.SKIPPED: frozenset({StepState.SUPERSEDED}),
    StepState.WAITING_FOR_HUMAN: frozenset(
        {StepState.SUCCEEDED, StepState.SUPERSEDED, StepState.CANCELLED}
    ),
    StepState.FAILED: frozenset(),
    StepState.CANCELLED: frozenset(),
    StepState.SUPERSEDED: frozenset(),
}

COMMAND_TRANSITIONS: dict[CommandState, frozenset[CommandState]] = {
    CommandState.PENDING: frozenset({CommandState.LEASED, CommandState.CANCELLED}),
    CommandState.LEASED: frozenset(
        {CommandState.PROCESSING, CommandState.PENDING, CommandState.CANCELLED}
    ),
    CommandState.PROCESSING: frozenset(
        {CommandState.SUCCEEDED, CommandState.FAILED, CommandState.PENDING}
    ),
    CommandState.SUCCEEDED: frozenset(),
    CommandState.FAILED: frozenset(),
    CommandState.CANCELLED: frozenset(),
}


def require_transition[StateT: StrEnum](
    current: StateT, target: StateT, table: dict[StateT, frozenset[StateT]]
) -> None:
    if target not in table[current]:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
            f"invalid transition: {current.value} -> {target.value}",
        )


def record_initial_workflow_event(
    session: Session, workflow: WorkflowInstanceRecord, *, actor_type: str, actor_id: str
) -> None:
    session.add(
        WorkflowEventRecord(
            workflow_id=workflow.workflow_id,
            sequence=1,
            event_type="WORKFLOW_REQUESTED",
            prior_state=None,
            new_state=WorkflowState.REQUESTED.value,
            step_key=workflow.current_step_key,
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=None,
            payload={},
        )
    )


def transition_workflow(
    session: Session,
    workflow_id: str,
    target: WorkflowState,
    event_type: str,
    *,
    actor_type: str,
    actor_id: str,
    command_id: str | None,
    step_key: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_lock_version: int | None = None,
) -> WorkflowInstanceRecord:
    workflow = _lock_workflow(session, workflow_id)
    if expected_lock_version is not None and workflow.lock_version != expected_lock_version:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
            "workflow optimistic lock conflict",
        )
    current = WorkflowState(workflow.state)
    require_transition(current, target, WORKFLOW_TRANSITIONS)
    workflow.state = target.value
    workflow.lock_version += 1
    workflow.updated_at = datetime.now(UTC)
    if target in {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
        workflow.completed_at = datetime.now(UTC)
    _append_event(
        session,
        workflow,
        event_type,
        current.value,
        target.value,
        step_key,
        actor_type,
        actor_id,
        command_id,
        payload,
    )
    return workflow


def transition_stage(
    session: Session,
    workflow_id: str,
    target: WorkflowStage,
    current_step_key: str,
    event_type: str,
    *,
    actor_type: str,
    actor_id: str,
    command_id: str | None,
    payload: dict[str, Any] | None = None,
) -> WorkflowInstanceRecord:
    workflow = _lock_workflow(session, workflow_id)
    current = WorkflowStage(workflow.stage)
    require_transition(current, target, STAGE_TRANSITIONS)
    workflow.stage = target.value
    workflow.current_step_key = current_step_key
    workflow.lock_version += 1
    workflow.updated_at = datetime.now(UTC)
    _append_event(
        session,
        workflow,
        event_type,
        workflow.state,
        workflow.state,
        current_step_key,
        actor_type,
        actor_id,
        command_id,
        {"prior_stage": current.value, "new_stage": target.value, **(payload or {})},
    )
    return workflow


def transition_step(step_run: WorkflowStepRunRecord, target: StepState) -> None:
    current = StepState(step_run.state)
    require_transition(current, target, STEP_TRANSITIONS)
    step_run.state = target.value
    now = datetime.now(UTC)
    if target == StepState.RUNNING:
        step_run.started_at = now
    if (
        target
        in {
            StepState.SUCCEEDED,
            StepState.SKIPPED,
            StepState.FAILED,
            StepState.CANCELLED,
            StepState.SUPERSEDED,
        }
        and step_run.finished_at is None
    ):
        step_run.finished_at = now


def record_workflow_event(
    session: Session,
    workflow_id: str,
    event_type: str,
    *,
    actor_type: str,
    actor_id: str,
    command_id: str | None,
    step_key: str | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowInstanceRecord:
    workflow = _lock_workflow(session, workflow_id)
    workflow.lock_version += 1
    workflow.updated_at = datetime.now(UTC)
    _append_event(
        session,
        workflow,
        event_type,
        workflow.state,
        workflow.state,
        step_key,
        actor_type,
        actor_id,
        command_id,
        payload,
    )
    return workflow


def transition_command(command: WorkflowCommandRecord, target: CommandState) -> None:
    current = CommandState(command.state)
    require_transition(current, target, COMMAND_TRANSITIONS)
    command.state = target.value
    if target in {CommandState.SUCCEEDED, CommandState.FAILED, CommandState.CANCELLED}:
        command.processed_at = datetime.now(UTC)


def _lock_workflow(session: Session, workflow_id: str) -> WorkflowInstanceRecord:
    workflow = session.execute(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == workflow_id)
        .with_for_update()
    ).scalar_one_or_none()
    if workflow is None:
        raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow does not exist")
    return workflow


def _append_event(
    session: Session,
    workflow: WorkflowInstanceRecord,
    event_type: str,
    prior_state: str,
    new_state: str,
    step_key: str | None,
    actor_type: str,
    actor_id: str,
    command_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    sequence = session.scalar(
        select(func.coalesce(func.max(WorkflowEventRecord.sequence), 0) + 1).where(
            WorkflowEventRecord.workflow_id == workflow.workflow_id
        )
    )
    if sequence is None:
        raise RuntimeError("failed to allocate workflow event sequence")
    session.add(
        WorkflowEventRecord(
            workflow_id=workflow.workflow_id,
            sequence=sequence,
            event_type=event_type,
            prior_state=prior_state,
            new_state=new_state,
            step_key=step_key,
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=command_id,
            payload=payload or {},
        )
    )

"""Transactional persistence operations for definitions, commands, and audit history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from eom_identifiers import content_sha256
from eom_workflow import CompiledWorkflowDefinition, WorkflowRequest
from eom_workflow.identifiers import (
    new_approval_request_id,
    new_command_id,
    new_definition_id,
    new_step_run_id,
    new_workflow_id,
)
from eom_workflow.schemas import result_schema_protocol
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.state_machine import (
    ACTIVE_WORKFLOW_STATES,
    ApprovalState,
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    record_initial_workflow_event,
    transition_command,
    transition_step,
)


class CommandType(StrEnum):
    START_WORKFLOW = "START_WORKFLOW"
    ADVANCE_WORKFLOW = "ADVANCE_WORKFLOW"
    APPROVE_WORKFLOW = "APPROVE_WORKFLOW"
    REQUEST_REWORK = "REQUEST_REWORK"
    CANCEL_WORKFLOW = "CANCEL_WORKFLOW"
    RETRY_STEP = "RETRY_STEP"
    RECONCILE_WORKFLOW = "RECONCILE_WORKFLOW"


def import_workflow_definition(
    session: Session, compiled: CompiledWorkflowDefinition
) -> tuple[WorkflowDefinitionRecord, bool]:
    definition = compiled.definition
    existing = session.scalar(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.definition_key == definition.definition_key,
            WorkflowDefinitionRecord.definition_version == definition.definition_version,
        )
    )
    if existing is not None:
        if existing.definition_hash != compiled.sha256:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_CONFLICT,
                "definition key and version already exist with a different hash",
            )
        return existing, False
    record = WorkflowDefinitionRecord(
        definition_id=new_definition_id(),
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        schema_version=definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )
    session.add(record)
    session.flush()
    return record, True


def workflow_business_fingerprint(
    definition: WorkflowDefinitionRecord, request: WorkflowRequest
) -> str:
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "request": request.model_dump(mode="json", exclude_none=True),
        }
    )


def _matching_submission(
    session: Session, *, idempotency_key: str, request_hash: str
) -> WorkflowInstanceRecord | None:
    existing = session.scalar(
        select(WorkflowInstanceRecord).where(
            WorkflowInstanceRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None and existing.request_hash != request_hash:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE,
            "workflow idempotency key was reused with different input",
        )
    return existing


def _active_equivalent(session: Session, request_hash: str) -> WorkflowInstanceRecord | None:
    return session.scalar(
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.request_hash == request_hash,
            WorkflowInstanceRecord.state.in_(
                tuple(state.value for state in ACTIVE_WORKFLOW_STATES)
            ),
        )
        .order_by(WorkflowInstanceRecord.created_at, WorkflowInstanceRecord.workflow_id)
        .limit(1)
    )


def _successful_equivalent(
    session: Session, request_hash: str, *, actor_type: str, actor_id: str
) -> WorkflowInstanceRecord | None:
    return session.scalar(
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.request_hash == request_hash,
            WorkflowInstanceRecord.state == WorkflowState.COMPLETED.value,
            WorkflowInstanceRecord.created_actor_type == actor_type,
            WorkflowInstanceRecord.created_actor_id == actor_id,
        )
        .order_by(
            WorkflowInstanceRecord.created_at.desc(),
            WorkflowInstanceRecord.workflow_id.desc(),
        )
        .limit(1)
    )


def create_workflow_instance(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: WorkflowRequest,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    runtime_context: dict[str, Any] | None = None,
) -> tuple[WorkflowInstanceRecord, bool]:
    request_data = request.model_dump(mode="json", exclude_none=True)
    request_hash = workflow_business_fingerprint(definition, request)
    existing = _matching_submission(
        session, idempotency_key=idempotency_key, request_hash=request_hash
    )
    if existing is not None:
        return existing, False
    active = _active_equivalent(session, request_hash)
    if active is not None:
        return active, False
    successful = _successful_equivalent(
        session, request_hash, actor_type=actor_type, actor_id=actor_id
    )
    if successful is not None:
        return successful, False
    canonical_definition = definition.canonical_definition
    start_step = canonical_definition.get("start_step")
    if not isinstance(start_step, str):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored definition has no start step",
        )
    role_protocols = {
        result_schema_protocol(str(step["result_schema"]))
        for step in canonical_definition.get("steps", [])
        if isinstance(step, dict) and step.get("type") == "agent"
    }
    if len(role_protocols) != 1:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored definition has inconsistent role protocol versions",
        )
    role_schema_version = next(iter(role_protocols))
    initial_context = dict(runtime_context or {})
    initial_context["artifact_pointers"] = []
    workflow = WorkflowInstanceRecord(
        workflow_id=new_workflow_id(),
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version=role_schema_version,
        state=WorkflowState.REQUESTED.value,
        stage=WorkflowStage.AUTHORING.value,
        current_step_key=start_step,
        request_payload=request_data,
        initial_request=request_data,
        runtime_context=initial_context,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type=actor_type,
        created_actor_id=actor_id,
    )
    try:
        with session.begin_nested():
            session.add(workflow)
            session.flush()
    except IntegrityError:
        existing = _matching_submission(
            session, idempotency_key=idempotency_key, request_hash=request_hash
        )
        if existing is not None:
            return existing, False
        active = _active_equivalent(session, request_hash)
        if active is not None:
            return active, False
        raise
    record_initial_workflow_event(session, workflow, actor_type=actor_type, actor_id=actor_id)
    return workflow, True


def enqueue_command(
    session: Session,
    *,
    workflow_id: str,
    command_type: CommandType,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
    source: str,
    idempotency_key: str,
    available_at: datetime | None = None,
) -> tuple[WorkflowCommandRecord, bool]:
    request_hash = content_sha256(
        {
            "workflow_id": workflow_id,
            "command_type": command_type.value,
            "payload": payload,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "source": source,
        }
    )
    existing = session.scalar(
        select(WorkflowCommandRecord).where(
            WorkflowCommandRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE,
                "command idempotency key was reused with different input",
            )
        return existing, False
    if session.get(WorkflowInstanceRecord, workflow_id) is None:
        raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow does not exist")
    command = WorkflowCommandRecord(
        command_id=new_command_id(),
        workflow_id=workflow_id,
        command_type=command_type.value,
        payload=payload,
        actor_type=actor_type,
        actor_id=actor_id,
        source=source,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        state=CommandState.PENDING.value,
        attempts=0,
        available_at=available_at or datetime.now(UTC),
    )
    session.add(command)
    session.flush()
    return command, True


def claim_next_command(
    session: Session,
    *,
    runner_id: str,
    lease_seconds: int,
    workflow_id: str | None = None,
) -> WorkflowCommandRecord | None:
    now = datetime.now(UTC)
    query = (
        select(WorkflowCommandRecord)
        .where(_claimable_command_filter(now))
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if workflow_id is not None:
        query = query.where(WorkflowCommandRecord.workflow_id == workflow_id)
    command = session.execute(query).scalar_one_or_none()
    if command is None:
        return None
    if command.state != CommandState.PENDING.value:
        transition_command(command, CommandState.PENDING)
    transition_command(command, CommandState.LEASED)
    command.attempts += 1
    command.lease_owner = runner_id
    command.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.flush()
    return command


def claimable_command_exists(session: Session, *, workflow_id: str | None = None) -> bool:
    """Check for pending or reclaimable work without locking or changing it."""
    query = (
        select(WorkflowCommandRecord.command_id)
        .where(_claimable_command_filter(datetime.now(UTC)))
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .limit(1)
    )
    if workflow_id is not None:
        query = query.where(WorkflowCommandRecord.workflow_id == workflow_id)
    return session.scalar(query) is not None


def _claimable_command_filter(now: datetime) -> ColumnElement[bool]:
    return or_(
        (
            (WorkflowCommandRecord.state == CommandState.PENDING.value)
            & (WorkflowCommandRecord.available_at <= now)
        ),
        (
            WorkflowCommandRecord.state.in_(
                [CommandState.LEASED.value, CommandState.PROCESSING.value]
            )
            & (WorkflowCommandRecord.lease_expires_at < now)
        ),
    )


def create_step_run(
    session: Session,
    *,
    workflow_id: str,
    step_key: str,
    step_type: str,
    worker_role: str | None,
    result_schema: str | None,
    input_pointer_manifest: dict[str, Any],
    max_attempts: int,
) -> WorkflowStepRunRecord:
    latest_attempt = session.scalar(
        select(func.coalesce(func.max(WorkflowStepRunRecord.attempt), 0)).where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == step_key,
        )
    )
    attempt = int(latest_attempt or 0) + 1
    if attempt > max_attempts:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REWORK_LIMIT_EXCEEDED,
            "workflow step attempt limit exceeded",
        )
    step = WorkflowStepRunRecord(
        step_run_id=new_step_run_id(),
        workflow_id=workflow_id,
        step_key=step_key,
        attempt=attempt,
        step_type=step_type,
        worker_role=worker_role,
        result_schema=result_schema,
        state=StepState.PENDING.value,
        input_pointer_manifest=input_pointer_manifest,
    )
    session.add(step)
    session.flush()
    previous = session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == step_key,
            WorkflowStepRunRecord.state == StepState.SUPERSEDED.value,
            WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
        )
        .order_by(WorkflowStepRunRecord.attempt.desc())
        .limit(1)
    )
    if previous is not None:
        previous.superseded_by_step_run_id = step.step_run_id
    transition_step(step, StepState.READY)
    return step


def link_superseded_attempts(session: Session, workflow_id: str) -> None:
    superseded = list(
        session.scalars(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.state == StepState.SUPERSEDED.value,
                WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
            )
        )
    )
    for previous in superseded:
        replacement = session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.step_key == previous.step_key,
                WorkflowStepRunRecord.attempt > previous.attempt,
                WorkflowStepRunRecord.state != StepState.SUPERSEDED.value,
            )
            .order_by(WorkflowStepRunRecord.attempt)
            .limit(1)
        )
        if replacement is not None:
            previous.superseded_by_step_run_id = replacement.step_run_id


def create_approval_request(
    session: Session,
    *,
    workflow_id: str,
    step_run_id: str,
    allowed_roles: tuple[str, ...],
    allowed_rework_targets: tuple[str, ...],
) -> ApprovalRequestRecord:
    active = active_approval(session, workflow_id, for_update=True)
    if active is not None:
        raise WorkflowError(
            WorkflowErrorCode.APPROVAL_STALE,
            "workflow already has an active approval request",
        )
    approval = ApprovalRequestRecord(
        approval_request_id=new_approval_request_id(),
        workflow_id=workflow_id,
        step_run_id=step_run_id,
        status=ApprovalState.PENDING.value,
        lock_version=1,
        allowed_roles=list(allowed_roles),
        allowed_rework_targets=list(allowed_rework_targets),
    )
    session.add(approval)
    session.flush()
    return approval


def active_approval(
    session: Session, workflow_id: str, *, for_update: bool = False
) -> ApprovalRequestRecord | None:
    query = select(ApprovalRequestRecord).where(
        ApprovalRequestRecord.workflow_id == workflow_id,
        ApprovalRequestRecord.status == ApprovalState.PENDING.value,
    )
    if for_update:
        query = query.with_for_update()
    return session.execute(query).scalar_one_or_none()


def list_workflow_events(session: Session, workflow_id: str) -> list[WorkflowEventRecord]:
    return list(
        session.scalars(
            select(WorkflowEventRecord)
            .where(WorkflowEventRecord.workflow_id == workflow_id)
            .order_by(WorkflowEventRecord.sequence)
        )
    )


def list_step_runs(session: Session, workflow_id: str) -> list[WorkflowStepRunRecord]:
    return list(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == workflow_id)
            .order_by(
                WorkflowStepRunRecord.attempt,
                WorkflowStepRunRecord.step_run_id,
            )
        )
    )

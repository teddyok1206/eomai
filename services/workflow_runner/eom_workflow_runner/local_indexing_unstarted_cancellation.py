"""Deployment-owner cancellation of one exact, never-claimed INDEX request."""

from __future__ import annotations

from eom_identifiers import content_sha256
from eom_identity_service import lock_current_local_indexing_service_metadata
from eom_workflow.local_embedding_request import (
    LocalEmbeddingServiceWorkflowRequest,
    local_embedding_request_service,
    parse_local_embedding_executable_request,
)
from eom_workflow.local_indexing_unstarted_cancellation import (
    LocalIndexingUnstartedCancellationCommand,
    LocalIndexingUnstartedCancellationReceipt,
    parse_local_indexing_cancellation_command,
    parse_local_indexing_cancellation_receipt,
)
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from eom_workflow_runner.local_indexing_preallocation_retirement import (
    LocalIndexingRetirementError,
    _owner,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_start_command import (
    LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.repository import (
    CommandType,
    validate_local_embedding_workflow_submission,
)
from eom_workflow_runner.state_machine import (
    CommandState,
    WorkflowStage,
    WorkflowState,
    transition_command,
    transition_stage,
    transition_workflow,
)

CANCELLATION_EVENT = "LOCAL_INDEXING_UNSTARTED_CANCELLED"
_STAGE_EVENT = "LOCAL_INDEXING_UNSTARTED_STAGE_CANCELLED"


class LocalIndexingCancellationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def cancel_unstarted_indexing_workflow(
    session: Session, command: LocalIndexingUnstartedCancellationCommand
) -> LocalIndexingUnstartedCancellationReceipt:
    """One short caller-owned transaction; never claim, repair, enqueue or activate.

    The sibling maintenance operation owns the same PostgreSQL-owner guard. Reuse
    that package-internal adapter rather than copying its principal/table checks.
    """
    command = parse_local_indexing_cancellation_command(command)
    try:
        principal = _owner(session)
    except LocalIndexingRetirementError as error:
        raise LocalIndexingCancellationError(
            error.code.replace("LOCAL_INDEXING_RETIREMENT_", "LOCAL_INDEXING_CANCELLATION_")
        ) from None
    try:
        return _cancel(session, command, principal)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_BUSY") from error
        raise


def _cancel(
    session: Session, command: LocalIndexingUnstartedCancellationCommand, principal: str
) -> LocalIndexingUnstartedCancellationReceipt:
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
        .with_for_update(nowait=True)
        .execution_options(populate_existing=True)
    )
    if workflow is None:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_SCOPE_INVALID")
    request = parse_local_embedding_executable_request(workflow.initial_request)
    if (
        not isinstance(request, LocalEmbeddingServiceWorkflowRequest)
        or request.request_sha256 != command.workflow_request_sha256
        or local_embedding_request_service(request) != command.service
        or workflow.created_actor_type != "local_indexing_service"
        or workflow.created_actor_id != command.service.service_id
    ):
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_SCOPE_INVALID")
    definition = session.get(
        WorkflowDefinitionRecord, workflow.definition_id, populate_existing=True
    )
    if definition is None:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_SCOPE_INVALID")
    validate_local_embedding_workflow_submission(
        session,
        workflow,
        definition=definition,
        request=request,
        actor_type="local_indexing_service",
        actor_id=command.service.service_id,
    )
    commands = tuple(
        session.scalars(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == command.workflow_id)
            .order_by(WorkflowCommandRecord.command_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord.step_run_id)
            .where(WorkflowStepRunRecord.workflow_id == command.workflow_id)
            .limit(1)
            .with_for_update(nowait=True)
        )
    )
    if len(commands) != 1 or steps:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_UNSTARTED_UNPROVEN")
    original = commands[0]
    if (
        original.command_id != command.command_id
        or original.command_type != CommandType.START_WORKFLOW.value
        or original.attempts != 0
        or original.lease_generation != 0
        or original.lease_owner is not None
        or original.lease_token is not None
        or original.lease_expires_at is not None
        or original.error_code is not None
    ):
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_UNSTARTED_UNPROVEN")
    # Prove the original producer/hash/key/actor without creating a START command.
    start, created = resolve_native_start_command(
        session,
        workflow=workflow,
        workflow_created=False,
        actor_type="local_indexing_service",
        actor_id=command.service.service_id,
        source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    )
    if start is not original or created:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_SCOPE_INVALID")
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(WorkflowEventRecord.workflow_id == command.workflow_id)
            .order_by(WorkflowEventRecord.sequence)
            .limit(4)
        )
    )
    if (
        not events
        or events[0].sequence != 1
        or events[0].event_type != "WORKFLOW_REQUESTED"
        or events[0].actor_type != "local_indexing_service"
        or events[0].actor_id != command.service.service_id
    ):
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_HISTORY_INVALID")
    if len(events) == 3 and events[-1].event_type == CANCELLATION_EVENT:
        receipt = parse_local_indexing_cancellation_receipt(events[-1].payload)
        if receipt.command != command:
            raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_REPLAY_CONFLICT")
        if (
            tuple((event.sequence, event.event_type) for event in events)
            != ((1, "WORKFLOW_REQUESTED"), (2, _STAGE_EVENT), (3, CANCELLATION_EVENT))
            or any(
                event.actor_type != "database_owner"
                or event.actor_id != receipt.performed_by
                or event.command_id != command.command_id
                for event in events[1:]
            )
            or (workflow.state, workflow.stage, original.state) != ("CANCELLED",) * 3
            or workflow.failure_code is not None
            or workflow.completed_at is None
            or workflow.current_step_key != "encode_batch"
            or original.processed_at is None
        ):
            raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_HISTORY_INVALID")
        return receipt
    if len(events) != 1:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_HISTORY_INVALID")
    if (
        workflow.state != "REQUESTED"
        or workflow.stage != "LOCAL_EMBEDDING"
        or workflow.current_step_key != "encode_batch"
        or workflow.failure_code is not None
        or workflow.completed_at is not None
        or original.state != "PENDING"
        or original.processed_at is not None
    ):
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_UNSTARTED_UNPROVEN")
    identity = lock_current_local_indexing_service_metadata(session, command.service)
    if identity.runtime_source_commit == command.successor_source_commit:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_SCOPE_INVALID")
    now = session.scalar(select(func.clock_timestamp()))
    if now is None:
        raise LocalIndexingCancellationError("LOCAL_INDEXING_CANCELLATION_CONTEXT_INVALID")
    body = {
        "schema_version": "local-indexing-unstarted-cancellation/1.0",
        "record_type": "RECEIPT",
        "command": command.model_dump(mode="json"),
        "performed_by": principal,
        "performed_at": now.isoformat().replace("+00:00", "Z"),
        "prior_workflow_state": "REQUESTED",
        "prior_command_state": "PENDING",
        "step_run_count": 0,
        "new_workflow_state": "CANCELLED",
        "new_stage": "CANCELLED",
        "new_command_state": "CANCELLED",
    }
    receipt = parse_local_indexing_cancellation_receipt(
        body | {"receipt_sha256": content_sha256(body)}
    )
    transition_command(original, CommandState.CANCELLED)
    transition_stage(
        session,
        command.workflow_id,
        WorkflowStage.CANCELLED,
        "encode_batch",
        _STAGE_EVENT,
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
    )
    transition_workflow(
        session,
        command.workflow_id,
        WorkflowState.CANCELLED,
        CANCELLATION_EVENT,
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
        step_key="encode_batch",
        payload=receipt.model_dump(mode="json"),
    )
    session.flush()
    return receipt

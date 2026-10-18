"""Exact private START/ADVANCE linkage, never source or physical-execution authority."""

from __future__ import annotations

import re

from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from sqlalchemy.orm import Session, object_session

from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.native_start_command import (
    PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE as PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
)
from eom_workflow_runner.native_step_completion import native_application_step
from eom_workflow_runner.repository import CommandType, command_business_fingerprint

PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE = "private-chat-query-owner"


def private_chat_query_continuation_key(step_run_id: str, parent_command_id: str) -> str:
    if (
        type(step_run_id) is not str
        or type(parent_command_id) is not str
        or re.fullmatch(r"steprun_[0-9a-f]{32}", step_run_id) is None
        or re.fullmatch(r"wfcmd_[0-9a-f]{32}", parent_command_id) is None
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")
    return f"private-chat-query-pending:{step_run_id}:{parent_command_id}"


def _require_command_metadata(
    workflow: WorkflowInstanceRecord,
    command: WorkflowCommandRecord,
    *,
    kind: CommandType,
    payload: dict[str, str],
    source: str,
    key: str,
) -> None:
    if (
        command.workflow_id != workflow.workflow_id
        or command.command_type != kind.value
        or command.payload != payload
        or command.actor_type != workflow.created_actor_type
        or command.actor_id != workflow.created_actor_id
        or command.source != source
        or command.idempotency_key != key
        or command.request_hash
        != command_business_fingerprint(
            workflow_id=workflow.workflow_id,
            command_type=kind,
            payload=payload,
            actor_type=workflow.created_actor_type,
            actor_id=workflow.created_actor_id,
            source=source,
        )
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")


def _require_start(workflow: WorkflowInstanceRecord, command: WorkflowCommandRecord) -> None:
    _require_command_metadata(
        workflow,
        command,
        kind=CommandType.START_WORKFLOW,
        payload={},
        source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
        key=f"start:{workflow.workflow_id}",
    )


def _require_successful_predecessor(command: WorkflowCommandRecord) -> None:
    # A historical lease may have expired; its existence is execution metadata,
    # never current authority. The owner reauthorizes the current caller separately.
    if (
        command.state != "SUCCEEDED"
        or command.attempts < 1
        or command.lease_generation < 1
        or not command.lease_owner
        or not command.lease_token
        or command.lease_expires_at is None
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE")


def _continuation_parent_id(command: WorkflowCommandRecord, step_run_id: str) -> str:
    prefix = f"private-chat-query-pending:{step_run_id}:"
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.startswith(
        prefix
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")
    parent_id = command.idempotency_key[len(prefix) :]
    if private_chat_query_continuation_key(step_run_id, parent_id) != command.idempotency_key:
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")
    return parent_id


def require_private_chat_query_command(
    session: Session,
    workflow: WorkflowInstanceRecord,
    command: WorkflowCommandRecord,
    request: PrivateChatQueryWorkflowRequest,
) -> None:
    if command.command_type == CommandType.START_WORKFLOW.value:
        _require_start(workflow, command)
        return
    step = native_application_step(session, workflow.workflow_id, "encode_private_chat_query")
    if (
        command.command_type != CommandType.ADVANCE_WORKFLOW.value
        or step is None
        or step.attempt != 1
        or step.state not in {"RUNNING", "SUCCEEDED"}
        or step.workflow_id != workflow.workflow_id
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != "embedding-private-chat-query-result@1.0"
        or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID")
    parent_id = _continuation_parent_id(command, step.step_run_id)
    if parent_id == command.command_id:
        raise ValueError("PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE")
    _require_command_metadata(
        workflow,
        command,
        kind=CommandType.ADVANCE_WORKFLOW,
        payload={"step_run_id": step.step_run_id},
        source=PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
        key=private_chat_query_continuation_key(step.step_run_id, parent_id),
    )
    parent = session.get(WorkflowCommandRecord, parent_id, populate_existing=True)
    if parent is None or object_session(parent) is not session:
        raise ValueError("PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE")
    _require_successful_predecessor(parent)
    if parent.command_type == CommandType.START_WORKFLOW.value:
        _require_start(workflow, parent)
    else:
        previous = _continuation_parent_id(parent, step.step_run_id)
        _require_command_metadata(
            workflow,
            parent,
            kind=CommandType.ADVANCE_WORKFLOW,
            payload={"step_run_id": step.step_run_id},
            source=PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
            key=private_chat_query_continuation_key(step.step_run_id, previous),
        )
    launch = read_native_query_launch(
        session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
    )
    if not isinstance(launch, PrivateChatQueryLaunchAssociation):
        raise ValueError("PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING")
    original = session.get(
        WorkflowCommandRecord, launch.original_command_id, populate_existing=True
    )
    if (
        original is None
        or object_session(original) is not session
        or original.state != "SUCCEEDED"
        or original.lease_generation < launch.original_command_generation
        or (
            parent.command_type == CommandType.START_WORKFLOW.value
            and parent.command_id != original.command_id
        )
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE")
    _require_start(workflow, original)
    _require_successful_predecessor(original)

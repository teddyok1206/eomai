"""One native START identity/replay invariant, shared by INDEX and QUERY use cases."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandType,
    command_business_fingerprint,
    enqueue_command,
)

LOCAL_EMBEDDING_SUBMISSION_SOURCE: Final = "local_embedding_submission"
REFERENCE_QUERY_SUBMISSION_SOURCE: Final = "reference_query_submission"
type NativeStartSource = Literal["local_embedding_submission", "reference_query_submission"]
_REPLAY_ERRORS = MappingProxyType(
    {
        LOCAL_EMBEDDING_SUBMISSION_SOURCE: "LOCAL_EMBEDDING_SUBMISSION_REPLAY_INVALID",
        REFERENCE_QUERY_SUBMISSION_SOURCE: "REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID",
    }
)


def resolve_native_start_command(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    workflow_created: bool,
    actor_type: str,
    actor_id: str,
    source: NativeStartSource,
) -> tuple[WorkflowCommandRecord, bool]:
    """Caller retains current purpose authorization and the atomic submission savepoint.

    This does not authorize an actor or revive missing/terminal commands. A new
    START is created only for a newly created Workflow, never for a replay.
    """
    if source not in _REPLAY_ERRORS:
        raise ValueError("NATIVE_START_SOURCE_INVALID")
    error = _REPLAY_ERRORS[source]
    if workflow.created_actor_type != actor_type or workflow.created_actor_id != actor_id:
        raise ValueError(error)
    key = f"start:{workflow.workflow_id}"
    if workflow_created:
        command, created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type=actor_type,
            actor_id=actor_id,
            source=source,
            idempotency_key=key,
        )
    else:
        existing = session.scalar(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
        if existing is None:
            raise ValueError(error)
        command = existing
        created = False
    if (
        command.workflow_id != workflow.workflow_id
        or command.idempotency_key != key
        or command.command_type != CommandType.START_WORKFLOW.value
        or command.payload != {}
        or command.actor_type != actor_type
        or command.actor_id != actor_id
        or command.source != source
        or command.request_hash
        != command_business_fingerprint(
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type=actor_type,
            actor_id=actor_id,
            source=source,
        )
    ):
        raise ValueError(error)
    return command, created

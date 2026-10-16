"""One bounded existing-queue observation, not retrieval or native execution authority."""

from __future__ import annotations

from eom_workflow.reference_query_workflow import REFERENCE_QUERY_WORKFLOW_KEY
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord


class NativeCpuSchedulingReadUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("NATIVE_CPU_SCHEDULING_READ_UNAVAILABLE")


def active_reference_query_command_exists(session: Session) -> bool:
    """Current leased work only; successful rows may legitimately retain old lease fields."""
    command, workflow = WorkflowCommandRecord, WorkflowInstanceRecord
    active = (
        select(command.command_id)
        .join(workflow, workflow.workflow_id == command.workflow_id)
        .where(
            command.state.in_(("LEASED", "PROCESSING")),
            command.command_type.in_(("START_WORKFLOW", "ADVANCE_WORKFLOW")),
            command.lease_owner.is_not(None),
            command.lease_token.is_not(None),
            command.lease_generation > 0,
            command.attempts > 0,
            command.lease_expires_at > func.current_timestamp(),
            workflow.definition_key == REFERENCE_QUERY_WORKFLOW_KEY,
            workflow.state == "RUNNING",
            workflow.stage == "LOCAL_EMBEDDING",
            workflow.created_actor_type == "human",
            command.actor_type == workflow.created_actor_type,
            command.actor_id == workflow.created_actor_id,
        )
    )
    value = session.scalar(select(active.exists()))
    if type(value) is not bool:
        raise NativeCpuSchedulingReadUnavailable()
    return value


def should_defer_background_cpu_claim(engine: Engine) -> bool:
    """A fresh short snapshot; no session, lease or SQL lock survives this call."""
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            return active_reference_query_command_exists(session)
    except (SQLAlchemyError, OSError):
        raise NativeCpuSchedulingReadUnavailable() from None

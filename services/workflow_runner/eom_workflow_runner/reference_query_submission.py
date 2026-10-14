"""Atomic QUERY Workflow/START submission, never implicit admission or execution."""

from __future__ import annotations

from dataclasses import dataclass

from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequest
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.native_start_command import (
    REFERENCE_QUERY_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.reference_query_admission import (
    ReferenceQueryOwnerAdmission,
    resolve_reference_query_submission_controls,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.repository import create_workflow_instance


@dataclass(frozen=True, slots=True)
class ReferenceQueryWorkflowSubmitted:
    """Root-local persistence observations, not a worker response/read capability."""

    workflow: WorkflowInstanceRecord
    command: WorkflowCommandRecord
    workflow_created: bool
    command_created: bool


def start_reference_query_in_session(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: ReferenceQueryWorkflowRequest,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    owner: ReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
) -> ReferenceQueryWorkflowSubmitted:
    """Current owner before savepoints and late; caller owns the root transaction.

    Numerical launch/readiness and consumer reads are separate use cases. No
    service/operator grant or default QUERY configuration is inferred here.
    """
    if session.in_nested_transaction():
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "reference query submission must enter in the root transaction",
        )
    scope = resolve_reference_query_submission_controls(
        session,
        definition=definition,
        request=request,
        actor_type=actor_type,
        actor_id=actor_id,
        owner=owner,
        executor=executor,
    )
    with session.begin_nested():
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=scope.request,
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_id=actor_id,
            reference_query_owner=owner,
            reference_query_executor=executor,
        )
        command, command_created = resolve_native_start_command(
            session,
            workflow=workflow,
            workflow_created=created,
            actor_type=actor_type,
            actor_id=actor_id,
            source=REFERENCE_QUERY_SUBMISSION_SOURCE,
        )
        late = resolve_reference_query_submission_controls(
            session,
            definition=definition,
            request=scope.request,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=owner,
            executor=executor,
        )
        if late != scope:
            raise ValueError("REFERENCE_QUERY_SUBMISSION_CONTEXT_INVALID")
        return ReferenceQueryWorkflowSubmitted(workflow, command, created, command_created)

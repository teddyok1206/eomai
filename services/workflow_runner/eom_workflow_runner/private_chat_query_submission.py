"""Atomic original private Workflow/START; no implicit native or source admission."""

from __future__ import annotations

from dataclasses import dataclass

from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    private_chat_query_submission_key,
    validate_private_chat_query_submission_context,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.native_start_command import (
    PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.private_chat_query_admission import (
    PrivateChatQueryOwnerAdmission,
    resolve_private_chat_query_submission_controls,
)
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.repository import create_workflow_instance


@dataclass(frozen=True, slots=True)
class PrivateChatQueryWorkflowSubmitted:
    """Caller-root persistence observations, never a worker response or grant."""

    workflow: WorkflowInstanceRecord
    command: WorkflowCommandRecord
    workflow_created: bool
    command_created: bool


def start_private_chat_query_in_session(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: PrivateChatQueryWorkflowRequest,
    context: PrivateChatQuerySubmissionContext,
    actor_type: str,
    actor_id: str,
    owner: PrivateChatQueryOwnerAdmission,
    executor: PrivateChatQueryNativeExecutor,
) -> PrivateChatQueryWorkflowSubmitted:
    """Keep current source reads in the same clean root, not persistence savepoints.

    The caller owns prompt commit/rollback and must not mix unrelated writes. A
    late rejection discards this entire root, including released savepoints. The
    key comes from the original typed actor/turn; callers cannot supply another.
    No numerical model, unit start, worker permission or default policy is inferred.
    """
    context = validate_private_chat_query_submission_context(request, context)
    scope = resolve_private_chat_query_submission_controls(
        session,
        definition=definition,
        request=request,
        context=context,
        actor_type=actor_type,
        actor_id=actor_id,
        owner=owner,
        executor=executor,
    )
    try:
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=scope.request,
            idempotency_key=private_chat_query_submission_key(context),
            actor_type=actor_type,
            actor_id=actor_id,
            private_chat_query_context=context,
            private_chat_query_owner=owner,
            private_chat_query_executor=executor,
        )
        with session.begin_nested():
            command, command_created = resolve_native_start_command(
                session,
                workflow=workflow,
                workflow_created=created,
                actor_type=actor_type,
                actor_id=actor_id,
                source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
            )
        late = resolve_private_chat_query_submission_controls(
            session,
            definition=definition,
            request=scope.request,
            context=context,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=owner,
            executor=executor,
        )
        if late != scope:
            raise ValueError("PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID")
        return PrivateChatQueryWorkflowSubmitted(workflow, command, created, command_created)
    except BaseException:
        session.rollback()
        raise

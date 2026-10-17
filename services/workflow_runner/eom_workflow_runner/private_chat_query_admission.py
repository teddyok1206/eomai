"""Required private-purpose owner interface; no retained source or native capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_submission_context import PrivateChatQuerySubmissionContext
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_source_read import ResolvedPrivateChatQuerySources

if TYPE_CHECKING:
    from eom_workflow_runner.repository import CommandLeaseIdentity


class PrivateChatQueryOwnerAdmission(Protocol):
    def resolve_submission(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        context: PrivateChatQuerySubmissionContext,
    ) -> ResolvedPrivateChatQuerySources: ...

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: PrivateChatQueryWorkflowRequest,
    ) -> ResolvedPrivateChatQuerySources: ...

    def fence_mutation(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> None: ...

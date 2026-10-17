"""Required private-purpose numerical port; no default, native or source authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from eom_catalog_contracts.models import Sha256
from eom_workflow.models import JobId
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import RuntimeReadinessReport

if TYPE_CHECKING:
    from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class PrivateChatQueryStepPending:
    """Original execution observation only; not another attempt or a public QUERY."""

    native_launch_job_id: str
    association_sha256: str
    reason: Literal["BUSY", "UNCERTAIN"]

    def __post_init__(self) -> None:
        try:
            TypeAdapter(JobId).validate_python(self.native_launch_job_id, strict=True)
            TypeAdapter(Sha256).validate_python(self.association_sha256, strict=True)
            if self.reason not in {"BUSY", "UNCERTAIN"}:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("PRIVATE_CHAT_QUERY_PENDING_INVALID") from None


class PrivateChatQueryNativeExecutor(Protocol):
    def evaluate(self, request: PrivateChatQueryWorkflowRequest) -> RuntimeReadinessReport: ...

    def allocate_execution(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
    ) -> PrivateChatQueryLaunchAssociation: ...

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutput | PrivateChatQueryStepPending: ...

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: PrivateChatQueryStepOutput,
    ) -> PrivateChatQueryStepOutput: ...

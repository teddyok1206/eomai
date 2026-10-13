"""QUERY-specific numerical execution boundary; no INDEX/ROLE/default substitution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequest,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import RuntimeReadinessReport

if TYPE_CHECKING:
    from eom_workflow_runner.repository import CommandLeaseIdentity


class ReferenceQueryNativeExecutor(Protocol):
    """Readiness is not permission; execute must prove genuine QUERY-purpose provenance.

    No SQL transaction survives inference. Uncertain work raises unavailable and
    retains ownership/capacity, never returns success or a new identity retry.
    Canonical receipt validation repeats current source/session/execution closure
    at step success, terminal completion and replay. This port has no default.
    """

    def evaluate(self, request: ReferenceQueryWorkflowRequest) -> RuntimeReadinessReport: ...

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: ReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> ReferenceQueryStepOutput: ...

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: ReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: ReferenceQueryStepOutput,
    ) -> ReferenceQueryStepOutput: ...

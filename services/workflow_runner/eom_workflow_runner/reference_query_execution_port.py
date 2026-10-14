"""QUERY-specific numerical execution boundary; no INDEX/ROLE/default substitution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from eom_catalog_contracts.models import Sha256
from eom_workflow.models import JobId
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequest,
)
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import RuntimeReadinessReport

if TYPE_CHECKING:
    from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class ReferenceQueryStepPending:
    """Internal original-execution observation, never permission to launch/retry."""

    native_launch_job_id: str
    association_sha256: str
    reason: Literal["BUSY", "UNCERTAIN"]

    def __post_init__(self) -> None:
        TypeAdapter(JobId).validate_python(self.native_launch_job_id, strict=True)
        TypeAdapter(Sha256).validate_python(self.association_sha256, strict=True)
        if self.reason not in {"BUSY", "UNCERTAIN"}:
            raise ValueError("REFERENCE_QUERY_PENDING_INVALID")


class ReferenceQueryNativeExecutor(Protocol):
    """Readiness is not permission; execute must prove genuine QUERY-purpose provenance.

    No SQL transaction survives inference. Uncertain work retains its original
    ownership and pending identity, never success or a fresh inference retry.
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
    ) -> ReferenceQueryStepOutput | ReferenceQueryStepPending: ...

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

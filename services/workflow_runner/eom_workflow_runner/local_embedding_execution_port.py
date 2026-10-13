"""Required native executor interface; no launcher, default, Codex slot or authority."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow.local_embedding_workflow_receipt import LocalEmbeddingStepOutput
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import RuntimeReadinessReport

if TYPE_CHECKING:
    from eom_workflow_runner.repository import CommandLeaseIdentity

type NativeFencedRunnerTransaction = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class LocalEmbeddingStepPending:
    """Internal ordered existing owner reads, not a new wire receipt or retry grant."""

    readings: tuple[EmbeddingEncodingReadResult, ...]

    def __post_init__(self) -> None:
        if type(self.readings) is not tuple or not 1 <= len(self.readings) <= 1024:
            raise ValueError("LOCAL_EMBEDDING_PENDING_READS_INVALID")
        readings = tuple(EmbeddingEncodingReadResult.model_validate(row) for row in self.readings)
        keys = tuple(row.owned_job.request.encoding.encoding_sha256 for row in readings)
        if keys != tuple(sorted(set(keys))) or any(
            row.status in {"FAILED", "CANCELLED"} for row in readings
        ):
            raise ValueError("LOCAL_EMBEDDING_PENDING_READS_INVALID")
        object.__setattr__(self, "readings", readings)


class LocalEmbeddingNativeExecutor(Protocol):
    """Inject one admitted protected owner; absent means unavailable before create/claim.

    Readiness inspects exact owner-configured runtime/profile/control pins without
    a worker launch, IAM fence, session write or reusable authorization decision.
    Actual current owner/session/source/command fences are separate and required.
    Execute/reconcile uses canonical original request plus separately owned launch
    association; no SQL transaction remains open through inference. Workers read
    staged descriptors only and never access DB/NAS. No RoleExecutionResult/Codex
    fallback is accepted. Uncertain execution preserves ownership/capacity and
    does not return a completion carrier or authorize another inference.
    """

    def evaluate(self, request: LocalEmbeddingWorkflowRequestV11) -> RuntimeReadinessReport: ...

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: LocalEmbeddingWorkflowRequestV11,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> LocalEmbeddingStepOutput | LocalEmbeddingStepPending:
        """Return only actual published receipt carrier or exact pending owner reads.

        Completion reauthorizes all bindings and validates canonical producer/
        binary/receipt pointers with the existing owners. Original launch audit
        generation is not the current lease. Reclaimed/uncertain work needs linked
        recovery owner authority; this interface does not create that authority.
        """
        ...

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: LocalEmbeddingWorkflowRequestV11,
        command_lease: CommandLeaseIdentity,
        output: LocalEmbeddingStepOutput,
    ) -> LocalEmbeddingStepOutput:
        """Resolve and reauthorize the exact canonical receipt with existing owners.

        This short root transaction does not run inference. Resolve the carrier's
        raw member and canonical receipt, producer/Job, original plan/association,
        registration and current source/session closure. Return the SAME checked
        carrier, never repair it or substitute latest. A pass-through/default
        implementation is not authority. Step success and terminal/replay each
        call this seam; immutable receipt observations do not rewind index head.
        """
        ...

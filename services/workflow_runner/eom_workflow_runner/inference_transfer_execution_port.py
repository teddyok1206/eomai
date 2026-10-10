"""Optional Runner-owned purpose port, with no new queue or execution framework."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfile
from eom_catalog_service.inference_transfer_service import InferenceTransferSearchCommand
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.role_execution_port import RoleExecutionResult

FencedRunnerTransaction = Callable[[], AbstractContextManager[Session]]


class InferenceTransferPairSourcePort(Protocol):
    def authorize_pair(
        self,
        command: InferenceTransferSearchCommand,
        left_profile: InferenceTransferProfile,
        right_profile: InferenceTransferProfile,
    ) -> None:
        """Resolve/rebuild both exact profiles using current real-actor Catalog authority."""
        ...


class InferenceTransferRoleJobExecutor(Protocol):
    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: InferenceTransferWorkflowRequest,
        idempotency_key: str,
        fenced_transaction: FencedRunnerTransaction,
    ) -> RoleExecutionResult:
        """Execute only this purpose; command/step state machines stay in Runner."""
        ...

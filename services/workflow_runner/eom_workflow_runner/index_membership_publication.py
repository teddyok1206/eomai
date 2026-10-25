"""Existing INDEX publication without a physical allocation or numerical fallback."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)

from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.local_embedding_completed_read import read_completed_local_embedding
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    LocalEmbeddingServicePreparation,
    LocalEmbeddingServiceReconciliation,
    PreparedLocalEmbeddingReconciliation,
    ReconciliationState,
)
from eom_workflow_runner.local_indexing_runner_composition import (
    build_local_indexing_workflow_runner,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import NativeCommandActorSelection

if TYPE_CHECKING:
    from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission


@dataclass(frozen=True, slots=True)
class MembershipOnlyEmbeddingExecution:
    """Existing rows keep their device identity; this adapter cannot compute new ones."""

    request: SupportedLocalEmbeddingRequest

    def __post_init__(self) -> None:
        object.__setattr__(self, "request", parse_supported_local_embedding_request(self.request))

    @property
    def device(self) -> Literal["CPU", "CUDA"]:
        return self.request.resource_profile.device

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        if parse_supported_local_embedding_request(request) != self.request:
            raise ValueError("INDEX_MEMBERSHIP_REQUEST_MISMATCH")

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState:
        raise ValueError("INDEX_MEMBERSHIP_NUMERICAL_EXECUTION_FORBIDDEN")

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput | None:
        raise ValueError("INDEX_MEMBERSHIP_NUMERICAL_EXECUTION_FORBIDDEN")


def publish_prepared_index_membership(
    preparation: LocalEmbeddingServicePreparation,
    prepared: PreparedLocalEmbeddingReconciliation,
    selection: NativeCommandActorSelection,
) -> LocalEmbeddingReconciliationResult:
    """One original atomic START/claim/completion cycle; no hardware ownership is inferred."""
    request = prepared.request
    if (
        request is None
        or type(preparation) is not LocalEmbeddingServicePreparation
        or (
            prepared.observed.index_refresh_reason is None
            and prepared.observed.state is not ReconciliationState.RECOVERY_REQUIRED
        )
    ):
        raise ValueError("INDEX_MEMBERSHIP_PREPARATION_INVALID")
    actor_type, actor_id = supported_local_embedding_request_actor(request)
    if (
        type(selection) is not NativeCommandActorSelection
        or actor_type != "local_indexing_service"
        or selection.actor_type != actor_type
        or selection.actor_id != actor_id
        or selection.namespace != request.namespace
    ):
        raise ValueError("INDEX_MEMBERSHIP_SELECTION_INVALID")
    executor = CatalogNativeEmbeddingExecutor(
        owner=preparation.owner,
        publisher=preparation.publisher,
        execution_backend=MembershipOnlyEmbeddingExecution(request),
        runtime_profile=preparation.runtime_profile,
        source_commit=preparation.controls.source_commit,
    )
    submitted = LocalEmbeddingServiceReconciliation(
        executor, maximum_targets=preparation.maximum_targets
    ).submit_prepared(prepared)
    if submitted.workflow_id is None or submitted.command_id is None:
        raise ValueError("INDEX_MEMBERSHIP_SUBMISSION_INVALID")
    if submitted.workflow_state in {"FAILED", "CANCELLED"} or submitted.command_state in {
        "FAILED",
        "CANCELLED",
    }:
        return submitted
    if submitted.workflow_state != "COMPLETED":
        runner = build_local_indexing_workflow_runner(executor, selection)
        runner.run_once(submitted.workflow_id)
    with preparation.publisher.sessions.begin() as session:
        preparation.owner.resolve_sources(session, request)
        workflow = session.get(
            WorkflowInstanceRecord, submitted.workflow_id, populate_existing=True
        )
        command = session.get(WorkflowCommandRecord, submitted.command_id, populate_existing=True)
        if workflow is None or command is None or command.workflow_id != workflow.workflow_id:
            raise ValueError("INDEX_MEMBERSHIP_SUBMISSION_INVALID")
        completed = workflow.state == "COMPLETED" and command.state == "SUCCEEDED"
        terminal = workflow.state in {"FAILED", "CANCELLED"} or command.state in {
            "FAILED",
            "CANCELLED",
        }
        if completed:
            read_completed_local_embedding(session, preparation.owner, workflow)
        return replace(
            submitted,
            state=ReconciliationState.BATCH_COMPLETED
            if completed
            else (
                ReconciliationState.TERMINAL_INCOMPLETE
                if terminal
                else ReconciliationState.REPLAYED
            ),
            workflow_state=workflow.state,
            command_state=command.state,
        )

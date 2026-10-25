"""GPU-first namespace coordination over existing queues, preparation and finite execution."""

from __future__ import annotations

from dataclasses import replace

from eom_identity_service import PostgresLocalIndexingServiceFence
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
)

from eom_workflow_runner.document_embedding_batch_context import (
    document_embedding_batch_workflow_key,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.document_embedding_parent_preparation import (
    prepare_document_embedding_parent,
)
from eom_workflow_runner.document_embedding_routed_execution import (
    DrivenDocumentEmbeddingParent,
    drive_routed_document_embedding_parent_once,
)
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    ReconciliationState,
)
from eom_workflow_runner.local_indexing_routed_sources import PairedIndexingNamespacePreparation
from eom_workflow_runner.local_indexing_runner_composition import (
    build_local_indexing_workflow_runner,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    peek_command_candidate,
)


class RoutedLocalIndexingNamespaceRuntime:
    """One actual service namespace, not another queue or source authority.

    CPU work already selected earlier retains that device on recovery. New
    discovery goes through CUDA preparation; only a verified original BUSY
    result can choose CPU in the finite execution use case.
    """

    def __init__(
        self,
        pair: PairedIndexingNamespacePreparation,
        configuration: RoutedLocalIndexingOwnerConfiguration,
        launcher: FixedNativeIndexLauncher,
        service_fence: PostgresLocalIndexingServiceFence,
    ) -> None:
        if type(service_fence) is not PostgresLocalIndexingServiceFence:
            raise ValueError("LOCAL_INDEXING_SERVICE_RUNTIME_UNAVAILABLE")
        self.pair, self.configuration, self.launcher = pair, configuration, launcher
        self.service_fence = service_fence
        service_id = service_fence.pin.service.service_id
        self.namespace = pair.namespace
        self.gpu_selection = NativeCommandActorSelection(
            "local_indexing_service", service_id, self.namespace
        )
        cpu = CatalogNativeEmbeddingExecutor(
            owner=pair.cpu.owner,
            publisher=pair.cpu.publisher,
            execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
            runtime_profile=pair.cpu.runtime_profile,
            source_commit=pair.cpu.controls.source_commit,
        )
        self.cpu_runner = build_local_indexing_workflow_runner(
            cpu,
            NativeCommandActorSelection(
                "local_indexing_service",
                service_id,
                pair.cpu.owner.configuration.registry.namespace,
            ),
        )

    def run_once(self) -> WorkflowCommandRecord | None:
        """Drain the original CPU queue, never reselect its work as GPU."""
        return self.cpu_runner.run_once()

    def _pending_gpu(self) -> tuple[SupportedLocalEmbeddingRequest, str, str] | None:
        pair = self.pair
        with pair.cuda.publisher.sessions.begin() as session:
            self.service_fence.fence_current_service(session)
            candidate = peek_command_candidate(
                session,
                family=CommandExecutionFamily.LOCAL_EMBEDDING,
                actor_selection=self.gpu_selection,
            )
            if candidate is None:
                return None
            workflow = session.get(
                WorkflowInstanceRecord, candidate.workflow_id, populate_existing=True
            )
            if workflow is None:
                raise ValueError("LOCAL_INDEXING_ROUTED_WORKFLOW_MISSING")
            request = parse_supported_local_embedding_request(workflow.initial_request)
            pair.cuda.owner.resolve_sources(session, request)
            return request, workflow.workflow_id, workflow.idempotency_key

    def reconcile_once(self) -> LocalEmbeddingReconciliationResult:
        pending = self._pending_gpu()
        if pending is None:
            prepared = self.pair.cuda.prepare_once()
            observed, request = prepared.observed, prepared.request
            if request is None:
                return observed
        else:
            request, workflow_id, _key = pending
            observed = LocalEmbeddingReconciliationResult(
                ReconciliationState.RECOVERY_REQUIRED,
                request.graph_snapshot.graph_snapshot_revision_id,
                workflow_id=workflow_id,
            )
        parent = prepare_document_embedding_parent(self.pair, request, self.configuration)
        if pending is not None and pending[2] != document_embedding_batch_workflow_key(
            parent.request
        ):
            # Another original intent is not adopted or replaced just because its
            # source request happens to be semantically equivalent.
            return observed
        outcome = drive_routed_document_embedding_parent_once(
            parent, self.pair, request, self.launcher
        )
        if isinstance(outcome, DrivenDocumentEmbeddingParent):
            completed = (
                outcome.workflow_state == "COMPLETED" and outcome.command_state == "SUCCEEDED"
            )
            terminal = outcome.workflow_state in {
                "FAILED",
                "CANCELLED",
            } or outcome.command_state in {"FAILED", "CANCELLED"}
            return replace(
                observed,
                state=ReconciliationState.BATCH_COMPLETED
                if completed
                else ReconciliationState.TERMINAL_INCOMPLETE
                if terminal
                else ReconciliationState.REPLAYED,
                workflow_id=outcome.workflow_id,
                command_id=outcome.command_id,
                workflow_state=outcome.workflow_state,
                command_state=outcome.command_state,
            )
        if isinstance(outcome, ExistingEmbeddingBatchExecution):
            # Planning SUCCEEDED is not numerical or child completion. Supported
            # cold recovery is explicit; never dispatch another root here.
            return replace(observed, state=ReconciliationState.RECOVERY_REQUIRED)
        # Coverage-only is the existing no-demand result, not a zero-row model run.
        return replace(observed, state=ReconciliationState.UP_TO_DATE)

"""Finite original parent into existing INDEX/START, Runner, numerical and publication owners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)
from sqlalchemy import select

from eom_workflow_runner.document_embedding_batch_context import (
    document_embedding_batch_workflow_key,
)
from eom_workflow_runner.document_embedding_batch_driver import (
    DocumentBatchExecution,
    drive_document_embedding_batch_once,
    start_document_embedding_batch,
)
from eom_workflow_runner.document_embedding_catch_up import (
    DeferredDocumentEmbeddingParent,
    complete_document_catch_up,
    confirm_document_catch_up_cpu_backstop,
)
from eom_workflow_runner.document_embedding_cpu_batch_execution import (
    CatalogCpuDocumentBatchExecution,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.document_embedding_cuda_execution import (
    CatalogCudaDocumentEmbeddingExecution,
)
from eom_workflow_runner.document_embedding_parent_preparation import (
    PreparedDocumentEmbeddingParent,
)
from eom_workflow_runner.document_embedding_recovery import (
    CatalogRecoveredCudaDocumentEmbeddingExecution,
    read_document_embedding_completion,
)
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
)
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_submission import LocalEmbeddingCoverageOnly
from eom_workflow_runner.local_indexing_routed_sources import PairedIndexingNamespacePreparation
from eom_workflow_runner.local_indexing_runner_composition import (
    build_local_indexing_workflow_runner,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import NativeCommandActorSelection


@dataclass(frozen=True, slots=True)
class DrivenDocumentEmbeddingParent:
    """Fresh execution-state snapshot, not a canonical numerical or educational receipt."""

    device: Literal["CPU", "CUDA"]
    parent_request_sha256: str
    workflow_request_sha256: str
    workflow_id: str
    command_id: str
    workflow_state: str
    command_state: str


def _original_cpu_request(
    parent: PreparedDocumentEmbeddingParent,
    pair: PairedIndexingNamespacePreparation,
    request: SupportedLocalEmbeddingRequest,
) -> SupportedLocalEmbeddingRequest:
    """An existing original Workflow keeps its exact request, even across owner releases."""
    with parent.operation.publisher.sessions.begin() as session:
        pair.cuda.owner.resolve_sources(session, request)
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.idempotency_key
                == document_embedding_batch_workflow_key(parent.request)
            )
            .execution_options(populate_existing=True)
        )
        if workflow is not None:
            chosen = parse_supported_local_embedding_request(workflow.initial_request)
            pair.cpu.owner.resolve_sources(session, chosen)
            return chosen
    return pair.cpu.prepare_matching(pair.cuda, request, maximum_sources=pair.maximum_sources)


def drive_routed_document_embedding_parent_once(
    parent: PreparedDocumentEmbeddingParent,
    pair: PairedIndexingNamespacePreparation,
    request: SupportedLocalEmbeddingRequest,
    cpu_launcher: FixedNativeIndexLauncher,
) -> (
    DrivenDocumentEmbeddingParent
    | ExistingEmbeddingBatchExecution
    | LocalEmbeddingCoverageOnly
    | DeferredDocumentEmbeddingParent
):
    """One original physical context, no new allocation on a replay or fallback exception.

    A nonterminal outcome remains the original pending work. This method does
    not manufacture success, restart an unknown GPU or turn a hash/authority
    error into CPU work. Cold reconciliation delegates only an already committed
    original completion to its read-only recovery adapter.
    """
    if (
        type(parent) is not PreparedDocumentEmbeddingParent
        or type(pair) is not PairedIndexingNamespacePreparation
        or pair.cuda.publisher is not parent.operation.publisher
        or parent.request.parent_request_sha256 != request.request_sha256
    ):
        raise ValueError("DOCUMENT_BATCH_ROUTED_EXECUTION_INVALID")
    request = parse_supported_local_embedding_request(request)
    with parent.operation.publisher.sessions.begin() as session:
        pair.cuda.owner.resolve_sources(session, request)
    with parent.operation.open(parent.request, parent.allocation) as lane:
        backend: DocumentBatchExecution
        if isinstance(lane, ExistingEmbeddingBatchExecution):
            if (
                parent.reconciliation is not None
                and lane.history.route is not None
                and lane.history.route.decision.selected.backend.device == "CPU"
            ):
                return confirm_document_catch_up_cpu_backstop(parent, pair, request)
            if (
                lane.history.route is not None
                and lane.history.route.decision.selected.backend.device == "CPU"
            ):
                selected = pair.cpu
                chosen = _original_cpu_request(parent, pair, request)
                backend = CatalogCpuDocumentBatchExecution(
                    parent.operation,
                    parent.request,
                    lane,
                    selected.owner,
                    chosen,
                    FixedCpuDocumentEmbeddingExecution(cpu_launcher),
                )
            else:
                completed = read_document_embedding_completion(parent.operation, parent.request)
                if completed is None:
                    return lane
                selected, chosen = pair.cuda, request
                backend = CatalogRecoveredCudaDocumentEmbeddingExecution(
                    parent.operation, parent.request, completed, selected.owner, chosen
                )
        elif isinstance(lane, ActiveEmbeddingBatchExecution):
            selected, chosen = pair.cuda, request
            backend = CatalogCudaDocumentEmbeddingExecution(lane, selected.owner, chosen)
        else:
            assert isinstance(lane, UnavailableEmbeddingBatchExecution)
            if parent.reconciliation is not None:
                return confirm_document_catch_up_cpu_backstop(parent, pair, request)
            selected = pair.cpu
            chosen = _original_cpu_request(parent, pair, request)
            backend = CatalogCpuDocumentBatchExecution(
                parent.operation,
                parent.request,
                lane,
                selected.owner,
                chosen,
                FixedCpuDocumentEmbeddingExecution(cpu_launcher),
            )
        executor = CatalogNativeEmbeddingExecutor(
            owner=selected.owner,
            publisher=parent.operation.publisher,
            execution_backend=backend,
            runtime_profile=selected.runtime_profile,
            source_commit=parent.operation.source_commit,
        )
        submitted = start_document_embedding_batch(executor)
        if isinstance(submitted, LocalEmbeddingCoverageOnly):
            return submitted
        kind, actor_id = supported_local_embedding_request_actor(chosen)
        selection = (
            NativeCommandActorSelection(kind, actor_id, chosen.namespace)
            if kind == "local_indexing_service"
            else NativeCommandActorSelection(kind, actor_id)
        )
        runner = build_local_indexing_workflow_runner(executor, selection)
        drive_document_embedding_batch_once(executor, runner, submitted.workflow.workflow_id)
        with executor.publisher.sessions.begin() as session:
            selected.owner.resolve_sources(session, chosen)
            workflow = session.get(
                WorkflowInstanceRecord, submitted.workflow.workflow_id, populate_existing=True
            )
            command = session.get(
                WorkflowCommandRecord, submitted.command.command_id, populate_existing=True
            )
            if workflow is None or command is None or command.workflow_id != workflow.workflow_id:
                raise ValueError("DOCUMENT_BATCH_ROUTED_EXECUTION_INVALID")
            backend.validate_workflow(workflow)
            outcome = DrivenDocumentEmbeddingParent(
                backend.device,
                parent.request.request_sha256,
                chosen.request_sha256,
                workflow.workflow_id,
                submitted.command.command_id,
                workflow.state,
                command.state,
            )
        if (
            outcome.device == "CUDA"
            and outcome.workflow_state == "COMPLETED"
            and outcome.command_state == "SUCCEEDED"
        ):
            complete_document_catch_up(parent, pair, request, outcome.workflow_id)
        return outcome

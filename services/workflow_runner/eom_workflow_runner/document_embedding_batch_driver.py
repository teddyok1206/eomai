"""Existing atomic INDEX/START and purpose-only Runner for an original CUDA namespace batch."""

from __future__ import annotations

from eom_workflow.local_embedding_request_v2 import supported_local_embedding_request_actor

from eom_workflow_runner.document_embedding_cuda_execution import (
    CatalogCudaDocumentEmbeddingExecution,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_submission import (
    LocalEmbeddingSubmissionResult,
    LocalEmbeddingWorkflowSubmitted,
    start_local_embedding_in_session,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    admitted_workflow_definition,
)


def _backend(executor: CatalogNativeEmbeddingExecutor) -> CatalogCudaDocumentEmbeddingExecution:
    if not (
        type(executor) is CatalogNativeEmbeddingExecutor
        and type(executor.execution_backend) is CatalogCudaDocumentEmbeddingExecution
        and executor.owner is executor.execution_backend.owner
        and executor.publisher is executor.execution_backend.active.operation.publisher
    ):
        raise ValueError("DOCUMENT_BATCH_DRIVER_INVALID")
    return executor.execution_backend


def start_document_embedding_batch(
    executor: CatalogNativeEmbeddingExecutor,
) -> LocalEmbeddingSubmissionResult:
    """No direct Workflow rows: the supported use case retains current source/IAM and replay.

    A coverage-only result is not a numerical completion; the caller closes its
    unused physical parent. Another parent's equivalent Workflow is not adopted.
    """
    backend = _backend(executor)
    request = backend.request
    actor_type, actor_id = supported_local_embedding_request_actor(request)
    with executor.publisher.sessions.begin() as session:
        executor.owner.resolve_submission(session, request)
        definition = admitted_workflow_definition(
            session,
            definition_key=request.workflow_definition_key,
            definition_version=request.workflow_definition_version,
        )
        if definition is None or definition.definition_hash != request.workflow_definition_sha256:
            raise ValueError("DOCUMENT_BATCH_DRIVER_DEFINITION_INVALID")
        submitted = start_local_embedding_in_session(
            session,
            definition=definition,
            request=request,
            idempotency_key=backend.workflow_key,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=executor.owner,
            executor=executor,
        )
        if isinstance(submitted, LocalEmbeddingWorkflowSubmitted):
            backend.validate_workflow(submitted.workflow)
        return submitted


def drive_document_embedding_batch_once(
    executor: CatalogNativeEmbeddingExecutor, runner: WorkflowRunner, workflow_id: str
) -> WorkflowCommandRecord | None:
    """One existing claim/heartbeat/step/completion cycle; None is not a success receipt.

    Trusted composition supplies its purpose-only Runner; this application does
    not create another scheduler or infer a current session from stored IDs.
    Completed/index read and cold parent recovery retain their separate owners.
    """
    backend = _backend(executor)
    actor_type, actor_id = supported_local_embedding_request_actor(backend.request)
    if not (
        type(runner) is WorkflowRunner
        and runner.engine is executor.publisher.engine
        and runner.local_embedding_owner is executor.owner
        and runner.local_embedding_executor is executor
        and runner.command_families == frozenset({CommandExecutionFamily.LOCAL_EMBEDDING})
        and runner.command_actor_selection == NativeCommandActorSelection(actor_type, actor_id)
        and runner.available_roles == frozenset()
    ):
        raise ValueError("DOCUMENT_BATCH_DRIVER_RUNNER_INVALID")
    with executor.publisher.sessions.begin() as session:
        executor.owner.resolve_sources(session, backend.request)
        workflow = session.get(WorkflowInstanceRecord, workflow_id, populate_existing=True)
        if workflow is None or workflow.state not in {"REQUESTED", "RUNNING", "COMPLETED"}:
            raise ValueError("DOCUMENT_BATCH_DRIVER_WORKFLOW_INVALID")
        backend.validate_workflow(workflow)
    return runner.run_once(workflow_id)

"""Separate finite GPU catch-up over an immutable original CPU completion."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import uuid4

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationRequest,
    embedding_gpu_allocation_window_seconds,
)
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_identifiers import content_sha256
from eom_orchestrator.document_embedding_reconciliation_store import (
    DocumentEmbeddingReconciliationStore,
    DocumentReconciliationHistory,
)
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_workflow.document_embedding_reconciliation import (
    DOCUMENT_RECONCILIATION_PROTOCOL,
    DocumentEmbeddingReconciliationCompleted,
    DocumentEmbeddingReconciliationRequest,
    document_reconciliation_parent,
    prepare_document_reconciliation_intent,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation
from eom_workflow.embedding_batch_plan_family import SupportedEmbeddingBatchRequest
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_batch_context import (
    OriginalDocumentEmbeddingBatchContext,
    document_embedding_batch_workflow_key,
)
from eom_workflow_runner.document_embedding_parent_preparation import (
    PreparedDocumentEmbeddingParent,
)
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.local_embedding_completed_read import read_completed_local_embedding
from eom_workflow_runner.local_embedding_execution_context import native_embedding_registry_scope
from eom_workflow_runner.local_indexing_routed_sources import PairedIndexingNamespacePreparation
from eom_workflow_runner.models import WorkflowInstanceRecord


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_CATCH_UP_INVALID")


@dataclass(frozen=True, slots=True)
class DeferredDocumentEmbeddingParent:
    """Original GPU did not execute. Old CPU completion is reused, not a new success."""

    parent_request_sha256: str
    cpu_workflow_id: str


def _history(
    session: Session,
    operation: CatalogEmbeddingBatchExecution,
    parent: SupportedEmbeddingBatchRequest,
) -> EmbeddingBatchPlanHistory | None:
    with operation.admission.admit(session, parent) as sources:
        return EmbeddingBatchPlanStore(parent, sources.selection, sources.policy).read(session)


def _busy(history: EmbeddingBatchPlanHistory) -> None:
    route = history.route
    _require(
        history.failure is None
        and history.state in {"RUNNING", "SUCCEEDED"}
        and route is not None
        and route.decision.selected.backend.device == "CPU"
        and route.observation.status == "BUSY"
        and route.observation.phase == "PRE_EXECUTION"
        and route.observation.cuda_launch_state == "NOT_STARTED"
    )


def _cpu_basis(
    session: Session,
    operation: CatalogEmbeddingBatchExecution,
    origin: SupportedEmbeddingBatchRequest,
    original_history: EmbeddingBatchPlanHistory,
    pair: PairedIndexingNamespacePreparation,
    gpu_request: SupportedLocalEmbeddingRequest,
) -> tuple[DocumentEmbeddingReconciliationRequest, SupportedLocalEmbeddingRequest] | None:
    _busy(original_history)
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.idempotency_key == document_embedding_batch_workflow_key(origin)
        )
        .execution_options(populate_existing=True)
    )
    if workflow is None:
        return None
    _require(workflow.state not in {"FAILED", "CANCELLED"})
    if workflow.state != "COMPLETED":
        return None
    cpu_request = parse_supported_local_embedding_request(workflow.initial_request)
    route = original_history.route
    assert route is not None
    context = OriginalDocumentEmbeddingBatchContext(
        operation, origin, route.decision, pair.cpu.owner, cpu_request
    )
    context.validate_workflow(workflow)
    gpu = pair.cuda.owner.resolve_sources(session, gpu_request)
    cpu = pair.cpu.owner.resolve_sources(session, cpu_request)
    _require(
        cpu_request.resource_profile.device == "CPU"
        and gpu_request.resource_profile.device == "CUDA"
        and origin.parent_request_sha256 == gpu_request.request_sha256
        and cpu.admission.plan.recipe == gpu.admission.plan.recipe
        and {s.item_revision_id: s for s in cpu.admission.plan.sources}
        == {s.item_revision_id: s for s in gpu.admission.plan.sources}
    )
    output = read_completed_local_embedding(session, pair.cpu.owner, workflow)
    body = dict(
        schema_version=DOCUMENT_RECONCILIATION_PROTOCOL,
        message_type="REQUEST",
        source_request_sha256=gpu_request.request_sha256,
        origin_parent_job_id=original_history.job_id,
        origin_parent_request_sha256=origin.request_sha256,
        scope=origin.scope.model_dump(mode="json"),
        cpu_request_sha256=cpu_request.request_sha256,
        cpu_output=output.model_dump(mode="json"),
    )
    return (
        DocumentEmbeddingReconciliationRequest.model_validate(
            body | {"request_sha256": content_sha256(body)}
        ),
        cpu_request,
    )


def _fence(
    session: Session,
    pair: PairedIndexingNamespacePreparation,
    gpu: SupportedLocalEmbeddingRequest,
    cpu: SupportedLocalEmbeddingRequest,
) -> None:
    for preparation, request in ((pair.cuda, gpu), (pair.cpu, cpu)):
        owner = preparation.owner
        owner.fence_current_actor(session, request)
        owner.catalog.authorize_scope(
            session, owner.registry_caller(request), native_embedding_registry_scope(request)
        )


def _selected(
    base: PreparedDocumentEmbeddingParent,
    request: DocumentEmbeddingReconciliationRequest,
    history: DocumentReconciliationHistory,
    pair: PairedIndexingNamespacePreparation,
) -> PreparedDocumentEmbeddingParent:
    parent = document_reconciliation_parent(base.request, history.intent)
    body = base.allocation.control_request.model_dump(mode="json", exclude={"message_sha256"})
    body["parent_request_sha256"] = parent.request_sha256
    body["allocation_attempt_id"] = "embeddingallocation_" + uuid4().hex
    body["expires_monotonic_ns"] = (
        time.monotonic_ns()
        + embedding_gpu_allocation_window_seconds(
            min(
                pair.cuda.runtime_profile.resource_profile.timeout_seconds,
                MAX_EMBEDDING_WORK_BATCH_SECONDS,
            )
        )
        * 10**9
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        body | {"message_sha256": content_sha256(body)}
    )
    body = base.allocation.model_dump(mode="json", exclude={"record_sha256"})
    body |= dict(
        request_sha256=parent.request_sha256, control_request=control.model_dump(mode="json")
    )
    allocation = EmbeddingBatchAllocation.model_validate(
        body | {"record_sha256": content_sha256(body)}
    )
    return PreparedDocumentEmbeddingParent(
        base.operation, parent, allocation, request, history.intent
    )


def prepare_document_catch_up_parent(
    base: PreparedDocumentEmbeddingParent,
    pair: PairedIndexingNamespacePreparation,
    gpu_request: SupportedLocalEmbeddingRequest,
) -> PreparedDocumentEmbeddingParent:
    """Current source/CPU proof → indexed CAS head; never open a physical allocation here."""
    _require(base.reconciliation is None)
    with base.operation.publisher.sessions.begin() as session:
        pair.cuda.owner.resolve_sources(session, gpu_request)
        original = _history(session, base.operation, base.request)
        if original is None or original.route is None:
            return base
        if original.route.decision.selected.backend.device == "CUDA":
            return base
        proof = _cpu_basis(session, base.operation, base.request, original, pair, gpu_request)
        if proof is None:
            return base
        request, cpu_request = proof
        store = DocumentEmbeddingReconciliationStore(request)
        history = store.read(session)
        if history is None:
            first = prepare_document_reconciliation_intent(
                request,
                base.request,
                ordinal=1,
                previous_parent_job_id=original.job_id,
                previous_parent_request_sha256=base.request.request_sha256,
            )
            history = store.ensure(
                session, first, authorize=lambda: _fence(session, pair, gpu_request, cpu_request)
            )
        selected = _selected(base, request, history, pair)
        current = _history(session, base.operation, selected.request)
        if history.completion is not None or current is None or current.route is None:
            return selected
        if current.route.decision.selected.backend.device == "CUDA":
            return selected
        _busy(current)
        # Catch-up has no new CPU child. Its backstop is the pinned original
        # completion. An unexpected binding is not silently adopted or replaced.
        _require(current.bound is None)
        successor = prepare_document_reconciliation_intent(
            request,
            base.request,
            ordinal=history.intent.ordinal + 1,
            previous_parent_job_id=current.job_id,
            previous_parent_request_sha256=selected.request.request_sha256,
        )
        advanced = store.advance(
            session,
            history.intent,
            successor,
            authorize=lambda: _fence(session, pair, gpu_request, cpu_request),
        )
        return _selected(base, request, advanced, pair)


def confirm_document_catch_up_cpu_backstop(
    parent: PreparedDocumentEmbeddingParent,
    pair: PairedIndexingNamespacePreparation,
    gpu_request: SupportedLocalEmbeddingRequest,
) -> DeferredDocumentEmbeddingParent:
    """A verified new BUSY outcome reuses old CPU bytes; no new CPU Workflow/model."""
    _require(parent.reconciliation is not None and parent.intent is not None)
    assert parent.reconciliation is not None
    with parent.operation.publisher.sessions.begin() as session:
        pair.cuda.owner.resolve_sources(session, gpu_request)
        current = _history(session, parent.operation, parent.request)
        _require(current is not None)
        assert current is not None
        _busy(current)
        _require(current.bound is None)
        store = DocumentEmbeddingReconciliationStore(parent.reconciliation)
        origin = store.origin_parent(session)
        original = _history(session, parent.operation, origin)
        assert original is not None
        proof = _cpu_basis(session, parent.operation, origin, original, pair, gpu_request)
        _require(proof is not None and proof[0] == parent.reconciliation)
        assert proof is not None
        head = store.read(session)
        _require(head is not None and head.intent == parent.intent and head.completion is None)
        _fence(session, pair, gpu_request, proof[1])
        return DeferredDocumentEmbeddingParent(
            parent.request.request_sha256, parent.reconciliation.cpu_output.workflow_id
        )


def complete_document_catch_up(
    parent: PreparedDocumentEmbeddingParent,
    pair: PairedIndexingNamespacePreparation,
    gpu_request: SupportedLocalEmbeddingRequest,
    workflow_id: str,
) -> None:
    """Only a real completed CUDA child closes the audit history; CPU work stays unchanged."""
    if parent.reconciliation is None:
        return
    assert parent.intent is not None
    with parent.operation.publisher.sessions.begin() as session:
        pair.cuda.owner.resolve_sources(session, gpu_request)
        workflow = session.get(WorkflowInstanceRecord, workflow_id, populate_existing=True)
        _require(workflow is not None)
        assert workflow is not None
        _require(
            workflow.idempotency_key == document_embedding_batch_workflow_key(parent.request)
            and workflow.initial_request == gpu_request.model_dump(mode="json")
            and gpu_request.resource_profile.device == "CUDA"
        )
        output = read_completed_local_embedding(session, pair.cuda.owner, workflow)
        body = dict(
            schema_version=DOCUMENT_RECONCILIATION_PROTOCOL,
            message_type="COMPLETED",
            reconciliation_request_sha256=parent.reconciliation.request_sha256,
            intent_sha256=parent.intent.intent_sha256,
            output=output.model_dump(mode="json"),
        )
        completion = DocumentEmbeddingReconciliationCompleted.model_validate(
            body | {"completion_sha256": content_sha256(body)}
        )

        def authorize() -> None:
            owner = pair.cuda.owner
            owner.fence_current_actor(session, gpu_request)
            owner.catalog.authorize_scope(
                session,
                owner.registry_caller(gpu_request),
                native_embedding_registry_scope(gpu_request),
            )

        DocumentEmbeddingReconciliationStore(parent.reconciliation).complete(
            session,
            completion,
            authorize=authorize,
        )

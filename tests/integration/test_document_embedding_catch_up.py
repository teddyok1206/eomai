"""Actual paired Catalog/index/Workflow/Job IO; OS/root/model leaves explicitly synthetic."""

import time
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_allocation_window_seconds
from eom_orchestrator.document_embedding_reconciliation_store import (
    DocumentEmbeddingReconciliationStore,
)
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow_runner.document_embedding_catch_up import (
    DeferredDocumentEmbeddingParent,
    prepare_document_catch_up_parent,
)
from eom_workflow_runner.document_embedding_parent_preparation import (
    PreparedDocumentEmbeddingParent,
)
from eom_workflow_runner.document_embedding_routed_execution import (
    DrivenDocumentEmbeddingParent,
    drive_routed_document_embedding_parent_once,
)
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.integration.embedding_batch_root_fixtures import configure_synthetic_batch_runtime
from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def completed_cpu(value):
    original = value.start()
    assert value.advance(*original) is True
    value.finish(*original)
    assert value.launcher.forwards == 1
    return original, PreparedDocumentEmbeddingParent(
        value.gpu.operation, value.gpu.request, value.gpu.allocation
    )


def prepare(value, base):
    return prepare_document_catch_up_parent(base, value.gpu.pair, value.gpu.source_request)


def native(value, parent, status, monkeypatch):
    root = copy(value.gpu)
    root.request, root.allocation = parent.request, parent.allocation
    configure_synthetic_batch_runtime(root, monkeypatch, allocation_status=status)
    return root


@pytest.mark.parametrize("execution", ["cpu_fallback_catchup"], indirect=True)
def test_original_cpu_once_then_busy_without_cpu_duplication_then_cuda_completion(
    execution, monkeypatch
):
    value = execution
    original, base = completed_cpu(value)
    first = prepare(value, base)
    assert first.intent.ordinal == 1 and first.request != base.request
    busy = native(value, first, "BUSY", monkeypatch)
    deferred = drive_routed_document_embedding_parent_once(
        first, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert type(deferred) is DeferredDocumentEmbeddingParent
    assert deferred.cpu_workflow_id == original[0].workflow_id
    assert len(busy.dispatches) == 1 and value.launcher.forwards == 1
    second = prepare(value, base)
    assert second.intent.ordinal == 2 and second.request != first.request
    ready = native(value, second, "READY", monkeypatch)
    done = drive_routed_document_embedding_parent_once(
        second, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert type(done) is DrivenDocumentEmbeddingParent
    assert done.device == "CUDA" and done.workflow_state == "COMPLETED"
    assert done.command_state == "SUCCEEDED" and len(ready.dispatches) == 1 and ready.acked
    assert value.launcher.forwards == 1
    with value.sessions.begin() as session:
        cursor = DocumentEmbeddingReconciliationStore(second.reconciliation).read(session)
        assert cursor.completion.output.workflow_id == done.workflow_id
        assert session.get(WorkflowInstanceRecord, original[0].workflow_id).state == "COMPLETED"
    replay = drive_routed_document_embedding_parent_once(
        second, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert type(replay) is DrivenDocumentEmbeddingParent
    assert replay.workflow_id == done.workflow_id and len(ready.dispatches) == 1
    assert prepare(value, base).intent == second.intent
    assert value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback_catchup"], indirect=True)
def test_unknown_original_gpu_allocation_is_neither_cpu_retry_nor_another_intent(
    execution, monkeypatch
):
    value = execution
    _original, base = completed_cpu(value)
    selected = prepare(value, base)
    with (
        value.sessions.begin() as session,
        selected.operation.admission.admit(session, selected.request) as sources,
    ):
        history, created = EmbeddingBatchPlanStore(
            selected.request, sources.selection, sources.policy
        ).allocate(session, selected.allocation)
        assert created and history.state == "CLAIMED"
    replay = prepare(value, base)
    assert replay.intent == selected.intent and replay.request == selected.request
    root = native(value, replay, "READY", monkeypatch)
    outcome = drive_routed_document_embedding_parent_once(
        replay, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert type(outcome) is ExistingEmbeddingBatchExecution
    assert outcome.history == history
    assert root.dispatches == [] and value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback_catchup"], indirect=True)
def test_concurrent_preparation_selects_same_future_parent_without_allocating_a_root(execution):
    value = execution
    _original, base = completed_cpu(value)
    gate = Barrier(2)
    before = time.monotonic_ns()

    def select(_index):
        gate.wait(timeout=30)
        return prepare(value, base)

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(select, range(2)))
    assert left.request == right.request and left.intent == right.intent
    assert left.allocation != right.allocation
    after = time.monotonic_ns()
    budget = (
        embedding_gpu_allocation_window_seconds(
            min(value.gpu.pair.cuda.runtime_profile.resource_profile.timeout_seconds, 180)
        )
        * 10**9
    )
    for parent in (left, right):
        assert (
            before + budget
            <= parent.allocation.control_request.expires_monotonic_ns
            <= after + budget
        )
    assert value.launcher.forwards == 1 and len(value.gpu.dispatches) == 1


@pytest.mark.parametrize("execution", ["cpu_fallback_catchup"], indirect=True)
@pytest.mark.parametrize("fault", ("revoked", "failed_cpu"))
def test_source_denial_or_failed_cpu_history_never_creates_a_gpu_successor(execution, fault):
    value = execution
    original, base = completed_cpu(value)
    if fault == "revoked":
        value.current.allowed = False
    else:
        with value.sessions.begin() as session:
            session.get(WorkflowInstanceRecord, original[0].workflow_id).state = "FAILED"
    with pytest.raises((ValueError, AssertionError)):
        prepare(value, base)
    assert value.launcher.forwards == 1 and len(value.gpu.dispatches) == 1


@pytest.mark.parametrize("execution", ["cpu_fallback_catchup"], indirect=True)
def test_crash_after_original_busy_before_cpu_start_keeps_original_cpu_workflow_and_device(
    execution, monkeypatch
):
    value = execution
    base = PreparedDocumentEmbeddingParent(
        value.gpu.operation, value.gpu.request, value.gpu.allocation
    )
    # Explicit source-preparation seam: the operator fixture already published
    # this exact CPU plan. Production uses its actual service preparation/grant.
    matched = Mock(return_value=value.request)
    monkeypatch.setattr(value.gpu.pair.cpu, "prepare_matching", matched)
    original = drive_routed_document_embedding_parent_once(
        base, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert type(original) is DrivenDocumentEmbeddingParent
    assert original.device == "CPU" and original.workflow_state == "COMPLETED"
    assert matched.call_count == 1 and value.launcher.forwards == 1
    matched.side_effect = AssertionError("replay rebuilt the original CPU request")
    replay = drive_routed_document_embedding_parent_once(
        base, value.gpu.pair, value.gpu.source_request, value.launcher
    )
    assert replay.workflow_id == original.workflow_id and replay.device == "CPU"
    assert value.launcher.forwards == 1 and len(value.gpu.dispatches) == 1
    assert prepare(value, base).intent.ordinal == 1

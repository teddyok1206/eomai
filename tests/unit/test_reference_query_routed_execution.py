"""Real original selection/publication; explicit synthetic route/channel/Runner leaves."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow_runner import reference_query_routed_execution as module
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
)
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.reference_query_prepare_application import NativeReferenceQueryPreparation
from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession
from sqlalchemy.orm import Session

from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected
from tests.unit.test_reference_query_routed_selection import selection_case


@pytest.fixture
def original(tmp_path, monkeypatch, selected):
    value = selection_case(tmp_path, monkeypatch, selected)
    value.prepared = value.app.prepare(value.requests, idempotency_key="original-drive-test")
    cpu = Mock(spec=NativeReferenceQueryPreparation)
    cpu.owner = value.app.cpu
    value.session = RoutedReferenceQuerySession(cpu, value.app)
    return value


def pending(value):
    return module.RoutedReferenceQueryObservation(
        value.prepared.preparation.parent.request_sha256,
        None,
        "PENDING",
        tuple(
            module.RoutedReferenceQueryChildObservation(i, None, "PENDING", None) for i in range(2)
        ),
    )


def install_lane(monkeypatch, original, lane, *, existing=None):
    calls = []

    @contextmanager
    def opened(operation, parent, allocation):
        assert operation is original.prepared.operation
        assert parent == original.prepared.preparation.parent
        calls.append(allocation)
        yield lane

    monkeypatch.setattr(CatalogEmbeddingBatchExecution, "open", opened)
    monkeypatch.setattr(module, "_history", lambda _p: existing)
    observation = pending(original)
    monkeypatch.setattr(module, "observe_routed_reference_queries", lambda *_a: observation)
    return calls


def test_unallocated_original_is_pending_without_inventing_workflow_or_dispatch(
    original, monkeypatch
):
    store = Mock()
    store.read.return_value = None
    monkeypatch.setattr(module, "EmbeddingBatchPlanStore", lambda *_a: store)
    scalars = Session.scalars

    def empty_workflows(session, statement, *args, **kwargs):
        if statement.column_descriptions[0].get("entity") is WorkflowInstanceRecord:
            return iter(())  # The indexed workflow read is a synthetic leaf here.
        return scalars(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalars", empty_workflows)
    dispatch = Mock(side_effect=AssertionError("read must not allocate"))
    monkeypatch.setattr(CatalogEmbeddingBatchExecution, "open", dispatch)
    assert module.observe_routed_reference_queries(original.session, original.prepared) == pending(
        original
    )
    dispatch.assert_not_called()


def test_current_source_revocation_precedes_workflow_lookup(original, monkeypatch):
    original.deny = True
    store = Mock(side_effect=AssertionError("no plan read after denial"))
    monkeypatch.setattr(module, "EmbeddingBatchPlanStore", store)
    with pytest.raises(ValueError, match="SYNTHETIC_ACTUAL_SOURCE_DENIED"):
        module.observe_routed_reference_queries(original.session, original.prepared)
    store.assert_not_called()


@pytest.mark.parametrize("state", ("READY", "FAILED"))
def test_terminal_observation_does_not_open_or_replay_an_execution(original, monkeypatch, state):
    observation = module.RoutedReferenceQueryObservation(
        original.prepared.preparation.parent.request_sha256, "CUDA", state, ()
    )
    monkeypatch.setattr(module, "observe_routed_reference_queries", lambda *_a: observation)
    opened = Mock(side_effect=AssertionError("no new physical side effect"))
    monkeypatch.setattr(CatalogEmbeddingBatchExecution, "open", opened)
    assert (
        module.drive_routed_reference_queries_once(original.session, original.prepared)
        is observation
    )
    opened.assert_not_called()


def test_active_cuda_uses_existing_batch_runner_and_always_closes_group(original, monkeypatch):
    active = Mock(spec=ActiveEmbeddingBatchExecution)
    active.history = Mock()
    calls = install_lane(monkeypatch, original, active)
    group, executor = Mock(), Mock()
    monkeypatch.setattr(module, "CatalogReferenceQueryBatchGroup", lambda a, o: group)
    monkeypatch.setattr(module, "CatalogBatchReferenceQueryExecutor", lambda g: executor)
    contexts = (Mock(), Mock())
    monkeypatch.setattr(module, "_contexts", lambda *_a: contexts)
    started = Mock(return_value=("workflow_" + "a" * 32, "workflow_" + "b" * 32))
    driven = Mock()
    monkeypatch.setattr(module, "start_batch_reference_queries", started)
    monkeypatch.setattr(module, "drive_batch_reference_queries", driven)
    forbidden = Mock(side_effect=AssertionError("CUDA does not borrow CPU"))
    monkeypatch.setattr(module, "_drive_cpu", forbidden)
    module.drive_routed_reference_queries_once(original.session, original.prepared)
    assert len(calls) == 1
    started.assert_called_once_with(executor, contexts)
    driven.assert_called_once_with(executor, started.return_value)
    group.abort.assert_called_once()
    forbidden.assert_not_called()


def test_cuda_error_is_not_cpu_permission_and_does_not_erase_original(original, monkeypatch):
    active = Mock(spec=ActiveEmbeddingBatchExecution)
    active.history = Mock()
    install_lane(monkeypatch, original, active)
    group = Mock()
    monkeypatch.setattr(module, "CatalogReferenceQueryBatchGroup", lambda *_a: group)
    monkeypatch.setattr(module, "CatalogBatchReferenceQueryExecutor", lambda *_a: Mock())
    monkeypatch.setattr(module, "_contexts", lambda *_a: ())
    monkeypatch.setattr(
        module, "start_batch_reference_queries", Mock(side_effect=RuntimeError("synthetic CUDA"))
    )
    forbidden = Mock(side_effect=AssertionError("no exception fallback"))
    monkeypatch.setattr(module, "_drive_cpu", forbidden)
    with pytest.raises(RuntimeError, match="synthetic CUDA"):
        module.drive_routed_reference_queries_once(original.session, original.prepared)
    group.abort.assert_called_once()
    forbidden.assert_not_called()
    assert original.app.prepare(
        original.requests, idempotency_key="original-drive-test"
    ).manifest == (original.prepared.manifest)


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_existing_route_keeps_original_allocation_and_never_creates_a_new_candidate(
    original, monkeypatch, device
):
    history = SimpleNamespace(
        allocation=Mock(),
        failure=None,
        route=SimpleNamespace(
            decision=SimpleNamespace(
                selected=SimpleNamespace(backend=SimpleNamespace(device=device))
            )
        ),
    )
    lane = ExistingEmbeddingBatchExecution(history)
    calls = install_lane(monkeypatch, original, lane, existing=history)
    cpu = Mock()
    monkeypatch.setattr(module, "_drive_cpu", cpu)
    candidate = Mock(side_effect=AssertionError("never reallocate an original"))
    monkeypatch.setattr(type(original.prepared), "allocation_candidate", candidate)
    assert (
        module.drive_routed_reference_queries_once(original.session, original.prepared).state
        == "PENDING"
    )
    assert calls == [history.allocation]
    candidate.assert_not_called()
    if device == "CPU":
        cpu.assert_called_once_with(original.session, original.prepared, lane)
    else:
        cpu.assert_not_called()


def test_foreign_session_cannot_observe_or_drive_original(original):
    foreign = Mock(spec=NativeReferenceQueryPreparation)
    foreign.owner = Mock()
    with pytest.raises(ValueError, match="REFERENCE_QUERY_ROUTED_EXECUTION_INVALID"):
        module.drive_routed_reference_queries_once(
            RoutedReferenceQuerySession(foreign, original.app), original.prepared
        )

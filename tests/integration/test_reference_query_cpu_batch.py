"""Guarded PostgreSQL parent binding; current child IAM/lease/numerics are synthetic."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_workflow_runner.reference_query_cpu_batch import (
    CatalogCpuReferenceQueryBatchGroup,
    RoutedCpuReferenceQueryExecution,
)

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.reference_query_cpu_batch_fixtures import cpu_batch_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def grouped(guarded_engine, tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", workspace_root=tmp_path, nas_artifact_root=artifacts
        ),
    )
    return cpu_batch_case(tmp_path, monkeypatch, publisher=publisher)


def history(value):
    with value.publisher.sessions.begin() as session:
        return value.store.read(session)


def complete(value):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(value.group.join, value.materials[i], value.sources[i]) for i in (1, 0)
        ]
        for future in futures:
            future.result(timeout=20)


def test_out_of_order_prepare_binds_once_in_original_order_without_any_model(grouped):
    before = history(grouped)
    assert before.state == "RUNNING" and before.bound is None
    complete(grouped)
    saved = history(grouped)
    assert saved.state == "SUCCEEDED" and saved.bound is not None
    assert tuple(row.workflow_id for row in saved.bound.children) == tuple(
        value.association.workflow_id for value in grouped.materials
    )
    assert {row.native_input_sha256 for row in saved.bound.children} == {
        value.request.request_sha256 for value in grouped.materials
    }
    assert set(grouped.source_calls) == {source.launch.workflow_id for source in grouped.sources}
    assert saved.route == before.route and saved.allocation == before.allocation


def test_cold_already_bound_child_does_not_wait_for_completed_siblings_or_rebind(grouped):
    complete(grouped)
    saved = history(grouped)
    fresh = CatalogCpuReferenceQueryBatchGroup(
        grouped.operation, grouped.request, grouped.original, grouped.query_owner
    )
    fresh.join(grouped.materials[1], grouped.sources[1])
    assert history(grouped) == saved


def test_current_source_revocation_wakes_waiting_child_and_never_binds(grouped):
    entered = Event()

    def first():
        entered.set()
        grouped.group.join(grouped.materials[0], grouped.sources[0])

    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting = pool.submit(first)
        assert entered.wait(2)
        grouped.denied_child = grouped.sources[1].launch.workflow_id
        rejected = pool.submit(grouped.group.join, grouped.materials[1], grouped.sources[1])
        with pytest.raises(ValueError, match="REVOKED"):
            rejected.result(timeout=10)
        with pytest.raises(ValueError):
            waiting.result(timeout=10)
    assert history(grouped).bound is None


def test_expired_gather_does_not_bind_partial_batch_or_start_cpu(grouped):
    grouped.group._deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError):
        grouped.group.join(grouped.materials[0], grouped.sources[0])
    assert history(grouped).bound is None


def test_changed_bound_child_is_not_reused_or_replaced(grouped):
    complete(grouped)
    saved = history(grouped)
    first = grouped.materials[0]
    other = grouped.sources[1]
    with pytest.raises(ValueError):
        grouped.group.join(first, other)
    assert history(grouped) == saved


def test_cpu_strategy_requires_exact_group_owner_before_touching_launcher(grouped):
    from eom_workflow_runner.reference_query_cpu_execution import CpuReferenceQueryExecutionContext

    launcher = Mock()
    adapter = RoutedCpuReferenceQueryExecution(grouped.group, launcher)
    source = grouped.sources[0]
    foreign = CpuReferenceQueryExecutionContext(Mock(), source.command_lease)
    with pytest.raises(ValueError):
        adapter.run(grouped.materials[0], source=foreign)
    launcher.run.assert_not_called()


def test_cpu_strategy_keeps_explicit_original_workflow_fence_outside_another_runner_context(
    grouped, monkeypatch
):
    from contextlib import contextmanager
    from contextvars import ContextVar

    from eom_workflow_runner import reference_query_cpu_batch as module
    from eom_workflow_runner.reference_query_cpu_execution import CpuReferenceQueryExecutionContext

    complete(grouped)
    material, source = grouped.materials[0], grouped.sources[0]
    foreign_context = ContextVar("synthetic_foreign_query_context")
    foreign_context.set(grouped.materials[1].association.workflow_id)
    calls = []

    @contextmanager
    def explicit(factory, *, owner, workflow_id, request, lease):
        assert foreign_context.get() != workflow_id
        assert (
            owner is grouped.query_owner
            and request == material.workflow_request
            and lease == source.command_lease
        )
        calls.append(workflow_id)
        with factory.begin() as session:
            session.info["source_workflow"] = workflow_id
            yield session

    monkeypatch.setattr(module, "native_fenced_runner_transaction", explicit)
    launcher = Mock()
    adapter = RoutedCpuReferenceQueryExecution(grouped.group, launcher)
    context = CpuReferenceQueryExecutionContext(grouped.query_owner, source.command_lease)
    assert adapter.run(material, source=context) is launcher.run.return_value
    assert calls == [material.association.workflow_id] * 2
    launcher.run.assert_called_once_with(material)


def test_interrupted_parent_bind_rolls_back_and_wakes_siblings_without_numerical_work(
    grouped, monkeypatch
):
    from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore

    before = history(grouped)
    original = EmbeddingBatchPlanStore.bind
    waiting = Event()
    condition_wait = grouped.group._condition.wait

    def observed_wait(timeout):
        waiting.set()
        return condition_wait(timeout)

    def interrupted(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic parent bind interruption")

    monkeypatch.setattr(grouped.group._condition, "wait", observed_wait)
    monkeypatch.setattr(EmbeddingBatchPlanStore, "bind", interrupted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(grouped.group.join, grouped.materials[0], grouped.sources[0])
        assert waiting.wait(10)
        second = pool.submit(grouped.group.join, grouped.materials[1], grouped.sources[1])
        with pytest.raises(KeyboardInterrupt, match="bind interruption"):
            second.result(timeout=15)
        with pytest.raises(ValueError):
            first.result(timeout=15)
    assert history(grouped) == before

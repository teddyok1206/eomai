"""Real bounded threads, synthetic existing owner leaves; no model or live grant."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_orchestrator import background_storage, host_package_maintenance
from eom_workflow_runner import local_indexing_service_entry as entry
from eom_workflow_runner import native_cpu_scheduling_read as scheduling
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    ReconciliationState,
)
from eom_workflow_runner.local_indexing_cpu_lane import LocalIndexingCpuLane
from eom_workflow_runner.local_indexing_routed_namespace import RoutedLocalIndexingNamespaceRuntime


def leaf(view="CONCRETE_FACETS"):
    value = Mock(spec=RoutedLocalIndexingNamespaceRuntime)
    value.namespace = SimpleNamespace(view=view)
    value.run_once.return_value = None
    value.reconcile_once.return_value = LocalEmbeddingReconciliationResult(
        ReconciliationState.UP_TO_DATE, "graph"
    )
    return value


def runtime(*namespaces):
    return SimpleNamespace(
        namespaces=namespaces, engine=Mock(), configuration=SimpleNamespace(poll_interval_seconds=5)
    )


def command():
    return SimpleNamespace(workflow_id="original", command_id="original-command", state="SUCCEEDED")


@pytest.fixture(autouse=True)
def synthetic_capacity(monkeypatch):
    monkeypatch.setattr(background_storage, "require_background_write_capacity", Mock())
    monkeypatch.setattr(host_package_maintenance, "require_host_package_maintenance_idle", Mock())
    read = Mock(return_value=False)
    monkeypatch.setattr(scheduling, "should_defer_background_cpu_claim", read)
    return read


def test_gpu_progresses_while_cpu_command_is_still_running(capsys):
    started, release, finished, stop = Event(), Event(), Event(), Event()
    namespace = leaf()

    def cpu():
        started.set()
        assert release.wait(5), "GPU discovery was blocked by the CPU command"
        finished.set()
        return command()

    def gpu():
        assert started.wait(5)
        assert not finished.is_set()
        stop.set()
        release.set()
        return LocalEmbeddingReconciliationResult(ReconciliationState.BATCH_COMPLETED, "graph")

    namespace.run_once.side_effect = cpu
    namespace.reconcile_once.side_effect = gpu
    try:
        entry.serve_local_indexing(runtime(namespace), stop)
    finally:
        release.set()
    assert finished.is_set()
    namespace.run_once.assert_called_once()
    namespace.reconcile_once.assert_called_once()
    output = capsys.readouterr().out
    assert output.count("LOCAL_INDEXING_COMMAND_OBSERVED") == 1
    assert output.count("LOCAL_INDEXING_RECONCILIATION_STARTED") == 1


def test_cpu_lane_has_one_outstanding_call_and_round_robins_without_unbounded_queue():
    started, release, stop = Event(), Event(), Event()
    first, second = leaf("CONTENT_ONLY"), leaf("CONCRETE_FACETS")
    observed = Mock()

    def blocked():
        started.set()
        assert release.wait(5)
        return command()

    first.run_once.side_effect = blocked
    second.run_once.return_value = command()
    with ThreadPoolExecutor(max_workers=1) as executor:
        lane = LocalIndexingCpuLane(executor, (first, second), stop, observed)
        try:
            lane.start_next()
            assert started.wait(5)
            for _ in range(100):
                lane.poll()
                lane.start_next()
            first.run_once.assert_called_once()
            second.run_once.assert_not_called()
            release.set()
            lane.poll(wait=True)
            lane.start_next()
            lane.poll(wait=True)
            lane.poll()
        finally:
            release.set()
            lane.drain()
    second.run_once.assert_called_once()
    assert [call.args[0] for call in observed.call_args_list] == ["CONTENT_ONLY", "CONCRETE_FACETS"]


def test_two_gpu_batches_can_finish_before_one_slow_cpu_call(monkeypatch):
    namespace, started, release, stop = leaf(), Event(), Event(), Event()
    calls = []

    def cpu():
        started.set()
        assert release.wait(5)
        return command()

    def gpu():
        assert started.wait(5)
        assert not release.is_set()
        calls.append("GPU")
        if len(calls) == 2:
            stop.set()
            release.set()
        return LocalEmbeddingReconciliationResult(ReconciliationState.BATCH_COMPLETED, "graph")

    namespace.run_once.side_effect = cpu
    namespace.reconcile_once.side_effect = gpu
    selected = runtime(namespace)
    selected.configuration.poll_interval_seconds = 0  # synthetic clock, not an operating policy
    monkeypatch.setattr(stop, "wait", lambda _seconds: False)
    try:
        entry.serve_local_indexing(selected, stop)
    finally:
        release.set()
    assert calls == ["GPU", "GPU"]
    namespace.run_once.assert_called_once()


def test_cpu_failure_is_reported_once_not_retried_or_hidden_by_drain():
    namespace, stop, observed = leaf(), Event(), Mock()
    namespace.run_once.side_effect = ValueError("synthetic CPU failure")
    with ThreadPoolExecutor(max_workers=1) as executor:
        lane = LocalIndexingCpuLane(executor, (namespace,), stop, observed)
        lane.start_next()
        with pytest.raises(ValueError, match="synthetic CPU failure"):
            lane.poll(wait=True)
        lane.drain()
    namespace.run_once.assert_called_once()
    observed.assert_not_called()


def test_stop_before_cpu_start_cannot_claim_a_command():
    namespace, stop = leaf(), Event()
    stop.set()
    with ThreadPoolExecutor(max_workers=1) as executor:
        lane = LocalIndexingCpuLane(executor, (namespace,), stop, Mock())
        lane.start_next()
        lane.drain()
    namespace.run_once.assert_not_called()


def test_shutdown_cancels_only_not_started_python_call_not_durable_work():
    blocker, occupied, stop = Event(), Event(), Event()
    namespace = leaf()

    def occupy():
        occupied.set()
        assert blocker.wait(5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        other = executor.submit(occupy)
        assert occupied.wait(5)
        lane = LocalIndexingCpuLane(executor, (namespace,), stop, Mock())
        try:
            lane.start_next()
            lane.drain()
        finally:
            blocker.set()
            other.result()
    namespace.run_once.assert_not_called()


def test_gpu_error_still_drains_already_started_cpu_command(capsys):
    namespace, started, release, finished, stop = leaf(), Event(), Event(), Event(), Event()

    def cpu():
        started.set()
        assert release.wait(5)
        finished.set()
        return command()

    def gpu():
        assert started.wait(5)
        release.set()
        raise ValueError("synthetic GPU failure")

    namespace.run_once.side_effect = cpu
    namespace.reconcile_once.side_effect = gpu
    with pytest.raises(ValueError, match="synthetic GPU failure"):
        entry.serve_local_indexing(runtime(namespace), stop)
    assert finished.is_set()
    namespace.run_once.assert_called_once()
    assert capsys.readouterr().out.count("LOCAL_INDEXING_COMMAND_OBSERVED") == 1


@pytest.mark.parametrize("reason", [True, "unknown"])
def test_query_priority_or_unknown_observation_still_defers_both_lanes(
    synthetic_capacity, monkeypatch, reason
):
    namespace, stop = leaf(), Event()
    if reason is True:
        synthetic_capacity.return_value = True
    else:
        synthetic_capacity.side_effect = scheduling.NativeCpuSchedulingReadUnavailable()
    monkeypatch.setattr(stop, "wait", lambda _seconds: stop.set())
    entry.serve_local_indexing(runtime(namespace), stop)
    namespace.run_once.assert_not_called()
    namespace.reconcile_once.assert_not_called()


def test_storage_guard_runs_before_either_lane_is_admitted(monkeypatch):
    namespace, stop = leaf(), Event()
    monkeypatch.setattr(
        background_storage,
        "require_background_write_capacity",
        Mock(side_effect=OSError("synthetic storage unavailable")),
    )
    with pytest.raises(OSError, match="storage unavailable"):
        entry.serve_local_indexing(runtime(namespace), stop)
    namespace.run_once.assert_not_called()
    namespace.reconcile_once.assert_not_called()

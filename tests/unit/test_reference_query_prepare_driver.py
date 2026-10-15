"""Actual single Thread handle; exact Runner target is simulated, never live inference."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Timer
from unittest.mock import Mock

import pytest
from eom_workflow_runner import reference_query_prepare_driver as driver_module
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection

from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_prepare_application import query_runner


def finish(driver):
    driver._thread.join(timeout=3)
    assert not driver.observe().active


def test_one_actual_handle_for_concurrent_same_and_other_workflow(source, monkeypatch):
    runner = query_runner(source.owner, Mock(spec=ReferenceQueryNativeExecutor))
    entered, release = Event(), Event()
    calls = []

    def run_once(workflow_id):
        calls.append(workflow_id)
        entered.set()
        assert release.wait(timeout=3)
        return None

    monkeypatch.setattr(runner, "run_once", run_once)
    driver = ReferenceQueryPrepareDriver()
    workflow_id = "workflow_" + "a" * 32
    other = "workflow_" + "b" * 32
    assert driver.offer(workflow_id, runner) == "STARTED"
    assert entered.wait(timeout=3) and driver.observe().active
    try:
        barrier = Barrier(4)

        def offer(index):
            barrier.wait(timeout=3)
            return driver.offer(other if index % 2 else workflow_id, runner)

        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(offer, range(4))) == [
                "ALREADY_ACTIVE",
                "BUSY",
                "ALREADY_ACTIVE",
                "BUSY",
            ]
        assert calls == [workflow_id] and driver.observe().workflow_id == workflow_id
    finally:
        release.set()
        finish(driver)
    assert driver.observe().outcome == "NO_READY_COMMAND"
    assert driver.offer(other, runner) == "STARTED"
    finish(driver)
    assert calls == [workflow_id, other]


def test_failed_invocation_is_redacted_and_never_automatically_repeated(source, monkeypatch):
    runner = query_runner(source.owner, Mock(spec=ReferenceQueryNativeExecutor))
    run = Mock(side_effect=RuntimeError("synthetic private detail"))
    monkeypatch.setattr(runner, "run_once", run)
    driver = ReferenceQueryPrepareDriver()
    workflow_id = "workflow_" + "a" * 32
    assert driver.offer(workflow_id, runner) == "STARTED"
    finish(driver)
    assert driver.observe().outcome == "UNAVAILABLE"
    run.assert_called_once_with(workflow_id)
    assert "private detail" not in repr(driver.observe())
    assert not hasattr(driver._thread, "_args")


def test_thread_start_failure_retains_no_queued_runner_or_exception(source, monkeypatch):
    runner = query_runner(source.owner, Mock(spec=ReferenceQueryNativeExecutor))
    run = Mock(side_effect=AssertionError("thread did not start"))
    monkeypatch.setattr(runner, "run_once", run)
    monkeypatch.setattr(driver_module.Thread, "start", Mock(side_effect=RuntimeError("synthetic")))
    driver = ReferenceQueryPrepareDriver()
    assert driver.offer("workflow_" + "a" * 32, runner) == "UNAVAILABLE"
    assert not driver.observe().active and driver.observe().outcome == "START_FAILED"
    assert driver._thread is None and not hasattr(driver, "runner")
    run.assert_not_called()


def test_close_drains_original_handle_and_never_accepts_another_offer(source, monkeypatch):
    runner = query_runner(source.owner, Mock(spec=ReferenceQueryNativeExecutor))
    entered, release = Event(), Event()

    def run_once(_workflow):
        entered.set()
        assert release.wait(timeout=3)
        return None

    monkeypatch.setattr(runner, "run_once", run_once)
    driver = ReferenceQueryPrepareDriver()
    workflow = "workflow_" + "a" * 32
    assert driver.offer(workflow, runner) == "STARTED" and entered.wait(timeout=3)
    timer = Timer(0.05, release.set)
    timer.start()
    try:
        driver.close()
    finally:
        release.set()
        timer.join(timeout=3)
    assert not driver.observe().active
    assert driver.offer(workflow, runner) == "UNAVAILABLE"


@pytest.mark.parametrize("fault", ("family", "actor", "role", "owner", "workflow"))
def test_wrong_family_actor_role_or_target_is_rejected_before_thread(source, monkeypatch, fault):
    runner = query_runner(source.owner, Mock(spec=ReferenceQueryNativeExecutor))
    workflow_id = "workflow_" + "a" * 32
    if fault == "family":
        runner.command_families = frozenset({CommandExecutionFamily.LOCAL_EMBEDDING})
    elif fault == "actor":
        runner.command_actor_selection = NativeCommandActorSelection(
            "human", "operator_" + "f" * 32
        )
    elif fault == "role":
        runner.available_roles = frozenset({"authoring"})
    elif fault == "owner":
        runner.reference_query_owner = None
    else:
        workflow_id = "not-a-workflow"
    run = Mock(side_effect=AssertionError("execution before validation"))
    monkeypatch.setattr(runner, "run_once", run)
    driver = ReferenceQueryPrepareDriver()
    with pytest.raises(ValueError):
        driver.offer(workflow_id, runner)
    assert not driver.observe().active and driver.observe().workflow_id is None
    run.assert_not_called()

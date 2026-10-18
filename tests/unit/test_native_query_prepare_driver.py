"""One actual handle across both explicit families; actual Runner bodies are synthetic."""

import threading
from threading import Event
from unittest.mock import Mock

import pytest
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver

from tests.unit.test_private_chat_query_prepare_application import application as application
from tests.unit.test_private_chat_query_source_owner import source as source
from tests.unit.test_reference_query_owner_admission import make_source_case
from tests.unit.test_reference_query_prepare_application import query_runner


@pytest.fixture
def reference(tmp_path, monkeypatch):
    parent = tmp_path / "reference"
    parent.mkdir()
    source = make_source_case(parent, monkeypatch)
    return query_runner(source.owner, Mock())


def test_mixed_families_share_one_actual_handle_and_never_coalesce_same_id(
    application, reference, monkeypatch
):
    private = application.runner
    entered, release = Event(), Event()
    calls = []

    def run_once(workflow):
        calls.append(workflow)
        entered.set()
        assert release.wait(timeout=3)
        return None

    monkeypatch.setattr(private, "run_once", run_once)
    reference_run = Mock(return_value=None)
    monkeypatch.setattr(reference, "run_once", reference_run)
    driver = NativeQueryPrepareDriver()
    workflow = "workflow_" + "a" * 32
    assert driver.offer_private_chat_query(workflow, private) == "STARTED"
    assert entered.wait(timeout=3) and driver.observe().active
    try:
        assert driver.offer_private_chat_query(workflow, private) == "ALREADY_ACTIVE"
        assert driver.offer(workflow, reference) == "BUSY"
        assert driver.offer("workflow_" + "b" * 32, reference) == "BUSY"
        reference_run.assert_not_called()
        assert calls == [workflow]
    finally:
        release.set()
        driver._thread.join(timeout=3)
    assert not driver.observe().active and not hasattr(driver._thread, "_args")
    assert driver.offer(workflow, reference) == "STARTED"
    driver._thread.join(timeout=3)
    reference_run.assert_called_once_with(workflow)
    driver.close()
    assert driver.offer_private_chat_query(workflow, private) == "UNAVAILABLE"


def test_each_public_entry_keeps_its_own_concrete_family_guard(application, reference, monkeypatch):
    private = application.runner
    private_run, reference_run = Mock(), Mock()
    monkeypatch.setattr(private, "run_once", private_run)
    monkeypatch.setattr(reference, "run_once", reference_run)
    driver = NativeQueryPrepareDriver()
    workflow = "workflow_" + "a" * 32
    with pytest.raises(ValueError, match="REFERENCE_QUERY_PREPARE_RUNNER_INVALID"):
        driver.offer(workflow, private)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_PREPARE_RUNNER_INVALID"):
        driver.offer_private_chat_query(workflow, reference)
    assert driver.observe().workflow_id is None and not driver.observe().active
    private_run.assert_not_called()
    reference_run.assert_not_called()


def test_private_exception_has_no_automatic_retry_or_retained_authority(application, monkeypatch):
    private = application.runner
    run = Mock(side_effect=RuntimeError("private question must not enter drive metadata"))
    monkeypatch.setattr(private, "run_once", run)
    driver = NativeQueryPrepareDriver()
    workflow = "workflow_" + "a" * 32
    assert driver.offer_private_chat_query(workflow, private) == "STARTED"
    driver._thread.join(timeout=3)
    assert driver.observe().outcome == "UNAVAILABLE"
    assert not driver.observe().active and not hasattr(driver._thread, "_args")
    assert "private question" not in repr(driver.observe())
    run.assert_called_once_with(workflow)


@pytest.mark.parametrize("error_type", (KeyboardInterrupt, SystemExit))
def test_interrupted_child_is_unknown_without_an_excepthook_disclosure(
    application, monkeypatch, error_type
):
    run = Mock(side_effect=error_type("synthetic private detail"))
    hook = Mock()
    monkeypatch.setattr(application.runner, "run_once", run)
    monkeypatch.setattr(threading, "excepthook", hook)
    driver = NativeQueryPrepareDriver()
    workflow = "workflow_" + "a" * 32
    assert driver.offer_private_chat_query(workflow, application.runner) == "STARTED"
    driver._thread.join(timeout=3)
    assert not driver.observe().active and driver.observe().outcome == "UNAVAILABLE"
    hook.assert_not_called()
    run.assert_called_once_with(workflow)

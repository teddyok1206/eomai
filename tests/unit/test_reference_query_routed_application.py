"""Canonical selection with simulated completion; actual finite service Thread in driver tests."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV3,
    ReferenceQueryPrepareRequestV3,
)
from eom_workflow_runner import reference_query_routed_application as application
from eom_workflow_runner import reference_query_routed_execution as execution
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_execution import original as original
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


def snapshot(prepared, *, state="PENDING", device=None):
    return execution.RoutedReferenceQueryObservation(
        prepared.preparation.parent.request_sha256,
        device,
        state,
        tuple(
            execution.RoutedReferenceQueryChildObservation(i, None, "PENDING", None)
            for i in range(len(prepared.selection.anchors))
        ),
    )


def batch_request(original):
    return ReferenceQueryPrepareRequestV3.model_validate(
        seal(
            dict(
                schema_version="system-rag-reference-query-prepare-request/3.0",
                operation="PREPARE_REFERENCE_QUERY",
                operation_id="queryprepare_" + "d" * 32,
                idempotency_key="original-drive-test",
                requests=[r.model_dump(mode="json") for r in original.requests],
            ),
            "request_sha256",
        )
    )


def test_preparation_pending_and_same_key_observation_reauthorize_and_keep_original(
    original, monkeypatch
):
    driver = ReferenceQueryPrepareDriver()
    original.session.cpu.driver = driver
    offered = Mock(return_value="BUSY")
    monkeypatch.setattr(driver, "offer_routed_reference_batch", offered)
    monkeypatch.setattr(application, "observe_routed_reference_queries", lambda _s, p: snapshot(p))
    app = application.RoutedNativeReferenceQueryPreparation(original.session)
    request = batch_request(original)
    first, again = app.prepare(request), app.prepare(request)
    assert isinstance(first, ReferenceQueryPrepareReplyV3)
    assert first == again and first.status == "PENDING"
    assert first.workflow_id is None and all(c.workflow_id is None for c in first.children)
    assert first.preparation == original.prepared.manifest
    assert offered.call_count == 2
    original.deny = True
    with pytest.raises(ValueError, match="SYNTHETIC_ACTUAL_SOURCE_DENIED"):
        app.prepare(request)
    assert offered.call_count == 2


def test_parent_failure_preserves_pending_children_and_is_not_offered_again(original, monkeypatch):
    driver = ReferenceQueryPrepareDriver()
    original.session.cpu.driver = driver
    offered = Mock()
    monkeypatch.setattr(driver, "offer_routed_reference_batch", offered)
    monkeypatch.setattr(
        application, "observe_routed_reference_queries", lambda _s, p: snapshot(p, state="FAILED")
    )
    result = application.RoutedNativeReferenceQueryPreparation(original.session).prepare(
        batch_request(original)
    )
    assert result.status == "FAILED" and result.error_code == "REFERENCE_QUERY_EXECUTION_FAILED"
    assert result.preparation == original.prepared.manifest
    offered.assert_not_called()


def test_service_uses_one_handle_for_original_batch_and_drops_capture_after_thread(
    original, monkeypatch
):
    entered, release = Event(), Event()
    calls = []

    def finite(session, prepared):
        calls.append((session, prepared))
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(state="READY")

    monkeypatch.setattr(execution, "drive_routed_reference_queries_once", finite)
    driver = ReferenceQueryPrepareDriver()
    try:
        assert driver.offer_routed_reference_batch(original.session, original.prepared) == "STARTED"
        assert entered.wait(3)
        assert (
            driver.offer_routed_reference_batch(original.session, original.prepared)
            == "ALREADY_ACTIVE"
        )
        other = original.app.prepare(original.requests, idempotency_key="other-original-drive")
        assert driver.offer_routed_reference_batch(original.session, other) == "BUSY"
        assert driver.observe().active and driver.observe().workflow_id is None
    finally:
        release.set()
        driver.close()
    assert len(calls) == 1 and driver.observe().outcome == "PROCESSED"
    assert not hasattr(driver._thread, "_args")
    assert driver.offer_routed_reference_batch(original.session, original.prepared) == "UNAVAILABLE"


@pytest.mark.parametrize("interrupt", (RuntimeError, KeyboardInterrupt))
def test_failed_thread_never_retries_or_retains_exception_or_credentials(
    original, monkeypatch, interrupt
):
    driven = Mock(side_effect=interrupt("synthetic private detail"))
    monkeypatch.setattr(execution, "drive_routed_reference_queries_once", driven)
    driver = ReferenceQueryPrepareDriver()
    assert driver.offer_routed_reference_batch(original.session, original.prepared) == "STARTED"
    driver.close()
    driven.assert_called_once_with(original.session, original.prepared)
    assert driver.observe().outcome == "UNAVAILABLE" and not driver.observe().active
    assert not hasattr(driver._thread, "_args") and "private detail" not in repr(driver.observe())

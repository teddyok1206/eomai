"""Legacy CPU reply dispatch with synthetic presence/route leaves; no live run."""

from unittest.mock import Mock

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareReplyV2,
    ReferenceQueryPrepareRequestV2,
    parse_supported_reference_query_prepare_request,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_workflow_runner.reference_query_preparation import ReferenceQueryPreparationUnavailable
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.reference_query_routed_application import (
    RoutedNativeReferenceQueryPreparation,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_application import batch_request, snapshot
from tests.unit.test_reference_query_routed_execution import original as original
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


@pytest.mark.parametrize("state", ("PENDING", "READY", "FAILED", "DENIED"))
@pytest.mark.parametrize("family", ("1.0", "1.1", "2.0"))
def test_original_cpu_reply_never_enters_new_device_preparation(
    original, monkeypatch, state, family
):
    body = original.requests[0].model_dump(mode="json")
    body["schema_version"] = f"system-rag-reference-query-prepare-request/{family}"
    if family != "1.0":
        body["consumer_purpose"] = "ITEM_REVIEW"
    request = parse_supported_reference_query_prepare_request(seal(body, "request_sha256"))
    workflow_id = "workflow_" + "b" * 32
    reply_type = (
        ReferenceQueryPrepareReplyV2
        if isinstance(request, ReferenceQueryPrepareRequestV2)
        else ReferenceQueryPrepareReply
    )
    family = "2.0" if isinstance(request, ReferenceQueryPrepareRequestV2) else "1.0"
    reply = reply_type.model_validate(
        dict(
            schema_version=f"system-rag-reference-query-prepare-reply/{family}",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=request.operation_id,
            request_sha256=request.request_sha256,
            status="FAILED" if state == "DENIED" else state,
            workflow_id=None if state == "DENIED" else workflow_id,
            selection=CompletedSimilarityQuerySelection(
                workflow_id=workflow_id,
                workflow_request_sha256="sha256:" + "b" * 64,
                context_request_sha256="sha256:" + "c" * 64,
            )
            if state == "READY"
            else None,
            error_code="REFERENCE_QUERY_EXECUTION_FAILED"
            if state == "FAILED"
            else "AUTHORITY_UNAVAILABLE"
            if state == "DENIED"
            else None,
        )
    )
    driver = ReferenceQueryPrepareDriver()
    original.session.cpu.driver = driver
    observer = Mock(return_value=reply)
    original.session.cpu.observe_existing = observer
    forbidden = Mock(side_effect=AssertionError("original CPU work must not acquire a new route"))
    monkeypatch.setattr(original.session.selection, "prepare", forbidden)
    try:
        result = RoutedNativeReferenceQueryPreparation(original.session).prepare(request)
        assert result == reply
        observer.assert_called_once_with(request)
        forbidden.assert_not_called()
        assert not driver.observe().active
    finally:
        driver.close()


def test_new_single_request_without_cpu_work_enters_routed_preparation(original, monkeypatch):
    request = original.requests[0]
    driver = ReferenceQueryPrepareDriver()
    original.session.cpu.driver = driver
    original.session.cpu.observe_existing.return_value = None
    prepared = Mock(side_effect=ReferenceQueryPreparationUnavailable("INDEX_NOT_PREPARED"))
    monkeypatch.setattr(original.session.selection, "prepare", prepared)
    try:
        result = RoutedNativeReferenceQueryPreparation(original.session).prepare(request)
        assert result.status == "UNAVAILABLE" and result.error_code == "INDEX_NOT_PREPARED"
        original.session.cpu.observe_existing.assert_called_once_with(request)
        original.session.cpu.prepare.assert_not_called()
        prepared.assert_called_once_with((request,), idempotency_key=request.idempotency_key)
        assert not driver.observe().active
    finally:
        driver.close()


def test_explicit_batch_does_not_adopt_legacy_individual_keys(original, monkeypatch):
    from eom_workflow_runner import reference_query_routed_application as module

    driver = ReferenceQueryPrepareDriver()
    original.session.cpu.driver = driver
    original.session.cpu.observe_existing.side_effect = AssertionError("distinct batch intent")
    offered = Mock(return_value="BUSY")
    monkeypatch.setattr(driver, "offer_routed_reference_batch", offered)
    monkeypatch.setattr(module, "observe_routed_reference_queries", lambda _s, p: snapshot(p))
    try:
        result = RoutedNativeReferenceQueryPreparation(original.session).prepare(
            batch_request(original)
        )
        assert result.status == "PENDING"
        original.session.cpu.observe_existing.assert_not_called()
        original.session.cpu.prepare.assert_not_called()
        assert offered.call_count == 1
        session, prepared = offered.call_args.args
        assert session is original.session and prepared.manifest == result.preparation
    finally:
        driver.close()

"""Public request4 crosses real HTTP/Unix/capture framing; owner data is synthetic."""

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    routed_reference_query_error_reply,
)

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_public_solution_query_preparation_contracts import public_prepare_request
from tests.unit.test_reference_query_prepare_transport import exchange


@pytest.mark.parametrize("http", (False, True))
@pytest.mark.parametrize("count", (1, 5, 32))
def test_public_request4_retains_actual_http_capture_and_no_legacy_fallback(
    observation, monkeypatch, http, count
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        through_http=http,
        request_value=public_prepare_request(count),
        reply_factory=lambda request: routed_reference_query_error_reply(
            request,
            status="UNAVAILABLE",
            error_code="INDEX_NOT_PREPARED",
        ),
    )
    assert isinstance(reply, ReferenceQueryPrepareReplyV4)
    assert reply.status == "UNAVAILABLE" and reply.children == ()
    assert calls == [source.operator.operator_id]
    assert source.raw_token not in repr(reply)


@pytest.mark.parametrize("fault", ("application", "wrong_reply", "capture_hash"))
def test_public_prepare_failure_cannot_reauthenticate_retry_or_downgrade(
    observation, monkeypatch, fault
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        fault=fault,
        request_value=public_prepare_request(),
        reply_factory=lambda request: routed_reference_query_error_reply(
            request,
            status="UNAVAILABLE",
            error_code="INDEX_NOT_PREPARED",
        ),
    )
    assert calls == ([] if fault == "capture_hash" else [source.operator.operator_id])
    assert reply is None or isinstance(reply, ReferenceQueryPrepareReplyV4)

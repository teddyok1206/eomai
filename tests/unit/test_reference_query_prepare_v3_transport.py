"""Actual HTTP/socket/current-capture carrier; application results remain synthetic."""

import pytest
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareReplyV3

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_reference_query_prepare_transport import exchange
from tests.unit.test_reference_query_prepare_v3_contracts import bulk_body, observation_body


@pytest.mark.parametrize("count", (1, 3))
@pytest.mark.parametrize("ready", (False, True))
@pytest.mark.parametrize("http", (False, True))
def test_finite_original_request_and_truthful_pending_or_complete_round_trip(
    observation, monkeypatch, count, ready, http
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        through_http=http,
        request_value=bulk_body(count),
        reply_factory=lambda r: ReferenceQueryPrepareReplyV3.model_validate(
            observation_body(r, ready=ready)
        ),
    )
    assert reply is not None and len(reply.children) == count
    assert reply.status == ("READY" if ready else "PENDING")
    assert calls == [source.operator.operator_id]
    assert source.raw_token not in repr(reply)


@pytest.mark.parametrize(
    "fault", ("application", "partial_final_write", "wrong_reply", "capture_hash")
)
def test_error_is_not_reauthentication_automatic_retry_or_a_new_request(
    observation, monkeypatch, fault
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        fault=fault,
        request_value=bulk_body(),
        reply_factory=lambda r: ReferenceQueryPrepareReplyV3.model_validate(observation_body(r)),
    )
    assert calls == ([] if fault == "capture_hash" else [source.operator.operator_id])
    assert reply is None or reply.status == "FAILED"

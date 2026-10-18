"""Acknowledged identity and bounded progress; source/native authority are declared fixtures."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_query_prepare import PrivateChatQueryPrepareProtocolError
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator import private_chat_query_completion as wait_module
from eom_orchestrator import private_chat_query_prepare_client as client_module
from eom_orchestrator.general_chat_socket import ChatTransportError
from eom_orchestrator.private_chat_query_prepare_client import PrivateChatQueryPrepareClient
from eom_workflow_runner.private_chat_query_preparation import (
    PrivateChatQueryPreparationUnavailable,
)
from eom_workflow_runner.private_chat_query_prepare_application import PrivateChatQueryNotPrepared

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_private_chat_query_owner_host import profile as profile
from tests.unit.test_private_chat_query_owner_host import running as running
from tests.unit.test_private_chat_query_prepare_exchange import case as case
from tests.unit.test_private_chat_query_prepare_exchange import ready


@pytest.fixture
def local(case, monkeypatch):
    sent = []
    clock = SimpleNamespace(now=1000.0, stopped=False, wait_extra=0)

    def exchange(_endpoint, document, **kwargs):
        assert kwargs["timeout"] == 20.0
        sent.append(document)
        return case.dispatch.execute(document).model_dump(mode="json")

    wire = Mock(side_effect=exchange)
    monkeypatch.setattr(client_module, "exchange_chat_frame", wire)
    monkeypatch.setattr(wait_module, "monotonic", lambda: clock.now)

    def wait(seconds):
        clock.now += seconds + clock.wait_extra
        return clock.stopped

    stop = SimpleNamespace(is_set=lambda: clock.stopped, wait=wait)
    # Explicit endpoint is not touched: transport is a declared fixture here.
    client = PrivateChatQueryPrepareClient(object())
    return SimpleNamespace(client=client, sent=sent, wire=wire, clock=clock, stop=stop, case=case)


def pending(local):
    result = local.client.execute(local.case.request)
    assert result.status == "PENDING"
    return result


def test_explicit_continuation_and_read_use_real_separate_unix_exchanges(case, profile, running):
    client = PrivateChatQueryPrepareClient(profile.chat)
    first = client.execute(case.request)
    observed = client.read_original(case.request, first)
    resumed = client.continue_pending_original(case.request, first)
    assert first.workflow_id == observed.workflow_id == resumed.workflow_id
    assert first.status == observed.status == resumed.status == "PENDING"
    assert observed.action == "READ_PRIVATE_CHAT_QUERY"
    assert resumed.action == "PREPARE_PRIVATE_CHAT_QUERY"
    assert case.application.prepare.call_count == 2 and case.application.read.call_count == 1
    assert profile.factory.application.call_count == 3


def test_continuation_reuses_exact_prepare_bytes_and_read_changes_only_action_hash(local):
    request = local.case.request
    first = pending(local)
    local.client.read_original(request, first)
    local.client.continue_pending_original(request, first)
    before, read, resumed = local.sent
    assert before == resumed == request.model_dump(mode="json")
    assert read["action"] == "READ_PRIVATE_CHAT_QUERY"
    assert read["request_sha256"] != before["request_sha256"]
    assert {k: v for k, v in before.items() if k not in {"action", "request_sha256"}} == {
        k: v for k, v in read.items() if k not in {"action", "request_sha256"}
    }


@pytest.mark.parametrize("method", ("read_original", "continue_pending_original"))
def test_different_original_workflow_in_reply_is_rejected_without_followup(local, method):
    first = pending(local)
    changed = replace(local.case.result, workflow_id="workflow_" + "f" * 32)
    local.case.application.prepare.return_value = changed
    local.case.application.read.return_value = changed
    with pytest.raises(PrivateChatQueryPrepareProtocolError, match="REPLY_INVALID"):
        getattr(local.client, method)(local.case.request, first)
    assert len(local.sent) == 2


@pytest.mark.parametrize("method", ("read_original", "continue_pending_original"))
def test_unknown_transport_outcome_does_not_retry_or_fallback(local, method):
    first = pending(local)
    local.wire.side_effect = ChatTransportError("UNAVAILABLE")
    with pytest.raises(ChatTransportError):
        getattr(local.client, method)(local.case.request, first)
    assert local.wire.call_count == 2


@pytest.mark.parametrize("method", ("read_original", "continue_pending_original"))
def test_failed_acknowledgement_cannot_authorize_another_request(local, method):
    local.case.application.prepare.side_effect = ValueError("synthetic local failure")
    # A malformed caller value is rejected before any wire request.
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        getattr(local.client, method)(local.case.request, {"status": "FAILED"})
    assert local.wire.call_count == 0


def await_original(local, deadline=None):
    return wait_module.wait_for_original_private_chat_query(
        local.client,
        local.case.request,
        stop=local.stop,
        deadline=local.clock.now + 300 if deadline is None else deadline,
    )


def test_known_busy_original_can_progress_later_without_new_identity(local):
    local.case.application.prepare.side_effect = [
        local.case.result,
        local.case.result,
        ready(local.case),
    ]
    result = await_original(local)
    assert result.status == "READY" and local.clock.now == 1010
    assert [value["action"] for value in local.sent] == [
        "PREPARE_PRIVATE_CHAT_QUERY",
        "READ_PRIVATE_CHAT_QUERY",
        "PREPARE_PRIVATE_CHAT_QUERY",
        "READ_PRIVATE_CHAT_QUERY",
        "PREPARE_PRIVATE_CHAT_QUERY",
    ]
    prepares = [value for value in local.sent if value["action"] == "PREPARE_PRIVATE_CHAT_QUERY"]
    assert prepares == [local.case.request.model_dump(mode="json")] * 3


def test_read_ready_returns_canonical_reply_without_another_prepare(local):
    local.case.application.read.return_value = ready(local.case)
    result = await_original(local)
    assert result.status == "READY" and result.action == "READ_PRIVATE_CHAT_QUERY"
    assert local.case.application.prepare.call_count == local.case.application.read.call_count == 1


def test_waiter_exposes_actual_prepare_ack_without_relabelling_read_ready(local):
    local.case.application.read.return_value = ready(local.case)
    acknowledgements = []
    result = wait_module.wait_for_original_private_chat_query(
        local.client,
        local.case.request,
        stop=local.stop,
        deadline=local.clock.now + 300,
        on_acknowledged=acknowledgements.append,
    )
    assert len(acknowledgements) == 1
    assert acknowledgements[0].action == "PREPARE_PRIVATE_CHAT_QUERY"
    assert acknowledgements[0].status == "PENDING"
    assert result.action == "READ_PRIVATE_CHAT_QUERY" and result.status == "READY"
    assert acknowledgements[0].workflow_id == result.workflow_id


def test_initial_ready_returns_without_sleep_read_or_continuation(local):
    local.case.application.prepare.return_value = ready(local.case)
    assert await_original(local).status == "READY"
    assert local.clock.now == 1000 and len(local.sent) == 1
    local.case.application.read.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    (
        (PrivateChatQueryPreparationUnavailable(), "UNAVAILABLE"),
        (SimilarityContextReadError("SOURCE_ACCESS_DENIED"), "FAILED"),
    ),
)
def test_initial_absence_or_denial_returns_without_progress_calls(local, error, status):
    local.case.application.prepare.side_effect = error
    result = await_original(local)
    assert result.status == status and len(local.sent) == 1
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        local.client.continue_pending_original(local.case.request, result)
    assert len(local.sent) == 1


@pytest.mark.parametrize(
    "error,status",
    (
        (PrivateChatQueryNotPrepared(), "UNAVAILABLE"),
        (SimilarityContextReadError("SOURCE_ACCESS_DENIED"), "FAILED"),
    ),
)
def test_missing_or_revoked_original_on_read_never_falls_back_to_preparation(local, error, status):
    local.case.application.read.side_effect = error
    result = await_original(local)
    assert result.status == status and len(local.sent) == 2
    assert local.case.application.prepare.call_count == 1


def test_permanent_busy_is_bounded_and_is_not_reported_as_empty_or_complete(local):
    result = await_original(local)
    assert result.status == "PENDING" and result.context is None
    assert len(local.sent) == 25 and local.clock.now == 1060
    assert local.case.application.prepare.call_count == 13
    assert local.case.application.read.call_count == 12


def test_stop_interrupts_before_any_further_rpc(local):
    local.stop.wait = lambda _seconds: True
    result = await_original(local)
    assert result.status == "PENDING" and len(local.sent) == 1


def test_delayed_wakeup_never_starts_a_rpc_after_deadline(local):
    local.clock.wait_extra = 50
    result = await_original(local, local.clock.now + 40)
    assert result.status == "PENDING" and len(local.sent) == 1


def test_long_caller_deadline_is_still_capped_by_owner_budget(local):
    original = local.wire.side_effect

    def cost(*args, **kwargs):
        local.clock.now += 10
        return original(*args, **kwargs)

    local.wire.side_effect = cost
    result = await_original(local, local.clock.now + 10000)
    assert result.status == "PENDING"
    assert local.clock.now <= 1180 and len(local.sent) < 25


@pytest.mark.parametrize("deadline", (None, True, float("nan"), float("inf"), 1005.0))
def test_bad_or_too_short_budget_never_submits_work(local, deadline):
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        wait_module.wait_for_original_private_chat_query(
            local.client, local.case.request, stop=local.stop, deadline=deadline
        )
    local.wire.assert_not_called()


@pytest.mark.parametrize("fail_call", (1, 2, 3))
def test_waiter_stops_at_first_unknown_outcome_without_automatic_replay(local, fail_call):
    original = local.wire.side_effect
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        if len(calls) == fail_call:
            raise ChatTransportError("UNAVAILABLE")
        return original(*args, **kwargs)

    local.wire.side_effect = failing
    with pytest.raises(ChatTransportError):
        await_original(local)
    assert len(calls) == fail_call

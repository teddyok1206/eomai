from __future__ import annotations

import pytest
from eom_orchestrator import general_chat_native_worker as runtime
from eom_orchestrator.general_chat_native_worker import (
    IsolatedCodexChatWorker,
    source_chat_worker_policy,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerFault

from tests.unit.test_general_chat_resident import answer, staged


@pytest.fixture
def synthetic_native(monkeypatch):
    events = []

    class Channel:
        closed = False

        def __init__(self):
            self.process = self
            self.returncode = None

        def poll(self):
            return self.returncode

        def close(self):
            self.closed = True
            self.returncode = 0
            events.append(("closed", id(self)))

    channel = Channel()
    channels = []

    class Session:
        ready = False

        def __init__(self, selected_channel, *, model, cwd, reasoning_effort=None):
            self.channel = selected_channel
            events.append(("construct", model, cwd))

        def initialize(self):
            events.append(("initialize",))
            self.ready = True

        def answer(self, request, **_):
            events.append(("answer", request.turn_id))
            return answer(request)

        def close(self):
            self.ready = False
            self.channel.close()

    def start(*, model, **_):
        current = channel if not channels else Channel()
        channels.append(current)
        events.append(("isolated-start", model, id(current)))
        return current

    monkeypatch.setattr(runtime.CodexChatStdio, "start", start)
    monkeypatch.setattr(runtime, "CodexChatSession", Session)
    monkeypatch.setattr(
        runtime, "require_native_chat_identity", lambda: events.append(("identity",))
    )
    monkeypatch.setattr(runtime, "require_native_chat_capability", lambda **_: None)
    return events, channel


def worker():
    return IsolatedCodexChatWorker(policy=source_chat_worker_policy(model="synthetic-model"))


def test_actual_profile_prompt_digest_and_model_are_checked_before_native_start(synthetic_native):
    events, _ = synthetic_native
    selected = source_chat_worker_policy(model="synthetic-model")
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        IsolatedCodexChatWorker(
            policy=selected.model_copy(update={"prompt_sha256": "sha256:" + "f" * 64})
        )
    assert not events


def test_idle_admission_does_not_create_account_bearing_session(synthetic_native):
    events, channel = synthetic_native
    current = worker()
    current.require_admission(current.policy)
    assert not any(event[0] in {"initialize", "isolated-start", "answer"} for event in events)
    assert current.session is None and current.channel is None
    assert current.answer(staged(1)) == answer(staged(1))
    assert channel.closed and channel.poll() is not None
    assert current.session is None and current.channel is None
    current.require_admission(current.policy)
    current.close()
    with pytest.raises(ChatWorkerFault):
        current.require_admission(current.policy)


def test_each_turn_uses_new_process_and_no_cached_account(synthetic_native):
    events, _ = synthetic_native
    current = worker()
    assert current.answer(staged(1)) == answer(staged(1))
    assert current.answer(staged(2)) == answer(staged(2))
    starts = [event for event in events if event[0] == "isolated-start"]
    assert len(starts) == 2 and starts[0][2] != starts[1][2]
    assert not current.retirement_requested.is_set()


@pytest.mark.parametrize("change", ["model", "identity", "closed", "retired"])
def test_changed_policy_or_unavailable_worker_is_not_admitted(
    synthetic_native, monkeypatch, change
):
    events, _ = synthetic_native
    current = worker()
    expected = current.policy
    if change == "model":
        expected = source_chat_worker_policy(model="different-model")
    elif change == "closed":
        current.close()
    elif change == "retired":
        current.retirement_requested.set()
    else:

        def unavailable():
            raise RuntimeError("private OS detail")

        monkeypatch.setattr(runtime, "require_native_chat_identity", unavailable)
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        current.require_admission(expected)
    assert not any(event[0] == "answer" for event in events)


@pytest.mark.parametrize("method", ["initialize", "__init__"])
def test_start_failure_closes_native_without_exporting_private_error(
    synthetic_native, monkeypatch, method
):
    _, channel = synthetic_native
    current = worker()

    def unavailable(*args, **kwargs):
        raise RuntimeError("private account response must not escape")

    monkeypatch.setattr(runtime.CodexChatSession, method, unavailable)
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        current.answer(staged(1))
    assert channel.closed and current.retirement_requested.is_set()


def test_known_result_after_native_retirement_is_preserved(synthetic_native, monkeypatch):
    _, channel = synthetic_native
    current = worker()

    def retire(session, request, **_):
        session.close()
        return answer(request)

    monkeypatch.setattr(runtime.CodexChatSession, "answer", retire)
    assert current.answer(staged(1)) == answer(staged(1))
    assert channel.closed and current.retirement_requested.is_set()


def test_unknown_native_outcome_retires_without_retry(synthetic_native, monkeypatch):
    _, channel = synthetic_native
    current = worker()
    calls = []

    def unknown(session, request, **_):
        calls.append(request)
        raise RuntimeError("unknown native outcome")

    monkeypatch.setattr(runtime.CodexChatSession, "answer", unknown)
    with pytest.raises(RuntimeError):
        current.answer(staged(1))
    assert calls == [staged(1)] and channel.closed and current.retirement_requested.is_set()
    with pytest.raises(ChatWorkerFault):
        current.answer(staged(1))
    assert calls == [staged(1)]


def test_confirmed_failure_does_not_retire_worker_or_reuse_native(synthetic_native, monkeypatch):
    events, channel = synthetic_native
    current = worker()
    failed = answer(staged(1)).model_copy(
        update={"status": "FAILED", "reply": "", "failure_code": "CODEX_TURN_FAILED"}
    )
    original = runtime.CodexChatSession.answer

    def fail_first(session, request, **kwargs):
        return (
            failed if request.turn_id == staged(1).turn_id else original(session, request, **kwargs)
        )

    monkeypatch.setattr(runtime.CodexChatSession, "answer", fail_first)
    assert current.answer(staged(1)) == failed
    assert channel.closed and not current.retirement_requested.is_set()
    assert current.answer(staged(2)) == answer(staged(2))
    assert len([event for event in events if event[0] == "initialize"]) == 2


def test_unconfirmed_process_exit_prevents_result_publication(synthetic_native, monkeypatch):
    _, channel = synthetic_native
    current = worker()
    monkeypatch.setattr(channel, "close", lambda: None)
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_RECONCILIATION_REQUIRED"):
        current.answer(staged(1))
    assert current.retirement_requested.is_set()

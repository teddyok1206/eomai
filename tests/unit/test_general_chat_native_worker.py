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

    channel = Channel()

    class Session:
        ready = False

        def __init__(self, selected_channel, *, model, cwd):
            assert selected_channel is channel
            events.append(("construct", model, cwd))

        def initialize(self):
            events.append(("initialize",))
            self.ready = True

        def answer(self, request):
            events.append(("answer", request.turn_id))
            return answer(request)

        def close(self):
            self.ready = False
            channel.close()

    def start(*, model):
        events.append(("isolated-start", model))
        return channel

    def identity():
        events.append(("os-identity",))

    monkeypatch.setattr(runtime.CodexChatStdio, "start", start)
    monkeypatch.setattr(runtime, "CodexChatSession", Session)
    monkeypatch.setattr(runtime, "require_native_chat_identity", identity)
    return events, channel


def test_actual_profile_prompt_digest_and_model_are_checked_before_native_start(synthetic_native):
    events, _ = synthetic_native
    selected = source_chat_worker_policy(model="synthetic-model")
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        IsolatedCodexChatWorker(
            policy=selected.model_copy(update={"prompt_sha256": "sha256:" + "f" * 64})
        )
    assert not events


def test_admitted_native_reuses_exact_adapter_and_check_does_not_generate(synthetic_native):
    events, channel = synthetic_native
    selected = source_chat_worker_policy(model="synthetic-model")
    worker = IsolatedCodexChatWorker(policy=selected)
    worker.require_admission(selected)
    assert not any(event[0] == "answer" for event in events)
    assert worker.answer(staged(1)) == answer(staged(1))
    assert len([event for event in events if event[0] == "answer"]) == 1
    worker.close()
    assert channel.closed
    with pytest.raises(ChatWorkerFault):
        worker.require_admission(selected)


@pytest.mark.parametrize("change", ["model", "process", "identity", "session"])
def test_changed_policy_or_lost_runtime_is_not_admitted(synthetic_native, monkeypatch, change):
    events, channel = synthetic_native
    selected = source_chat_worker_policy(model="synthetic-model")
    worker = IsolatedCodexChatWorker(policy=selected)
    expected = selected
    if change == "model":
        expected = source_chat_worker_policy(model="different-model")
    elif change == "process":
        channel.returncode = 1
    elif change == "session":
        worker.session.ready = False
    else:

        def unavailable():
            raise RuntimeError("private OS detail")

        monkeypatch.setattr(runtime, "require_native_chat_identity", unavailable)
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        worker.require_admission(expected)
    assert not any(event[0] == "answer" for event in events)


def test_initialization_failure_closes_native_and_does_not_export_private_error(
    synthetic_native, monkeypatch
):
    _, channel = synthetic_native

    def unavailable(self):
        raise RuntimeError("private account response must not escape")

    monkeypatch.setattr(runtime.CodexChatSession, "initialize", unavailable)
    with pytest.raises(ChatWorkerFault) as failure:
        IsolatedCodexChatWorker(policy=source_chat_worker_policy(model="synthetic-model"))
    assert str(failure.value) == "GENERAL_CHAT_WORKER_NOT_READY" and channel.closed


def test_session_construction_failure_also_closes_the_started_process(
    synthetic_native, monkeypatch
):
    _, channel = synthetic_native

    def fail_construction(*args, **kwargs):
        raise RuntimeError("private construction error")

    monkeypatch.setattr(runtime, "CodexChatSession", fail_construction)
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        IsolatedCodexChatWorker(policy=source_chat_worker_policy(model="synthetic-model"))
    assert channel.closed


def test_known_answer_is_returned_when_native_requests_bounded_retirement(
    synthetic_native, monkeypatch
):
    events, channel = synthetic_native
    worker = IsolatedCodexChatWorker(policy=source_chat_worker_policy(model="synthetic-model"))

    def retire(request):
        worker.close()
        return answer(request)

    monkeypatch.setattr(worker.session, "answer", retire)
    assert worker.answer(staged(1)) == answer(staged(1))
    assert channel.closed and worker.retirement_requested.is_set()
    assert len([event for event in events if event[0] == "initialize"]) == 1


def test_unknown_native_exception_poison_requests_retirement_without_retry(
    synthetic_native, monkeypatch
):
    _, channel = synthetic_native
    worker = IsolatedCodexChatWorker(policy=source_chat_worker_policy(model="synthetic-model"))
    calls = []

    def unknown(request):
        calls.append(request)
        raise RuntimeError("unknown native outcome")

    monkeypatch.setattr(worker.session, "answer", unknown)
    with pytest.raises(RuntimeError):
        worker.answer(staged(1))
    assert calls == [staged(1)] and channel.closed and worker.retirement_requested.is_set()
    with pytest.raises(ChatWorkerFault):
        worker.answer(staged(1))
    assert calls == [staged(1)]

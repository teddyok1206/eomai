from __future__ import annotations

from collections import deque
from threading import Event, Lock, Thread

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.general_chat_execution import ChatClaim
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_resident import GeneralChatResident
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat import ChatTurnInput, ChatTurnResult, read_chat_turn_input
from eom_protocol.general_chat_dispatch import ChatExecutionIdentity

RUNTIME = "chatrt_" + "a" * 32


def staged(index: int) -> ChatTurnInput:
    messages = [{"role": "user", "text": f"사용자별 질문 {index}"}]
    return read_chat_turn_input(
        {
            "protocol_version": "general-chat-turn/1.0",
            "conversation_id": f"chat_{index:032x}",
            "turn_id": f"chatturn_{index:032x}",
            "claim_id": f"chatclaim_{index:032x}",
            "prompt_revision": "general-chat/1.0.0",
            "context_sha256": content_sha256(messages),
            "messages": messages,
        }
    )


def answer(request: ChatTurnInput) -> ChatTurnResult:
    return ChatTurnResult(
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
        claim_id=request.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        status="SUCCEEDED",
        reply="실제 모델을 사용하지 않은 합성 테스트 답변",
        failure_code=None,
    )


class Execution:
    def __init__(self, stop: Event, requests: tuple[ChatTurnInput, ...] = ()) -> None:
        self.stop = stop
        self.requests = {request.turn_id: request for request in requests}
        self.queue = deque(requests)
        self.completed: list[ChatTurnResult] = []
        self.active: ChatClaim | None = None
        self.heartbeats = 0
        self.claims = 0
        self.withdrawals: list[str] = []
        self.heartbeat_seen = Event()
        self.claim_seen = Event()
        self.lock = Lock()

    def heartbeat(self, *, runtime_id: str) -> None:
        assert runtime_id == RUNTIME
        with self.lock:
            self.heartbeats += 1
            if self.heartbeats >= 2:
                self.heartbeat_seen.set()

    def withdraw(self, *, runtime_id: str) -> bool:
        self.withdrawals.append(runtime_id)
        return True

    def claim_next(self, *, runtime_id: str) -> ChatClaim | None:
        self.claims += 1
        self.claim_seen.set()
        if not self.queue:
            return None
        request = self.queue.popleft()
        self.active = ChatClaim(
            runtime_id, request.conversation_id, request.turn_id, request.claim_id
        )
        return self.active

    def prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatTurnInput:
        assert identity.boot_id == "chatboot_" + "b" * 32
        return self.requests[claim.turn_id]

    def complete(self, claim: ChatClaim, result: ChatTurnResult) -> None:
        assert claim == self.active
        self.completed.append(result)
        self.active = None
        if not self.queue:
            self.stop.set()


class Worker:
    def __init__(self) -> None:
        self.calls: list[ChatTurnInput] = []
        self.checks = 0
        self.execution_identity = ChatExecutionIdentity(
            boot_id="chatboot_" + "b" * 32,
            policy=source_chat_worker_policy(model="synthetic-model"),
        )

    def check_admission(self) -> None:
        self.checks += 1

    def answer(self, request: ChatTurnInput) -> ChatTurnResult:
        self.calls.append(request)
        return answer(request)


def resident(execution: Execution, worker: Worker) -> GeneralChatResident:
    return GeneralChatResident(
        execution, worker, runtime_id=RUNTIME, heartbeat_seconds=0.01, idle_seconds=0.01
    )


def test_dedicated_resident_consumes_all_owner_queue_serially_once() -> None:
    stop = Event()
    requests = tuple(staged(index) for index in range(1, 4))
    execution, worker = Execution(stop, requests), Worker()
    resident(execution, worker).run(stop)
    assert tuple(worker.calls) == requests
    assert tuple(result.turn_id for result in execution.completed) == tuple(
        request.turn_id for request in requests
    )
    assert execution.claims == 3 and execution.active is None
    assert execution.withdrawals == [RUNTIME]


def test_pre_stopped_resident_does_not_announce_or_claim() -> None:
    stop = Event()
    stop.set()
    execution, worker = Execution(stop, (staged(1),)), Worker()
    resident(execution, worker).run(stop)
    assert execution.heartbeats == execution.claims == worker.checks == 0
    assert not execution.withdrawals and not worker.calls


def test_idle_slot_is_resident_without_idle_model_calls() -> None:
    stop = Event()
    execution, worker = Execution(stop), Worker()
    runner = resident(execution, worker)
    thread = Thread(target=runner.run, args=(stop,))
    thread.start()
    try:
        assert execution.heartbeat_seen.wait(2)
        with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_IN_USE"):
            runner.run(Event())
    finally:
        stop.set()
        thread.join(2)
    assert not thread.is_alive() and not worker.calls
    assert execution.withdrawals == [RUNTIME]


def test_graceful_stop_keeps_heartbeat_and_commits_claimed_known_answer() -> None:
    stop = Event()
    execution = Execution(stop, (staged(1), staged(2)))

    class DrainingWorker(Worker):
        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            stop.set()
            assert execution.heartbeat_seen.wait(2)
            return super().answer(request)

    worker = DrainingWorker()
    resident(execution, worker).run(stop)
    assert execution.heartbeats >= 2
    assert len(worker.calls) == len(execution.completed) == 1
    assert len(execution.queue) == 1 and execution.withdrawals == [RUNTIME]


def test_lost_admission_stops_new_claims_but_preserves_known_result() -> None:
    stop, executing = Event(), Event()
    execution = Execution(stop, (staged(1), staged(2)))

    class LostWorker(Worker):
        def check_admission(self) -> None:
            if executing.is_set():
                raise ChatError("GENERAL_CHAT_WORKER_NOT_READY")
            super().check_admission()

        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            executing.set()
            assert stop.wait(2)
            assert execution.withdrawals == [RUNTIME]
            return super().answer(request)

    worker = LostWorker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
        resident(execution, worker).run(stop)
    assert len(worker.calls) == len(execution.completed) == execution.claims == 1
    assert len(execution.queue) == 1 and execution.active is None
    assert execution.withdrawals == [RUNTIME, RUNTIME]


def test_unknown_worker_outcome_never_retries_or_invents_completion() -> None:
    stop = Event()
    execution = Execution(stop, (staged(1), staged(2)))

    class UnknownWorker(Worker):
        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            self.calls.append(request)
            raise RuntimeError("private native body must not appear")

    worker = UnknownWorker()
    with pytest.raises(ChatError) as failure:
        resident(execution, worker).run(stop)
    assert str(failure.value) == "GENERAL_CHAT_RUNTIME_STOPPED"
    assert execution.active is not None and len(execution.queue) == 1
    assert len(worker.calls) == execution.claims == 1 and not execution.completed
    assert execution.withdrawals == [RUNTIME]


@pytest.mark.parametrize("field", ["claim_id", "conversation_id", "request_sha256"])
def test_foreign_or_modified_result_never_completes_or_replays(field: str) -> None:
    stop = Event()
    execution = Execution(stop, (staged(1), staged(2)))

    class InvalidWorker(Worker):
        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            result = super().answer(request).model_dump(mode="json")
            result[field] = (
                "sha256:" + "f" * 64
                if field == "request_sha256"
                else field.removesuffix("_id") + "_" + "f" * 32
            )
            return ChatTurnResult.model_validate(result)

    worker = InvalidWorker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_STOPPED"):
        resident(execution, worker).run(stop)
    assert len(worker.calls) == 1 and not execution.completed
    assert execution.active is not None and execution.withdrawals == [RUNTIME]


def test_wrong_prepared_claim_never_reaches_worker() -> None:
    stop = Event()

    class WrongExecution(Execution):
        def prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatTurnInput:
            return staged(99)

    execution, worker = WrongExecution(stop, (staged(1),)), Worker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_CLAIM_MISMATCH"):
        resident(execution, worker).run(stop)
    assert not worker.calls and not execution.completed
    assert execution.active is not None and execution.withdrawals == [RUNTIME]


def test_uncertain_commit_preserves_result_without_second_inference() -> None:
    stop = Event()

    class UnknownCommit(Execution):
        def complete(self, claim: ChatClaim, result: ChatTurnResult) -> None:
            self.completed.append(result)
            raise RuntimeError("unknown database outcome")

    execution, worker = UnknownCommit(stop, (staged(1), staged(2))), Worker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_STOPPED"):
        resident(execution, worker).run(stop)
    assert len(worker.calls) == len(execution.completed) == execution.claims == 1
    assert execution.active is not None and execution.withdrawals == [RUNTIME]


def test_uncertain_initial_heartbeat_also_withdraws_exact_runtime() -> None:
    stop = Event()

    class UnknownHeartbeat(Execution):
        def heartbeat(self, *, runtime_id: str) -> None:
            super().heartbeat(runtime_id=runtime_id)
            raise RuntimeError("connection lost after possible commit")

    execution, worker = UnknownHeartbeat(stop, (staged(1),)), Worker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_STOPPED"):
        resident(execution, worker).run(stop)
    assert not worker.calls and execution.claims == 0
    assert execution.withdrawals == [RUNTIME]


def test_failed_worker_admission_never_claims_or_announces() -> None:
    stop = Event()

    class NotAdmitted(Worker):
        def check_admission(self) -> None:
            raise ChatError("GENERAL_CHAT_WORKER_NOT_READY")

    execution, worker = Execution(stop, (staged(1),)), NotAdmitted()
    with pytest.raises(ChatError, match="GENERAL_CHAT_WORKER_NOT_READY"):
        resident(execution, worker).run(stop)
    assert execution.heartbeats == execution.claims == 0
    assert not execution.withdrawals and not worker.calls


def test_valid_worker_failure_retains_failed_evidence_not_partial_answer() -> None:
    stop = Event()
    execution = Execution(stop, (staged(1),))

    class FailedWorker(Worker):
        def answer(self, request: ChatTurnInput) -> ChatTurnResult:
            self.calls.append(request)
            document = answer(request).model_dump(mode="json")
            document.update(status="FAILED", reply="", failure_code="CODEX_TIMEOUT")
            return ChatTurnResult.model_validate(document)

    worker = FailedWorker()
    resident(execution, worker).run(stop)
    assert len(worker.calls) == len(execution.completed) == 1
    assert execution.completed[0].status == "FAILED"
    assert execution.completed[0].reply == ""
    assert execution.completed[0].failure_code == "CODEX_TIMEOUT"


def test_prepare_failure_preserves_claim_without_worker_call() -> None:
    stop = Event()

    class MissingEvidence(Execution):
        def prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatTurnInput:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")

    execution, worker = MissingEvidence(stop, (staged(1),)), Worker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_POINTER_INVALID"):
        resident(execution, worker).run(stop)
    assert execution.active is not None and not worker.calls and not execution.completed
    assert execution.withdrawals == [RUNTIME]


def test_withdraw_failure_is_reported_without_retrying_inference() -> None:
    stop = Event()

    class FailedWithdrawal(Execution):
        def withdraw(self, *, runtime_id: str) -> bool:
            super().withdraw(runtime_id=runtime_id)
            raise RuntimeError("private database error body")

    execution, worker = FailedWithdrawal(stop, (staged(1),)), Worker()
    with pytest.raises(ChatError, match="GENERAL_CHAT_RUNTIME_STOPPED"):
        resident(execution, worker).run(stop)
    assert len(worker.calls) == len(execution.completed) == 1
    assert execution.withdrawals == [RUNTIME]


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("heartbeat_seconds", 0),
        ("heartbeat_seconds", 11),
        ("heartbeat_seconds", float("nan")),
        ("heartbeat_seconds", float("inf")),
        ("idle_seconds", 0),
        ("idle_seconds", 31),
        ("idle_seconds", float("nan")),
    ],
)
def test_runtime_intervals_are_finite_bounded(parameter: str, value: float) -> None:
    stop = Event()
    with pytest.raises(ValueError):
        GeneralChatResident(Execution(stop), Worker(), runtime_id=RUNTIME, **{parameter: value})

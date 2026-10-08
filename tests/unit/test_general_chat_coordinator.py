"""Epoch renewal is recovery-first, not a model retry or a new queue."""

from __future__ import annotations

from threading import Event, Thread

import pytest
from eom_orchestrator import general_chat_coordinator as runtime
from eom_orchestrator.general_chat_execution import ChatClaim
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code
from eom_protocol.general_chat_worker_messages import ChatWorkerOutput

from tests.unit.test_general_chat_dispatch import dispatch
from tests.unit.test_general_chat_resident import Execution, Worker, answer, staged


class RecoveryExecution:
    def __init__(self, active=False):
        self.claim = (
            ChatClaim(
                dispatch().runtime_id,
                staged(1).conversation_id,
                staged(1).turn_id,
                staged(1).claim_id,
            )
            if active
            else None
        )
        self.events = []

    def active_claim(self):
        self.events.append("read-claim")
        return self.claim

    def execution_receipt(self, claim):
        assert claim == self.claim
        self.events.append("read-pinned-receipt")
        return dispatch()

    def reconcile_known_result(self, claim, result):
        assert claim == self.claim and result == answer(staged(1))
        self.events.append("reconcile-exact")
        self.claim = None


class RecoveryWorker:
    def __init__(self, execution, state="KNOWN"):
        self.execution, self.state = execution, state

    def lookup(self, ticket):
        assert ticket == dispatch().ticket
        self.execution.events.append("read-local-result")
        return ChatWorkerOutput(
            state=self.state,
            result=answer(staged(1)) if self.state == "KNOWN" else None,
        )


def test_new_epoch_is_created_only_after_known_result_reconciliation(monkeypatch):
    stop = Event()
    execution = RecoveryExecution(active=True)

    class Resident:
        def __init__(self, selected_execution, worker, *, runtime_id):
            assert selected_execution is execution and execution.claim is None
            assert runtime_id.startswith("chatrt_")
            execution.events.append("new-epoch")

        def run(self, phase_stop):
            assert phase_stop is not stop
            stop.set()

    monkeypatch.setattr(runtime, "GeneralChatResident", Resident)
    runtime.run_chat_coordinator(
        execution,
        lambda: RecoveryWorker(execution),
        stop=stop,
        report_state=lambda _: None,
    )
    assert execution.events == [
        "read-claim",
        "read-pinned-receipt",
        "read-local-result",
        "reconcile-exact",
        "new-epoch",
    ]


@pytest.mark.parametrize("state", ["UNKNOWN", "ABSENT"])
def test_unknown_old_result_never_admits_or_dispatches_a_new_epoch(monkeypatch, state):
    stop = Event()
    execution = RecoveryExecution(active=True)
    reports = []

    def forbidden(*args, **kwargs):
        pytest.fail("unknown result must not start a resident")

    def report(code):
        reports.append(code)
        stop.set()

    monkeypatch.setattr(runtime, "GeneralChatResident", forbidden)
    runtime.run_chat_coordinator(
        execution,
        lambda: RecoveryWorker(execution, state),
        stop=stop,
        report_state=report,
    )
    assert reports == ["GENERAL_CHAT_RECONCILIATION_REQUIRED"]
    assert execution.claim is not None
    assert execution.events == ["read-claim", "read-pinned-receipt", "read-local-result"]


def test_boot_change_renews_only_client_and_runtime_not_old_identity(monkeypatch):
    stop = Event()
    execution = RecoveryExecution()
    selected = []
    reports = []

    class Resident:
        def __init__(self, execution, worker, *, runtime_id):
            selected.append((worker, runtime_id))

        def run(self, phase_stop):
            if len(selected) == 1:
                phase_stop.set()
                raise ChatError("GENERAL_CHAT_WORKER_NOT_READY")
            stop.set()

    monkeypatch.setattr(runtime, "GeneralChatResident", Resident)
    runtime.run_chat_coordinator(
        execution,
        lambda: RecoveryWorker(execution),
        stop=stop,
        report_state=reports.append,
        retry_seconds=0.001,
    )
    assert len(selected) == 2
    assert selected[0][0] is not selected[1][0] and selected[0][1] != selected[1][1]
    assert reports == ["GENERAL_CHAT_WORKER_NOT_READY"]
    assert execution.events == ["read-claim", "read-claim"]


def test_global_stop_drains_in_flight_known_answer_and_joins_epoch_threads():
    stop, entered, release = Event(), Event(), Event()

    class OwnerExecution(Execution):
        def active_claim(self):
            return self.active

        def heartbeat(self, *, runtime_id):
            self.heartbeats += 1

    class BlockingWorker(Worker):
        def answer(self, request):
            entered.set()
            assert release.wait(3)
            return super().answer(request)

    execution, worker = OwnerExecution(stop, (staged(1),)), BlockingWorker()
    thread = Thread(
        target=runtime.run_chat_coordinator,
        args=(execution, lambda: worker),
        kwargs={"stop": stop, "report_state": lambda _: None},
    )
    thread.start()
    try:
        assert entered.wait(2)
        stop.set()
        assert thread.is_alive() and not execution.completed
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert execution.completed == [answer(staged(1))]
    assert len(execution.withdrawals) == 1 and len(worker.calls) == 1


def test_unavailable_worker_keeps_zero_claims_and_sanitizes_optional_reporter_failure():
    stop = Event()
    execution = RecoveryExecution()
    calls = 0

    def worker_factory():
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        raise RuntimeError("credential=/private/not-for-reporting")

    reports = []

    def report(code):
        reports.append(code)
        raise RuntimeError("optional reporter failed")

    runtime.run_chat_coordinator(
        execution,
        worker_factory,
        stop=stop,
        report_state=report,
        retry_seconds=0.001,
    )
    assert reports == ["GENERAL_CHAT_RUNTIME_STOPPED"] and not execution.events


@pytest.mark.parametrize("interval", [0, -1, 31, float("nan"), float("inf")])
def test_invalid_admission_intervals_are_rejected(interval):
    with pytest.raises(ValueError):
        runtime.run_chat_coordinator(
            RecoveryExecution(),
            lambda: None,
            stop=Event(),
            report_state=lambda _: None,
            retry_seconds=interval,
        )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("private secret"),
        ChatError("not-a-code"),
        ChatError("GENERAL_CHAT_" + "X" * 48),
    ],
)
def test_reporting_codes_never_export_arbitrary_exception_text(error):
    assert safe_chat_error_code(error) == "GENERAL_CHAT_RUNTIME_STOPPED"

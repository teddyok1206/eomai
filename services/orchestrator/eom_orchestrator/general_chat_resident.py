"""Single dedicated execution loop; never generates or replays an unknown turn.

The application knows only execution and worker ports. OS admission, native
processes, private transport, DB and Artifact publication stay in their adapters.
"""

from __future__ import annotations

import math
import re
from contextlib import suppress
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from typing import Protocol

from eom_protocol.general_chat_dispatch import ChatExecutionIdentity
from eom_protocol.general_chat_turn_contracts import (
    ChatInputContract as ChatTurnInput,
)
from eom_protocol.general_chat_turn_contracts import (
    ChatResultContract as ChatTurnResult,
)
from eom_protocol.general_chat_turn_contracts import (
    read_chat_input as read_chat_turn_input,
)
from eom_protocol.general_chat_turn_contracts import (
    read_chat_result as read_chat_turn_result,
)

from eom_orchestrator.general_chat_execution import ChatClaim, ChatPreparationRejected
from eom_orchestrator.general_chat_state import CHAT_HEARTBEAT_TTL, ChatError, safe_chat_error_code


class ChatExecutionPort(Protocol):
    def heartbeat(self, *, runtime_id: str) -> None: ...
    def withdraw(self, *, runtime_id: str) -> bool: ...
    def claim_next(self, *, runtime_id: str) -> ChatClaim | None: ...
    def prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatTurnInput: ...
    def complete(self, claim: ChatClaim, result: ChatTurnResult) -> None: ...


class ChatWorkerPort(Protocol):
    @property
    def execution_identity(self) -> ChatExecutionIdentity: ...

    def check_admission(self) -> None:
        """Bounded, thread-safe readiness check; no inference/auth enrollment.

        The adapter must verify the configured isolated worker, effective policy
        and native liveness, including during an answer. A UI badge is not proof.
        """
        ...

    def answer(self, request: ChatTurnInput) -> ChatTurnResult:
        """Execute once; unknown outcome raises, never silently retries."""
        ...


class GeneralChatResident:
    def __init__(
        self,
        execution: ChatExecutionPort,
        worker: ChatWorkerPort,
        *,
        runtime_id: str,
        heartbeat_seconds: float = 10.0,
        idle_seconds: float = 1.0,
    ) -> None:
        if re.fullmatch(r"chatrt_[0-9a-f]{32}", runtime_id) is None:
            raise ValueError("invalid dedicated runtime identity")
        if not math.isfinite(heartbeat_seconds) or not (
            0 < heartbeat_seconds <= CHAT_HEARTBEAT_TTL.total_seconds() / 3
        ):
            raise ValueError("heartbeat interval exceeds admission budget")
        if not math.isfinite(idle_seconds) or not 0 < idle_seconds <= 30:
            raise ValueError("invalid idle interval")
        self.execution = execution
        self.worker = worker
        self.runtime_id = runtime_id
        self.heartbeat_seconds = heartbeat_seconds
        self.idle_seconds = idle_seconds
        self._run_lock = Lock()

    def _monitor(self, done: Event, stop: Event, errors: SimpleQueue[str]) -> None:
        while not done.wait(self.heartbeat_seconds):
            try:
                self.worker.check_admission()
                self.execution.heartbeat(runtime_id=self.runtime_id)
            except Exception as error:
                errors.put(safe_chat_error_code(error))
                # A long answer may still drain; revoke known-lost availability
                # immediately instead of waiting for that answer to return.
                with suppress(Exception):
                    self.execution.withdraw(runtime_id=self.runtime_id)
                stop.set()
                return

    def run(self, stop: Event) -> None:
        """Block until drained/stopped; exact failures require operator recovery.

        Stop interrupts only idle waiting/new claims. An already claimed answer
        can drain under its original lease; a known validated result is committed
        even after stop. The owning adapter must bound worker/DB calls so shutdown
        and heartbeat cannot wait indefinitely.
        """
        if not self._run_lock.acquire(blocking=False):
            raise ChatError("GENERAL_CHAT_RUNTIME_IN_USE")
        announced = False
        done = Event()
        errors: SimpleQueue[str] = SimpleQueue()
        monitor: Thread | None = None
        monitor_started = False
        failure: str | None = None
        try:
            if stop.is_set():
                return
            self.worker.check_admission()
            identity = self.worker.execution_identity
            if stop.is_set():
                return
            # A timed-out DB call may already have committed; exact-runtime
            # withdrawal is also required after an uncertain initial announcement.
            announced = True
            self.execution.heartbeat(runtime_id=self.runtime_id)
            monitor = Thread(
                target=self._monitor,
                args=(done, stop, errors),
                name="general-chat-heartbeat",
            )
            monitor.start()
            monitor_started = True
            while not stop.is_set():
                self.worker.check_admission()
                if stop.is_set():
                    break
                claim = self.execution.claim_next(runtime_id=self.runtime_id)
                if claim is None:
                    stop.wait(self.idle_seconds)
                    continue
                try:
                    request = read_chat_turn_input(
                        self.execution.prepare(claim, identity=identity).model_dump(mode="json")
                    )
                except ChatPreparationRejected:
                    # No worker call occurred; the supported owner transition released
                    # this exact claim. Other queued conversations may proceed normally.
                    continue
                if claim.runtime_id != self.runtime_id or (
                    request.conversation_id,
                    request.turn_id,
                    request.claim_id,
                ) != (claim.conversation_id, claim.turn_id, claim.claim_id):
                    raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
                result = read_chat_turn_result(
                    self.worker.answer(request).model_dump(mode="json"), request=request
                )
                self.execution.complete(claim, result)
        except Exception as error:
            failure = safe_chat_error_code(error)
        finally:
            done.set()
            if monitor is not None and monitor_started:
                monitor.join()
            if failure is None:
                with suppress(Empty):
                    failure = errors.get_nowait()
            # Even an exception during drain must not leave the slot falsely READY.
            # Withdrawal never releases/reassigns the active claim or alters history.
            if announced:
                try:
                    self.execution.withdraw(runtime_id=self.runtime_id)
                except Exception as error:
                    if failure is None:
                        failure = safe_chat_error_code(error)
            self._run_lock.release()
        if failure is not None:
            raise ChatError(failure) from None

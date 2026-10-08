"""Keep transcript RPC independent of a fenced/unavailable execution epoch."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Thread
from typing import Protocol
from uuid import uuid4

from eom_orchestrator.general_chat_recovery import (
    ChatRecoveryExecutionPort,
    ChatRecoveryWorkerPort,
    recover_known_chat_turn,
)
from eom_orchestrator.general_chat_resident import (
    ChatExecutionPort,
    ChatWorkerPort,
    GeneralChatResident,
)
from eom_orchestrator.general_chat_state import safe_chat_error_code


class ChatOwnerExecutionPort(ChatExecutionPort, ChatRecoveryExecutionPort, Protocol):
    pass


class ChatRuntimeWorkerPort(ChatWorkerPort, ChatRecoveryWorkerPort, Protocol):
    pass


_FENCED_WAIT_SECONDS = {
    "GENERAL_CHAT_RECONCILIATION_REQUIRED": 30.0,
    "GENERAL_CHAT_RECOVERY_NOT_QUIESCENT": 10.0,
}


def _relay_stop(stop: Event, phase_stop: Event, phase_done: Event) -> None:
    while not phase_done.is_set():
        if stop.wait(0.2):
            phase_stop.set()
            return


def run_chat_coordinator(
    execution: ChatOwnerExecutionPort,
    worker_factory: Callable[[], ChatRuntimeWorkerPort],
    *,
    stop: Event,
    report_state: Callable[[str], None],
    retry_seconds: float = 3.0,
) -> None:
    if not math.isfinite(retry_seconds) or not 0 < retry_seconds <= 30:
        raise ValueError("invalid chat admission retry interval")
    last_state: str | None = None
    while not stop.is_set():
        state = "GENERAL_CHAT_RUNTIME_DRAINED"
        try:
            # A new client may admit a new worker boot, but only after old exact
            # known-result recovery. Unknown/absent outcomes never reach run/claim.
            worker = worker_factory()
            recover_known_chat_turn(execution, worker)
            if stop.is_set():
                break
            phase_stop, phase_done = Event(), Event()
            relay = Thread(
                target=_relay_stop,
                args=(stop, phase_stop, phase_done),
                name="general-chat-stop",
            )
            relay.start()
            try:
                GeneralChatResident(
                    execution,
                    worker,
                    runtime_id="chatrt_" + uuid4().hex,
                ).run(phase_stop)
            finally:
                phase_done.set()
                relay.join()
        except Exception as error:
            state = safe_chat_error_code(error)
        if stop.is_set():
            break
        if state != last_state:
            # Observability is optional and cannot alter execution/recovery.
            with suppress(Exception):
                report_state(state)
            last_state = state
        stop.wait(_FENCED_WAIT_SECONDS.get(state, retry_seconds))

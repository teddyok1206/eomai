"""One finite handle for two explicit native QUERY families, never a queue or grant."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Thread
from typing import Literal

from eom_workflow.models import WorkflowId
from pydantic import TypeAdapter

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.native_query_prepare_runner import (
    NativeQueryDriveOffer,
    require_private_chat_query_prepare_runner,
    require_reference_query_prepare_runner,
)
from eom_workflow_runner.repository import CommandExecutionFamily

type NativeQueryDriveOutcome = Literal[
    "PROCESSED", "NO_READY_COMMAND", "UNAVAILABLE", "START_FAILED"
]


@dataclass(frozen=True, slots=True)
class NativeQueryDriveObservation:
    workflow_id: str | None
    active: bool
    outcome: NativeQueryDriveOutcome | None


class NativeQueryPrepareDriver:
    """Service-owned single handle. Busy requests retain only their existing DB work.

    No SQL roots or captured runner are stored in a task registry. One command is
    naturally bounded by the existing native execution limits. On exit Thread
    discards its arguments, including the operation-local capture.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._thread: Thread | None = None
        self._workflow_id: str | None = None
        self._outcome: NativeQueryDriveOutcome | None = None
        self._family: CommandExecutionFamily | None = None
        self._closed = False

    def close(self) -> None:
        """Stop offers and drain only the existing bounded invocation; never cancel/retry it."""
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join()

    def observe(self) -> NativeQueryDriveObservation:
        with self._lock:
            return NativeQueryDriveObservation(
                self._workflow_id,
                self._thread is not None and self._thread.is_alive(),
                self._outcome,
            )

    def offer(self, workflow_id: str, runner: WorkflowRunner) -> NativeQueryDriveOffer:
        """Preserved reference-only public entry; private work cannot borrow its guard."""
        require_reference_query_prepare_runner(runner)
        return self._offer(workflow_id, runner, family=CommandExecutionFamily.REFERENCE_QUERY)

    def offer_private_chat_query(
        self, workflow_id: str, runner: WorkflowRunner
    ) -> NativeQueryDriveOffer:
        require_private_chat_query_prepare_runner(runner)
        return self._offer(workflow_id, runner, family=CommandExecutionFamily.PRIVATE_CHAT_QUERY)

    def _offer(
        self, workflow_id: str, runner: WorkflowRunner, *, family: CommandExecutionFamily
    ) -> NativeQueryDriveOffer:
        workflow_id = TypeAdapter(WorkflowId).validate_python(workflow_id, strict=True)
        with self._lock:
            if self._closed:
                return "UNAVAILABLE"
            if self._thread is not None and self._thread.is_alive():
                return (
                    "ALREADY_ACTIVE"
                    if (self._workflow_id, self._family) == (workflow_id, family)
                    else "BUSY"
                )
            self._workflow_id, self._outcome = workflow_id, None
            self._family = family
            thread = Thread(
                target=self._run_once,
                args=(workflow_id, runner),
                name=(
                    "eom-reference-query-driver"
                    if family is CommandExecutionFamily.REFERENCE_QUERY
                    else "eom-private-chat-query-driver"
                ),
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except (RuntimeError, OSError):
                self._thread = None
                self._outcome = "START_FAILED"
                return "UNAVAILABLE"
            return "STARTED"

    def _run_once(self, workflow_id: str, runner: WorkflowRunner) -> None:
        try:
            command = runner.run_once(workflow_id)
            outcome: NativeQueryDriveOutcome = (
                "NO_READY_COMMAND" if command is None else "PROCESSED"
            )
        except BaseException:
            # The durable claim/Job may already exist. Never retry here, change
            # the row, retain an exception/traceback or infer Workflow failure.
            # A cancelled child is unknown too; do not disclose private input
            # through the process-wide thread exception hook.
            outcome = "UNAVAILABLE"
        with self._lock:
            self._outcome = outcome
        # Retain the actual Thread handle until it is no longer alive, not an
        # early false IDLE flag that could overlap another physical invocation.

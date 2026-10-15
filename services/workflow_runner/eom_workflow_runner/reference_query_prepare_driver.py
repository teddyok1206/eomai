"""One actual Runner invocation, no memory queue, cached authority or native restart."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Thread
from typing import Literal

from eom_workflow.models import WorkflowId
from pydantic import TypeAdapter

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.reference_query_prepare_application import (
    ReferenceQueryDriveOffer,
    require_reference_query_prepare_runner,
)

type ReferenceQueryDriveOutcome = Literal[
    "PROCESSED", "NO_READY_COMMAND", "UNAVAILABLE", "START_FAILED"
]


@dataclass(frozen=True, slots=True)
class ReferenceQueryDriveObservation:
    workflow_id: str | None
    active: bool
    outcome: ReferenceQueryDriveOutcome | None


class ReferenceQueryPrepareDriver:
    """Service-owned single handle. Busy requests retain only their existing DB work.

    No SQL roots or captured runner are stored in a task registry. One command is
    naturally bounded by the existing native execution limits. On exit Thread
    discards its arguments, including the operation-local capture.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._thread: Thread | None = None
        self._workflow_id: str | None = None
        self._outcome: ReferenceQueryDriveOutcome | None = None
        self._closed = False

    def close(self) -> None:
        """Stop offers and drain only the existing bounded invocation; never cancel/retry it."""
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join()

    def observe(self) -> ReferenceQueryDriveObservation:
        with self._lock:
            return ReferenceQueryDriveObservation(
                self._workflow_id,
                self._thread is not None and self._thread.is_alive(),
                self._outcome,
            )

    def offer(self, workflow_id: str, runner: WorkflowRunner) -> ReferenceQueryDriveOffer:
        workflow_id = TypeAdapter(WorkflowId).validate_python(workflow_id, strict=True)
        require_reference_query_prepare_runner(runner)
        with self._lock:
            if self._closed:
                return "UNAVAILABLE"
            if self._thread is not None and self._thread.is_alive():
                return "ALREADY_ACTIVE" if self._workflow_id == workflow_id else "BUSY"
            self._workflow_id, self._outcome = workflow_id, None
            thread = Thread(
                target=self._run_once,
                args=(workflow_id, runner),
                name="eom-reference-query-driver",
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
            outcome: ReferenceQueryDriveOutcome = (
                "NO_READY_COMMAND" if command is None else "PROCESSED"
            )
        except Exception:
            # The durable claim/Job may already exist. Never retry here, change
            # the row, retain an exception/traceback or infer Workflow failure.
            outcome = "UNAVAILABLE"
        with self._lock:
            self._outcome = outcome
        # Retain the actual Thread handle until it is no longer alive, not an
        # early false IDLE flag that could overlap another physical invocation.

"""One finite handle for two explicit native QUERY families, never a queue or grant."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Thread
from typing import TYPE_CHECKING, Literal

from eom_workflow.models import WorkflowId
from pydantic import TypeAdapter

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.native_query_prepare_runner import (
    NativeQueryDriveOffer,
    require_private_chat_query_prepare_runner,
    require_reference_query_prepare_runner,
)
from eom_workflow_runner.repository import CommandExecutionFamily

if TYPE_CHECKING:
    from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession
    from eom_workflow_runner.reference_query_routed_selection import (
        PreparedRoutedReferenceQuerySelection,
    )

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
        self._routed_parent_sha256: str | None = None
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

    def offer_routed_reference_batch(
        self,
        session: RoutedReferenceQuerySession,
        prepared: PreparedRoutedReferenceQuerySelection,
    ) -> NativeQueryDriveOffer:
        """One finite original batch on the existing service handle, never a task registry."""
        from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession
        from eom_workflow_runner.reference_query_routed_selection import (
            PreparedRoutedReferenceQuerySelection,
        )

        if (
            type(session) is not RoutedReferenceQuerySession
            or type(prepared) is not PreparedRoutedReferenceQuerySelection
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_COMPOSITION_INVALID")
        parent = prepared.preparation.parent.request_sha256
        with self._lock:
            if self._closed:
                return "UNAVAILABLE"
            if self._thread is not None and self._thread.is_alive():
                return "ALREADY_ACTIVE" if self._routed_parent_sha256 == parent else "BUSY"
            self._workflow_id, self._outcome = None, None
            self._family, self._routed_parent_sha256 = (
                CommandExecutionFamily.REFERENCE_QUERY,
                parent,
            )
            thread = Thread(
                target=self._run_routed_once,
                args=(session, prepared),
                name="eom-routed-reference-query-driver",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except (RuntimeError, OSError):
                self._thread, self._outcome = None, "START_FAILED"
                return "UNAVAILABLE"
            return "STARTED"

    def _run_routed_once(
        self, session: RoutedReferenceQuerySession, prepared: PreparedRoutedReferenceQuerySelection
    ) -> None:
        from eom_workflow_runner.reference_query_routed_execution import (
            drive_routed_reference_queries_once,
        )

        try:
            observed = drive_routed_reference_queries_once(session, prepared)
            outcome: NativeQueryDriveOutcome = (
                "PROCESSED" if observed.state == "READY" else "UNAVAILABLE"
            )
        except BaseException:
            # The original preparation/claim may already exist. No retained
            # exception/capture, automatic retry, fresh identity or CPU fallback.
            outcome = "UNAVAILABLE"
        with self._lock:
            self._outcome = outcome

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
            self._routed_parent_sha256 = None
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

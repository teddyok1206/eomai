"""Close a proven original pre-launch failure; never execute, retry or publish bytes."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    PRELAUNCH_FAILURE_CODE,
    PRELAUNCH_FAILURE_EVENT,
    BenchmarkPrelaunchFailureDecision,
    BenchmarkPrelaunchObservation,
    BenchmarkPrelaunchPredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    BenchmarkSourceAdmission,
    require_benchmark_job_in_session,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import (
    BenchmarkLaunchHistory,
    BenchmarkLaunchJournal,
    record_benchmark_prelaunch_predecessor_in_session,
    require_benchmark_prelaunch_observation,
    require_benchmark_prelaunch_predecessor,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionAdmission
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState, transition_job


class BenchmarkPrelaunchFailureError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CapturedBenchmarkPrelaunchInspection(Protocol):
    """Trusted adapter-owned live capture, not a model-supplied parsed observation."""

    @property
    def observation(self) -> BenchmarkPrelaunchObservation: ...

    def assert_current(self) -> None: ...


class BenchmarkPrelaunchInspection(Protocol):
    """Installed composition must select the actual protected-root proof adapter."""

    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> AbstractContextManager[CapturedBenchmarkPrelaunchInspection]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkPrelaunchFailureClosure:
    decision: BenchmarkPrelaunchFailureDecision
    event_sequence: int
    created: bool

    @property
    def predecessor(self) -> BenchmarkPrelaunchPredecessorReference:
        return BenchmarkPrelaunchPredecessorReference.from_decision(
            self.decision, event_sequence=self.event_sequence
        )


def _existing_closure(history: BenchmarkLaunchHistory) -> BenchmarkPrelaunchFailureClosure | None:
    failure = history.prelaunch_failure
    if failure is not None:
        if history.job_state != JobState.FAILED:
            raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_TERMINAL_CONFLICT")
        return BenchmarkPrelaunchFailureClosure(failure.decision, failure.event_sequence, False)
    if history.job_state != JobState.RUNNING:
        raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_TERMINAL_OR_FOREIGN")
    return None


def _original_invocation(history: BenchmarkLaunchHistory) -> BenchmarkWorkerInvocation:
    if len(history.launches) != 1 or history.launches[0].receipt is not None:
        raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_ORIGINAL_UNRESOLVED_REQUIRED")
    invocation = history.launches[0].invocation
    if invocation.device != "CPU" or invocation.launch_ordinal != 1:
        raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_CPU_FIRST_REQUIRED")
    return invocation


class BenchmarkPrelaunchFailureApplication:
    """Fresh-authorized original-Job failure recording; no capacity, launch or NAS effects."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        admission: BenchmarkExecutionAdmission,
        inspection: BenchmarkPrelaunchInspection,
    ) -> None:
        self.sessions, self.admission, self.inspection = sessions, admission, inspection
        self.journal = BenchmarkLaunchJournal(admission, admission)

    def close(
        self, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> BenchmarkPrelaunchFailureClosure:
        try:
            embedding_device_benchmark_bytes(request)
        except (ValueError, TypeError, SchemaError):
            raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_REQUEST_INVALID") from None
        # Discover only the already-reserved original invocation under current
        # authority; no SQL transaction spans the expensive initial OS capture.
        with (
            self.sessions() as session,
            session.begin(),
            self.admission.admit_execution_in_session(session, request),
        ):
            history = self.journal.read(session, request, job_id=job_id)
            replay = _existing_closure(history)
            if replay is not None:
                return replay
            invocation = _original_invocation(history)
        with self.inspection.capture(request, invocation) as captured:
            observation = require_benchmark_prelaunch_observation(
                request, invocation, captured.observation
            )
            captured.assert_current()
            with self.sessions() as session, session.begin():
                with self.admission.admit_execution_in_session(session, request):
                    history = self.journal.read(session, request, job_id=job_id)
                    replay = _existing_closure(history)
                    if replay is not None:
                        if replay.decision.observation != observation:
                            raise BenchmarkPrelaunchFailureError(
                                "BENCHMARK_PRELAUNCH_REPLAY_CONFLICT"
                            )
                        captured.assert_current()
                        return replay
                    if _original_invocation(history) != invocation:
                        raise BenchmarkPrelaunchFailureError(
                            "BENCHMARK_PRELAUNCH_RESERVATION_CHANGED"
                        )
                    captured.assert_current()
                    body = dict(
                        schema_version="embedding-benchmark-prelaunch-failure/1.0",
                        kind="FAILURE_DECISION",
                        job_id=job_id,
                        execution_id=invocation.execution_id,
                        request_sha256=request.request_sha256,
                        invocation_sha256=invocation.invocation_sha256,
                        from_state="RUNNING",
                        to_state="FAILED",
                        error_code=PRELAUNCH_FAILURE_CODE,
                        observation=observation.model_dump(mode="json"),
                        actor_id=request.operator_audit_id,
                        decided_at=datetime.now(UTC)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z"),
                    )
                    decision = BenchmarkPrelaunchFailureDecision.model_validate(
                        body | {"decision_sha256": content_sha256(body)}
                    )
                    job = transition_job(
                        session,
                        job_id,
                        JobState.FAILED,
                        PRELAUNCH_FAILURE_EVENT,
                        data=decision.model_dump(mode="json"),
                    )
                    job.error_code = PRELAUNCH_FAILURE_CODE
                    job.error_message = "benchmark preparation failed before native CPU start"
                    session.flush()
                    validated = self.journal.read(session, request, job_id=job_id)
                    stored = validated.prelaunch_failure
                    if stored is None:
                        raise BenchmarkPrelaunchFailureError("BENCHMARK_PRELAUNCH_HISTORY_INVALID")
                    result = BenchmarkPrelaunchFailureClosure(decision, stored.event_sequence, True)
                    captured.assert_current()
                # A late proof failure, like a late Identity/source failure,
                # must roll back the same terminal transition and audit event.
                captured.assert_current()
            return result


def submit_benchmark_prelaunch_successor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    predecessor: BenchmarkPrelaunchPredecessorReference,
    *,
    source_admission: BenchmarkSourceAdmission,
) -> tuple[JobRecord, bool]:
    """Register a guarded new revision and its pinned parent in one authorized root.

    No execution ID is allocated here. Ordinary owner installation, capacity and
    current-source admission still apply before any later native launch.
    """
    try:
        embedding_device_benchmark_bytes(request)
        predecessor = BenchmarkPrelaunchPredecessorReference.model_validate(predecessor)
    except (ValueError, TypeError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_PRELAUNCH_SUCCESSOR_INVALID") from None
    with source_admission.admit_in_session(session, request) as inputs:
        require_benchmark_prelaunch_predecessor(session, request, inputs, predecessor)
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=source_admission
        )
        record_benchmark_prelaunch_predecessor_in_session(
            session, request, inputs, predecessor, job_id=job.job_id
        )
        require_benchmark_job_in_session(session, request, job_id=job.job_id)
        return job, created

"""Close one proven started CPU failure; never compute, retry or publish a fake result."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.embedding_benchmark_budget600_failure import (
    BenchmarkBudget600FailureDecision,
    BenchmarkBudget600PoststartObservation,
    BenchmarkBudget600PredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_budget1200_failure import (
    BenchmarkBudget1200FailureDecision,
    BenchmarkBudget1200PoststartObservation,
    BenchmarkBudget1200PredecessorReference,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    POSTSTART_FAILURE_CODE,
    POSTSTART_FAILURE_EVENT,
    BenchmarkPoststartFailureDecision,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
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
    record_benchmark_poststart_predecessor_in_session,
    require_benchmark_poststart_observation,
    require_benchmark_poststart_predecessor,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionAdmission
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState, transition_job


class BenchmarkPoststartFailureError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CapturedBenchmarkPoststartInspection(Protocol):
    """Live adapter-owned capture; parsing a user/model observation is insufficient."""

    @property
    def observation(
        self,
    ) -> (
        BenchmarkPoststartObservation
        | BenchmarkBudget600PoststartObservation
        | BenchmarkBudget1200PoststartObservation
    ): ...

    def assert_current(self) -> None: ...


class BenchmarkPoststartInspection(Protocol):
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> AbstractContextManager[CapturedBenchmarkPoststartInspection]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkPoststartFailureClosure:
    decision: (
        BenchmarkPoststartFailureDecision
        | BenchmarkBudget600FailureDecision
        | BenchmarkBudget1200FailureDecision
    )
    event_sequence: int
    created: bool

    @property
    def predecessor(
        self,
    ) -> (
        BenchmarkPoststartPredecessorReference
        | BenchmarkBudget600PredecessorReference
        | BenchmarkBudget1200PredecessorReference
    ):
        if isinstance(self.decision, BenchmarkBudget600FailureDecision):
            return BenchmarkBudget600PredecessorReference.from_decision(
                self.decision, event_sequence=self.event_sequence
            )
        if isinstance(self.decision, BenchmarkBudget1200FailureDecision):
            return BenchmarkBudget1200PredecessorReference.from_decision(
                self.decision, event_sequence=self.event_sequence
            )
        return BenchmarkPoststartPredecessorReference.from_decision(
            self.decision, event_sequence=self.event_sequence
        )


def _existing_closure(history: BenchmarkLaunchHistory) -> BenchmarkPoststartFailureClosure | None:
    failure = history.poststart_failure
    if failure is not None:
        if history.job_state != JobState.FAILED:
            raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_TERMINAL_CONFLICT")
        return BenchmarkPoststartFailureClosure(failure.decision, failure.event_sequence, False)
    if history.job_state != JobState.RUNNING:
        raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_TERMINAL_OR_FOREIGN")
    return None


def _original_invocation(history: BenchmarkLaunchHistory) -> BenchmarkWorkerInvocation:
    if len(history.launches) != 1 or history.launches[0].receipt is not None:
        raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_ORIGINAL_UNRESOLVED_REQUIRED")
    invocation = history.launches[0].invocation
    if invocation.device != "CPU" or invocation.launch_ordinal != 1:
        raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_CPU_FIRST_REQUIRED")
    return invocation


class BenchmarkPoststartFailureApplication:
    """Current-source-fenced append-only failure closure, without capacity or NAS effects."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        admission: BenchmarkExecutionAdmission,
        inspection: BenchmarkPoststartInspection,
    ) -> None:
        self.sessions, self.admission, self.inspection = sessions, admission, inspection
        self.journal = BenchmarkLaunchJournal(admission, admission)

    def close(
        self, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> BenchmarkPoststartFailureClosure:
        try:
            embedding_device_benchmark_bytes(request)
        except (ValueError, TypeError, SchemaError):
            raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_REQUEST_INVALID") from None
        # Discover the exact reserved invocation before expensive OS capture; do
        # not hold a DB transaction while reading protected partial outputs.
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
            observation = require_benchmark_poststart_observation(
                request, invocation, captured.observation
            )
            captured.assert_current()
            with self.sessions() as session, session.begin():
                with self.admission.admit_execution_in_session(session, request):
                    history = self.journal.read(session, request, job_id=job_id)
                    replay = _existing_closure(history)
                    if replay is not None:
                        if replay.decision.observation != observation:
                            raise BenchmarkPoststartFailureError(
                                "BENCHMARK_POSTSTART_REPLAY_CONFLICT"
                            )
                        captured.assert_current()
                        return replay
                    if _original_invocation(history) != invocation:
                        raise BenchmarkPoststartFailureError(
                            "BENCHMARK_POSTSTART_RESERVATION_CHANGED"
                        )
                    captured.assert_current()
                    body = dict(
                        schema_version=observation.schema_version,
                        kind="FAILURE_DECISION",
                        job_id=job_id,
                        execution_id=invocation.execution_id,
                        request_sha256=request.request_sha256,
                        invocation_sha256=invocation.invocation_sha256,
                        from_state="RUNNING",
                        to_state="FAILED",
                        error_code=POSTSTART_FAILURE_CODE,
                        observation=observation.model_dump(mode="json"),
                        actor_id=request.operator_audit_id,
                        decided_at=datetime.now(UTC)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z"),
                    )
                    decision: (
                        BenchmarkPoststartFailureDecision
                        | BenchmarkBudget600FailureDecision
                        | BenchmarkBudget1200FailureDecision
                    )
                    if isinstance(observation, BenchmarkBudget600PoststartObservation):
                        decision = BenchmarkBudget600FailureDecision.model_validate(
                            body | {"decision_sha256": content_sha256(body)}
                        )
                    elif isinstance(observation, BenchmarkBudget1200PoststartObservation):
                        decision = BenchmarkBudget1200FailureDecision.model_validate(
                            body | {"decision_sha256": content_sha256(body)}
                        )
                    else:
                        decision = BenchmarkPoststartFailureDecision.model_validate(
                            body | {"decision_sha256": content_sha256(body)}
                        )
                    job = transition_job(
                        session,
                        job_id,
                        JobState.FAILED,
                        POSTSTART_FAILURE_EVENT,
                        data=decision.model_dump(mode="json"),
                    )
                    job.error_code = POSTSTART_FAILURE_CODE
                    job.error_message = "benchmark native CPU failed after actual start"
                    session.flush()
                    validated = self.journal.read(session, request, job_id=job_id)
                    stored = validated.poststart_failure
                    if stored is None:
                        raise BenchmarkPoststartFailureError("BENCHMARK_POSTSTART_HISTORY_INVALID")
                    result = BenchmarkPoststartFailureClosure(decision, stored.event_sequence, True)
                    captured.assert_current()
                # Roll back the event and terminal state together on late source,
                # identity, original-process, partial-file or cleanup changes.
                captured.assert_current()
            return result


def submit_benchmark_poststart_successor_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    predecessor: (
        BenchmarkPoststartPredecessorReference
        | BenchmarkBudget600PredecessorReference
        | BenchmarkBudget1200PredecessorReference
    ),
    *,
    source_admission: BenchmarkSourceAdmission,
) -> tuple[JobRecord, bool]:
    """One explicit budget successor after durable failure closure, never automatic retry."""
    try:
        embedding_device_benchmark_bytes(request)
        predecessor = (
            BenchmarkBudget600PredecessorReference.model_validate(predecessor)
            if isinstance(predecessor, BenchmarkBudget600PredecessorReference)
            else (
                BenchmarkBudget1200PredecessorReference.model_validate(predecessor)
                if isinstance(predecessor, BenchmarkBudget1200PredecessorReference)
                else BenchmarkPoststartPredecessorReference.model_validate(predecessor)
            )
        )
    except (ValueError, TypeError, SchemaError):
        raise BenchmarkJobAdmissionError("BENCHMARK_POSTSTART_SUCCESSOR_INVALID") from None
    with source_admission.admit_in_session(session, request) as inputs:
        require_benchmark_poststart_predecessor(session, request, inputs, predecessor)
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=source_admission
        )
        record_benchmark_poststart_predecessor_in_session(
            session, request, inputs, predecessor, job_id=job.job_id
        )
        require_benchmark_job_in_session(session, request, job_id=job.job_id)
        return job, created

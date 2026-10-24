"""One bounded launch-recovery use case; typed proof families retain different guards."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.embedding_benchmark_failed_attempt import (
    BenchmarkFailedAttemptDecision,
    BenchmarkFailedAttemptObservation,
    require_benchmark_failed_attempt_observation,
)
from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    BenchmarkPreackObservation,
    BenchmarkPreackRecoveryDecision,
    require_benchmark_preack_observation,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.embedding_benchmark_launch_history import BenchmarkLaunchJournal
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionAdmission


class CapturedBenchmarkLaunchInspection(Protocol):
    @property
    def observation(self) -> BenchmarkPreackObservation | BenchmarkFailedAttemptObservation: ...

    def assert_current(self) -> None: ...


class BenchmarkLaunchInspection(Protocol):
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> AbstractContextManager[CapturedBenchmarkLaunchInspection]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchRecovery:
    decision: BenchmarkPreackRecoveryDecision | BenchmarkFailedAttemptDecision
    event_sequence: int
    created: bool


class BenchmarkLaunchRecoveryApplication:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        admission: BenchmarkExecutionAdmission,
        inspection: BenchmarkLaunchInspection,
    ) -> None:
        self.sessions, self.admission, self.inspection = sessions, admission, inspection
        self.journal = BenchmarkLaunchJournal(admission, admission)

    def recover(
        self, request: BenchmarkOwnerRequest, *, job_id: str, execution_id: str
    ) -> BenchmarkLaunchRecovery:
        embedding_device_benchmark_bytes(request)
        with (
            self.sessions() as session,
            session.begin(),
            self.admission.admit_execution_in_session(session, request),
        ):
            history = self.journal.read(session, request, job_id=job_id)
            for retired in history.retired_launches:
                if retired.invocation.execution_id == execution_id:
                    return BenchmarkLaunchRecovery(retired.decision, retired.event_sequence, False)
            if (
                history.job_state != "RUNNING"
                or not history.launches
                or history.launches[-1].receipt is not None
                or history.launches[-1].invocation.execution_id != execution_id
            ):
                raise ValueError("BENCHMARK_PREACK_NOT_RECOVERABLE")
            invocation = history.launches[-1].invocation
        with self.inspection.capture(request, invocation) as captured:
            observed = captured.observation
            observation = (
                require_benchmark_preack_observation(request, invocation, observed)
                if isinstance(observed, BenchmarkPreackObservation)
                else require_benchmark_failed_attempt_observation(request, invocation, observed)
            )
            captured.assert_current()
            with self.sessions() as session, session.begin():
                with self.admission.admit_execution_in_session(session, request):
                    captured.assert_current()
                    body = dict(
                        schema_version=observation.schema_version,
                        kind="RECOVERY_DECISION",
                        job_id=job_id,
                        execution_id=execution_id,
                        request_sha256=request.request_sha256,
                        invocation_sha256=invocation.invocation_sha256,
                        from_state="RUNNING",
                        to_state="RUNNING",
                        reason=(
                            "CUDA_PREACK_FAILED_NO_COMPUTE"
                            if isinstance(observation, BenchmarkPreackObservation)
                            else "FAILED_AFTER_ROOT_ACK"
                        ),
                        observation=observation.model_dump(mode="json"),
                        actor_id=request.operator_audit_id,
                        decided_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    )
                    sealed = body | {"decision_sha256": content_sha256(body)}
                    decision = (
                        BenchmarkPreackRecoveryDecision.model_validate(sealed)
                        if isinstance(observation, BenchmarkPreackObservation)
                        else BenchmarkFailedAttemptDecision.model_validate(sealed)
                    )
                    history, created = self.journal.recover_launch(session, request, decision)
                    result = next(
                        row
                        for row in history.retired_launches
                        if row.invocation.execution_id == execution_id
                    )
                    captured.assert_current()
                captured.assert_current()
            return BenchmarkLaunchRecovery(result.decision, result.event_sequence, created)

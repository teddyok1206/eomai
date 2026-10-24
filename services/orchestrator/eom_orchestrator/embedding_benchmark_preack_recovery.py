"""Bounded pre-ACK recovery with actual operator/source and live root-proof fences."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

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


class CapturedBenchmarkPreackInspection(Protocol):
    @property
    def observation(self) -> BenchmarkPreackObservation: ...

    def assert_current(self) -> None: ...


class BenchmarkPreackInspection(Protocol):
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> AbstractContextManager[CapturedBenchmarkPreackInspection]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkPreackRecovery:
    decision: BenchmarkPreackRecoveryDecision
    event_sequence: int
    created: bool


class BenchmarkPreackRecoveryApplication:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        admission: BenchmarkExecutionAdmission,
        inspection: BenchmarkPreackInspection,
    ) -> None:
        self.sessions, self.admission, self.inspection = sessions, admission, inspection
        self.journal = BenchmarkLaunchJournal(admission, admission)

    def recover(
        self, request: BenchmarkOwnerRequest, *, job_id: str, execution_id: str
    ) -> BenchmarkPreackRecovery:
        embedding_device_benchmark_bytes(request)
        with (
            self.sessions() as session,
            session.begin(),
            self.admission.admit_execution_in_session(session, request),
        ):
            history = self.journal.read(session, request, job_id=job_id)
            for retired in history.retired_preack_launches:
                if retired.invocation.execution_id == execution_id:
                    return BenchmarkPreackRecovery(retired.decision, retired.event_sequence, False)
            if (
                history.job_state != "RUNNING"
                or not history.launches
                or history.launches[-1].receipt is not None
                or history.launches[-1].invocation.execution_id != execution_id
            ):
                raise ValueError("BENCHMARK_PREACK_NOT_RECOVERABLE")
            invocation = history.launches[-1].invocation
        with self.inspection.capture(request, invocation) as captured:
            observation = require_benchmark_preack_observation(
                request, invocation, captured.observation
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
                        reason="CUDA_PREACK_FAILED_NO_COMPUTE",
                        observation=observation.model_dump(mode="json"),
                        actor_id=request.operator_audit_id,
                        decided_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    )
                    decision = BenchmarkPreackRecoveryDecision.model_validate(
                        body | {"decision_sha256": content_sha256(body)}
                    )
                    history, created = self.journal.recover_preack(session, request, decision)
                    result = next(
                        row
                        for row in history.retired_preack_launches
                        if row.invocation.execution_id == execution_id
                    )
                    captured.assert_current()
                captured.assert_current()
            return BenchmarkPreackRecovery(result.decision, result.event_sequence, created)

"""One manually admitted six-launch series; final device assessment stays a separate stage."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    BenchmarkCheckpoint,
    BenchmarkLaunchReceipt,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    validate_benchmark_checkpoint,
)
from eom_identifiers import content_sha256, sha256_bytes
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkSourceAdmission,
    benchmark_job_key,
    require_benchmark_job_in_session,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import (
    BenchmarkLaunchJournal,
    BenchmarkResultReader,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_cpu_execution import (
    native_cpu_capacity,
    require_no_active_native_cpu_execution,
)
from eom_orchestrator.state_machine import JobState, transition_job


class BenchmarkOwnerError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BenchmarkExecutionAdmission(BenchmarkSourceAdmission, BenchmarkResultReader, Protocol):
    def admit_execution_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> AbstractContextManager[BenchmarkStagedInputs]:
        """Reviewed benchmark controls AND current fresh administrator/source authority."""
        ...


class BenchmarkLaunchExecution(Protocol):
    """Trusted Orchestrator child use case, not a worker-supplied callable or grant.

    A concrete installed adapter must retain actual unit/process/device ownership,
    capture checkpoint/resources and verify cleanup, reauthorize before publication,
    and use the existing Orchestrator Artifact publisher. Missing adapter is unavailable.
    This port and a parsed receipt cannot prove any of those live gates.
    """

    def assert_installed(self, request: BenchmarkOwnerRequest) -> None: ...

    def run_and_publish(
        self,
        invocation: BenchmarkWorkerInvocation,
        inputs: BenchmarkStagedInputs,
        authorization: BenchmarkLaunchAuthorization,
    ) -> BenchmarkLaunchReceipt: ...


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchSeries:
    job_id: str
    request_sha256: str
    receipts: tuple[BenchmarkLaunchReceipt, ...]
    dispatch_count: int
    state: str


class BenchmarkLaunchAuthorization:
    """Bound original Job/invocation, independently reauthorized in every short SQL root."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        request: BenchmarkOwnerRequest,
        invocation: BenchmarkWorkerInvocation,
        journal: BenchmarkLaunchJournal,
    ) -> None:
        self._sessions, self._request, self._invocation, self._journal = (
            sessions,
            request,
            invocation,
            journal,
        )

    def assert_current(self) -> None:
        """Required before a child effect/publication; no cached grant is returned."""
        with self._sessions() as session, session.begin():
            history = self._journal.read(session, self._request, job_id=self._invocation.job_id)
            if (
                history.job_state != JobState.RUNNING
                or len(history.launches) != self._invocation.launch_ordinal
                or history.launches[-1].invocation != self._invocation
                or history.launches[-1].receipt is not None
            ):
                raise BenchmarkOwnerError("BENCHMARK_OWNER_LAUNCH_AUTHORIZATION_INVALID")

    def authorize_checkpoint(self, checkpoint: BenchmarkCheckpoint) -> None:
        """The fixed channel still owns peer, sequence, deadline and transcript checks."""
        validate_benchmark_checkpoint(self._invocation, checkpoint, checkpoint.sequence)
        self.assert_current()


def _invocation(
    request: BenchmarkOwnerRequest, inputs: BenchmarkStagedInputs, job_id: str, ordinal: int
) -> BenchmarkWorkerInvocation:
    device = BENCHMARK_DEVICE_SEQUENCE[ordinal - 1]
    raw = embedding_device_benchmark_bytes(inputs)
    body = {
        "schema_version": "embedding-device-benchmark-invocation/1.0",
        "kind": "WORKER_INVOCATION",
        "purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK",
        "benchmark_id": request.benchmark_id,
        "benchmark_revision_id": request.benchmark_revision_id,
        "job_id": job_id,
        "execution_id": uuid4().hex,
        "owner_request_sha256": request.request_sha256,
        "launch_ordinal": ordinal,
        "device": device,
        "local_input": {
            "member_name": "benchmark-inputs.json",
            "sha256": sha256_bytes(raw),
            "byte_count": len(raw),
        },
        "input_set_sha256": request.input_set_sha256,
        "family": request.family.model_dump(mode="json"),
        "runtime": (request.cpu if device == "CPU" else request.cuda).model_dump(mode="json"),
        "recipe": request.recipe.model_dump(mode="json"),
        "execution_policy": request.execution_policy.model_dump(mode="json"),
    }
    return BenchmarkWorkerInvocation.model_validate(
        {**body, "invocation_sha256": content_sha256(body)}
    )


class BenchmarkExecutionOwner:
    """Application ordering only; release composition supplies actual control admission/runtime.

    source_admission must be the reviewed benchmark-purpose/current administrator
    composition, not the source-read-only adapter or a worker-controlled implementation.
    Runtime and result-reader ports are infrastructure boundaries, not activation claims.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        admission: BenchmarkExecutionAdmission,
        execution: BenchmarkLaunchExecution | None,
    ) -> None:
        self.sessions, self.admission, self.execution = sessions, admission, execution
        self.journal = BenchmarkLaunchJournal(admission, admission)

    def _read_validated_series(
        self, request: BenchmarkOwnerRequest
    ) -> BenchmarkLaunchSeries | None:
        # Completed series replay reauthorizes immutable evidence, not today's numerical
        # installation/capacity. It must not load a model or contend with another encode.
        with (
            self.sessions() as session,
            session.begin(),
            self.admission.admit_execution_in_session(session, request),
        ):
            job = session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            if job is None:
                return None
            history = self.journal.read(session, request, job_id=job.job_id)
            if history.job_state == JobState.VALIDATING_RESULT:
                receipts = self.journal.require_completed(session, request, job_id=job.job_id)
                return BenchmarkLaunchSeries(
                    job.job_id, request.request_sha256, receipts, 0, JobState.VALIDATING_RESULT
                )
            if history.launches and history.launches[-1].receipt is None:
                raise BenchmarkOwnerError("BENCHMARK_OWNER_ORIGINAL_EXECUTION_UNRESOLVED")
            if history.job_state not in {JobState.VALIDATED, JobState.RUNNING}:
                raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
            return None

    def run_launches(self, request: BenchmarkOwnerRequest) -> BenchmarkLaunchSeries:
        embedding_device_benchmark_bytes(request)
        replay = self._read_validated_series(request)
        if replay is not None:
            return replay
        if self.execution is None:
            raise BenchmarkOwnerError("BENCHMARK_OWNER_EXECUTION_UNAVAILABLE")
        # No Job/claim is allocated when actual installed/capacity admission is unavailable.
        self.execution.assert_installed(request)
        with native_cpu_capacity():
            require_no_active_native_cpu_execution()
            with (
                self.sessions() as session,
                session.begin(),
                self.admission.admit_execution_in_session(session, request),
            ):
                job, _ = submit_benchmark_job_in_session(
                    session, request, source_admission=self.admission
                )
                job_id = job.job_id
            with (
                self.sessions() as session,
                session.begin(),
                self.admission.admit_execution_in_session(session, request),
            ):
                job = require_benchmark_job_in_session(session, request, job_id=job_id)
                if job.status == JobState.VALIDATED:
                    for state, event in (
                        (JobState.QUEUED, "BENCHMARK_SERIES_QUEUED"),
                        (JobState.CLAIMED, "BENCHMARK_OWNER_CLAIMED"),
                        (JobState.RUNNING, "BENCHMARK_SERIES_RUNNING"),
                    ):
                        transition_job(session, job_id, state, event)
                elif job.status not in {JobState.RUNNING, JobState.VALIDATING_RESULT}:
                    raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
            dispatches = 0
            while True:
                with self.sessions() as session, session.begin():
                    history = self.journal.read(session, request, job_id=job_id)
                if history.launches and history.launches[-1].receipt is None:
                    raise BenchmarkOwnerError("BENCHMARK_OWNER_ORIGINAL_EXECUTION_UNRESOLVED")
                if len(history.launches) == 6:
                    break
                if history.job_state != JobState.RUNNING:
                    raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
                self.execution.assert_installed(request)
                with (
                    self.sessions() as session,
                    session.begin(),
                    self.admission.admit_execution_in_session(session, request) as inputs,
                ):
                    invocation = _invocation(request, inputs, job_id, len(history.launches) + 1)
                    _, created = self.journal.reserve(session, request, invocation)
                    if not created:
                        raise BenchmarkOwnerError("BENCHMARK_OWNER_DISPATCH_NOT_NEW")
                authorization = BenchmarkLaunchAuthorization(
                    self.sessions, request, invocation, self.journal
                )
                authorization.assert_current()
                dispatches += 1
                try:
                    receipt = self.execution.run_and_publish(invocation, inputs, authorization)
                except Exception as error:
                    # A launch/commit might have occurred. Its original durable reservation
                    # remains unresolved; no replacement identity, retry or success rewrite.
                    raise BenchmarkOwnerError("BENCHMARK_OWNER_EXECUTION_UNCERTAIN") from error
                with self.sessions() as session, session.begin():
                    self.journal.record(session, request, receipt)
            with self.sessions() as session, session.begin():
                receipts = self.journal.require_completed(session, request, job_id=job_id)
                job = require_benchmark_job_in_session(session, request, job_id=job_id)
                if job.status == JobState.RUNNING:
                    with self.admission.admit_in_session(session, request):
                        transition_job(
                            session,
                            job_id,
                            JobState.VALIDATING_RESULT,
                            "BENCHMARK_LAUNCHES_COMPLETE",
                        )
                elif job.status != JobState.VALIDATING_RESULT:
                    raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
            return BenchmarkLaunchSeries(
                job_id, request.request_sha256, receipts, dispatches, JobState.VALIDATING_RESULT
            )

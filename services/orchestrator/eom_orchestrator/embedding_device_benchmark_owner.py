"""One manually admitted six-launch series; final device assessment stays a separate stage."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import uuid4

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    BenchmarkCheckpoint,
    BenchmarkLaunchReceipt,
    BenchmarkNearTieReference,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_checkpoint,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkSourceAdmission,
    benchmark_job_key,
    require_benchmark_job_in_session,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import (
    BenchmarkLaunchHistory,
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


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchProgress:
    """A clean recorded prefix, not a complete series or an authentication grant."""

    job_id: str
    request_sha256: str
    receipts: tuple[BenchmarkLaunchReceipt, ...]
    dispatch_count: int
    state: str

    @property
    def next_launch_ordinal(self) -> int | None:
        return len(self.receipts) + 1 if self.state == JobState.RUNNING else None


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
            self._current_history(session)

    def _current_history(self, session: Session) -> BenchmarkLaunchHistory:
        history = self._journal.read(session, self._request, job_id=self._invocation.job_id)
        if (
            history.job_state != JobState.RUNNING
            or len(history.launches) != self._invocation.launch_ordinal
            or history.launches[-1].invocation != self._invocation
            or history.launches[-1].receipt is not None
        ):
            raise BenchmarkOwnerError("BENCHMARK_OWNER_LAUNCH_AUTHORIZATION_INVALID")
        return history

    def require_cpu_reference(self) -> ArtifactMemberPointer:
        """Resolve CPU1's already committed seal before a later launch can stage/start.

        Catalog's reader validates the referenced f64 and complete-span clusters in
        this same current source root. A parsed timestamp or local file is no substitute.
        """
        with self._sessions() as session, session.begin():
            history = self._current_history(session)
            first = history.launches[0]
            receipt = first.receipt
            if (
                self._invocation.launch_ordinal <= 1
                or first.invocation.device != "CPU"
                or first.invocation.launch_ordinal != 1
                or receipt is None
                or receipt.cleanup != "CONFIRMED"
                or receipt.evidence.member_path != "near-tie-reference.json"
                or receipt.evidence.schema_ref
                != "eom://schemas/knowledge/embedding-device-benchmark/1.0#/$defs/nearTieReference"
                or receipt.evidence.media_type != "application/json"
                or (receipt.evidence.artifact_id, receipt.evidence.artifact_revision_id)
                != (receipt.worker_result.artifact_id, receipt.worker_result.artifact_revision_id)
            ):
                raise BenchmarkOwnerError("BENCHMARK_OWNER_CPU_REFERENCE_REQUIRED")
            raw = self._journal.result_reader.read_in_session(
                session, self._request, receipt.evidence
            )
            reference = parse_embedding_device_benchmark_bytes(raw)
            if (
                not isinstance(reference, BenchmarkNearTieReference)
                or embedding_device_benchmark_bytes(reference) != raw
                or sha256_bytes(raw) != receipt.evidence.sha256
                or reference.request_sha256 != self._request.request_sha256
                or reference.input_set_sha256 != self._request.input_set_sha256
                or reference.family_sha256 != self._request.family.family_sha256
                or reference.cpu_document_space_sha256
                != self._request.cpu.spaces.document.space_sha256
                or reference.cpu_query_space_sha256 != self._request.cpu.spaces.query.space_sha256
            ):
                raise BenchmarkOwnerError("BENCHMARK_OWNER_CPU_REFERENCE_INVALID")
            return receipt.evidence

    def authorize_checkpoint(self, checkpoint: BenchmarkCheckpoint) -> None:
        """The fixed channel still owns peer, sequence, deadline and transcript checks."""
        validate_benchmark_checkpoint(self._invocation, checkpoint, checkpoint.sequence)
        self.assert_current()

    def assert_invocation(self, invocation: BenchmarkWorkerInvocation) -> None:
        """A resource/OS adapter cannot reuse another invocation's current authorization."""
        embedding_device_benchmark_bytes(invocation)
        if invocation != self._invocation:
            raise BenchmarkOwnerError("BENCHMARK_OWNER_LAUNCH_AUTHORIZATION_INVALID")
        self.assert_current()


def _invocation(
    request: BenchmarkOwnerRequest, inputs: BenchmarkStagedInputs, job_id: str, ordinal: int
) -> BenchmarkWorkerInvocation:
    device = BENCHMARK_DEVICE_SEQUENCE[ordinal - 1]
    raw = embedding_device_benchmark_bytes(inputs)
    body = {
        "schema_version": {
            "embedding-device-benchmark-request/1.0": "embedding-device-benchmark-invocation/1.0",
            "embedding-device-benchmark-request/1.1": "embedding-device-benchmark-invocation/1.1",
            "embedding-device-benchmark-request/1.2": "embedding-device-benchmark-invocation/1.2",
        }[request.schema_version],
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
            if history.job_state in {
                JobState.VALIDATING_RESULT,
                JobState.COMMITTING,
                JobState.SUCCEEDED,
            }:
                receipts = self.journal.require_completed(session, request, job_id=job.job_id)
                return BenchmarkLaunchSeries(
                    job.job_id, request.request_sha256, receipts, 0, history.job_state
                )
            if history.launches and history.launches[-1].receipt is None:
                raise BenchmarkOwnerError("BENCHMARK_OWNER_ORIGINAL_EXECUTION_UNRESOLVED")
            if history.job_state not in {JobState.VALIDATED, JobState.RUNNING}:
                raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
            return None

    def run_launches(self, request: BenchmarkOwnerRequest) -> BenchmarkLaunchSeries:
        """Complete the original six-launch series without implicit reauthentication."""
        progress = self._run_launches(request, maximum_dispatches=6)
        return BenchmarkLaunchSeries(
            progress.job_id,
            progress.request_sha256,
            progress.receipts,
            progress.dispatch_count,
            progress.state,
        )

    def run_next_launch(self, request: BenchmarkOwnerRequest) -> BenchmarkLaunchProgress:
        """Dispatch at most one new launch and return only its validated clean prefix.

        A trusted operator may obtain fresh actual authentication between calls;
        this method neither authenticates nor extends/caches current authority.
        Unresolved work must be closed through its supported application first.
        """
        return self._run_launches(request, maximum_dispatches=1)

    def _run_launches(
        self, request: BenchmarkOwnerRequest, *, maximum_dispatches: Literal[1, 6]
    ) -> BenchmarkLaunchProgress:
        embedding_device_benchmark_bytes(request)
        replay = self._read_validated_series(request)
        if replay is not None:
            return BenchmarkLaunchProgress(
                replay.job_id,
                replay.request_sha256,
                replay.receipts,
                replay.dispatch_count,
                replay.state,
            )
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
            while dispatches < maximum_dispatches:
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
                history = self.journal.read(session, request, job_id=job_id)
                job = require_benchmark_job_in_session(session, request, job_id=job_id)
                if len(history.launches) < 6:
                    completed = self.journal.require_completed_prefix(
                        session, request, job_id=job_id
                    )
                    if job.status != JobState.RUNNING:
                        raise BenchmarkOwnerError("BENCHMARK_OWNER_TERMINAL_OR_FOREIGN")
                    return BenchmarkLaunchProgress(
                        job_id,
                        request.request_sha256,
                        tuple(launch.receipt for launch in completed),
                        dispatches,
                        JobState.RUNNING,
                    )
                receipts = self.journal.require_completed(session, request, job_id=job_id)
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
            return BenchmarkLaunchProgress(
                job_id, request.request_sha256, receipts, dispatches, JobState.VALIDATING_RESULT
            )

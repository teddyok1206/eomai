"""Six ordered reservations in the original Job; never permission to execute a unit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkLaunchReceipt,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    BenchmarkSourceAdmission,
    require_benchmark_job_in_session,
)
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.state_machine import ALLOWED_TRANSITIONS, JobState

RESERVED_EVENT = "BENCHMARK_LAUNCH_RESERVED"
RECORDED_EVENT = "BENCHMARK_LAUNCH_RECORDED"


class BenchmarkResultReader(Protocol):
    def read_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, pointer: ArtifactMemberPointer
    ) -> bytes:
        """Resolve exact authorized fixed members, never arbitrary worker-chosen paths.

        CPU near-tie reference reads additionally validate their same-Artifact f64
        member, original source/space closure and frozen complete-span clustering.
        """
        ...


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchRecord:
    invocation: BenchmarkWorkerInvocation
    receipt: BenchmarkLaunchReceipt | None


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchHistory:
    job_state: str
    launches: tuple[BenchmarkLaunchRecord, ...]


def _require_receipt(
    invocation: BenchmarkWorkerInvocation, receipt: BenchmarkLaunchReceipt
) -> None:
    if (
        receipt.job_id != invocation.job_id
        or receipt.execution_id != invocation.execution_id
        or receipt.launch_ordinal != invocation.launch_ordinal
        or receipt.device != invocation.device
        or receipt.invocation_sha256 != invocation.invocation_sha256
        or receipt.observed_runtime_sha256 != invocation.runtime.numerical_runtime.runtime_sha256
    ):
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RECEIPT_CONFLICT")


def _history(
    session: Session, job: JobRecord, request: BenchmarkOwnerRequest, inputs: BenchmarkStagedInputs
) -> BenchmarkLaunchHistory:
    rows = tuple(
        session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job.job_id)
            .order_by(JobEventRecord.sequence)
            .limit(33)
        )
    )
    launches: list[BenchmarkLaunchRecord] = []
    execution_ids: set[str] = set()
    if len(rows) > 32 or tuple(row.sequence for row in rows) != tuple(range(1, len(rows) + 1)):
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    state = JobState.VALIDATED
    for row in rows[2:]:
        if row.event not in {RESERVED_EVENT, RECORDED_EVENT}:
            if row.from_state != state or row.to_state not in ALLOWED_TRANSITIONS[state]:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            state = JobState(row.to_state)
            continue
        if state != JobState.RUNNING:
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
        if (row.from_state, row.to_state) != ("RUNNING", "RUNNING"):
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
        value = parse_embedding_device_benchmark(row.data)
        if row.event == RESERVED_EVENT:
            if (
                not isinstance(value, BenchmarkWorkerInvocation)
                or (launches and launches[-1].receipt is None)
                or value.job_id != job.job_id
                or value.launch_ordinal != len(launches) + 1
                or value.execution_id in execution_ids
                or (
                    launches
                    and launches[-1].receipt is not None
                    and launches[-1].receipt.cleanup != "CONFIRMED"
                )
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            validate_benchmark_invocation(request, value, inputs)
            execution_ids.add(value.execution_id)
            launches.append(BenchmarkLaunchRecord(value, None))
        else:
            if (
                not isinstance(value, BenchmarkLaunchReceipt)
                or not launches
                or launches[-1].receipt is not None
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
            _require_receipt(launches[-1].invocation, value)
            launches[-1] = BenchmarkLaunchRecord(launches[-1].invocation, value)
    if state != job.status or len(launches) > 6:
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    return BenchmarkLaunchHistory(job.status, tuple(launches))


def _append(
    session: Session,
    job: JobRecord,
    event: str,
    value: BenchmarkWorkerInvocation | BenchmarkLaunchReceipt,
) -> None:
    # The original Job row is already locked, including exact event replays.
    sequence = session.scalar(
        select(func.coalesce(func.max(JobEventRecord.sequence), 0) + 1).where(
            JobEventRecord.job_id == job.job_id
        )
    )
    if sequence is None:
        raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_HISTORY_INVALID")
    job.updated_at = datetime.now(UTC)
    session.add(
        JobEventRecord(
            job_id=job.job_id,
            sequence=sequence,
            from_state="RUNNING",
            to_state="RUNNING",
            event=event,
            data=value.model_dump(mode="json"),
        )
    )
    session.flush()


class BenchmarkLaunchJournal:
    """Short current-source-fenced roots, not a scheduler, launcher or Artifact publisher."""

    def __init__(
        self, source_admission: BenchmarkSourceAdmission, result_reader: BenchmarkResultReader
    ) -> None:
        self.source_admission, self.result_reader = source_admission, result_reader

    def _result(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        invocation: BenchmarkWorkerInvocation,
        receipt: BenchmarkLaunchReceipt,
    ) -> BenchmarkWorkerResult:
        raw = self.result_reader.read_in_session(session, request, receipt.worker_result)
        result = parse_embedding_device_benchmark_bytes(raw)
        if (
            not isinstance(result, BenchmarkWorkerResult)
            or embedding_device_benchmark_bytes(result) != raw
            or sha256_bytes(raw) != receipt.worker_result.sha256
            or result.execution_id != invocation.execution_id
            or result.invocation_sha256 != invocation.invocation_sha256
            or result.launch_ordinal != invocation.launch_ordinal
            or result.device != invocation.device
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RESULT_CONFLICT")
        return result

    def read(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> BenchmarkLaunchHistory:
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=job_id)
            return _history(session, job, request, inputs)

    def reserve(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        invocation: BenchmarkWorkerInvocation,
    ) -> tuple[BenchmarkLaunchHistory, bool]:
        embedding_device_benchmark_bytes(invocation)
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=invocation.job_id)
            validate_benchmark_invocation(request, invocation, inputs)
            history = _history(session, job, request, inputs)
            if invocation.launch_ordinal <= len(history.launches):
                if history.launches[invocation.launch_ordinal - 1].invocation != invocation:
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RESERVATION_CONFLICT")
                return history, False
            if (
                job.status != JobState.RUNNING
                or invocation.launch_ordinal != len(history.launches) + 1
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RUNNABLE")
            if history.launches:
                previous = history.launches[-1]
                receipt = previous.receipt
                if receipt is None or receipt.cleanup != "CONFIRMED":
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_PREVIOUS_UNRESOLVED")
                if (
                    self._result(session, request, previous.invocation, receipt).status
                    != "COMPLETED"
                ):
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_PREVIOUS_NOT_COMPLETED")
            if invocation.execution_id in {row.invocation.execution_id for row in history.launches}:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_EXECUTION_REUSED")
            _append(session, job, RESERVED_EVENT, invocation)
            return _history(session, job, request, inputs), True

    def record(
        self, session: Session, request: BenchmarkOwnerRequest, receipt: BenchmarkLaunchReceipt
    ) -> tuple[BenchmarkLaunchHistory, bool]:
        embedding_device_benchmark_bytes(receipt)
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=receipt.job_id)
            history = _history(session, job, request, inputs)
            if receipt.launch_ordinal > len(history.launches):
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RESERVED")
            prior = history.launches[receipt.launch_ordinal - 1]
            _require_receipt(prior.invocation, receipt)
            if prior.receipt is not None:
                if prior.receipt != receipt:
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_RECEIPT_CONFLICT")
                return history, False
            if job.status != JobState.RUNNING:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_NOT_RUNNABLE")
            # Retain valid FAILED/UNCERTAIN evidence, but never invent a published result.
            self._result(session, request, prior.invocation, receipt)
            _append(session, job, RECORDED_EVENT, receipt)
            return _history(session, job, request, inputs), True

    def require_completed(
        self, session: Session, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> tuple[BenchmarkLaunchReceipt, ...]:
        """Current exact evidence for all six launches, not parent success or device approval."""
        with self.source_admission.admit_in_session(session, request) as inputs:
            job = require_benchmark_job_in_session(session, request, job_id=job_id)
            history = _history(session, job, request, inputs)
            if len(history.launches) != 6:
                raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
            receipts: list[BenchmarkLaunchReceipt] = []
            for launch in history.launches:
                receipt = launch.receipt
                if (
                    receipt is None
                    or receipt.cleanup != "CONFIRMED"
                    or self._result(session, request, launch.invocation, receipt).status
                    != "COMPLETED"
                ):
                    raise BenchmarkJobAdmissionError("BENCHMARK_LAUNCH_SERIES_INCOMPLETE")
                receipts.append(receipt)
            return tuple(receipts)

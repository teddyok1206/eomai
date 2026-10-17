"""Original bounded benchmark Job registration; no worker claim, launch or success."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
    validate_benchmark_staged_inputs,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from sqlalchemy import Boolean, func, select
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job

BENCHMARK_JOB_PROTOCOL = "embedding-device-benchmark/1.0"
BENCHMARK_JOB_TASK = "native_embedding_device_benchmark"
# One bounded administrative submission namespace; not physical worker capacity.
_SUBMISSION_LOCK = int.from_bytes(b"EOMBENCH", "big", signed=True)


class BenchmarkJobAdmissionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BenchmarkSourceAdmission(Protocol):
    def admit_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> AbstractContextManager[BenchmarkStagedInputs]:
        """Official current Catalog/Identity fences held through this root mutation."""
        ...


def benchmark_job_key(request: BenchmarkOwnerRequest) -> str:
    """Identity key only, never request validation or an authority grant."""
    return "embedding-benchmark:" + request.benchmark_id + ":" + request.benchmark_revision_id


def submit_benchmark_job_in_session(
    session: Session,
    request: BenchmarkOwnerRequest,
    *,
    source_admission: BenchmarkSourceAdmission,
) -> tuple[JobRecord, bool]:
    """Caller promptly commits or rolls back this original root, never a savepoint.

    Registration is not authority for a later launch/read. Trusted application
    composition must supply the actual Catalog adapter; this module never mints identity.
    """
    embedding_device_benchmark_bytes(request)
    if session.in_nested_transaction():
        raise BenchmarkJobAdmissionError("BENCHMARK_JOB_ROOT_TRANSACTION_REQUIRED")
    with source_admission.admit_in_session(session, request) as inputs:
        validate_benchmark_staged_inputs(request, inputs)
        if (
            session.scalar(select(func.pg_try_advisory_xact_lock(_SUBMISSION_LOCK, type_=Boolean)))
            is not True
        ):
            raise BenchmarkJobAdmissionError("BENCHMARK_JOB_SUBMISSION_BUSY")
        schema = CATALOG_SCHEMA_RESOURCES[EMBEDDING_DEVICE_BENCHMARK_SCHEMA]
        try:
            ensure_protocol_version(session, BENCHMARK_JOB_PROTOCOL, schema.sha256)
        except RuntimeError:
            raise BenchmarkJobAdmissionError("BENCHMARK_JOB_PROTOCOL_UNAVAILABLE") from None
        session.flush()
        protocol = session.get(ProtocolVersionRecord, BENCHMARK_JOB_PROTOCOL)
        if protocol is None or protocol.schema_sha256 != schema.sha256:
            raise BenchmarkJobAdmissionError("BENCHMARK_JOB_PROTOCOL_UNAVAILABLE")
        key = benchmark_job_key(request)
        job = session.scalar(
            select(JobRecord)
            .where(JobRecord.idempotency_key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        payload = request.model_dump(mode="json")
        expected_hash = content_sha256(
            {
                "protocol_version": BENCHMARK_JOB_PROTOCOL,
                "task_type": BENCHMARK_JOB_TASK,
                "request": payload,
            }
        )
        if job is not None:
            initial = tuple(
                session.scalars(
                    select(JobEventRecord)
                    .where(JobEventRecord.job_id == job.job_id, JobEventRecord.sequence.in_((1, 2)))
                    .order_by(JobEventRecord.sequence)
                )
            )
            if (
                job.protocol_version != BENCHMARK_JOB_PROTOCOL
                or job.task_type != BENCHMARK_JOB_TASK
                or job.request_hash != expected_hash
                or job.request != payload
                or job.worker_slot_id is not None
                or job.status not in JobState
                or tuple(
                    (event.sequence, event.from_state, event.to_state, event.event, event.data)
                    for event in initial
                )
                != (
                    (1, None, "CREATED", "JOB_CREATED", {}),
                    (2, "CREATED", "VALIDATED", "BENCHMARK_REQUEST_VALIDATED", {}),
                )
            ):
                raise BenchmarkJobAdmissionError("BENCHMARK_JOB_HISTORY_CONFLICT")
            return job, False
        job, created = submit_structured_job(
            session,
            job_id=new_job_id(),
            protocol_version=BENCHMARK_JOB_PROTOCOL,
            idempotency_key=key,
            task_type=BENCHMARK_JOB_TASK,
            request=payload,
            logical_artifact_id=new_logical_artifact_id(),
            revision_id=new_revision_id(),
        )
        if not created:
            raise BenchmarkJobAdmissionError("BENCHMARK_JOB_HISTORY_CONFLICT")
        job = transition_job(session, job.job_id, JobState.VALIDATED, "BENCHMARK_REQUEST_VALIDATED")
        return job, True

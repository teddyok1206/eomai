"""Existing Job/event persistence for the fixed native encoding owner; no admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingAttachedEvent,
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
    LocalEmbeddingOwnedJob,
    parse_embedding_encoding_job_message,
)
from eom_workflow.schemas import LOCAL_EMBEDDING_SCHEMA_RESOURCES
from pydantic import BaseModel
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.state_machine import JobState, require_transition

ENCODING_PROTOCOL_VERSION = "embedding-encoding-job/1.0"
ENCODING_TASK_TYPE = "native_embedding_encoding"
OWNED_EVENT = "EMBEDDING_ENCODING_OWNED"
BORROWED_EVENT = "EMBEDDING_ENCODING_BORROWED"
ASSOCIATION_EVENT = "EMBEDDING_ENCODING_LAUNCH"
COMPLETED_EVENT = "EMBEDDING_ENCODING_COMPLETED"
_RETRY_LIMIT = 3


class EmbeddingEncodingReservationError(RuntimeError):
    """Stable content-free error; no input, SQL, actor or token disclosure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EncodingReservation:
    job: JobRecord
    owned_job: LocalEmbeddingOwnedJob
    owner: EmbeddingEncodingAttachedEvent
    completion: EmbeddingEncodingCompletedEvent | None


def _message[Message: BaseModel](value: object, expected: type[Message]) -> Message:
    try:
        parsed = parse_embedding_encoding_job_message(value)
        if not isinstance(parsed, expected):
            raise ValueError("different native record")
        return parsed
    except ValueError:
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID") from None


def _request_hash(request: EmbeddingEncodingJobRequest) -> str:
    # The existing structured Job wrapper is intentionally not the wire request hash.
    return content_sha256(
        {
            "protocol_version": ENCODING_PROTOCOL_VERSION,
            "task_type": ENCODING_TASK_TYPE,
            "request": request.model_dump(mode="json"),
        }
    )


def owned_job(job: JobRecord) -> LocalEmbeddingOwnedJob:
    request: EmbeddingEncodingJobRequest = _message(job.request, EmbeddingEncodingJobRequest)
    if (
        job.protocol_version != ENCODING_PROTOCOL_VERSION
        or job.task_type != ENCODING_TASK_TYPE
        or job.idempotency_key != request.idempotency_key
        or job.request_hash != _request_hash(request)
        or job.worker_slot_id is not None
    ):
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_REQUEST_CONFLICT")
    try:
        return LocalEmbeddingOwnedJob(
            job_reference=EmbeddingEncodingJobReference(
                job_id=job.job_id,
                request_sha256=request.request_sha256,
                allocated_artifact_id=job.logical_artifact_id,
                allocated_artifact_revision_id=job.revision_id,
            ),
            request=request,
        )
    except ValueError:
        raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID") from None


def _is_key_race(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    return (
        getattr(original, "sqlstate", None) == "23505"
        and getattr(diagnostic, "constraint_name", None) == "jobs_idempotency_key_key"
    )


class EmbeddingEncodingReservationStorage:
    """One coherent storage leaf, not a scheduler, registry or public permission port."""

    @staticmethod
    def require_protocol(session: Session) -> None:
        expected = next(
            row[3] for row in LOCAL_EMBEDDING_SCHEMA_RESOURCES if row[0] == "encoding-job"
        )
        record = session.get(
            ProtocolVersionRecord, ENCODING_PROTOCOL_VERSION, populate_existing=True
        )
        if record is None or record.schema_sha256 != expected:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE")

    @staticmethod
    def lock_launch(session: Session, job_id: str) -> JobRecord:
        job = session.scalar(
            select(JobRecord)
            .where(JobRecord.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or job.task_type == ENCODING_TASK_TYPE or job.worker_slot_id is not None:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_LAUNCH_INVALID")
        if job.status in {JobState.FAILED.value, JobState.CANCELLED.value}:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN")
        return job

    @staticmethod
    def reserve(
        session: Session, requests: tuple[EmbeddingEncodingJobRequest, ...]
    ) -> tuple[tuple[JobRecord, ...], frozenset[str]]:
        keys = tuple(request.idempotency_key for request in requests)
        proposed: dict[str, dict[str, Any]] = {
            request.idempotency_key: {
                "job_id": new_job_id(),
                "protocol_version": ENCODING_PROTOCOL_VERSION,
                "idempotency_key": request.idempotency_key,
                "request_hash": _request_hash(request),
                "task_type": ENCODING_TASK_TYPE,
                "request": request.model_dump(mode="json"),
                "status": JobState.CREATED.value,
                "logical_artifact_id": new_logical_artifact_id(),
                "revision_id": new_revision_id(),
            }
            for request in requests
        }
        created: frozenset[str] = frozenset()
        for attempt in range(_RETRY_LIMIT):
            existing = set(
                session.scalars(
                    select(JobRecord.idempotency_key).where(JobRecord.idempotency_key.in_(keys))
                )
            )
            missing = tuple(key for key in keys if key not in existing)
            try:
                with session.begin_nested():
                    if missing:
                        # Sorted multi-row INSERT precedes all existing reservation locks.
                        session.execute(
                            insert(JobRecord).values([proposed[key] for key in missing])
                        )
                created = frozenset(proposed[key]["job_id"] for key in missing)
                break
            except IntegrityError as error:
                if not _is_key_race(error):
                    raise
                if attempt + 1 == _RETRY_LIMIT:
                    raise EmbeddingEncodingReservationError(
                        "EMBEDDING_ENCODING_RACE_RETRY_EXHAUSTED"
                    ) from None
        jobs = tuple(
            session.scalars(
                select(JobRecord)
                .where(JobRecord.idempotency_key.in_(keys))
                .order_by(JobRecord.idempotency_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(jobs) != len(requests):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_NOT_FOUND")
        for job, requested in zip(jobs, requests, strict=True):
            if owned_job(job).request != requested:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_REQUEST_CONFLICT")
        return jobs, created

    @staticmethod
    def lock_references(
        session: Session, references: tuple[EmbeddingEncodingJobReference, ...], *, lock: bool
    ) -> tuple[JobRecord, ...]:
        statement = (
            select(JobRecord)
            .where(JobRecord.job_id.in_(ref.job_id for ref in references))
            .order_by(JobRecord.idempotency_key)
        )
        # Keep Job state and subsequent immutable event projection one consistent read.
        statement = statement.with_for_update() if lock else statement.with_for_update(read=True)
        jobs = tuple(session.scalars(statement.execution_options(populate_existing=True)))
        by_id = {job.job_id: job for job in jobs}
        if len(by_id) != len(references):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_NOT_FOUND")
        for reference in references:
            if owned_job(by_id[reference.job_id]).job_reference != reference:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_REFERENCE_MISMATCH")
        return jobs

    @staticmethod
    def events(
        session: Session, job_ids: tuple[str, ...], names: tuple[str, ...]
    ) -> tuple[JobEventRecord, ...]:
        return tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id.in_(job_ids), JobEventRecord.event.in_(names))
                .order_by(JobEventRecord.job_id, JobEventRecord.sequence)
                .execution_options(populate_existing=True)
            )
        )

    @classmethod
    def reservations(
        cls, session: Session, jobs: tuple[JobRecord, ...]
    ) -> tuple[EncodingReservation, ...]:
        owners: dict[str, EmbeddingEncodingAttachedEvent] = {}
        completed: dict[str, EmbeddingEncodingCompletedEvent] = {}
        for event in cls.events(
            session, tuple(job.job_id for job in jobs), (OWNED_EVENT, COMPLETED_EVENT)
        ):
            if event.job_id in (owners if event.event == OWNED_EVENT else completed):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID")
            if event.event == OWNED_EVENT:
                owners[event.job_id] = _message(event.data, EmbeddingEncodingAttachedEvent)
            else:
                completed[event.job_id] = _message(event.data, EmbeddingEncodingCompletedEvent)
        records = []
        for job in jobs:
            original = owned_job(job)
            owner, completion = owners.get(job.job_id), completed.get(job.job_id)
            if (
                owner is None
                or owner.owned_job != original
                or (job.status == JobState.SUCCEEDED.value) != (completion is not None)
                or (
                    completion is not None
                    and (completion.owned_job != original or completion.intent != owner.intent)
                )
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID")
            records.append(EncodingReservation(job, original, owner, completion))
        return tuple(records)

    @classmethod
    def association(
        cls, session: Session, launch_id: str
    ) -> LocalEmbeddingLaunchAssociation | None:
        events = cls.events(session, (launch_id,), (ASSOCIATION_EVENT,))
        if len(events) > 1:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID")
        if not events:
            return None
        return _message(events[0].data, LocalEmbeddingLaunchAssociation)

    @classmethod
    def owned_launch_references(
        cls,
        session: Session,
        launch_id: str,
        plan_keys: tuple[str, ...],
    ) -> tuple[EmbeddingEncodingJobReference, ...]:
        if not 1 <= len(plan_keys) <= 1024:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        job_ids = tuple(
            session.scalars(
                select(JobRecord.job_id).where(JobRecord.idempotency_key.in_(plan_keys))
            )
        )
        owners = []
        for event in cls.events(session, job_ids, (OWNED_EVENT,)):
            attached = _message(event.data, EmbeddingEncodingAttachedEvent)
            if attached.intent.native_launch_job_id == launch_id:
                owners.append(attached.owned_job.job_reference)
        return tuple(owners)

    @staticmethod
    def sequences(session: Session, jobs: tuple[JobRecord, ...]) -> dict[str, int]:
        rows = session.execute(
            select(JobEventRecord.job_id, func.max(JobEventRecord.sequence))
            .where(JobEventRecord.job_id.in_(job.job_id for job in jobs))
            .group_by(JobEventRecord.job_id)
        )
        return {str(job_id): int(sequence) for job_id, sequence in rows}

    @staticmethod
    def append(
        session: Session,
        job: JobRecord,
        sequences: dict[str, int],
        event: str,
        data: dict[str, Any],
        *,
        target: JobState | None = None,
    ) -> None:
        current = JobState(job.status)
        if target is not None:
            require_transition(current, target)
            job.status = target.value
            job.updated_at = datetime.now(UTC)
            if target in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
                job.completed_at = datetime.now(UTC)
        sequence = sequences.get(job.job_id, 0) + 1
        sequences[job.job_id] = sequence
        session.add(
            JobEventRecord(
                job_id=job.job_id,
                sequence=sequence,
                from_state=None if sequence == 1 else current.value,
                to_state=job.status,
                event=event,
                data=data,
            )
        )

    @classmethod
    def attach(
        cls,
        session: Session,
        jobs: tuple[JobRecord, ...],
        created: frozenset[str],
        intent: LocalEmbeddingLaunchIntent,
    ) -> None:
        sequences = cls.sequences(session, jobs)
        attachments = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(
                    JobEventRecord.job_id.in_(job.job_id for job in jobs),
                    JobEventRecord.event.in_((OWNED_EVENT, BORROWED_EVENT)),
                    JobEventRecord.data["intent"]["native_launch_job_id"].astext
                    == intent.native_launch_job_id,
                )
                .order_by(JobEventRecord.job_id, JobEventRecord.sequence)
            )
        )
        attached = {}
        by_id = {job.job_id: job for job in jobs}
        for event in attachments:
            value: EmbeddingEncodingAttachedEvent = _message(
                event.data, EmbeddingEncodingAttachedEvent
            )
            if (
                event.job_id in attached
                or value.intent != intent
                or value.owned_job != owned_job(by_id[event.job_id])
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_INTENT_CONFLICT")
            attached[event.job_id] = value
        for job in jobs:
            if job.job_id in attached:
                continue
            body = {
                "schema_version": ENCODING_PROTOCOL_VERSION,
                "record_type": "ATTACHED",
                "owned_job": owned_job(job).model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
            }
            document = body | {"event_sha256": content_sha256(body)}
            _message(document, EmbeddingEncodingAttachedEvent)
            if job.job_id in created:
                cls.append(session, job, sequences, "JOB_CREATED", {})
                cls.append(
                    session,
                    job,
                    sequences,
                    "EMBEDDING_ENCODING_VALIDATED",
                    {},
                    target=JobState.VALIDATED,
                )
                cls.append(
                    session, job, sequences, "EMBEDDING_ENCODING_READY", {}, target=JobState.QUEUED
                )
                cls.append(session, job, sequences, OWNED_EVENT, document, target=JobState.CLAIMED)
            else:
                cls.append(session, job, sequences, BORROWED_EVENT, document)
        session.flush()

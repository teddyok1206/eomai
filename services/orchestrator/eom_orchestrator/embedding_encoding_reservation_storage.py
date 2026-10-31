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
from eom_workflow.embedding_cpu_failure_recovery import (
    CPU_FAILURE_RECOVERY_PROTOCOL,
    CPU_FAILURE_RECOVERY_SCHEMA_SHA256,
    KnownFailedCpuEmbeddingEncoding,
)
from eom_workflow.embedding_cpu_preparation_failure import (
    CPU_PREPARATION_FAILURE_PROTOCOL,
    CPU_PREPARATION_FAILURE_SCHEMA_SHA256,
    KnownFailedCpuPreparationEncoding,
)
from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_PROTOCOL,
    ENCODING_RECOVERY_SCHEMA_SHA256,
    ENCODING_RETRY_PRODUCER_EVENT,
    ENCODING_RETRY_SUCCESSOR_EVENT,
    MAX_ENCODING_RETRIES,
    RECOVERABLE_ENCODING_FAILURE_CODES,
    RECOVERABLE_ENCODING_FAILURE_EVENTS,
    EmbeddingEncodingRetryDeclaration,
    SupportedEncodingFailure,
    encoding_failure_disposition,
    parse_supported_encoding_failure,
)
from eom_workflow.embedding_unpublished_recovery import (
    UNPUBLISHED_RECOVERY_PROTOCOL,
    UNPUBLISHED_RECOVERY_SCHEMA_SHA256,
    UnpublishedEmbeddingEncodingFailure,
)
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    SupportedEmbeddingAttachedEvent,
    SupportedEmbeddingCompletedEvent,
    SupportedEmbeddingIntent,
    embedding_ownership_version,
    parse_supported_embedding_association,
    parse_supported_embedding_attached,
    parse_supported_embedding_completed,
    parse_supported_embedding_message,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_SHA256,
)
from eom_workflow.local_embedding_encoding_ownership_v3 import (
    EMBEDDING_ENCODING_OWNERSHIP_V3_SCHEMA_SHA256,
)
from eom_workflow.local_embedding_encoding_ownership_v4 import (
    EMBEDDING_ENCODING_OWNERSHIP_V4_SCHEMA_SHA256,
)
from eom_workflow.schemas import LOCAL_EMBEDDING_SCHEMA_RESOURCES
from pydantic import BaseModel
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
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
    owner: SupportedEmbeddingAttachedEvent
    completion: SupportedEmbeddingCompletedEvent | None


def _message[Message: BaseModel](
    value: object, expected: type[Message] | tuple[type[Message], ...]
) -> Message:
    try:
        parsed = parse_supported_embedding_message(value)
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


def owned_job(
    job: JobRecord, retry: EmbeddingEncodingRetryDeclaration | None = None
) -> LocalEmbeddingOwnedJob:
    request: EmbeddingEncodingJobRequest = _message(job.request, EmbeddingEncodingJobRequest)
    key = request.idempotency_key
    if retry is not None:
        retry = EmbeddingEncodingRetryDeclaration.model_validate(retry)
        key = retry.storage_idempotency_key
        if (
            retry.encoding_sha256 != request.encoding.encoding_sha256
            or retry.successor.job_id != job.job_id
            or retry.successor.request_sha256 != request.request_sha256
            or retry.successor.allocated_artifact_id != job.logical_artifact_id
            or retry.successor.allocated_artifact_revision_id != job.revision_id
        ):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_REFERENCE_INVALID")
    if (
        job.protocol_version != ENCODING_PROTOCOL_VERSION
        or job.task_type != ENCODING_TASK_TYPE
        or job.idempotency_key != key
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
    def prepare_protocol(session: Session) -> None:
        expected = next(
            row[3] for row in LOCAL_EMBEDDING_SCHEMA_RESOURCES if row[0] == "encoding-job"
        )
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session, ENCODING_PROTOCOL_VERSION, expected
        )

    @staticmethod
    def prepare_mixed_ownership_protocol(session: Session) -> None:
        """Explicit deployment preparation; never called by runtime read or claim."""
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session,
            "embedding-encoding-ownership/2.0",
            EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_SHA256,
        )

    @staticmethod
    def prepare_public_ownership_protocol(session: Session) -> None:
        """Explicit owner-only deployment preparation; never a claim-time self-grant."""
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session,
            "embedding-encoding-ownership/3.0",
            EMBEDDING_ENCODING_OWNERSHIP_V3_SCHEMA_SHA256,
        )

    @staticmethod
    def prepare_registered_public_ownership_protocol(session: Session) -> None:
        """Schema-owner release preparation, never runtime self-registration."""
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session,
            "embedding-encoding-ownership/4.0",
            EMBEDDING_ENCODING_OWNERSHIP_V4_SCHEMA_SHA256,
        )

    @staticmethod
    def prepare_recovery_protocol(session: Session) -> None:
        """Explicit schema-owner deployment preparation, not runtime bootstrap."""
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session, ENCODING_RECOVERY_PROTOCOL, ENCODING_RECOVERY_SCHEMA_SHA256
        )
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session, UNPUBLISHED_RECOVERY_PROTOCOL, UNPUBLISHED_RECOVERY_SCHEMA_SHA256
        )
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session, CPU_FAILURE_RECOVERY_PROTOCOL, CPU_FAILURE_RECOVERY_SCHEMA_SHA256
        )
        EmbeddingEncodingReservationStorage._prepare_protocol(
            session, CPU_PREPARATION_FAILURE_PROTOCOL, CPU_PREPARATION_FAILURE_SCHEMA_SHA256
        )

    @staticmethod
    def require_recovery_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, ENCODING_RECOVERY_PROTOCOL, populate_existing=True
        )
        if record is None or record.schema_sha256 != ENCODING_RECOVERY_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RECOVERY_UNAVAILABLE")

    @staticmethod
    def require_unpublished_recovery_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, UNPUBLISHED_RECOVERY_PROTOCOL, populate_existing=True
        )
        if record is None or record.schema_sha256 != UNPUBLISHED_RECOVERY_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RECOVERY_UNAVAILABLE")

    @staticmethod
    def require_cpu_failure_recovery_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, CPU_FAILURE_RECOVERY_PROTOCOL, populate_existing=True
        )
        if record is None or record.schema_sha256 != CPU_FAILURE_RECOVERY_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RECOVERY_UNAVAILABLE")

    @staticmethod
    def require_cpu_preparation_failure_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, CPU_PREPARATION_FAILURE_PROTOCOL, populate_existing=True
        )
        if record is None or record.schema_sha256 != CPU_PREPARATION_FAILURE_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RECOVERY_UNAVAILABLE")

    @staticmethod
    def _prepare_protocol(session: Session, version: str, expected: str) -> None:
        """Explicit deployment-owner initialization, NEVER called by runtime reads.

        Only the actual table-owner login may prepare the released hash. An
        existing different hash is an error, not an upsert or migration.
        """
        root = session.get_transaction()
        if (
            root is None
            or not root.is_active
            or session.in_nested_transaction()
            or session.get_bind().dialect.name != "postgresql"
        ):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_OWNER_REQUIRED")
        owner = session.scalar(
            text(
                "SELECT SESSION_USER = CURRENT_USER AND SESSION_USER = "
                "pg_catalog.pg_get_userbyid(relation.relowner) "
                "FROM pg_catalog.pg_class relation "
                "WHERE relation.oid = 'app.protocol_versions'::regclass"
            )
        )
        if owner is not True:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_OWNER_REQUIRED")
        session.execute(
            postgres_insert(ProtocolVersionRecord)
            .values(version=version, schema_sha256=expected)
            .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
        )
        record = session.get(ProtocolVersionRecord, version, populate_existing=True)
        if record is None or record.schema_sha256 != expected:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE")

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
    def require_mixed_ownership_protocol(session: Session) -> None:
        """Read-only prerequisite, separate from the unchanged numerical protocol1."""
        record = session.get(
            ProtocolVersionRecord, "embedding-encoding-ownership/2.0", populate_existing=True
        )
        if record is None or record.schema_sha256 != EMBEDDING_ENCODING_OWNERSHIP_V2_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE")

    @staticmethod
    def require_public_ownership_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, "embedding-encoding-ownership/3.0", populate_existing=True
        )
        if record is None or record.schema_sha256 != EMBEDDING_ENCODING_OWNERSHIP_V3_SCHEMA_SHA256:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE")

    @staticmethod
    def require_registered_public_ownership_protocol(session: Session) -> None:
        record = session.get(
            ProtocolVersionRecord, "embedding-encoding-ownership/4.0", populate_existing=True
        )
        if record is None or record.schema_sha256 != EMBEDDING_ENCODING_OWNERSHIP_V4_SCHEMA_SHA256:
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
        return EmbeddingEncodingReservationStorage.current_producers(
            session, jobs, lock=True
        ), created

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
        origins = EmbeddingEncodingReservationStorage.retry_origins(session, jobs)
        for reference in references:
            if (
                owned_job(by_id[reference.job_id], origins.get(reference.job_id)).job_reference
                != reference
            ):
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
        owners: dict[str, SupportedEmbeddingAttachedEvent] = {}
        completed: dict[str, SupportedEmbeddingCompletedEvent] = {}
        for event in cls.events(
            session, tuple(job.job_id for job in jobs), (OWNED_EVENT, COMPLETED_EVENT)
        ):
            if event.job_id in (owners if event.event == OWNED_EVENT else completed):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID")
            if event.event == OWNED_EVENT:
                owners[event.job_id] = parse_supported_embedding_attached(event.data)
            else:
                completed[event.job_id] = parse_supported_embedding_completed(event.data)
        origins = cls.retry_origins(session, jobs)
        records = []
        for job in jobs:
            original = owned_job(job, origins.get(job.job_id))
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
    def association(cls, session: Session, launch_id: str) -> SupportedEmbeddingAssociation | None:
        events = cls.events(session, (launch_id,), (ASSOCIATION_EVENT,))
        if len(events) > 1:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_HISTORY_INVALID")
        if not events:
            return None
        return parse_supported_embedding_association(events[0].data)

    @classmethod
    def owned_launch_references(
        cls,
        session: Session,
        launch_id: str,
        plan_keys: tuple[str, ...],
    ) -> tuple[EmbeddingEncodingJobReference, ...]:
        if not 1 <= len(plan_keys) <= 1024:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        roots = tuple(
            session.scalars(
                select(JobRecord)
                .where(JobRecord.idempotency_key.in_(plan_keys))
                .order_by(JobRecord.idempotency_key)
            )
        )
        job_ids = tuple(job.job_id for job in cls.current_producers(session, roots, lock=False))
        owners = []
        for event in cls.events(session, job_ids, (OWNED_EVENT,)):
            attached = parse_supported_embedding_attached(event.data)
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
        intent: SupportedEmbeddingIntent,
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
        origins = cls.retry_origins(session, jobs)
        attached = {}
        by_id = {job.job_id: job for job in jobs}
        for event in attachments:
            value: SupportedEmbeddingAttachedEvent = parse_supported_embedding_attached(event.data)
            if (
                event.job_id in attached
                or value.intent != intent
                or value.owned_job != owned_job(by_id[event.job_id], origins.get(event.job_id))
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_INTENT_CONFLICT")
            attached[event.job_id] = value
        for job in jobs:
            if job.job_id in attached:
                continue
            body = {
                "schema_version": embedding_ownership_version(intent),
                "record_type": "ATTACHED",
                "owned_job": owned_job(job, origins.get(job.job_id)).model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
            }
            document = body | {"event_sha256": content_sha256(body)}
            parse_supported_embedding_attached(document)
            if job.job_id in created:
                if job.job_id not in origins:
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

    @classmethod
    def retry_origins(
        cls, session: Session, jobs: tuple[JobRecord, ...]
    ) -> dict[str, EmbeddingEncodingRetryDeclaration]:
        ids = tuple(
            j.job_id for j in jobs if j.idempotency_key.startswith("embedding-encode-retry:")
        )
        if not ids:
            return {}
        cls.require_recovery_protocol(session)
        values = {}
        for event in cls.events(session, ids, (ENCODING_RETRY_PRODUCER_EVENT,)):
            record = EmbeddingEncodingRetryDeclaration.model_validate(event.data)
            if (
                event.job_id in values
                or record.successor.job_id != event.job_id
                or (event.from_state != "CREATED" or event.to_state != "CREATED")
            ):
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_HISTORY_INVALID")
            values[event.job_id] = record
        if set(values) != set(ids):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_HISTORY_INVALID")
        return values

    @classmethod
    def known_failures(
        cls, session: Session, jobs: tuple[JobRecord, ...]
    ) -> dict[str, SupportedEncodingFailure]:
        failed = {
            j.job_id: j
            for j in jobs
            if j.status == "FAILED" and j.error_code in RECOVERABLE_ENCODING_FAILURE_CODES
        }
        if not failed:
            return {}
        cls.require_recovery_protocol(session)
        origins = cls.retry_origins(session, tuple(failed.values()))
        reservations = {r.job.job_id: r for r in cls.reservations(session, tuple(failed.values()))}
        values = {}
        for event in cls.events(session, tuple(failed), RECOVERABLE_ENCODING_FAILURE_EVENTS):
            record = parse_supported_encoding_failure(event.data)
            kind = encoding_failure_disposition(record)
            if isinstance(record, UnpublishedEmbeddingEncodingFailure):
                cls.require_unpublished_recovery_protocol(session)
            if isinstance(record, KnownFailedCpuEmbeddingEncoding):
                cls.require_cpu_failure_recovery_protocol(session)
            if isinstance(record, KnownFailedCpuPreparationEncoding):
                cls.require_cpu_preparation_failure_protocol(session)
            prior = reservations[event.job_id]
            if (
                event.job_id in values
                or event.event != kind.encoding_event
                or failed[event.job_id].error_code != kind.code
                or record.owned_job != owned_job(failed[event.job_id], origins.get(event.job_id))
                or (
                    record.native_launch_job_id != prior.owner.intent.native_launch_job_id
                    or event.from_state != "RUNNING"
                    or event.to_state != "FAILED"
                )
            ):
                raise EmbeddingEncodingReservationError(
                    "EMBEDDING_ENCODING_FAILURE_HISTORY_INVALID"
                )
            values[event.job_id] = record
        if set(values) != set(failed):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_FAILURE_HISTORY_INVALID")
        return values

    @classmethod
    def record_known_failures(
        cls, session: Session, values: tuple[SupportedEncodingFailure, ...]
    ) -> None:
        """Storage leaf only: caller must prove exact original root retirement/current owner.

        No public runtime endpoint accepts these values as authority. The fixed
        maintenance application owns OS/schema-owner admission and Workflow/native
        transitions around this one caller transaction. Partial records roll back.
        """
        cls.require_protocol(session)
        cls.require_recovery_protocol(session)
        records = tuple(parse_supported_encoding_failure(v) for v in values)
        ids = tuple(v.owned_job.job_reference.job_id for v in records)
        if not 1 <= len(ids) <= 1024 or ids != tuple(sorted(set(ids))):
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_BATCH_INVALID")
        for launch_id in sorted({v.native_launch_job_id for v in records}):
            cls.lock_launch(session, launch_id)
        jobs = cls.lock_references(
            session, tuple(v.owned_job.job_reference for v in records), lock=True
        )
        by_id = {j.job_id: j for j in jobs}
        observed = {r.job.job_id: r for r in cls.reservations(session, jobs)}
        previous = cls.known_failures(session, jobs)
        sequences = cls.sequences(session, jobs)
        for value in records:
            kind = encoding_failure_disposition(value)
            if isinstance(value, UnpublishedEmbeddingEncodingFailure):
                cls.require_unpublished_recovery_protocol(session)
            if isinstance(value, KnownFailedCpuEmbeddingEncoding):
                cls.require_cpu_failure_recovery_protocol(session)
            if isinstance(value, KnownFailedCpuPreparationEncoding):
                cls.require_cpu_preparation_failure_protocol(session)
            job = by_id[value.owned_job.job_reference.job_id]
            owner = observed[job.job_id]
            if (
                owner.owned_job != value.owned_job
                or owner.owner.intent.native_launch_job_id != value.native_launch_job_id
            ):
                raise EmbeddingEncodingReservationError(
                    "EMBEDDING_ENCODING_FAILURE_HISTORY_INVALID"
                )
            if job.status == "FAILED" and previous.get(job.job_id) == value:
                continue
            if job.status != "RUNNING" or owner.completion is not None:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_TERMINAL_OR_FOREIGN")
            cls.append(
                session,
                job,
                sequences,
                kind.encoding_event,
                value.model_dump(mode="json"),
                target=JobState.FAILED,
            )
            job.error_code = kind.code
            job.error_message = kind.message
        session.flush()

    @classmethod
    def current_producers(
        cls, session: Session, roots: tuple[JobRecord, ...], *, lock: bool
    ) -> tuple[JobRecord, ...]:
        """At most three append-only edges, bulk indexed reads; explicit Job reads never follow."""
        if not any(
            j.status == "FAILED" and j.error_code in RECOVERABLE_ENCODING_FAILURE_CODES
            for j in roots
        ):
            return roots
        current = {j.job_id: j for j in roots}
        root_values = {j.job_id: owned_job(j).job_reference for j in roots}
        for _ in range(MAX_ENCODING_RETRIES + 1):
            candidates = tuple(
                j
                for j in current.values()
                if j.status == "FAILED" and j.error_code in RECOVERABLE_ENCODING_FAILURE_CODES
            )
            if not candidates:
                break
            edges = cls.events(
                session, tuple(j.job_id for j in candidates), (ENCODING_RETRY_SUCCESSOR_EVENT,)
            )
            if not edges:
                break
            origins = cls.retry_origins(session, candidates)
            failures = cls.known_failures(session, candidates)
            edge_map = {}
            for event in edges:
                record = EmbeddingEncodingRetryDeclaration.model_validate(event.data)
                if (
                    event.job_id in edge_map
                    or record.predecessor.job_id != event.job_id
                    or (event.from_state != "FAILED" or event.to_state != "FAILED")
                ):
                    raise EmbeddingEncodingReservationError(
                        "EMBEDDING_ENCODING_RETRY_HISTORY_INVALID"
                    )
                edge_map[event.job_id] = record
            statement = (
                select(JobRecord)
                .where(JobRecord.job_id.in_(r.successor.job_id for r in edge_map.values()))
                .order_by(JobRecord.idempotency_key)
            )
            if lock:
                statement = statement.with_for_update()
            next_jobs = {
                j.job_id: j
                for j in session.scalars(statement.execution_options(populate_existing=True))
            }
            next_origins = cls.retry_origins(session, tuple(next_jobs.values()))
            for root_id, previous in tuple(current.items()):
                edge = edge_map.get(previous.job_id)
                if edge is None:
                    continue
                origin, failure = origins.get(previous.job_id), failures.get(previous.job_id)
                successor = next_jobs.get(edge.successor.job_id)
                if (
                    failure is None
                    or successor is None
                    or (
                        edge.logical_job != root_values[root_id]
                        or edge.predecessor != owned_job(previous, origin).job_reference
                        or edge.attempt != (1 if origin is None else origin.attempt + 1)
                        or edge.predecessor_failure_sha256 != failure.event_sha256
                        or next_origins.get(successor.job_id) != edge
                        or owned_job(successor, edge).request != failure.owned_job.request
                    )
                ):
                    raise EmbeddingEncodingReservationError(
                        "EMBEDDING_ENCODING_RETRY_HISTORY_INVALID"
                    )
                current[root_id] = successor
        else:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_LIMIT_EXCEEDED")
        return tuple(current[j.job_id] for j in roots)

    @classmethod
    def retry_known_failed(
        cls, session: Session, requests: tuple[EmbeddingEncodingJobRequest, ...]
    ) -> tuple[tuple[JobRecord, ...], frozenset[str]]:
        """Caller retains fresh current-source/launch fences; no resurrection or numerical work."""
        jobs, unprepared = cls.reserve(session, requests)
        if unprepared:
            raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_NOT_PREPARED")
        failures = cls.known_failures(session, jobs)
        origins = cls.retry_origins(session, jobs)
        keys = tuple(r.idempotency_key for r in requests)
        roots = {
            j.idempotency_key: j
            for j in session.scalars(select(JobRecord).where(JobRecord.idempotency_key.in_(keys)))
        }
        created, selected = set(), []
        proposals = []
        sequences = cls.sequences(session, jobs)
        for request, previous in zip(requests, jobs, strict=True):
            failure = failures.get(previous.job_id)
            if failure is None:
                selected.append(previous)
                continue
            origin = origins.get(previous.job_id)
            attempt = 1 if origin is None else origin.attempt + 1
            if attempt > MAX_ENCODING_RETRIES:
                raise EmbeddingEncodingReservationError("EMBEDDING_ENCODING_RETRY_LIMIT_EXCEEDED")
            successor = JobRecord(
                job_id=new_job_id(),
                protocol_version=ENCODING_PROTOCOL_VERSION,
                idempotency_key="pending-retry-declaration",
                request_hash=_request_hash(request),
                task_type=ENCODING_TASK_TYPE,
                request=request.model_dump(mode="json"),
                status="CREATED",
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )
            reference = EmbeddingEncodingJobReference(
                job_id=successor.job_id,
                request_sha256=request.request_sha256,
                allocated_artifact_id=successor.logical_artifact_id,
                allocated_artifact_revision_id=successor.revision_id,
            )
            body = dict(
                schema_version=ENCODING_RECOVERY_PROTOCOL,
                record_type="RETRY",
                logical_job=owned_job(roots[request.idempotency_key]).job_reference.model_dump(
                    mode="json"
                ),
                predecessor=failure.owned_job.job_reference.model_dump(mode="json"),
                successor=reference.model_dump(mode="json"),
                encoding_sha256=request.encoding.encoding_sha256,
                attempt=attempt,
                predecessor_failure_sha256=failure.event_sha256,
            )
            declaration = EmbeddingEncodingRetryDeclaration.model_validate(
                body | {"event_sha256": content_sha256(body)}
            )
            successor.idempotency_key = declaration.storage_idempotency_key
            proposals.append((previous, successor, declaration))
            created.add(successor.job_id)
            selected.append(successor)
        # Insert all producer rows before dependent events; no per-target flush
        # or assumed ORM relationship ordering, including autoflush=False owners.
        session.add_all(successor for _previous, successor, _declaration in proposals)
        session.flush()
        for previous, successor, declaration in proposals:
            cls.append(
                session,
                previous,
                sequences,
                ENCODING_RETRY_SUCCESSOR_EVENT,
                declaration.model_dump(mode="json"),
            )
            cls.append(session, successor, sequences, "JOB_CREATED", {})
            cls.append(
                session,
                successor,
                sequences,
                ENCODING_RETRY_PRODUCER_EVENT,
                declaration.model_dump(mode="json"),
            )
        session.flush()
        return tuple(selected), frozenset(created)

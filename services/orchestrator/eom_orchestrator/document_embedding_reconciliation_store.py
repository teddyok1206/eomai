"""Indexed append-only catch-up intent in existing Jobs; never a queue, claim or GPU grant."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_workflow.document_embedding_reconciliation import (
    DOCUMENT_RECONCILIATION_PROTOCOL,
    DOCUMENT_RECONCILIATION_SCHEMA_SHA256,
    DocumentEmbeddingReconciliationAttempt,
    DocumentEmbeddingReconciliationCompleted,
    DocumentEmbeddingReconciliationRequest,
)
from eom_workflow.embedding_batch_plan import EmbeddingBatchRoute
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    embedding_batch_plan_schema_identity,
    parse_embedding_batch_plan_request,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.state_machine import JobState, record_initial_event, transition_job

_TASK = "document_embedding_reconciliation"
_SELECTED = "DOCUMENT_RECONCILIATION_SELECTED"
_START = (
    ("JOB_CREATED", None, "CREATED"),
    ("DOCUMENT_RECONCILIATION_VALIDATED", "CREATED", "VALIDATED"),
    ("DOCUMENT_RECONCILIATION_QUEUED", "VALIDATED", "QUEUED"),
    ("DOCUMENT_RECONCILIATION_CLAIMED", "QUEUED", "CLAIMED"),
    ("DOCUMENT_RECONCILIATION_OPENED", "CLAIMED", "RUNNING"),
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_RECONCILIATION_HISTORY_INVALID")


def _root(session: Session) -> None:
    current = session.get_transaction()
    _require(
        current is not None
        and current.is_active
        and not session.in_nested_transaction()
        and session.get_bind().dialect.name == "postgresql"
    )


@dataclass(frozen=True, slots=True)
class DocumentReconciliationHistory:
    job_id: str
    intent: DocumentEmbeddingReconciliationAttempt
    completion: DocumentEmbeddingReconciliationCompleted | None


class DocumentEmbeddingReconciliationStore:
    """Actual source/CPU/GPU-outcome authority belongs to the caller's mandatory callback.

    A selected future batch ID is a value, not a dangling Job pointer or dispatch
    permission. Original Plan allocation and the existing Workflow queue remain
    their owners. No transaction survives into physical allocation or inference.
    """

    def __init__(self, request: DocumentEmbeddingReconciliationRequest) -> None:
        self.request = DocumentEmbeddingReconciliationRequest.model_validate(request)
        self.key = "document-embedding-reconciliation:" + self.request.request_sha256.removeprefix(
            "sha256:"
        )

    def _job(self, session: Session, *, update: bool = False) -> JobRecord | None:
        _root(session)
        query = select(JobRecord).where(JobRecord.idempotency_key == self.key)
        if update:
            query = query.with_for_update()
        job = session.scalar(query.execution_options(populate_existing=True))
        if job is None:
            return None
        protocol = session.get(
            ProtocolVersionRecord, DOCUMENT_RECONCILIATION_PROTOCOL, populate_existing=True
        )
        payload = self.request.model_dump(mode="json")
        _require(
            job.protocol_version == DOCUMENT_RECONCILIATION_PROTOCOL
            and job.task_type == _TASK
            and job.request == payload
            and job.request_hash
            == content_sha256(
                dict(protocol_version=job.protocol_version, task_type=_TASK, request=payload)
            )
            and job.worker_slot_id is None
            and protocol is not None
            and protocol.schema_sha256 == DOCUMENT_RECONCILIATION_SCHEMA_SHA256
            and job.status in {"RUNNING", "SUCCEEDED"}
        )
        return job

    def origin_parent(self, session: Session) -> SupportedEmbeddingBatchRequest:
        _root(session)
        return self._previous(
            session,
            self.request.origin_parent_job_id,
            self.request.origin_parent_request_sha256,
        )

    def _previous(
        self, session: Session, job_id: str, request_sha256: str
    ) -> SupportedEmbeddingBatchRequest:
        original = session.get(JobRecord, job_id, populate_existing=True)
        _require(original is not None and original.task_type == "embedding_batch_plan")
        assert original is not None
        parent = parse_embedding_batch_plan_request(original.request)
        protocol, schema_sha256 = embedding_batch_plan_schema_identity(parent)
        schema = session.get(ProtocolVersionRecord, protocol, populate_existing=True)
        _require(
            parent.request_sha256 == request_sha256
            and parent.parent_request_sha256 == self.request.source_request_sha256
            and parent.scope == self.request.scope
            and parent.purpose == "INDEX"
            and original.protocol_version == protocol
            and original.worker_slot_id is None
            and schema is not None
            and schema.schema_sha256 == schema_sha256
            and original.status in {"RUNNING", "SUCCEEDED"}
            and original.request_hash
            == content_sha256(
                dict(
                    protocol_version=protocol,
                    task_type=original.task_type,
                    request=original.request,
                )
            )
        )
        row = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == job_id, JobEventRecord.sequence == 5
            )
        )
        _require(row is not None and row.event == "EMBEDDING_PLAN_ROUTED")
        assert row is not None
        route = EmbeddingBatchRoute.model_validate(row.data)
        _require(
            route.request_sha256 == request_sha256
            and route.decision.selected.backend.device == "CPU"
            and route.observation.status == "BUSY"
            and route.observation.phase == "PRE_EXECUTION"
            and route.observation.cuda_launch_state == "NOT_STARTED"
            and route.decision.reason == "GPU_BUSY_CPU_FALLBACK"
        )
        return parent

    def read(self, session: Session) -> DocumentReconciliationHistory | None:
        job = self._job(session)
        if job is None:
            return None
        self.origin_parent(session)
        initial = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id, JobEventRecord.sequence <= 5)
                .order_by(JobEventRecord.sequence)
            )
        )
        _require(len(initial) == 5)
        for number, (row, expected) in enumerate(zip(initial, _START, strict=True), 1):
            _require(
                row.sequence == number
                and (row.event, row.from_state, row.to_state) == expected
                and row.data == {}
            )
        # Unique(job_id, sequence) supports this reverse range without a history
        # scan. At most three terminal events follow the last selected intent.
        tail = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id, JobEventRecord.sequence > 5)
                .order_by(JobEventRecord.sequence.desc())
                .limit(5)
            )
        )
        selected = tail[3:] if job.status == "SUCCEEDED" else tail
        _require(bool(selected))
        row = selected[0]
        _require(row.event == _SELECTED and row.from_state == row.to_state == "RUNNING")
        head = DocumentEmbeddingReconciliationAttempt.model_validate(row.data)
        _require(
            head.reconciliation_request_sha256 == self.request.request_sha256
            and row.sequence == 5 + head.ordinal
        )
        if head.ordinal == 1:
            _require(
                head.previous_parent_job_id == self.request.origin_parent_job_id
                and head.previous_parent_request_sha256 == self.request.origin_parent_request_sha256
            )
        else:
            self._previous(
                session, head.previous_parent_job_id, head.previous_parent_request_sha256
            )
            _require(len(selected) >= 2)
            prior_row = selected[1]
            prior = DocumentEmbeddingReconciliationAttempt.model_validate(prior_row.data)
            _require(
                prior_row.event == _SELECTED
                and prior_row.sequence == row.sequence - 1
                and prior.ordinal == head.ordinal - 1
                and prior.reconciliation_request_sha256 == self.request.request_sha256
                and prior.parent_request_sha256 == head.previous_parent_request_sha256
            )
        completion = None
        if job.status == "SUCCEEDED":
            footer = tuple(reversed(tail[:3]))
            footer_transitions = (
                ("DOCUMENT_RECONCILIATION_VERIFIED", "RUNNING", "VALIDATING_RESULT"),
                ("DOCUMENT_RECONCILIATION_COMMITTING", "VALIDATING_RESULT", "COMMITTING"),
                ("DOCUMENT_RECONCILIATION_COMPLETED", "COMMITTING", "SUCCEEDED"),
            )
            for offset, (entry, transition) in enumerate(
                zip(footer, footer_transitions, strict=True), 1
            ):
                _require(
                    (entry.event, entry.from_state, entry.to_state) == transition
                    and entry.sequence == row.sequence + offset
                )
            completion = DocumentEmbeddingReconciliationCompleted.model_validate(footer[0].data)
            _require(
                completion.reconciliation_request_sha256 == self.request.request_sha256
                and completion.intent_sha256 == head.intent_sha256
                and all(
                    entry.data == {"completion_sha256": completion.completion_sha256}
                    for entry in footer[1:]
                )
            )
        return DocumentReconciliationHistory(job.job_id, head, completion)

    def ensure(
        self,
        session: Session,
        first: DocumentEmbeddingReconciliationAttempt,
        *,
        authorize: Callable[[], object],
    ) -> DocumentReconciliationHistory:
        _root(session)
        first = DocumentEmbeddingReconciliationAttempt.model_validate(first)
        _require(
            first.ordinal == 1
            and first.reconciliation_request_sha256 == self.request.request_sha256
            and first.previous_parent_job_id == self.request.origin_parent_job_id
            and first.previous_parent_request_sha256 == self.request.origin_parent_request_sha256
        )
        _require(authorize() is None)
        self.origin_parent(session)
        session.execute(
            insert(ProtocolVersionRecord)
            .values(
                version=DOCUMENT_RECONCILIATION_PROTOCOL,
                schema_sha256=DOCUMENT_RECONCILIATION_SCHEMA_SHA256,
            )
            .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
        )
        ensure_protocol_version(
            session, DOCUMENT_RECONCILIATION_PROTOCOL, DOCUMENT_RECONCILIATION_SCHEMA_SHA256
        )
        payload, job_id = self.request.model_dump(mode="json"), new_job_id()
        created = session.scalar(
            insert(JobRecord)
            .values(
                job_id=job_id,
                protocol_version=DOCUMENT_RECONCILIATION_PROTOCOL,
                idempotency_key=self.key,
                request_hash=content_sha256(
                    dict(
                        protocol_version=DOCUMENT_RECONCILIATION_PROTOCOL,
                        task_type=_TASK,
                        request=payload,
                    )
                ),
                task_type=_TASK,
                request=payload,
                status="CREATED",
                logical_artifact_id=new_logical_artifact_id(),
                revision_id=new_revision_id(),
            )
            .on_conflict_do_nothing(index_elements=[JobRecord.idempotency_key])
            .returning(JobRecord.job_id)
        )
        if created is not None:
            job = session.get(JobRecord, job_id)
            assert job is not None
            record_initial_event(session, job)
            session.flush()
            for event, _before, after in _START[1:]:
                transition_job(session, job_id, JobState(after), event)
                session.flush()
            self._append(session, job_id, first)
        _require(authorize() is None)
        result = self.read(session)
        _require(result is not None)
        assert result is not None
        return result

    def advance(
        self,
        session: Session,
        expected: DocumentEmbeddingReconciliationAttempt,
        successor: DocumentEmbeddingReconciliationAttempt,
        *,
        authorize: Callable[[], object],
    ) -> DocumentReconciliationHistory:
        job = self._job(session, update=True)
        _require(job is not None)
        expected = DocumentEmbeddingReconciliationAttempt.model_validate(expected)
        successor = DocumentEmbeddingReconciliationAttempt.model_validate(successor)
        current = self.read(session)
        assert current is not None
        _require(
            successor.reconciliation_request_sha256 == self.request.request_sha256
            and successor.ordinal == expected.ordinal + 1
            and successor.previous_parent_request_sha256 == expected.parent_request_sha256
            and current.completion is None
        )
        _require(authorize() is None)
        self._previous(
            session, successor.previous_parent_job_id, successor.previous_parent_request_sha256
        )
        if current.intent != successor:
            _require(current.intent == expected)
            self._append(session, current.job_id, successor)
        _require(authorize() is None)
        result = self.read(session)
        assert result is not None
        return result

    @staticmethod
    def _append(
        session: Session, job_id: str, intent: DocumentEmbeddingReconciliationAttempt
    ) -> None:
        session.add(
            JobEventRecord(
                job_id=job_id,
                sequence=5 + intent.ordinal,
                from_state="RUNNING",
                to_state="RUNNING",
                event=_SELECTED,
                data=intent.model_dump(mode="json"),
            )
        )
        session.flush()

    def complete(
        self,
        session: Session,
        completion: DocumentEmbeddingReconciliationCompleted,
        *,
        authorize: Callable[[], object],
    ) -> DocumentReconciliationHistory:
        _require(self._job(session, update=True) is not None)
        completion = DocumentEmbeddingReconciliationCompleted.model_validate(completion)
        current = self.read(session)
        assert current is not None
        _require(
            completion.reconciliation_request_sha256 == self.request.request_sha256
            and completion.intent_sha256 == current.intent.intent_sha256
        )
        _require(authorize() is None)
        if current.completion is None:
            for state, event, data in (
                (
                    JobState.VALIDATING_RESULT,
                    "DOCUMENT_RECONCILIATION_VERIFIED",
                    completion.model_dump(mode="json"),
                ),
                (
                    JobState.COMMITTING,
                    "DOCUMENT_RECONCILIATION_COMMITTING",
                    {"completion_sha256": completion.completion_sha256},
                ),
                (
                    JobState.SUCCEEDED,
                    "DOCUMENT_RECONCILIATION_COMPLETED",
                    {"completion_sha256": completion.completion_sha256},
                ),
            ):
                transition_job(session, current.job_id, state, event, data=data)
                session.flush()
        else:
            _require(current.completion == completion)
        _require(authorize() is None)
        result = self.read(session)
        assert result is not None
        return result

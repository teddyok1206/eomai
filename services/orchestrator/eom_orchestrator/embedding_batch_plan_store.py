"""Atomic finite planning in existing Job history; no queue, compute, source or retry grant."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_PROTOCOL,
    BATCH_PLAN_SCHEMA_SHA256,
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchChildBinding,
    EmbeddingBatchFailure,
    EmbeddingBatchPlanRequest,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
    validate_embedding_batch_allocation,
    validate_embedding_batch_binding,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_route_record,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    validate_embedding_device_batch_profile,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.state_machine import JobState, record_initial_event, transition_job

_TASK = "embedding_batch_plan"
_PREFIX = "embedding-batch-plan:"
_EVENTS = (
    ("JOB_CREATED", None, "CREATED"),
    ("EMBEDDING_PLAN_VALIDATED", "CREATED", "VALIDATED"),
    ("EMBEDDING_PLAN_QUEUED", "VALIDATED", "QUEUED"),
    ("EMBEDDING_PLAN_ALLOCATION", "QUEUED", "CLAIMED"),
    ("EMBEDDING_PLAN_ROUTED", "CLAIMED", "RUNNING"),
    ("EMBEDDING_PLAN_BOUND", "RUNNING", "VALIDATING_RESULT"),
    ("EMBEDDING_PLAN_CONFIRMED", "VALIDATING_RESULT", "COMMITTING"),
    ("EMBEDDING_PLAN_COMPLETED", "COMMITTING", "SUCCEEDED"),
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_PLAN_HISTORY_INVALID")


def _root(session: Session) -> None:
    root = session.get_transaction()
    _require(
        root is not None
        and root.is_active
        and not session.in_nested_transaction()
        and session.get_bind().dialect.name == "postgresql"
    )


def embedding_batch_plan_key(request: EmbeddingBatchPlanRequest) -> str:
    request = EmbeddingBatchPlanRequest.model_validate(request)
    return _PREFIX + content_sha256(
        {
            "batch_id": request.batch_id,
            "actor_kind": request.scope.actor_kind,
            "actor_id": request.scope.actor_id,
        }
    ).removeprefix("sha256:")


@dataclass(frozen=True, slots=True)
class EmbeddingBatchPlanHistory:
    job_id: str
    state: str
    allocation: EmbeddingBatchAllocation
    route: EmbeddingBatchRoute | None
    bound: EmbeddingBatchBound | None
    failure: EmbeddingBatchFailure | None


class EmbeddingBatchPlanStore:
    """Caller owns fresh actual-actor/source/physical fences in each root transaction.

    A successful planning Job means immutable device/child binding, NOT numerical
    success. This store cannot launch/relaunch, authenticate, reserve encodings or
    publish outputs. Existing unique Job keys and row locks own concurrent history.
    """

    def __init__(
        self,
        request: EmbeddingBatchPlanRequest,
        selection: EmbeddingBatchSelection,
        policy: EmbeddingDeviceRoutingPolicy,
    ) -> None:
        validate_embedding_batch_plan_controls(request, selection, policy)
        self.request = EmbeddingBatchPlanRequest.model_validate(request)
        self.policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
        self.key = embedding_batch_plan_key(self.request)

    def _job(self, session: Session, *, update: bool = False) -> JobRecord | None:
        _root(session)
        job = session.scalar(
            select(JobRecord)
            .where(JobRecord.idempotency_key == self.key)
            .with_for_update(read=not update)
            .execution_options(populate_existing=True)
        )
        if job is None:
            return None
        payload = self.request.model_dump(mode="json")
        _require(
            job.protocol_version == BATCH_PLAN_PROTOCOL
            and job.task_type == _TASK
            and job.worker_slot_id is None
            and job.request == payload
            and job.request_hash
            == content_sha256(
                {"protocol_version": BATCH_PLAN_PROTOCOL, "task_type": _TASK, "request": payload}
            )
        )
        protocol = session.get(ProtocolVersionRecord, BATCH_PLAN_PROTOCOL, populate_existing=True)
        _require(protocol is not None and protocol.schema_sha256 == BATCH_PLAN_SCHEMA_SHA256)
        return job

    def read(self, session: Session) -> EmbeddingBatchPlanHistory | None:
        job = self._job(session)
        if job is None:
            return None
        rows = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id)
                .order_by(JobEventRecord.sequence)
                .limit(10)
            )
        )
        _require(4 <= len(rows) <= 9)
        failure = None
        normal = rows
        if rows[-1].event == "EMBEDDING_PLAN_FAILED":
            last = rows[-1]
            failure = EmbeddingBatchFailure.model_validate(last.data)
            _require(
                failure.request_sha256 == self.request.request_sha256
                and last.from_state == rows[-2].to_state
                and last.to_state == "FAILED"
                and last.from_state in {"CLAIMED", "RUNNING"}
            )
            normal = rows[:-1]
        _require(len(normal) in {4, 5, 8})
        for ordinal, (row, expected) in enumerate(zip(normal, _EVENTS, strict=False), 1):
            _require(
                row.sequence == ordinal and (row.event, row.from_state, row.to_state) == expected
            )
            if ordinal <= 3:
                _require(row.data == {})
        _require(rows[-1].sequence == len(rows) and job.status == rows[-1].to_state)
        allocation = EmbeddingBatchAllocation.model_validate(normal[3].data)
        validate_embedding_batch_allocation(self.request, self.policy, allocation)
        route = None if len(normal) < 5 else EmbeddingBatchRoute.model_validate(normal[4].data)
        if route is not None:
            validate_embedding_batch_route_record(self.request, self.policy, allocation, route)
        bound = None if len(normal) < 8 else EmbeddingBatchBound.model_validate(normal[5].data)
        if bound is not None:
            assert route is not None
            validate_embedding_batch_binding(self.request, route, bound)
            _require(
                all(row.data == {"bound_record_sha256": bound.record_sha256} for row in normal[6:])
            )
        return EmbeddingBatchPlanHistory(job.job_id, job.status, allocation, route, bound, failure)

    def allocate(
        self, session: Session, allocation: EmbeddingBatchAllocation
    ) -> tuple[EmbeddingBatchPlanHistory, bool]:
        """Only a newly created allocation can own its original dispatch; replay never does."""
        _root(session)
        allocation = EmbeddingBatchAllocation.model_validate(allocation)
        validate_embedding_batch_allocation(self.request, self.policy, allocation)
        session.execute(
            insert(ProtocolVersionRecord)
            .values(version=BATCH_PLAN_PROTOCOL, schema_sha256=BATCH_PLAN_SCHEMA_SHA256)
            .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
        )
        ensure_protocol_version(session, BATCH_PLAN_PROTOCOL, BATCH_PLAN_SCHEMA_SHA256)
        payload = self.request.model_dump(mode="json")
        job_id = new_job_id()
        inserted = session.scalar(
            insert(JobRecord)
            .values(
                job_id=job_id,
                protocol_version=BATCH_PLAN_PROTOCOL,
                idempotency_key=self.key,
                request_hash=content_sha256(
                    {
                        "protocol_version": BATCH_PLAN_PROTOCOL,
                        "task_type": _TASK,
                        "request": payload,
                    }
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
        if inserted is None:
            original = self.read(session)
            _require(original is not None)
            assert original is not None
            return original, False
        job = session.get(JobRecord, job_id)
        assert job is not None
        record_initial_event(session, job)
        session.flush()
        for state, event in (
            (JobState.VALIDATED, _EVENTS[1][0]),
            (JobState.QUEUED, _EVENTS[2][0]),
            (JobState.CLAIMED, _EVENTS[3][0]),
        ):
            transition_job(
                session,
                job_id,
                state,
                event,
                data=allocation.model_dump(mode="json") if state is JobState.CLAIMED else {},
            )
            session.flush()
        session.flush()
        result = self.read(session)
        assert result is not None
        return result, True

    def route(self, session: Session, record: EmbeddingBatchRoute) -> EmbeddingBatchPlanHistory:
        _require(self._job(session, update=True) is not None)
        history = self.read(session)
        assert history is not None
        record = EmbeddingBatchRoute.model_validate(record)
        validate_embedding_batch_route_record(self.request, self.policy, history.allocation, record)
        if history.route is not None:
            _require(history.route == record)
            return history
        _require(history.state == "CLAIMED" and history.failure is None)
        transition_job(
            session,
            history.job_id,
            JobState.RUNNING,
            _EVENTS[4][0],
            data=record.model_dump(mode="json"),
        )
        session.flush()
        result = self.read(session)
        assert result is not None
        return result

    def bind(
        self,
        session: Session,
        record: EmbeddingBatchBound,
        batch: EmbeddingWorkBatchInput,
        *,
        authorize_child: Callable[[EmbeddingBatchChildBinding], None],
    ) -> EmbeddingBatchPlanHistory:
        record = EmbeddingBatchBound.model_validate(record)
        _require(callable(authorize_child))

        def sources() -> None:
            check: Callable[[EmbeddingBatchChildBinding], object] = authorize_child
            for child in record.children:
                _require(check(child) is None)

        sources()
        _require(self._job(session, update=True) is not None)
        history = self.read(session)
        assert history is not None
        _require(history.route is not None)
        assert history.route is not None
        record = EmbeddingBatchBound.model_validate(record)
        batch = validate_embedding_device_batch_profile(self.policy, history.route.decision, batch)
        validate_embedding_batch_binding(self.request, history.route, record, batch)
        sources()
        if history.bound is not None:
            _require(history.bound == record)
            return history
        _require(history.state == "RUNNING" and history.failure is None)
        for state, event in (
            (JobState.VALIDATING_RESULT, _EVENTS[5][0]),
            (JobState.COMMITTING, _EVENTS[6][0]),
            (JobState.SUCCEEDED, _EVENTS[7][0]),
        ):
            transition_job(
                session,
                history.job_id,
                state,
                event,
                data=record.model_dump(mode="json")
                if state is JobState.VALIDATING_RESULT
                else {"bound_record_sha256": record.record_sha256},
            )
            session.flush()
        session.flush()
        result = self.read(session)
        assert result is not None
        return result

    def record_failure(
        self, session: Session, record: EmbeddingBatchFailure
    ) -> EmbeddingBatchPlanHistory:
        """Caller must have proven original planning failure; never reclassify numerical history."""
        _require(self._job(session, update=True) is not None)
        history = self.read(session)
        assert history is not None
        record = EmbeddingBatchFailure.model_validate(record)
        _require(record.request_sha256 == self.request.request_sha256)
        if history.failure is not None:
            _require(history.failure == record)
            return history
        _require(history.state in {"CLAIMED", "RUNNING"} and history.bound is None)
        transition_job(
            session,
            history.job_id,
            JobState.FAILED,
            "EMBEDDING_PLAN_FAILED",
            data=record.model_dump(mode="json"),
        )
        session.flush()
        result = self.read(session)
        assert result is not None
        return result

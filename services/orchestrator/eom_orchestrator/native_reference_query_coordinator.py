"""Original QUERY Job and append-only checkpoints; current authority is upstream."""

from __future__ import annotations

from dataclasses import dataclass

from eom_identifiers import content_sha256, new_logical_artifact_id, new_revision_id
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryPhase,
    NativeReferenceQueryCheckpoint,
    parse_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow.reference_query_workflow import REFERENCE_QUERY_EXECUTION_PROTOCOL
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job

NATIVE_QUERY_TASK = "native_reference_query_launch"
NATIVE_QUERY_LAUNCH_EVENT = "REFERENCE_QUERY_NATIVE_LAUNCH"
_STAGES: dict[NativeQueryPhase, tuple[JobState, JobState]] = {
    "ALLOCATION": (JobState.CLAIMED, JobState.RUNNING),
    "EXECUTED": (JobState.RUNNING, JobState.VALIDATING_RESULT),
    "PUBLISHED": (JobState.VALIDATING_RESULT, JobState.COMMITTING),
    "COMPLETED": (JobState.COMMITTING, JobState.SUCCEEDED),
}
_EVENTS = {"REFERENCE_QUERY_NATIVE_" + phase: phase for phase in _STAGES}
# Registry keys and JSON schema versions are distinct identities. The former has
# an existing VARCHAR(32) bound; the released checkpoint bytes/hash stay unchanged.
NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL = "native-query-coordinator/1.0"


class NativeReferenceQueryHistoryError(ValueError):
    pass


def _root(session: Session) -> None:
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_OWNER_ROOT_REQUIRED")


def _protocol(session: Session, version: str, digest: str, *, create: bool = False) -> None:
    if create:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                insert(ProtocolVersionRecord)
                .values(version=version, schema_sha256=digest)
                .on_conflict_do_nothing(index_elements=[ProtocolVersionRecord.version])
            )
        ensure_protocol_version(session, version, digest)
        session.flush()
    protocol = session.get(ProtocolVersionRecord, version, populate_existing=True)
    if protocol is None or protocol.schema_sha256 != digest:
        raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_HISTORY_PROTOCOL_INVALID")


def native_reference_query_launch_key(
    workflow_id: str, step_run_id: str, request_sha256: str
) -> str:
    return "native-reference-query:" + content_sha256(
        {
            "workflow_id": workflow_id,
            "step_run_id": step_run_id,
            "attempt": 1,
            "request_sha256": request_sha256,
        }
    ).removeprefix("sha256:")


@dataclass(frozen=True, slots=True)
class NativeReferenceQueryHistory:
    state: str
    launch: ReferenceQueryLaunchAssociation
    records: tuple[NativeReferenceQueryCheckpoint, ...]


def read_native_reference_query_launch(
    session: Session,
    *,
    request: SupportedReferenceQueryWorkflowRequest,
    workflow_id: str,
    step_run_id: str,
) -> ReferenceQueryLaunchAssociation | None:
    """Caller fences the actual Workflow and current execution/read authority first."""
    _root(session)
    request = parse_supported_reference_query_workflow_request(request)
    job = session.scalar(
        select(JobRecord)
        .where(
            JobRecord.idempotency_key
            == native_reference_query_launch_key(workflow_id, step_run_id, request.request_sha256)
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        return None
    _protocol(
        session, REFERENCE_QUERY_EXECUTION_PROTOCOL, REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[2]
    )
    events = tuple(
        session.scalars(
            select(JobEventRecord).where(
                JobEventRecord.job_id == job.job_id,
                JobEventRecord.event == NATIVE_QUERY_LAUNCH_EVENT,
            )
        )
    )
    try:
        if len(events) != 1:
            raise ValueError("QUERY original launch count differs")
        launch = parse_reference_query_launch_association(events[0].data)
        payload = request.model_dump(mode="json")
        if (
            job.job_id != launch.native_launch_job_id
            or job.worker_slot_id is not None
            or job.task_type != NATIVE_QUERY_TASK
            or job.protocol_version != REFERENCE_QUERY_EXECUTION_PROTOCOL
            or job.request != payload
            or job.request_hash
            != content_sha256(
                {
                    "protocol_version": REFERENCE_QUERY_EXECUTION_PROTOCOL,
                    "task_type": NATIVE_QUERY_TASK,
                    "request": payload,
                }
            )
            or (events[0].from_state, events[0].to_state) != ("QUEUED", "CLAIMED")
            or launch.workflow_id != workflow_id
            or launch.step_run_id != step_run_id
            or launch.workflow_request_sha256 != request.request_sha256
            or launch.context_request_sha256 != request.context_request.request_sha256
            or launch.runtime_bundle != request.runtime_bundle
            or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
        ):
            raise ValueError("QUERY original Job closure differs")
        return launch
    except (ValueError, TypeError, KeyError):
        raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_LAUNCH_HISTORY_INVALID") from None


def create_native_reference_query_launch(
    session: Session,
    *,
    request: SupportedReferenceQueryWorkflowRequest,
    launch: ReferenceQueryLaunchAssociation,
) -> ReferenceQueryLaunchAssociation:
    """Within held Workflow→command locks, create or return ONLY the original launch.

    This does not verify native text, current authority, installed units or admission.
    The owner must validate the complete prepared handoff before physical launch.
    """
    _root(session)
    request = parse_supported_reference_query_workflow_request(request)
    launch = parse_reference_query_launch_association(launch)
    existing = read_native_reference_query_launch(
        session, request=request, workflow_id=launch.workflow_id, step_run_id=launch.step_run_id
    )
    if existing is not None:
        return existing
    if (
        launch.workflow_request_sha256 != request.request_sha256
        or launch.context_request_sha256 != request.context_request.request_sha256
        or launch.runtime_bundle != request.runtime_bundle
        or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
    ):
        raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_LAUNCH_REQUEST_INVALID")
    _protocol(
        session,
        REFERENCE_QUERY_EXECUTION_PROTOCOL,
        REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[2],
        create=True,
    )
    job, created = submit_structured_job(
        session,
        job_id=launch.native_launch_job_id,
        protocol_version=REFERENCE_QUERY_EXECUTION_PROTOCOL,
        idempotency_key=native_reference_query_launch_key(
            launch.workflow_id, launch.step_run_id, request.request_sha256
        ),
        task_type=NATIVE_QUERY_TASK,
        request=request.model_dump(mode="json"),
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    if not created:
        raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_LAUNCH_RACE_UNRECONCILED")
    for state, event in (
        (JobState.VALIDATED, "REFERENCE_QUERY_REQUEST_VALIDATED"),
        (JobState.QUEUED, "REFERENCE_QUERY_COORDINATOR_QUEUED"),
        (JobState.CLAIMED, NATIVE_QUERY_LAUNCH_EVENT),
    ):
        transition_job(
            session,
            job.job_id,
            state,
            event,
            data=launch.model_dump(mode="json") if state is JobState.CLAIMED else {},
        )
    return launch


class NativeReferenceQueryCoordinator:
    """No current-auth defaults: caller retains fresh actual owner fences per root."""

    def __init__(
        self,
        request: SupportedReferenceQueryWorkflowRequest,
        launch: ReferenceQueryLaunchAssociation,
    ) -> None:
        self.request = parse_supported_reference_query_workflow_request(request)
        self.launch = parse_reference_query_launch_association(launch)

    def read(self, session: Session) -> NativeReferenceQueryHistory:
        original = read_native_reference_query_launch(
            session,
            request=self.request,
            workflow_id=self.launch.workflow_id,
            step_run_id=self.launch.step_run_id,
        )
        if original != self.launch:
            raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_ORIGINAL_LAUNCH_CHANGED")
        job = session.get(JobRecord, original.native_launch_job_id, populate_existing=True)
        assert job is not None
        rows = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(
                    JobEventRecord.job_id == job.job_id, JobEventRecord.event.in_(tuple(_EVENTS))
                )
                .order_by(JobEventRecord.sequence)
            )
        )
        try:
            records = tuple(parse_native_reference_query_checkpoint(row.data) for row in rows)
            if records:
                _protocol(
                    session,
                    NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL,
                    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[2],
                )
            validate_native_reference_query_history(records, original, self.request)
            for row, record in zip(rows, records, strict=True):
                start, end = _STAGES[record.record_type]
                if _EVENTS[row.event] != record.record_type or (row.from_state, row.to_state) != (
                    start.value,
                    end.value,
                ):
                    raise ValueError("QUERY checkpoint event transition differs")
            expected = JobState.CLAIMED if not records else _STAGES[records[-1].record_type][1]
            if job.status not in {expected.value, JobState.FAILED.value, JobState.CANCELLED.value}:
                raise ValueError("QUERY state differs from checkpoint history")
            return NativeReferenceQueryHistory(job.status, original, records)
        except (ValueError, TypeError, KeyError):
            raise NativeReferenceQueryHistoryError(
                "REFERENCE_QUERY_CHECKPOINT_HISTORY_INVALID"
            ) from None

    def append(
        self, session: Session, record: NativeReferenceQueryCheckpoint
    ) -> NativeReferenceQueryHistory:
        _root(session)
        # Same Workflow→command→Job lock order as the original INDEX owner.
        session.scalar(
            select(JobRecord)
            .where(JobRecord.job_id == self.launch.native_launch_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        history = self.read(session)
        record = parse_native_reference_query_checkpoint(record)
        previous = {value.record_type: value for value in history.records}
        if record.record_type in previous:
            if previous[record.record_type] != record:
                raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_CHECKPOINT_CONFLICT")
            return history
        try:
            validate_native_reference_query_history(
                (*history.records, record), self.launch, self.request
            )
        except (ValueError, TypeError):
            raise NativeReferenceQueryHistoryError(
                "REFERENCE_QUERY_CHECKPOINT_ORDER_INVALID"
            ) from None
        if history.state != _STAGES[record.record_type][0].value:
            raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_CHECKPOINT_TERMINAL_OR_FOREIGN")
        _protocol(
            session,
            NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL,
            NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[2],
            create=True,
        )
        transition_job(
            session,
            self.launch.native_launch_job_id,
            _STAGES[record.record_type][1],
            "REFERENCE_QUERY_NATIVE_" + record.record_type,
            data=record.model_dump(mode="json"),
        )
        session.flush()
        return self.read(session)

    def record_known_failure(self, session: Session) -> NativeReferenceQueryHistory:
        """Only the observed fixed-unit failure; never timeout, repair or retry authority."""
        _root(session)
        job = session.scalar(
            select(JobRecord)
            .where(JobRecord.job_id == self.launch.native_launch_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        history = self.read(session)
        code = "NATIVE_QUERY_KNOWN_FAILED"
        if job is not None and history.state == JobState.FAILED.value and job.error_code == code:
            return history
        if job is None or history.state != JobState.RUNNING.value or len(history.records) != 1:
            raise NativeReferenceQueryHistoryError("REFERENCE_QUERY_FAILURE_TERMINAL_OR_FOREIGN")
        job = transition_job(
            session,
            job.job_id,
            JobState.FAILED,
            "REFERENCE_QUERY_NATIVE_EXECUTION_FAILED",
            data={"code": code},
        )
        job.error_code, job.error_message = code, "fixed CPU QUERY unit failed"
        session.flush()
        return self.read(session)

"""Original QUERY Job and append-only checkpoints; current authority is upstream."""

from __future__ import annotations

from dataclasses import dataclass

from eom_workflow.native_reference_query_coordinator import (
    NativeQueryPhase,
    SupportedNativeReferenceQueryCheckpoint,
    parse_supported_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_query_job_allocation import (
    NativeQueryLaunchError,
    create_native_query_launch,
    native_reference_query_key,
    read_native_query_launch,
    require_native_query_protocol,
    require_native_query_root,
)
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


def _checkpoint_protocol(record: SupportedNativeReferenceQueryCheckpoint) -> tuple[str, str]:
    if record.schema_version == "native-reference-query-coordinator/1.1":
        from eom_workflow.schemas import NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE

        return (
            "native-query-coordinator/1.1",
            NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE[2],
        )
    return (
        NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL,
        NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[2],
    )


class NativeReferenceQueryHistoryError(ValueError):
    pass


def _root(session: Session) -> None:
    try:
        require_native_query_root(session)
    except NativeQueryLaunchError as error:
        raise NativeReferenceQueryHistoryError(str(error)) from None


def _protocol(session: Session, version: str, digest: str, *, create: bool = False) -> None:
    try:
        require_native_query_protocol(session, version, digest, create=create)
    except NativeQueryLaunchError as error:
        raise NativeReferenceQueryHistoryError(str(error)) from None


def native_reference_query_launch_key(
    workflow_id: str, step_run_id: str, request_sha256: str
) -> str:
    return native_reference_query_key(workflow_id, step_run_id, request_sha256)


@dataclass(frozen=True, slots=True)
class NativeReferenceQueryHistory:
    state: str
    launch: ReferenceQueryLaunchAssociation
    records: tuple[SupportedNativeReferenceQueryCheckpoint, ...]


def read_native_reference_query_launch(
    session: Session,
    *,
    request: SupportedReferenceQueryWorkflowRequest,
    workflow_id: str,
    step_run_id: str,
) -> ReferenceQueryLaunchAssociation | None:
    """Caller holds actual Workflow/command/source fences; not execution authority."""
    request = parse_supported_reference_query_workflow_request(request)
    try:
        result = read_native_query_launch(
            session, request=request, workflow_id=workflow_id, step_run_id=step_run_id
        )
    except NativeQueryLaunchError as error:
        raise NativeReferenceQueryHistoryError(str(error)) from None
    assert result is None or isinstance(result, ReferenceQueryLaunchAssociation)
    return result


def create_native_reference_query_launch(
    session: Session,
    *,
    request: SupportedReferenceQueryWorkflowRequest,
    launch: ReferenceQueryLaunchAssociation,
) -> ReferenceQueryLaunchAssociation:
    """Allocate or replay the original reference Job under existing owner fences."""
    request = parse_supported_reference_query_workflow_request(request)
    launch = parse_reference_query_launch_association(launch)
    try:
        result = create_native_query_launch(session, request=request, launch=launch)
    except NativeQueryLaunchError as error:
        raise NativeReferenceQueryHistoryError(str(error)) from None
    assert isinstance(result, ReferenceQueryLaunchAssociation)
    return result


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
            records = tuple(
                parse_supported_native_reference_query_checkpoint(row.data) for row in rows
            )
            if records:
                _protocol(
                    session,
                    *_checkpoint_protocol(records[0]),
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
        self, session: Session, record: SupportedNativeReferenceQueryCheckpoint
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
        record = parse_supported_native_reference_query_checkpoint(record)
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
            *_checkpoint_protocol(record),
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

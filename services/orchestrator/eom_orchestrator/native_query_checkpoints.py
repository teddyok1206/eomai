"""Shared original QUERY Job/event persistence; typed purpose validation stays distinct."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCheckpoint,
    parse_native_private_chat_query_checkpoint,
    validate_native_private_chat_query_history,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryPhase,
    SupportedNativeReferenceQueryCheckpoint,
    parse_supported_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.schemas import (
    NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE,
    NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_query_job_allocation import (
    NativeQueryLaunchError,
    QueryIntent,
    QueryLaunch,
    read_native_query_launch,
    require_native_query_protocol,
    require_native_query_root,
)
from eom_orchestrator.state_machine import JobState, transition_job

type NativeQueryCheckpoint = (
    SupportedNativeReferenceQueryCheckpoint | NativePrivateChatQueryCheckpoint
)
NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL = "native-query-coordinator/1.0"
NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL = "native-private-query/1.0"
_STAGES: MappingProxyType[NativeQueryPhase, tuple[JobState, JobState]] = MappingProxyType(
    {
        "ALLOCATION": (JobState.CLAIMED, JobState.RUNNING),
        "EXECUTED": (JobState.RUNNING, JobState.VALIDATING_RESULT),
        "PUBLISHED": (JobState.VALIDATING_RESULT, JobState.COMMITTING),
        "COMPLETED": (JobState.COMMITTING, JobState.SUCCEEDED),
    }
)
_EVENTS = tuple(
    prefix + "_NATIVE_" + phase
    for prefix in ("REFERENCE_QUERY", "PRIVATE_CHAT_QUERY")
    for phase in _STAGES
)
_FAILURE_MESSAGES = MappingProxyType(
    {
        "native-reference-query-coordinator/1.0": "fixed CPU QUERY unit failed",
        "native-reference-query-coordinator/1.1": "fixed CPU QUERY unit failed",
        "native-reference-query-coordinator/1.2": "original finite CUDA QUERY batch failed",
        "native-private-chat-query-coordinator/1.0": "fixed CPU private QUERY unit failed",
    }
)


class NativeQueryHistoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NativeQueryHistory:
    state: str
    launch: QueryLaunch
    records: tuple[NativeQueryCheckpoint, ...]


def _checkpoint_protocol(record: NativeQueryCheckpoint) -> tuple[str, str]:
    if isinstance(record, NativePrivateChatQueryCheckpoint):
        return (
            NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL,
            NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE[2],
        )
    if record.schema_version == "native-reference-query-coordinator/1.1":
        return (
            "native-query-coordinator/1.1",
            NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE[2],
        )
    if record.schema_version == "native-reference-query-coordinator/1.2":
        return (
            "native-query-coordinator/1.2",
            NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE[2],
        )
    return (
        NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL,
        NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[2],
    )


class NativeQueryCheckpointStore:
    """Bounded shared persistence, never a source/claim/native execution capability."""

    def __init__(self, request: QueryIntent, launch: QueryLaunch) -> None:
        self.request, self.launch = request, launch
        private = isinstance(request, PrivateChatQueryWorkflowRequest)
        if private != isinstance(launch, PrivateChatQueryLaunchAssociation):
            raise NativeQueryHistoryError("QUERY_CHECKPOINT_PURPOSE_INVALID")
        self.prefix = "PRIVATE_CHAT_QUERY" if private else "REFERENCE_QUERY"

    def _root(self, session: Session) -> None:
        try:
            require_native_query_root(session)
        except NativeQueryLaunchError as error:
            raise NativeQueryHistoryError(str(error)) from None

    def _parse(self, value: object) -> NativeQueryCheckpoint:
        if isinstance(self.request, PrivateChatQueryWorkflowRequest):
            return parse_native_private_chat_query_checkpoint(value)
        return parse_supported_native_reference_query_checkpoint(value)

    def _validate(self, records: tuple[NativeQueryCheckpoint, ...]) -> None:
        if isinstance(self.request, PrivateChatQueryWorkflowRequest):
            if not isinstance(self.launch, PrivateChatQueryLaunchAssociation) or not all(
                isinstance(row, NativePrivateChatQueryCheckpoint) for row in records
            ):
                raise ValueError()
            validate_native_private_chat_query_history(
                tuple(row for row in records if isinstance(row, NativePrivateChatQueryCheckpoint)),
                self.launch,
                self.request,
            )
        else:
            if isinstance(self.launch, PrivateChatQueryLaunchAssociation) or any(
                isinstance(row, NativePrivateChatQueryCheckpoint) for row in records
            ):
                raise ValueError()
            validate_native_reference_query_history(
                tuple(
                    row for row in records if not isinstance(row, NativePrivateChatQueryCheckpoint)
                ),
                self.launch,
                self.request,
            )

    def read(self, session: Session) -> NativeQueryHistory:
        try:
            original = read_native_query_launch(
                session,
                request=self.request,
                workflow_id=self.launch.workflow_id,
                step_run_id=self.launch.step_run_id,
            )
        except NativeQueryLaunchError as error:
            raise NativeQueryHistoryError(str(error)) from None
        if original != self.launch:
            raise NativeQueryHistoryError(self.prefix + "_ORIGINAL_LAUNCH_CHANGED")
        job = session.get(JobRecord, original.native_launch_job_id, populate_existing=True)
        assert job is not None
        rows = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id, JobEventRecord.event.in_(_EVENTS))
                .order_by(JobEventRecord.sequence)
                .limit(5)
            )
        )
        try:
            records = tuple(self._parse(row.data) for row in rows)
            if records:
                require_native_query_protocol(session, *_checkpoint_protocol(records[0]))
            self._validate(records)
            for row, record in zip(rows, records, strict=True):
                start, end = _STAGES[record.record_type]
                if row.event != self.prefix + "_NATIVE_" + record.record_type or (
                    row.from_state,
                    row.to_state,
                ) != (start.value, end.value):
                    raise ValueError()
            expected = JobState.CLAIMED if not records else _STAGES[records[-1].record_type][1]
            if job.status not in {expected.value, JobState.FAILED.value, JobState.CANCELLED.value}:
                raise ValueError()
            return NativeQueryHistory(job.status, original, records)
        except (ValueError, TypeError, KeyError, NativeQueryLaunchError):
            raise NativeQueryHistoryError(self.prefix + "_CHECKPOINT_HISTORY_INVALID") from None

    def append(self, session: Session, record: NativeQueryCheckpoint) -> NativeQueryHistory:
        self._root(session)
        session.scalar(
            select(JobRecord)
            .where(JobRecord.job_id == self.launch.native_launch_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        history = self.read(session)
        record = self._parse(record)
        previous = {value.record_type: value for value in history.records}
        if record.record_type in previous:
            if previous[record.record_type] != record:
                raise NativeQueryHistoryError(self.prefix + "_CHECKPOINT_CONFLICT")
            return history
        try:
            self._validate((*history.records, record))
        except (ValueError, TypeError):
            raise NativeQueryHistoryError(self.prefix + "_CHECKPOINT_ORDER_INVALID") from None
        if history.state != _STAGES[record.record_type][0].value:
            raise NativeQueryHistoryError(self.prefix + "_CHECKPOINT_TERMINAL_OR_FOREIGN")
        try:
            require_native_query_protocol(session, *_checkpoint_protocol(record), create=True)
        except NativeQueryLaunchError as error:
            raise NativeQueryHistoryError(str(error)) from None
        transition_job(
            session,
            self.launch.native_launch_job_id,
            _STAGES[record.record_type][1],
            self.prefix + "_NATIVE_" + record.record_type,
            data=record.model_dump(mode="json"),
        )
        session.flush()
        return self.read(session)

    def record_known_failure(self, session: Session) -> NativeQueryHistory:
        self._root(session)
        job = session.scalar(
            select(JobRecord)
            .where(JobRecord.job_id == self.launch.native_launch_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        history = self.read(session)
        code = (
            "NATIVE_PRIVATE_QUERY_KNOWN_FAILED"
            if isinstance(self.request, PrivateChatQueryWorkflowRequest)
            else "NATIVE_QUERY_KNOWN_FAILED"
        )
        if job is not None and history.state == JobState.FAILED.value and job.error_code == code:
            return history
        if job is None or history.state != JobState.RUNNING.value or len(history.records) != 1:
            raise NativeQueryHistoryError(self.prefix + "_FAILURE_TERMINAL_OR_FOREIGN")
        job = transition_job(
            session,
            job.job_id,
            JobState.FAILED,
            self.prefix + "_NATIVE_EXECUTION_FAILED",
            data={"code": code},
        )
        job.error_code = code
        job.error_message = _FAILURE_MESSAGES[history.records[0].schema_version]
        session.flush()
        return self.read(session)

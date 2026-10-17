"""Retained typed reference QUERY API over the shared original Job/event store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from eom_workflow.native_reference_query_coordinator import (
    SupportedNativeReferenceQueryCheckpoint,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from sqlalchemy.orm import Session

from eom_orchestrator.native_query_checkpoints import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL as NATIVE_REFERENCE_QUERY_COORDINATOR_PROTOCOL,
)
from eom_orchestrator.native_query_checkpoints import (
    NativeQueryCheckpointStore,
    NativeQueryHistory,
    NativeQueryHistoryError,
)
from eom_orchestrator.native_query_job_allocation import (
    NativeQueryLaunchError,
    create_native_query_launch,
    native_reference_query_key,
    read_native_query_launch,
)

NATIVE_QUERY_TASK = "native_reference_query_launch"
NATIVE_QUERY_LAUNCH_EVENT = "REFERENCE_QUERY_NATIVE_LAUNCH"


class NativeReferenceQueryHistoryError(ValueError):
    pass


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
    request = parse_supported_reference_query_workflow_request(request)
    launch = parse_reference_query_launch_association(launch)
    try:
        result = create_native_query_launch(session, request=request, launch=launch)
    except NativeQueryLaunchError as error:
        raise NativeReferenceQueryHistoryError(str(error)) from None
    assert isinstance(result, ReferenceQueryLaunchAssociation)
    return result


class NativeReferenceQueryCoordinator:
    """The public reference signatures, errors and immutable bytes stay unchanged."""

    def __init__(
        self,
        request: SupportedReferenceQueryWorkflowRequest,
        launch: ReferenceQueryLaunchAssociation,
    ) -> None:
        self.request = parse_supported_reference_query_workflow_request(request)
        self.launch = parse_reference_query_launch_association(launch)
        self._store = NativeQueryCheckpointStore(self.request, self.launch)

    def _history(self, value: NativeQueryHistory) -> NativeReferenceQueryHistory:
        assert isinstance(value.launch, ReferenceQueryLaunchAssociation)
        return NativeReferenceQueryHistory(
            value.state,
            value.launch,
            cast(tuple[SupportedNativeReferenceQueryCheckpoint, ...], value.records),
        )

    def read(self, session: Session) -> NativeReferenceQueryHistory:
        try:
            return self._history(self._store.read(session))
        except NativeQueryHistoryError as error:
            raise NativeReferenceQueryHistoryError(str(error)) from None

    def append(
        self, session: Session, record: SupportedNativeReferenceQueryCheckpoint
    ) -> NativeReferenceQueryHistory:
        try:
            return self._history(self._store.append(session, record))
        except NativeQueryHistoryError as error:
            raise NativeReferenceQueryHistoryError(str(error)) from None

    def record_known_failure(self, session: Session) -> NativeReferenceQueryHistory:
        try:
            return self._history(self._store.record_known_failure(session))
        except NativeQueryHistoryError as error:
            raise NativeReferenceQueryHistoryError(str(error)) from None

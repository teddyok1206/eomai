"""Original QUERY Job/event allocation shared by reference and private purposes.

Callers own live source, Workflow/command and physical execution authorization.
This adapter performs no inference, file IO, claim recovery or automatic retry.
"""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import content_sha256, new_logical_artifact_id, new_revision_id
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    ReferenceQueryWorkflowRequestV3,
    ReferenceQueryWorkflowRequestV4,
    SupportedReferenceQueryWorkflowIntent,
    parse_reference_query_launch_association,
    parse_reference_query_workflow_request_v3,
    parse_reference_query_workflow_request_v4,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow.schemas import (
    PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE,
    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE,
    REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE,
    REFERENCE_QUERY_REQUEST_V4_SCHEMA_RESOURCE,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
from eom_orchestrator.state_machine import JobState, transition_job

type QueryIntent = SupportedReferenceQueryWorkflowIntent | PrivateChatQueryWorkflowRequest
type QueryLaunch = ReferenceQueryLaunchAssociation | PrivateChatQueryLaunchAssociation


class NativeQueryLaunchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Purpose:
    prefix: str
    task: str
    protocol: str
    schema_sha256: str
    key_prefix: str

    @property
    def event(self) -> str:
        return self.prefix + "_NATIVE_LAUNCH"


_REFERENCE = _Purpose(
    "REFERENCE_QUERY",
    "native_reference_query_launch",
    "reference-query/1.0",
    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[2],
    "native-reference-query:",
)
_PUBLIC_REFERENCE = _Purpose(
    "REFERENCE_QUERY",
    "native_reference_query_launch",
    "reference-query/2.0",
    REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE[2],
    "native-reference-query:",
)
_REGISTERED_PUBLIC_REFERENCE = _Purpose(
    "REFERENCE_QUERY",
    "native_reference_query_launch",
    "reference-query/3.0",
    REFERENCE_QUERY_REQUEST_V4_SCHEMA_RESOURCE[2],
    "native-reference-query:",
)
_PRIVATE = _Purpose(
    "PRIVATE_CHAT_QUERY",
    "native_private_chat_query_launch",
    "private-chat-query/1.0",
    PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE[3],
    "native-private-chat-query:",
)


def require_native_query_root(session: Session) -> None:
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise NativeQueryLaunchError("REFERENCE_QUERY_OWNER_ROOT_REQUIRED")


def require_native_query_protocol(
    session: Session, version: str, digest: str, *, create: bool = False
) -> None:
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
        raise NativeQueryLaunchError("REFERENCE_QUERY_HISTORY_PROTOCOL_INVALID")


def _intent(value: QueryIntent) -> tuple[QueryIntent, _Purpose]:
    if isinstance(value, PrivateChatQueryWorkflowRequest):
        try:
            return (
                PrivateChatQueryWorkflowRequest.model_validate(
                    raw_similarity_contract_value(value)
                ),
                _PRIVATE,
            )
        except (ValueError, TypeError, SchemaError):
            raise NativeQueryLaunchError("PRIVATE_CHAT_QUERY_LAUNCH_REQUEST_INVALID") from None
    if isinstance(value, ReferenceQueryWorkflowRequestV4):
        return parse_reference_query_workflow_request_v4(value), _REGISTERED_PUBLIC_REFERENCE
    if isinstance(value, ReferenceQueryWorkflowRequestV3):
        return parse_reference_query_workflow_request_v3(value), _PUBLIC_REFERENCE
    return parse_supported_reference_query_workflow_request(value), _REFERENCE


def native_query_launch_key(request: QueryIntent, workflow_id: str, step_run_id: str) -> str:
    request, purpose = _intent(request)
    identity = {"workflow_id": workflow_id, "step_run_id": step_run_id, "attempt": 1}
    if purpose in (_REFERENCE, _PUBLIC_REFERENCE, _REGISTERED_PUBLIC_REFERENCE):
        return native_reference_query_key(workflow_id, step_run_id, request.request_sha256)
    return purpose.key_prefix + content_sha256(identity).removeprefix("sha256:")


def native_reference_query_key(workflow_id: str, step_run_id: str, request_sha256: str) -> str:
    return _REFERENCE.key_prefix + content_sha256(
        {
            "workflow_id": workflow_id,
            "step_run_id": step_run_id,
            "attempt": 1,
            "request_sha256": request_sha256,
        }
    ).removeprefix("sha256:")


def _launch(request: QueryIntent, value: object) -> QueryLaunch:
    if isinstance(request, PrivateChatQueryWorkflowRequest):
        try:
            launch = PrivateChatQueryLaunchAssociation.model_validate(
                raw_similarity_contract_value(value)
            )
        except (ValueError, TypeError, SchemaError):
            raise NativeQueryLaunchError("PRIVATE_CHAT_QUERY_LAUNCH_REQUEST_INVALID") from None
        if (
            launch.basis_sha256 != request.context_request.query_basis.basis_sha256
            or launch.recipe_sha256 != request.context_request.views[0].recipe.recipe_sha256
        ):
            raise NativeQueryLaunchError("PRIVATE_CHAT_QUERY_LAUNCH_REQUEST_INVALID")
        return launch
    return parse_reference_query_launch_association(value)


def _require_parent(request: QueryIntent, launch: QueryLaunch, purpose: _Purpose) -> None:
    if (
        launch.workflow_request_sha256 != request.request_sha256
        or launch.context_request_sha256 != request.context_request.request_sha256
        or launch.runtime_bundle != request.runtime_bundle
        or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
    ):
        raise NativeQueryLaunchError(purpose.prefix + "_LAUNCH_REQUEST_INVALID")


def read_native_query_launch(
    session: Session, *, request: QueryIntent, workflow_id: str, step_run_id: str
) -> QueryLaunch | None:
    require_native_query_root(session)
    request, purpose = _intent(request)
    job = session.scalar(
        select(JobRecord)
        .where(
            JobRecord.idempotency_key == native_query_launch_key(request, workflow_id, step_run_id)
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        return None
    require_native_query_protocol(session, purpose.protocol, purpose.schema_sha256)
    rows = tuple(
        session.scalars(
            select(JobEventRecord).where(
                JobEventRecord.job_id == job.job_id, JobEventRecord.event == purpose.event
            )
        )
    )
    try:
        if len(rows) != 1:
            raise ValueError()
        launch = _launch(request, rows[0].data)
        _require_parent(request, launch, purpose)
        payload = request.model_dump(mode="json")
        if (
            job.job_id != launch.native_launch_job_id
            or job.worker_slot_id is not None
            or job.task_type != purpose.task
            or job.protocol_version != purpose.protocol
            or job.request != payload
            or job.request_hash
            != content_sha256(
                {
                    "protocol_version": purpose.protocol,
                    "task_type": purpose.task,
                    "request": payload,
                }
            )
            or (rows[0].from_state, rows[0].to_state) != ("QUEUED", "CLAIMED")
            or (launch.workflow_id, launch.step_run_id) != (workflow_id, step_run_id)
        ):
            raise ValueError()
        return launch
    except (ValueError, TypeError, KeyError):
        raise NativeQueryLaunchError(purpose.prefix + "_LAUNCH_HISTORY_INVALID") from None


def create_native_query_launch(
    session: Session, *, request: QueryIntent, launch: QueryLaunch
) -> QueryLaunch:
    require_native_query_root(session)
    request, purpose = _intent(request)
    launch = _launch(request, launch)
    existing = read_native_query_launch(
        session, request=request, workflow_id=launch.workflow_id, step_run_id=launch.step_run_id
    )
    if existing is not None:
        return existing
    _require_parent(request, launch, purpose)
    require_native_query_protocol(session, purpose.protocol, purpose.schema_sha256, create=True)
    try:
        job, created = submit_structured_job(
            session,
            job_id=launch.native_launch_job_id,
            protocol_version=purpose.protocol,
            idempotency_key=native_query_launch_key(
                request, launch.workflow_id, launch.step_run_id
            ),
            task_type=purpose.task,
            request=request.model_dump(mode="json"),
            logical_artifact_id=new_logical_artifact_id(),
            revision_id=new_revision_id(),
        )
    except IntegrityError:
        if purpose is _PRIVATE:
            # The caller must roll back its root, then inspect the original key.
            # Conflict is not proof of no committed work or permission to retry.
            raise NativeQueryLaunchError("PRIVATE_CHAT_QUERY_LAUNCH_CONFLICT") from None
        raise  # Preserve the reference path's existing exception contract.
    if not created:
        raise NativeQueryLaunchError(purpose.prefix + "_LAUNCH_RACE_UNRECONCILED")
    for state, event in (
        (JobState.VALIDATED, purpose.prefix + "_REQUEST_VALIDATED"),
        (JobState.QUEUED, purpose.prefix + "_COORDINATOR_QUEUED"),
        (JobState.CLAIMED, purpose.event),
    ):
        transition_job(
            session,
            job.job_id,
            state,
            event,
            data=launch.model_dump(mode="json") if state is JobState.CLAIMED else {},
        )
    return launch

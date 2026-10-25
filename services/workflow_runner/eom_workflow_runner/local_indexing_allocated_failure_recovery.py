"""Root/schema-owner failure recovery for one original allocated CUDA INDEX execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_catalog_service.embedding_retired_failure_read import (
    ResolvedRetiredEmbeddingFailure,
    read_retired_embedding_failure,
)
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import read_embedding_batch_plan_metadata
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_orchestrator.workflow_job_retirement import require_no_held_worker_leases
from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_PROTOCOL,
    KNOWN_ENCODING_FAILURE_CODE,
    KnownFailedEmbeddingEncoding,
    NativeEmbeddingFailureRecoveryCommand,
)
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingAssociation
from eom_workflow.local_embedding_request import (
    LocalEmbeddingServiceWorkflowRequest,
    local_embedding_request_service,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
    local_embedding_request_service_v2,
    parse_supported_local_embedding_request,
)
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_start_command import (
    LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.native_workflow_maintenance_authority import (
    ALLOCATED_MAINTENANCE_TABLES,
    require_native_workflow_maintenance_owner,
)
from eom_workflow_runner.repository import validate_local_embedding_workflow_submission
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    transition_command,
    transition_stage,
    transition_step,
    transition_workflow,
)

RECOVERY_EVENT = "LOCAL_INDEXING_ALLOCATED_FAILURE_RECOVERED"


class AllocatedIndexingFailureRecoveryError(ValueError):
    def __init__(self, reason: str) -> None:
        self.code = "ALLOCATED_INDEXING_FAILURE_" + reason
        super().__init__(self.code)


def _require(condition: bool, reason: str = "CONTEXT_INVALID") -> None:
    if not condition:
        raise AllocatedIndexingFailureRecoveryError(reason)


@dataclass(frozen=True, slots=True)
class RecoveredAllocatedIndexingFailure:
    command: NativeEmbeddingFailureRecoveryCommand
    step_run_id: str
    native_launch_job_id: str
    encoding_job_ids: tuple[str, ...]
    state: Literal["FAILED"]
    performed_by: str
    performed_at: datetime


def recover_retired_indexing_workflow(
    sessions: sessionmaker[Session], command: NativeEmbeddingFailureRecoveryCommand
) -> RecoveredAllocatedIndexingFailure:
    """Own one short root; late physical-fence failure rolls back EVERY metadata change.

    Root UID and actual schema ownership are independent requirements. Neither a
    proof-shaped command, expired lease nor stored service/operator ID is authority.
    No source data, model, unit effect, retry producer or new allocation is created.
    """
    command = NativeEmbeddingFailureRecoveryCommand.model_validate(command)
    try:
        with sessions.begin() as session:
            principal = require_native_workflow_maintenance_owner(
                session, ALLOCATED_MAINTENANCE_TABLES
            )
            with read_retired_embedding_failure(command.root) as physical:
                return _recover(session, command, physical, principal)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise AllocatedIndexingFailureRecoveryError("BUSY") from error
        raise


def _parent_binding(
    session: Session,
    command: NativeEmbeddingFailureRecoveryCommand,
    physical: ResolvedRetiredEmbeddingFailure,
    request: SupportedLocalEmbeddingRequest,
    association: SupportedEmbeddingAssociation,
    service_id: str,
) -> None:
    metadata = read_embedding_batch_plan_metadata(session, command.root.parent_plan_job_id)
    _require(metadata is not None, "PARENT_MISSING")
    assert metadata is not None
    parent, history = metadata
    _require(
        history.state == "SUCCEEDED"
        and parent.purpose == "INDEX"
        and parent.request_sha256 == command.root.parent_request_sha256
        and parent.parent_request_sha256 == request.request_sha256
        and parent.scope.actor_kind == "LOCAL_INDEXING_SERVICE"
        and parent.scope.actor_id == service_id
        and parent.scope.storage_partition == request.namespace.storage_partition
        and parent.scope.access_policy_sha256 == request.access_policy_sha256,
        "PARENT_MISMATCH",
    )
    allocation, route, bound = history.allocation, history.route, history.bound
    _require(route is not None and bound is not None and history.failure is None, "PARENT_MISMATCH")
    assert route is not None and bound is not None
    _require(
        allocation.request_sha256
        == route.request_sha256
        == bound.request_sha256
        == parent.request_sha256
        and allocation.control_request.parent_request_sha256 == parent.request_sha256
        and allocation.control_request.allocation_attempt_id == command.root.allocation_attempt_id
        and allocation.control_request.message_sha256 == physical.allocation_request_sha256
        and allocation.control_request.purpose == "INDEX"
        and allocation.control_request.routing_policy_sha256 == parent.routing_policy_sha256
        and allocation.control_request.child_set_sha256
        == content_sha256(list(parent.child_selection_sha256s))
        and route.allocation_record_sha256 == allocation.record_sha256
        and route.observation.request_sha256 == parent.request_sha256
        and route.observation.policy_sha256 == parent.routing_policy_sha256
        and route.observation.allocation_attempt_id == command.root.allocation_attempt_id
        and route.observation.status == "ACQUIRED"
        and route.decision.selected.backend.device == "CUDA"
        and route.decision.request_sha256 == parent.request_sha256
        and route.decision.policy_sha256 == parent.routing_policy_sha256
        and route.decision.allocation_attempt_id == command.root.allocation_attempt_id
        and route.decision.allocation_observation_sha256 == route.observation.observation_sha256
        and bound.route_record_sha256 == route.record_sha256
        and bound.resource_profile_sha256 == request.resource_profile.resource_profile_sha256
        and len(bound.children) == 1
        and tuple(c.selection_sha256 for c in bound.children) == parent.child_selection_sha256s,
        "PARENT_MISMATCH",
    )
    child = bound.children[0]
    _require(
        child.workflow_id == command.workflow_id
        and child.step_run_id == association.intent.step_run_id
        and child.native_job_id == association.intent.native_launch_job_id
        and child.workflow_request_sha256 == request.request_sha256
        and child.launch_association_sha256 == association.association_sha256
        and child.native_input_sha256 == association.owned_input_request_sha256,
        "PARENT_MISMATCH",
    )


def _recover(
    session: Session,
    command: NativeEmbeddingFailureRecoveryCommand,
    physical: ResolvedRetiredEmbeddingFailure,
    principal: str,
) -> RecoveredAllocatedIndexingFailure:
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
        .with_for_update(nowait=True)
        .execution_options(populate_existing=True)
    )
    _require(workflow is not None)
    assert workflow is not None
    request = parse_supported_local_embedding_request(workflow.initial_request)
    _require(
        isinstance(request, LocalEmbeddingServiceWorkflowRequest | LocalEmbeddingWorkflowRequestV2)
    )
    assert isinstance(
        request, LocalEmbeddingServiceWorkflowRequest | LocalEmbeddingWorkflowRequestV2
    )
    service = (
        local_embedding_request_service_v2(request)
        if isinstance(request, LocalEmbeddingWorkflowRequestV2)
        else local_embedding_request_service(request)
    )
    _require(
        workflow.created_actor_type == "local_indexing_service"
        and workflow.created_actor_id == service.service_id
        and request.request_sha256 == command.workflow_request_sha256
        and request.resource_profile.device == "CUDA"
        and physical.proof == command.root,
    )
    definition = session.get(
        WorkflowDefinitionRecord, workflow.definition_id, populate_existing=True
    )
    _require(definition is not None)
    assert definition is not None
    validate_local_embedding_workflow_submission(
        session,
        workflow,
        definition=definition,
        request=request,
        actor_type="local_indexing_service",
        actor_id=service.service_id,
    )
    commands = tuple(
        session.scalars(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == command.workflow_id)
            .order_by(WorkflowCommandRecord.command_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == command.workflow_id)
            .order_by(WorkflowStepRunRecord.step_run_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    _require(len(commands) == len(steps) == 1)
    original, step = commands[0], steps[0]
    start, _ = resolve_native_start_command(
        session,
        workflow=workflow,
        workflow_created=False,
        actor_type="local_indexing_service",
        actor_id=service.service_id,
        source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    )
    _require(
        start is original
        and original.command_id == command.command_id
        and original.lease_generation == original.attempts == command.lease_generation
        and step.step_key == "encode_batch"
        and step.attempt == 1
        and step.step_type == "application"
        and step.worker_role is None
        and step.result_schema == "incremental-embedding-result@1.0"
        and step.platform_job_id is None
        and step.output_pointer_manifest is None
        and step.input_pointer_manifest
        == {
            "source_plan": request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": request.source_plan_sha256,
        },
    )
    require_no_held_worker_leases(session, (workflow.workflow_id,))
    launch = read_native_embedding_launch(
        session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
    )
    _require(launch is not None)
    assert launch is not None
    coordinator = NativeEmbeddingCoordinator(launch.intent, request)
    history = coordinator.read(session)
    association = read_native_embedding_launch_association(session, launch.intent, request)
    _require(association is not None and len(history.records) == 1)
    assert association is not None
    _parent_binding(session, command, physical, request, association, service.service_id)
    refs = tuple(sorted((v.job_reference for v in association.owned_jobs), key=lambda r: r.job_id))
    storage = EmbeddingEncodingReservationStorage()
    jobs = storage.lock_references(session, refs, lock=True)
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == command.workflow_id,
                WorkflowEventRecord.event_type == RECOVERY_EVENT,
            )
            .order_by(WorkflowEventRecord.sequence)
            .limit(2)
        )
    )
    if events:
        _require(
            len(events) == 1
            and events[0].payload == command.model_dump(mode="json")
            and events[0].actor_type == "database_owner"
            and events[0].actor_id == principal
            and events[0].command_id == command.command_id
            and (workflow.state, workflow.stage, original.state, step.state, history.state)
            == ("FAILED",) * 5
            and (workflow.failure_code, original.error_code, step.error_code)
            == (KNOWN_ENCODING_FAILURE_CODE,) * 3,
            "REPLAY_CONFLICT",
        )
        failures = storage.known_failures(session, jobs)
        _require(
            set(failures) == {j.job_id for j in jobs}
            and all(
                f.root == command.root
                and f.native_launch_job_id == launch.intent.native_launch_job_id
                for f in failures.values()
            ),
            "REPLAY_CONFLICT",
        )
        coordinator.record_known_failure(session, command)
        return RecoveredAllocatedIndexingFailure(
            command,
            step.step_run_id,
            launch.intent.native_launch_job_id,
            tuple(sorted(failures)),
            "FAILED",
            principal,
            events[0].created_at,
        )
    now = session.scalar(select(func.clock_timestamp()))
    _require(
        now is not None
        and workflow.state == "RUNNING"
        and workflow.stage == "LOCAL_EMBEDDING"
        and workflow.current_step_key == "encode_batch"
        and original.state == "PROCESSING"
        and step.state == "RUNNING"
        and history.state == "RUNNING"
        and original.lease_expires_at is not None
        and original.lease_expires_at < now
        and original.lease_owner is not None
        and original.lease_token is not None
        and workflow.failure_code is None
        and original.error_code is None
        and step.error_code is None
        and workflow.completed_at is None
        and original.processed_at is None
        and step.finished_at is None,
        "NOT_RECOVERABLE",
    )
    failure_records = []
    for owned in association.owned_jobs:
        body = dict(
            schema_version=ENCODING_RECOVERY_PROTOCOL,
            record_type="FAILURE",
            owned_job=owned.model_dump(mode="json"),
            native_launch_job_id=launch.intent.native_launch_job_id,
            root=command.root.model_dump(mode="json"),
        )
        failure_records.append(
            KnownFailedEmbeddingEncoding.model_validate(
                body | {"event_sha256": content_sha256(body)}
            )
        )
    failed_encodings = tuple(
        sorted(failure_records, key=lambda f: f.owned_job.job_reference.job_id)
    )
    storage.prepare_recovery_protocol(session)
    storage.record_known_failures(session, failed_encodings)
    coordinator.record_known_failure(session, command)
    transition_command(original, CommandState.FAILED)
    original.error_code = KNOWN_ENCODING_FAILURE_CODE
    transition_step(step, StepState.FAILED)
    step.error_code = KNOWN_ENCODING_FAILURE_CODE
    workflow.failure_code = KNOWN_ENCODING_FAILURE_CODE
    transition_stage(
        session,
        workflow.workflow_id,
        WorkflowStage.FAILED,
        "encode_batch",
        "LOCAL_INDEXING_ALLOCATED_FAILURE_STAGE_FAILED",
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
    )
    transition_workflow(
        session,
        workflow.workflow_id,
        WorkflowState.FAILED,
        RECOVERY_EVENT,
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
        step_key="encode_batch",
        payload=command.model_dump(mode="json"),
    )
    session.flush()
    event = session.scalar(
        select(WorkflowEventRecord).where(
            WorkflowEventRecord.workflow_id == command.workflow_id,
            WorkflowEventRecord.event_type == RECOVERY_EVENT,
        )
    )
    assert event is not None
    return RecoveredAllocatedIndexingFailure(
        command,
        step.step_run_id,
        launch.intent.native_launch_job_id,
        tuple(f.owned_job.job_reference.job_id for f in failed_encodings),
        "FAILED",
        principal,
        event.created_at,
    )

"""Exact retired CUDA preparation with no BOUND or encoding association; owner maintenance."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from eom_catalog_service.embedding_retired_failure_read import read_retired_embedding_failure
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanStore,
    read_embedding_batch_plan_metadata,
)
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.local_embedding_control_artifacts import batch_execution_publication_exists
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_orchestrator.workflow_job_retirement import require_no_held_worker_leases
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import EmbeddingBatchFailure
from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_SCHEMA_REF,
    NativeEmbeddingFailureRecoveryCommand,
    encoding_failure_disposition,
)
from eom_workflow.local_embedding_request_v2 import (
    parse_supported_local_embedding_request,
    supported_local_embedding_request_service,
)
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from eom_workflow_runner.embedding_batch_plan_admission import resolve_embedding_batch_plan_controls
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
from eom_workflow_runner.repository import CommandType, validate_local_embedding_workflow_submission
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

ROUTED_PREPARATION_RECOVERY_EVENT = "LOCAL_INDEXING_ROUTED_PREPARATION_RECOVERED"
ROUTED_PREPARATION_RECOVERY_ARTIFACT = "control_embedding_routed_preparation_failure"
ROUTED_PREPARATION_RECOVERY_MEMBER = "recovery.json"


class RoutedPreparationRecoveryError(ValueError):
    def __init__(self, reason: str) -> None:
        self.code = "ROUTED_PREPARATION_RECOVERY_" + reason
        super().__init__(self.code)


def _require(condition: bool, reason: str = "CONTEXT_INVALID") -> None:
    if not condition:
        raise RoutedPreparationRecoveryError(reason)


@dataclass(frozen=True, slots=True)
class RecoveredRoutedPreparationFailure:
    command: NativeEmbeddingFailureRecoveryCommand
    evidence: ArtifactMemberPointer
    cancelled_command_id: str
    native_launch_job_id: str
    performed_by: str
    performed_at: datetime


def recover_retired_routed_preparation(
    sessions: sessionmaker[Session],
    command: NativeEmbeddingFailureRecoveryCommand,
    evidence: ArtifactMemberPointer,
) -> RecoveredRoutedPreparationFailure:
    """No compute/retry/source mutation. Late physical failure rolls back this entire root."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    command = NativeEmbeddingFailureRecoveryCommand.model_validate(command)
    evidence = ArtifactMemberPointer.model_validate(evidence)
    _require(
        evidence.schema_ref == ENCODING_RECOVERY_SCHEMA_REF
        and evidence.member_path == ROUTED_PREPARATION_RECOVERY_MEMBER
        and evidence.media_type == "application/json"
    )
    try:
        with sessions.begin() as session:
            principal = require_native_workflow_maintenance_owner(
                session, ALLOCATED_MAINTENANCE_TABLES
            )
            with read_retired_embedding_failure(command.root) as physical:
                _require(physical.proof == command.root)
                return _recover(
                    session, command, evidence, physical.allocation_request_sha256, principal
                )
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise RoutedPreparationRecoveryError("BUSY") from error
        raise


def _recover(
    session: Session,
    command: NativeEmbeddingFailureRecoveryCommand,
    evidence: ArtifactMemberPointer,
    allocation_sha256: str,
    principal: str,
) -> RecoveredRoutedPreparationFailure:
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
        .with_for_update(nowait=True)
        .execution_options(populate_existing=True)
    )
    _require(workflow is not None)
    assert workflow is not None
    request = parse_supported_local_embedding_request(workflow.initial_request)
    service = supported_local_embedding_request_service(request)
    _require(
        workflow.created_actor_type == "local_indexing_service"
        and workflow.created_actor_id == service.service_id
        and request.request_sha256 == command.workflow_request_sha256
        and request.resource_profile.device == request.space.runtime.device == "CUDA"
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
            .limit(3)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == command.workflow_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    _require(len(commands) == 2 and len(steps) == 1)
    by_id = {row.command_id: row for row in commands}
    start, created = resolve_native_start_command(
        session,
        workflow=workflow,
        workflow_created=False,
        actor_type="local_indexing_service",
        actor_id=service.service_id,
        source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    )
    _require(not created and by_id.get(command.command_id) is start)
    advance = next(row for row in commands if row is not start)
    step = steps[0]
    _require(
        start.state == "SUCCEEDED"
        and start.command_type == CommandType.START_WORKFLOW.value
        and start.lease_generation == start.attempts == command.lease_generation
        and start.error_code is None
        and start.processed_at is not None
        and advance.command_type == CommandType.ADVANCE_WORKFLOW.value
        and advance.actor_type == workflow.created_actor_type
        and advance.actor_id == workflow.created_actor_id
        and advance.attempts == advance.lease_generation == 0
        and advance.lease_owner is None
        and advance.lease_token is None
        and advance.lease_expires_at is None
        and advance.error_code is None
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
        }
    )
    require_no_held_worker_leases(session, (workflow.workflow_id,))
    launch = read_native_embedding_launch(
        session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
    )
    _require(launch is not None)
    assert launch is not None
    _require(
        launch.intent.command_id == command.command_id
        and launch.intent.lease_generation == command.lease_generation
        and read_native_embedding_launch_association(session, launch.intent, request) is None,
        "ASSOCIATION_OR_FOREIGN_INTENT",
    )
    coordinator = NativeEmbeddingCoordinator(launch.intent, request)
    native_history = coordinator.read(session)
    _require(len(native_history.records) == 1)
    parent_job = session.scalar(
        select(JobRecord)
        .where(JobRecord.job_id == command.root.parent_plan_job_id)
        .with_for_update(nowait=True)
        .execution_options(populate_existing=True)
    )
    _require(parent_job is not None)
    metadata = read_embedding_batch_plan_metadata(session, command.root.parent_plan_job_id)
    _require(metadata is not None)
    assert metadata is not None
    parent, history = metadata
    route = history.route
    allocation = history.allocation
    _require(
        parent.purpose == "INDEX"
        and len(parent.child_selection_sha256s) == 1
        and parent.request_sha256 == command.root.parent_request_sha256
        and parent.parent_request_sha256 == request.request_sha256
        and parent.scope.actor_kind == "LOCAL_INDEXING_SERVICE"
        and parent.scope.actor_id == service.service_id
        and parent.scope.storage_partition == request.namespace.storage_partition
        and parent.scope.access_policy_sha256 == request.access_policy_sha256
        and route is not None
        and history.bound is None
        and allocation.control_request.allocation_attempt_id == command.root.allocation_attempt_id
        and allocation.control_request.message_sha256 == allocation_sha256,
        "PARENT_MISMATCH",
    )
    assert route is not None
    _require(route.decision.selected.backend.device == "CUDA")
    _require(
        not batch_execution_publication_exists(
            session,
            parent_request_sha256=parent.request_sha256,
            allocation_record_sha256=allocation.record_sha256,
        ),
        "PUBLICATION_EXISTS",
    )
    reader = PinnedArtifactReadContext.for_session(session, CatalogSettings())
    selection, policy = resolve_embedding_batch_plan_controls(reader, parent)
    reader.prefetch(((evidence.artifact_id, evidence.artifact_revision_id),))
    raw = reader.read_pinned(
        **evidence.model_dump(mode="python"),
        expected_artifact_types=(ROUTED_PREPARATION_RECOVERY_ARTIFACT,),
        expected_primary_file=ROUTED_PREPARATION_RECOVERY_MEMBER,
        max_bytes=64 * 1024,
    ).payload
    _require(raw == canonical_json_bytes(command), "EVIDENCE_MISMATCH")
    store = EmbeddingBatchPlanStore(parent, selection, policy)
    kind = encoding_failure_disposition(command)
    body = dict(
        schema_version="embedding-batch-plan/1.0",
        message_type="FAILED",
        request_sha256=parent.request_sha256,
        error_code=kind.code,
        evidence=evidence.model_dump(mode="json"),
    )
    failure = EmbeddingBatchFailure.model_validate(body | {"record_sha256": content_sha256(body)})
    payload = dict(
        command=command.model_dump(mode="json"), evidence=evidence.model_dump(mode="json")
    )
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == command.workflow_id,
                WorkflowEventRecord.event_type == ROUTED_PREPARATION_RECOVERY_EVENT,
            )
            .limit(2)
        )
    )
    if events:
        _require(
            len(events) == 1
            and events[0].payload == payload
            and events[0].actor_type == "database_owner"
            and events[0].actor_id == principal
            and events[0].command_id == command.command_id
            and (workflow.state, workflow.stage, step.state, native_history.state, history.state)
            == ("FAILED",) * 5
            and advance.state == "CANCELLED"
            and advance.processed_at is not None
            and (workflow.failure_code, step.error_code) == (kind.code,) * 2
            and history.failure == failure,
            "REPLAY_CONFLICT",
        )
        coordinator.record_known_failure(session, command)
        performed_at = events[0].created_at
    else:
        _require(
            workflow.state == "RUNNING"
            and workflow.stage == "LOCAL_EMBEDDING"
            and workflow.current_step_key == "encode_batch"
            and workflow.failure_code is None
            and workflow.completed_at is None
            and step.state == native_history.state == history.state == "RUNNING"
            and step.error_code is None
            and step.finished_at is None
            and history.failure is None
            and advance.state == "PENDING"
            and advance.processed_at is None,
            "NOT_RECOVERABLE",
        )
        EmbeddingEncodingReservationStorage.prepare_recovery_protocol(session)
        store.record_failure(session, failure)
        coordinator.record_known_failure(session, command)
        transition_command(advance, CommandState.CANCELLED)
        transition_step(step, StepState.FAILED)
        step.error_code = workflow.failure_code = kind.code
        transition_stage(
            session,
            workflow.workflow_id,
            WorkflowStage.FAILED,
            "encode_batch",
            "LOCAL_INDEXING_ROUTED_PREPARATION_STAGE_FAILED",
            actor_type="database_owner",
            actor_id=principal,
            command_id=command.command_id,
        )
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.FAILED,
            ROUTED_PREPARATION_RECOVERY_EVENT,
            actor_type="database_owner",
            actor_id=principal,
            command_id=command.command_id,
            step_key="encode_batch",
            payload=payload,
        )
        session.flush()
        recorded_at = session.scalar(
            select(WorkflowEventRecord.created_at).where(
                WorkflowEventRecord.workflow_id == command.workflow_id,
                WorkflowEventRecord.event_type == ROUTED_PREPARATION_RECOVERY_EVENT,
            )
        )
        assert recorded_at is not None
        performed_at = recorded_at
    reader.revalidate_provenance()
    return RecoveredRoutedPreparationFailure(
        command,
        evidence,
        advance.command_id,
        launch.intent.native_launch_job_id,
        principal,
        performed_at,
    )

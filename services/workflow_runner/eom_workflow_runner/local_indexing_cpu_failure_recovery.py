"""Explicit owner failure closure for one terminated CPU INDEX and its original producers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_catalog_service.native_cpu_index_failure_read import (
    read_retired_native_cpu_index_failure,
)
from eom_identifiers import content_sha256
from eom_identity_service import lock_current_local_indexing_service_metadata
from eom_orchestrator.embedding_artifact_store import owned_embedding_publication_key
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_orchestrator.workflow_job_retirement import require_no_held_worker_leases
from eom_workflow.embedding_cpu_failure_recovery import (
    CpuEmbeddingFailureRecoveryCommand,
    KnownFailedCpuEmbeddingEncoding,
)
from eom_workflow.embedding_encoding_recovery import encoding_failure_disposition
from eom_workflow.local_embedding_request import (
    LocalEmbeddingServiceWorkflowRequest,
    local_embedding_request_service,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
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

CPU_FAILURE_RECOVERY_EVENT = "LOCAL_INDEXING_CPU_FAILURE_RECOVERED"


class CpuIndexingFailureRecoveryError(ValueError):
    def __init__(self, reason: str) -> None:
        self.code = "CPU_INDEXING_FAILURE_" + reason
        super().__init__(self.code)


def _require(condition: bool, reason: str = "CONTEXT_INVALID") -> None:
    if not condition:
        raise CpuIndexingFailureRecoveryError(reason)


@dataclass(frozen=True, slots=True)
class RecoveredCpuIndexingFailure:
    command: CpuEmbeddingFailureRecoveryCommand
    step_run_id: str
    native_launch_job_id: str
    encoding_job_ids: tuple[str, ...]
    preserved_command_count: int
    state: Literal["FAILED"]
    performed_by: str
    performed_at: datetime


def recover_retired_cpu_indexing_workflow(
    sessions: sessionmaker[Session], command: CpuEmbeddingFailureRecoveryCommand
) -> RecoveredCpuIndexingFailure:
    """One root/schema-owner transaction; never source authority, restart or failed→success."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    command = CpuEmbeddingFailureRecoveryCommand.model_validate(command)
    try:
        with sessions.begin() as session:
            principal = require_native_workflow_maintenance_owner(
                session, ALLOCATED_MAINTENANCE_TABLES
            )
            return _recover(session, command, principal)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise CpuIndexingFailureRecoveryError("BUSY") from error
        raise


def _recover(
    session: Session, command: CpuEmbeddingFailureRecoveryCommand, principal: str
) -> RecoveredCpuIndexingFailure:
    kind = encoding_failure_disposition(command)
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
        request.resource_profile.device == request.space.runtime.device == "CPU"
        and request.request_sha256 == command.workflow_request_sha256
        and workflow.created_actor_type == "local_indexing_service"
        and workflow.created_actor_id == service.service_id == command.current_service.service_id
        and service.service_revision_id != command.current_service.service_revision_id
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
            .limit(2049)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    _require(1 <= len(commands) <= 2048)
    by_id = {row.command_id: row for row in commands}
    current = by_id.get(command.command_id)
    _require(current is not None)
    assert current is not None
    _require(
        current.lease_generation == command.lease_generation
        and current.attempts >= current.lease_generation
        and all(row.state == "SUCCEEDED" for row in commands if row is not current)
    )
    resolve_native_start_command(
        session,
        workflow=workflow,
        workflow_created=False,
        actor_type="local_indexing_service",
        actor_id=service.service_id,
        source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
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
    _require(len(steps) == 1)
    step = steps[0]
    _require(
        step.step_key == "encode_batch"
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
        launch.intent.native_launch_job_id == command.root.native_launch_job_id
        and launch.intent.intent_sha256 == command.native_intent_sha256
        and launch.intent.command_id in by_id
    )
    coordinator = NativeEmbeddingCoordinator(launch.intent, request)
    history = coordinator.read(session)
    association = read_native_embedding_launch_association(session, launch.intent, request)
    _require(association is not None and len(history.records) == 1)
    assert association is not None
    _require(
        session.scalar(
            select(JobRecord.job_id).where(
                JobRecord.idempotency_key
                == owned_embedding_publication_key(
                    association, workflow_request_sha256=request.request_sha256
                )
            )
        )
        is None,
        "PUBLICATION_EXISTS",
    )
    storage = EmbeddingEncodingReservationStorage()
    refs = tuple(sorted((v.job_reference for v in association.owned_jobs), key=lambda r: r.job_id))
    jobs = storage.lock_references(session, refs, lock=True)
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == command.workflow_id,
                WorkflowEventRecord.event_type == CPU_FAILURE_RECOVERY_EVENT,
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
            and (workflow.state, workflow.stage, current.state, step.state, history.state)
            == ("FAILED",) * 5
            and (workflow.failure_code, current.error_code, step.error_code) == (kind.code,) * 3,
            "REPLAY_CONFLICT",
        )
        failed = storage.known_failures(session, jobs)
        _require(
            set(failed) == {job.job_id for job in jobs}
            and all(
                isinstance(f, KnownFailedCpuEmbeddingEncoding)
                and f.root == command.root
                and f.native_launch_job_id == launch.intent.native_launch_job_id
                for f in failed.values()
            ),
            "REPLAY_CONFLICT",
        )
        coordinator.record_known_failure(session, command)
        return RecoveredCpuIndexingFailure(
            command,
            step.step_run_id,
            launch.intent.native_launch_job_id,
            tuple(sorted(failed)),
            len(commands) - 1,
            "FAILED",
            principal,
            events[0].created_at,
        )
    # The old service is deliberately not revived. Current-head metadata is a
    # control-plane lock, never a source or runtime grant for its retired revision.
    lock_current_local_indexing_service_metadata(session, command.current_service)
    now = session.scalar(select(func.clock_timestamp()))
    _require(
        now is not None
        and workflow.state == "RUNNING"
        and workflow.stage == "LOCAL_EMBEDDING"
        and workflow.current_step_key == "encode_batch"
        and step.state == "RUNNING"
        and history.state == "RUNNING"
        and current.state == "PROCESSING"
        and current.lease_expires_at is not None
        and current.lease_expires_at < now
        and current.lease_owner is not None
        and current.lease_token is not None
        and current.processed_at is None
        and current.error_code is None
        and workflow.failure_code is None
        and workflow.completed_at is None
        and step.error_code is None
        and step.finished_at is None,
        "NOT_RECOVERABLE",
    )
    records = []
    for owned in sorted(association.owned_jobs, key=lambda value: value.job_reference.job_id):
        body = dict(
            schema_version=command.schema_version,
            record_type="FAILURE",
            owned_job=owned.model_dump(mode="json"),
            native_launch_job_id=launch.intent.native_launch_job_id,
            root=command.root.model_dump(mode="json"),
        )
        records.append(
            KnownFailedCpuEmbeddingEncoding.model_validate(
                body | {"event_sha256": content_sha256(body)}
            )
        )
    with read_retired_native_cpu_index_failure(command.root):
        storage.prepare_recovery_protocol(session)
        storage.record_known_failures(session, tuple(records))
        coordinator.record_known_failure(session, command)
        transition_command(current, CommandState.FAILED)
        current.error_code = kind.code
        transition_step(step, StepState.FAILED)
        step.error_code = kind.code
        workflow.failure_code = kind.code
        transition_stage(
            session,
            workflow.workflow_id,
            WorkflowStage.FAILED,
            "encode_batch",
            "LOCAL_INDEXING_CPU_FAILURE_STAGE_FAILED",
            actor_type="database_owner",
            actor_id=principal,
            command_id=command.command_id,
        )
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.FAILED,
            CPU_FAILURE_RECOVERY_EVENT,
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
                WorkflowEventRecord.event_type == CPU_FAILURE_RECOVERY_EVENT,
            )
        )
        assert event is not None
        result = RecoveredCpuIndexingFailure(
            command,
            step.step_run_id,
            launch.intent.native_launch_job_id,
            tuple(record.owned_job.job_reference.job_id for record in records),
            len(commands) - 1,
            "FAILED",
            principal,
            event.created_at,
        )
    return result

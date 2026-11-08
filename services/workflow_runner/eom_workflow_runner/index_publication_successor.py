"""Recover already-computed rows into an explicitly pinned newer INDEX, not old bytes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.embedding_registry import EmbeddingIndexRevisionId
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import (
    register_embedding_index,
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index_revision,
)
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_artifact_store import EmbeddingIndexPublicationScope
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch_association,
)
from eom_workflow.index_publication_recovery import IndexPublicationRecoveryCommand
from pydantic import Field
from sqlalchemy import func, select

from eom_workflow_runner.index_publication_recovery import build_publication_recovery_executor
from eom_workflow_runner.local_embedding_execution_context import native_embedding_registry_scope
from eom_workflow_runner.local_embedding_publications import native_embedding_publications
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_workflow_maintenance_authority import (
    ALLOCATED_MAINTENANCE_TABLES,
    require_native_workflow_maintenance_owner,
)
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

EVENT = "EMBEDDING_INDEX_PUBLICATION_REPLACED"


class PreparedIndexSuccessorPlan(FrozenModel):
    """Application-local pinned selection; uses existing registry/artifact wire contracts."""

    recovery: IndexPublicationRecoveryCommand
    expected_index_revision_id: EmbeddingIndexRevisionId
    expected_index_sha256: Sha256
    created_at: UtcDatetime
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class RecoveredIndexSuccessor:
    registration: PublicSolutionIndexRegistrationResultV4
    recovered_encoding_count: int
    binding_count: int
    replayed: bool


def _require(value: bool) -> None:
    if not value:
        raise ValueError("INDEX_PUBLICATION_SUCCESSOR_INVALID")


def publish_recovered_index_successor(
    publisher: ControlFileSetPublisher, plan: PreparedIndexSuccessorPlan
) -> RecoveredIndexSuccessor:
    """Preserve newer rows, register a new immutable index, close only the stale parent.

    No submit, model, service activation or raw status UPDATE. Artifact publication
    may survive SQL rollback; deterministic identity/time support the exact replay.
    """
    _require(os.getresuid() == (0, 0, 0))
    plan = PreparedIndexSuccessorPlan.model_validate(plan)
    body = plan.model_dump(mode="json")
    key = content_sha256(body)[7:]
    workflow_id = plan.recovery.workflow_id
    with publisher.sessions.begin() as session:
        principal = require_native_workflow_maintenance_owner(session, ALLOCATED_MAINTENANCE_TABLES)
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow_id)
            .with_for_update(nowait=True)
        )
        event = session.scalar(
            select(WorkflowEventRecord).where(
                WorkflowEventRecord.workflow_id == workflow_id,
                WorkflowEventRecord.event_type == EVENT,
            )
        )
        if event is not None:
            _require(
                event.payload["plan"] == body
                and workflow is not None
                and workflow.state == "FAILED"
                and workflow.failure_code == EVENT
                and event.actor_type == "database_owner"
                and event.actor_id == principal
            )
            old_command = session.get(WorkflowCommandRecord, event.command_id)
            old_step = session.get(WorkflowStepRunRecord, event.payload["step_run_id"])
            native = session.get(JobRecord, event.payload["native_job_id"])
            _require(old_command is not None and old_step is not None and native is not None)
            assert old_command is not None and old_step is not None and native is not None
            _require((old_command.state, old_step.state, native.status) == ("FAILED",) * 3)
            _require(
                (old_command.error_code, old_step.error_code, native.error_code) == (EVENT,) * 3
            )
            jobs = tuple(
                session.scalars(
                    select(JobRecord).where(
                        JobRecord.job_id.in_(event.payload["preserved_encoding_job_ids"])
                    )
                )
            )
            _require(
                len(jobs) == event.payload["recovered_encoding_count"]
                and all(v.status == "SUCCEEDED" for v in jobs)
            )
            return RecoveredIndexSuccessor(
                PublicSolutionIndexRegistrationResultV4.model_validate(
                    event.payload["registration"]
                ),
                event.payload["recovered_encoding_count"],
                event.payload["binding_count"],
                True,
            )
    executor = build_publication_recovery_executor(publisher, plan.recovery)
    with publisher.sessions.begin() as session:
        principal = require_native_workflow_maintenance_owner(session, ALLOCATED_MAINTENANCE_TABLES)
        executor.fence(session)
        request, workflow, step, coordinator, history = executor.fence.original(session)
        _require(len(history.records) == 2)
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == workflow_id)
                .with_for_update(nowait=True)
            )
        )
        now = session.scalar(select(func.clock_timestamp()))
        _require(len(commands) == 1)
        command = commands[0]
        _require(
            command.state == "PROCESSING"
            and command.lease_expires_at is not None
            and now is not None
            and command.lease_expires_at < now
            and command.error_code is None
        )
        caller = executor.owner.registry_caller(request)
        basis = executor.owner.catalog.prepare_registered_public_index_basis(
            session, caller, native_embedding_registry_scope(request)
        )
        _require(basis.previous is not None)
        assert basis.previous is not None
        previous_pointer, previous = basis.previous
        _require(
            (previous.index_revision_id, previous.index_sha256)
            == (plan.expected_index_revision_id, plan.expected_index_sha256)
        )
        association = read_native_embedding_launch_association(session, coordinator.intent, request)
        assert association is not None
        refs = tuple(
            sorted((v.job_reference for v in association.owned_jobs), key=lambda v: v.job_id)
        )
        storage = EmbeddingEncodingReservationStorage
        reservations = storage.reservations(
            session, storage.lock_references(session, refs, lock=False)
        )
        selected = []
        rows = {v.encoding.encoding_sha256: v for v in basis.reusable_rows}
        for row in reservations:
            _require(row.job.status == "SUCCEEDED" and row.completion is not None)
            assert row.completion is not None
            selected.append((row.owned_job, row.completion))
            encoded = RegisteredEmbeddingRow(
                row.owned_job.request.encoding, row.completion.receipt.row_ref
            )
            prior = rows.get(encoded.encoding.encoding_sha256)
            _require(prior is None or prior == encoded)
            rows[encoded.encoding.encoding_sha256] = encoded
        shards = dict(basis.shards)
        for pointer, shard in CatalogLocalEmbeddingEncodingArtifacts(
            session, executor.owner.settings
        ).resolve_shared_row_shards(tuple(selected)):
            _require(pointer not in shards or shards[pointer] == shard)
            shards[pointer] = shard
        assembled = assemble_registered_public_solution_index_revision(
            basis.full_plan,
            available_rows=tuple(rows.values()),
            shards=tuple(shards.items()),
            index_id=previous.index_id,
            index_revision_id="embeddingindexrev_" + key[:32],
            previous_manifest=previous_pointer,
            created_at=plan.created_at,
        )
        covered = {v.encoding.encoding_sha256 for v in assembled.index.bindings}
        _require(all(v.owned_job.request.encoding.encoding_sha256 in covered for v in reservations))
        _require(
            {v.binding_sha256 for v in previous.bindings}
            <= {v.binding_sha256 for v in assembled.index.bindings}
        )
        publications = native_embedding_publications(publisher, plan.source_commit)
        identity = ControlFileSetIdentity(
            "job_" + key[:32], "artifact_" + key[:32], "rev_" + key[:32]
        )
        with TemporaryDirectory(prefix="eom-index-successor-", dir="/var/lib") as name:
            saved = publications.artifacts.publish_index(
                index=assembled.index,
                shards=assembled.shards,
                previous=basis.previous,
                scope=EmbeddingIndexPublicationScope(
                    request.graph_snapshot,
                    request.access_policy_revision_id,
                    request.access_policy_sha256,
                ),
                workspace=Path(name),
                identity=identity,
            )
        value = dict(
            schema_version="embedding-registry-registration-command/5.0",
            operation="REGISTER_EMBEDDING_INDEX",
            operation_key="index-recovery:" + key,
            corpus_id=request.corpus_id,
            namespace=request.namespace.model_dump(mode="json"),
            index_id=assembled.index.index_id,
            index_revision_id=assembled.index.index_revision_id,
            index_manifest=saved.index_manifest.model_dump(mode="json"),
            index_sha256=assembled.index.index_sha256,
            graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
            policy_revision_id=request.access_policy_revision_id,
            policy_sha256=request.access_policy_sha256,
            expected_current_index_revision_id=previous.index_revision_id,
            expected_lock_version=basis.expected_lock_version,
            source_set_sha256=basis.full_plan.source_set_sha256,
            binding_set_sha256=content_sha256([v.binding_sha256 for v in assembled.index.bindings]),
            eligible_source_count=len(basis.full_plan.sources),
            binding_count=len(assembled.index.bindings),
            requested_at=plan.created_at,
        )
        # JSON normalization precedes the canonical request hash (UTC datetime).
        value["requested_at"] = plan.created_at.isoformat().replace("+00:00", "Z")
        registration_command = RegisterPublicSolutionIndexCommandV4.model_validate(
            value | {"request_sha256": content_sha256(value)}
        )
        result = register_embedding_index(
            session, caller, registration_command, executor.owner.catalog
        )
        verify_embedding_index_registration_observation(
            session, caller, registration_command, result, executor.owner.catalog
        )
        coordinator.retire_replaced_publication(session, result)
        transition_command(command, CommandState.FAILED)
        command.error_code = EVENT
        transition_step(step, StepState.FAILED)
        step.error_code = EVENT
        workflow.failure_code = EVENT
        transition_stage(
            session,
            workflow_id,
            WorkflowStage.FAILED,
            "encode_batch",
            EVENT + "_STAGE",
            actor_type="database_owner",
            actor_id=principal,
            command_id=command.command_id,
        )
        payload = dict(
            plan=body,
            registration=result.model_dump(mode="json"),
            recovered_encoding_count=len(reservations),
            binding_count=len(assembled.index.bindings),
            preserved_encoding_job_ids=[v.job.job_id for v in reservations],
            native_job_id=coordinator.intent.native_launch_job_id,
            step_run_id=step.step_run_id,
        )
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.FAILED,
            EVENT,
            actor_type="database_owner",
            actor_id=principal,
            command_id=command.command_id,
            step_key="encode_batch",
            payload=payload,
        )
        return RecoveredIndexSuccessor(
            result, len(reservations), len(assembled.index.bindings), False
        )

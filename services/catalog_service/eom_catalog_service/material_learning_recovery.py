"""Explicit failed-unit successor over the original immutable source revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialLearningRights
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningRetryResult,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparedArtifact,
    require_native_material_checkpoint_chain,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparedArtifact,
    require_native_visual_prepared_base,
)
from eom_catalog_contracts.material_native_visual_work import require_material_native_visual_bundle
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_intake_read import (
    material_intake_pointer,
    material_prepared_pointer,
    read_material_intake,
    read_material_prepared,
)
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import append_material_event
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.material_task_history import (
    MAX_MATERIAL_ATTEMPTS,
    read_material_task_histories,
)

if TYPE_CHECKING:
    from eom_catalog_service.material_registered_base_recovery import (
        MaterialRegisteredBaseRecoveryProof,
    )

_TERMINAL_TASKS = frozenset({"COMPLETED", "FAILED", "EXCEPTION", "CANCELLED"})
_ARTIFACT_FIELDS = (
    "input_artifact_id",
    "input_artifact_revision_id",
    "input_sha256",
    "output_artifact_id",
    "output_artifact_revision_id",
    "output_sha256",
    "item_revision_id",
    "graph_snapshot_revision_id",
)
_VISUAL_FAILED_OUTPUT_FIELDS = (
    "output_artifact_id",
    "output_artifact_revision_id",
    "output_sha256",
    "item_revision_id",
    "analysis_run_id",
    "solution_analysis_run_id",
    "graph_snapshot_revision_id",
)


@dataclass(frozen=True, slots=True)
class _NativeVisualPreparedTarget:
    prepared: MaterialArtifactMember
    artifacts: CatalogArtifactService


@dataclass(frozen=True, slots=True)
class _NativeReferencePreparedTarget:
    prepared: MaterialArtifactMember
    artifacts: CatalogArtifactService


type _NativePreparedTarget = _NativeVisualPreparedTarget | _NativeReferencePreparedTarget


def retry_material_learning_run(
    sessions: sessionmaker[Session], command: RetryMaterialLearningRunCommand
) -> MaterialLearningRetryResult:
    return _retry_material_learning_run(sessions, command, target=None)


def recover_native_material_visuals(
    sessions: sessionmaker[Session],
    command: RetryMaterialLearningRunCommand,
    *,
    prepared: MaterialArtifactMember,
    artifacts: CatalogArtifactService,
) -> MaterialLearningRetryResult:
    """Explicitly inherit a qualified visual checkpoint, never ordinary retry's base.

    This internal application action uses the existing retry wire and indexed run
    history; callers must publish the immutable prepared3 with its owning adapter.
    """
    target = _NativeVisualPreparedTarget(
        MaterialArtifactMember.model_validate(prepared.model_dump(mode="json")), artifacts
    )
    return _retry_material_learning_run(sessions, command, target=target)


def recover_native_material_references(
    sessions: sessionmaker[Session],
    command: RetryMaterialLearningRunCommand,
    *,
    prepared: MaterialArtifactMember,
    artifacts: CatalogArtifactService,
) -> MaterialLearningRetryResult:
    """One native successor for visual failures and owner-proven invalid accepted bases.

    Existing extraction/Item pins are inherited, never re-extracted or rewritten.
    The new task's later Graph owner alone creates its repaired base analysis.
    """
    target = _NativeReferencePreparedTarget(
        MaterialArtifactMember.model_validate(prepared.model_dump(mode="json")), artifacts
    )
    return _retry_material_learning_run(sessions, command, target=target)


def _retry_material_learning_run(
    sessions: sessionmaker[Session],
    command: RetryMaterialLearningRunCommand,
    *,
    target: _NativePreparedTarget | None,
) -> MaterialLearningRetryResult:
    command = RetryMaterialLearningRunCommand.model_validate(command.model_dump(mode="json"))
    identity_input = command.model_dump(mode="json")
    identity_namespace = "eom:material-retry:"
    if target is not None:
        identity_namespace = (
            "eom:material-native-reference-retry:"
            if isinstance(target, _NativeReferencePreparedTarget)
            else "eom:material-native-visual-retry:"
        )
        identity_input = {
            "command": identity_input,
            "prepared": target.prepared.model_dump(mode="json"),
        }
    identity = (
        "materialrun_"
        + uuid5(NAMESPACE_URL, identity_namespace + content_sha256(identity_input)).hex
    )
    with sessions.begin() as session:
        authorize_material_learning(session, command.actor_id)
        source = session.get(MaterialLearningRunRecord, command.run_id)
        if source is None or source.created_by != command.actor_id:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        # One lock order for every predecessor in this material revision, not
        # only for two callers retrying the same old run.
        revision = session.scalar(
            select(LearningMaterialRevisionRecord)
            .where(
                LearningMaterialRevisionRecord.material_revision_id == source.material_revision_id
            )
            .with_for_update()
        )
        material = session.get(LearningMaterialRecord, revision.material_id) if revision else None
        source = session.scalar(
            select(MaterialLearningRunRecord)
            .where(MaterialLearningRunRecord.run_id == command.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            source is None
            or revision is None
            or material is None
            or revision.created_by != command.actor_id
            or source.created_by != command.actor_id
            or material.created_by != command.actor_id
            or material.lifecycle_state != "ACTIVE"
            or material.current_revision_id != revision.material_revision_id
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        if source.updated_at != command.expected_updated_at:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_STATE_STALE")
        if source.state not in {"FAILED", "COMPLETED_WITH_EXCEPTIONS"}:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_PHASE_INVALID")
        if source.prepared_artifact_revision_id is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_RECOVERY_REQUIRED")
        if target is not None and (
            source.lease_expires_at is not None and source.lease_expires_at > datetime.now(UTC)
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == source.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        failed = tuple(row for row in tasks if row.state == "FAILED")
        reference_tasks = (
            tuple(
                row
                for row in failed
                if any(getattr(row, field) is not None for field in _VISUAL_FAILED_OUTPUT_FIELDS)
            )
            if isinstance(target, _NativeReferencePreparedTarget)
            else ()
        )
        if isinstance(target, _NativeReferencePreparedTarget) and (
            not reference_tasks or any(row.task_kind != "QUESTION" for row in failed)
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REFERENCE_RECOVERY_PHASE_INVALID")
        if isinstance(target, _NativeVisualPreparedTarget) and any(
            row.task_kind != "QUESTION"
            or any(getattr(row, field) is not None for field in _VISUAL_FAILED_OUTPUT_FIELDS)
            for row in failed
        ):
            # A changed visual input cannot improve an already accepted result.
            # Ordinary retry owns partial-result/Item/analysis reuse unchanged.
            raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_RECOVERY_PHASE_INVALID")
        if not failed or any(row.task_kind == "PREPARE" for row in failed):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_NO_RETRYABLE_TASKS")
        if any(row.state not in _TERMINAL_TASKS for row in tasks):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        visual = (
            _native_visual_checkpoint(session, source, revision, command.actor_id, target)
            if target is not None
            else None
        )
        references = (
            _native_reference_proofs(session, reference_tasks, command.actor_id, target.artifacts)
            if isinstance(target, _NativeReferencePreparedTarget)
            else ()
        )
        existing = session.get(MaterialLearningRunRecord, identity)
        if existing is not None:
            if existing.predecessor_run_id != source.run_id or (
                target is not None
                and (
                    existing.material_revision_id != source.material_revision_id
                    or existing.created_by != command.actor_id
                    or existing.attempt != source.attempt + 1
                    or (
                        existing.prepared_artifact_id,
                        existing.prepared_artifact_revision_id,
                        existing.prepared_sha256,
                    )
                    != (
                        target.prepared.artifact_id,
                        target.prepared.artifact_revision_id,
                        target.prepared.sha256,
                    )
                )
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
            if isinstance(target, _NativeReferencePreparedTarget) and (
                _native_reference_proofs(
                    session, reference_tasks, command.actor_id, target.artifacts
                )
                != references
            ):
                raise MaterialLearningSourceError("MATERIAL_NATIVE_REFERENCE_RECOVERY_CHANGED")
            return _result(source, existing, tasks, replayed=True)
        if source.attempt >= MAX_MATERIAL_ATTEMPTS or session.scalar(
            select(MaterialLearningRunRecord.run_id)
            .where(
                MaterialLearningRunRecord.material_revision_id == source.material_revision_id,
                MaterialLearningRunRecord.attempt > source.attempt,
            )
            .limit(1)
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
        # The succeeded source extraction remains owned by its original task.
        # Resolve only failed questions requiring that checkpoint; no per-item
        # history query for the book's already-completed units.
        resumable = tuple(
            row for row in failed if row.task_kind == "QUESTION" and row.output_artifact_revision_id
        )
        histories = read_material_task_histories(
            session, tasks if target is not None else resumable
        )
        result_owners = {row.task_id: histories[row.task_id].result_task() for row in resumable}
        quiescent_tasks = (
            tuple(row for history in histories.values() for row in history.tasks)
            if target is not None
            else failed
        )
        workflows = _quiescent_failed_workflows(
            session,
            quiescent_tasks,
            extra_workflows=tuple(
                row.workflow_id for row in result_owners.values() if row.workflow_id
            ),
        )
        if target is not None and any(
            workflow.created_actor_id != command.actor_id for workflow in workflows.values()
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        if any(
            row.workflow_id is None
            or workflows.get(row.workflow_id) is None
            or workflows[row.workflow_id].state != "COMPLETED"
            for row in result_owners.values()
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        if any(
            row.task_kind == "QUESTION"
            and row.item_revision_id
            and row.task_id not in result_owners
            for row in failed
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INHERITED_RESULT_INVALID")
        now = datetime.now(UTC)
        successor = MaterialLearningRunRecord(
            run_id=identity,
            material_revision_id=source.material_revision_id,
            attempt=source.attempt + 1,
            predecessor_run_id=source.run_id,
            state="PROCESSING"
            if any(row.task_kind in {"QUESTION", "EXPLANATION"} for row in tasks)
            else "DISCOVERING",
            next_event_sequence=1,
            created_by=source.created_by,
            prepared_artifact_id=target.prepared.artifact_id
            if target is not None
            else source.prepared_artifact_id,
            prepared_artifact_revision_id=target.prepared.artifact_revision_id
            if target is not None
            else source.prepared_artifact_revision_id,
            prepared_sha256=target.prepared.sha256
            if target is not None
            else source.prepared_sha256,
            created_at=now,
            updated_at=now,
        )
        session.add(successor)
        session.flush()
        append_material_event(
            session,
            successor,
            event_type="MATERIAL_NATIVE_REFERENCE_RETRY_STARTED"
            if isinstance(target, _NativeReferencePreparedTarget)
            else "MATERIAL_RETRY_STARTED",
            prior_state=None,
        )
        copies = []
        for row in tasks:
            state = row.state
            inherit = state != "FAILED"
            if state == "FAILED":
                inherit = row.task_id in result_owners
                state = (
                    "REGISTERED"
                    if inherit and row.item_revision_id
                    else "RESULT_READY"
                    if inherit
                    else "PENDING"
                )
            clone = MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid5(NAMESPACE_URL, f"{identity}:{row.task_id}").hex,
                run_id=identity,
                task_kind=row.task_kind,
                unit_key=row.unit_key,
                ordinal=row.ordinal,
                attempt=row.attempt + 1,
                predecessor_task_id=row.task_id,
                state=state,
                execution_lane="MATERIAL_LEARNING",
                error_code=row.error_code if state in {"EXCEPTION", "CANCELLED"} else None,
                created_at=now,
                updated_at=now,
                **{name: getattr(row, name) for name in _ARTIFACT_FIELDS} if inherit else {},
            )
            copies.append(clone)
        session.add_all(copies)
        session.flush()
        for row in copies:
            append_material_event(
                session,
                successor,
                event_type="MATERIAL_TASK_CHECKPOINT_INHERITED"
                if row.state != "PENDING"
                else "MATERIAL_TASK_RETRY_CREATED",
                prior_state=None,
                task=row,
            )
        authorize_material_learning(session, command.actor_id)
        # Reauthorize small checkpoint/source metadata, never re-extract or
        # republish accepted history. Ordinary retry retains its old boundary.
        if target is not None and (
            _native_visual_checkpoint(session, source, revision, command.actor_id, target) != visual
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_PREPARED_CHANGED")
        if isinstance(target, _NativeReferencePreparedTarget) and (
            _native_reference_proofs(session, reference_tasks, command.actor_id, target.artifacts)
            != references
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REFERENCE_RECOVERY_CHANGED")
        return _result(source, successor, tasks, replayed=False)


def _native_visual_checkpoint(
    session: Session,
    source: MaterialLearningRunRecord,
    revision: LearningMaterialRevisionRecord,
    actor_id: str,
    target: _NativePreparedTarget,
) -> MaterialNativeVisualPreparedArtifact:
    artifacts = target.artifacts
    if session.get_bind() is not artifacts.engine:
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_STORAGE_SCOPE_INVALID")
    material = session.get(LearningMaterialRecord, revision.material_id, populate_existing=True)
    if (
        material is None
        or material.created_by != actor_id
        or material.lifecycle_state != "ACTIVE"
        or material.current_revision_id != revision.material_revision_id
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
    if (
        source.prepared_artifact_id is None
        or source.prepared_artifact_revision_id is None
        or source.prepared_sha256 is None
    ):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_BASE_REQUIRED")
    base_pointer = material_prepared_pointer(
        session,
        artifact_id=source.prepared_artifact_id,
        revision_id=source.prepared_artifact_revision_id,
        sha256=source.prepared_sha256,
    )
    pointer = material_prepared_pointer(
        session,
        artifact_id=target.prepared.artifact_id,
        revision_id=target.prepared.artifact_revision_id,
        sha256=target.prepared.sha256,
    )
    if pointer != target.prepared:
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_PREPARED_POINTER_INVALID")

    def authorize() -> None:
        authorize_material_learning(session, actor_id)

    base = read_material_prepared(artifacts, base_pointer, authorize=authorize)
    prepared = read_material_prepared(artifacts, pointer, authorize=authorize)
    if not isinstance(base, MaterialNativePreparedArtifact) or not isinstance(
        prepared, MaterialNativeVisualPreparedArtifact
    ):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_BASE_REQUIRED")
    require_native_visual_prepared_base(prepared, base=base, base_pointer=base_pointer)
    intake_pointer = material_intake_pointer(
        session,
        artifact_id=revision.manifest_artifact_id,
        revision_id=revision.manifest_artifact_revision_id,
        sha256=revision.manifest_sha256,
    )
    intake = read_material_intake(artifacts, intake_pointer, authorize=authorize)
    if (
        not isinstance(intake, MaterialNativeLearningIntakeManifest)
        or intake.requested_by != actor_id
        or intake.material_id != revision.material_id
        or intake.material_revision_id != source.material_revision_id
    ):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_INTAKE_REQUIRED")
    require_native_material_checkpoint_chain(intake, prepared=base, intake_pointer=intake_pointer)
    bundle = read_material_native_bundle(
        artifacts,
        intake.native_bundle,
        sources=intake.sources,
        operator_id=actor_id,
        authorize=authorize,
    )
    require_material_native_visual_bundle(prepared, bundle)
    selected = {entry.source_role: entry.source_upload for entry in intake.sources}
    if any(entry.original != selected[entry.source_role].original for entry in base.sources):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_VISUAL_SOURCE_MISMATCH")
    sources = MaterialLearningSourceService(artifacts.engine, artifacts.settings)
    for selected_source in intake.sources:
        sources.resolve(selected_source.source_upload, operator_id=actor_id)
    rights = read_material_metadata(
        artifacts,
        intake.rights_attestation,
        MaterialLearningRights,
        schema_ref="eom://schemas/material-learning/rights/1.0",
        member_path="rights/attestation.json",
    )
    if (rights.material_id, rights.material_revision_id, rights.attested_by) != (
        intake.material_id,
        intake.material_revision_id,
        actor_id,
    ) or rights.source_hashes != tuple(
        entry.source_upload.original.sha256 for entry in intake.sources
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RIGHTS_MISMATCH")
    authorize()
    return prepared


def _native_reference_proofs(
    session: Session,
    tasks: tuple[MaterialLearningTaskRecord, ...],
    actor_id: str,
    artifacts: CatalogArtifactService,
) -> tuple[MaterialRegisteredBaseRecoveryProof, ...]:
    from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService

    analyses = KnowledgeAnalysisApplicationService(artifacts.engine, artifacts.settings)
    proofs = tuple(
        analyses.validate_material_base_recovery(session, task_id=row.task_id, operator_id=actor_id)
        for row in tasks
    )
    if any(
        (proof.task_id, proof.item_revision_id) != (row.task_id, row.item_revision_id)
        or (row.analysis_run_id is not None and proof.base_analysis_run_id != row.analysis_run_id)
        for row, proof in zip(tasks, proofs, strict=True)
    ):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_REFERENCE_RECOVERY_POINTER_INVALID")
    return proofs


def _quiescent_failed_workflows(
    session: Session,
    tasks: tuple[MaterialLearningTaskRecord, ...],
    *,
    extra_workflows: tuple[str, ...] = (),
) -> dict[str, WorkflowInstanceRecord]:
    analysis_ids = {
        identity
        for row in tasks
        for identity in (row.analysis_run_id, row.solution_analysis_run_id)
        if identity
    }
    analyses = (
        tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord).where(
                    KnowledgeAnalysisRunRecord.analysis_run_id.in_(analysis_ids)
                )
            )
        )
        if analysis_ids
        else ()
    )
    if {row.analysis_run_id for row in analyses} != analysis_ids or any(
        row.state not in {"ACCEPTED", "FAILED", "REJECTED", "CANCELLED"} for row in analyses
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
    workflow_ids = (
        set(extra_workflows)
        | {row.workflow_id for row in tasks if row.workflow_id}
        | {row.workflow_id for row in analyses}
    )
    if not workflow_ids:
        return {}
    workflows = {
        row.workflow_id: row
        for row in session.scalars(
            select(WorkflowInstanceRecord).where(
                WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
            )
        )
    }
    if (
        set(workflows) != workflow_ids
        or any(row.state not in {"COMPLETED", "FAILED", "CANCELLED"} for row in workflows.values())
        or session.scalar(
            select(WorkerLeaseRecord.lease_id)
            .where(
                WorkerLeaseRecord.workflow_id.in_(workflow_ids),
                WorkerLeaseRecord.state.in_({"ACTIVE", "RECONCILING"}),
            )
            .limit(1)
        )
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
    return workflows


def _result(
    source: MaterialLearningRunRecord,
    successor: MaterialLearningRunRecord,
    tasks: tuple[MaterialLearningTaskRecord, ...],
    *,
    replayed: bool,
) -> MaterialLearningRetryResult:
    return MaterialLearningRetryResult.model_validate(
        dict(
            predecessor_run_id=source.run_id,
            run_id=successor.run_id,
            state=successor.state,
            reused_tasks=sum(row.state == "COMPLETED" for row in tasks),
            retried_tasks=sum(row.state == "FAILED" for row in tasks),
            replayed=replayed,
        )
    )

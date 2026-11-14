"""Resume validated native discovery finalization without another model invocation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_discovery_finalization_recovery import (
    NativeMaterialDiscoveryFinalizationRecoveryResult,
    RecoverNativeMaterialDiscoveryFinalizationCommand,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialLearningRights
from eom_catalog_contracts.material_learning_intake import MaterialRunState
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    MaterialNativePreparedArtifact,
    require_native_material_checkpoint_chain,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_intake_read import (
    material_intake_pointer,
    material_preparation_pointer,
    material_prepared_pointer,
    read_material_intake,
    read_material_preparation,
    read_material_prepared,
)
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_coordinator import (
    bind_native_material_discovery_plan,
    read_material_discovery_plan,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import append_material_event
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.material_task_history import (
    MAX_MATERIAL_ATTEMPTS,
    read_material_task_histories,
)
from eom_catalog_service.settings import CatalogSettings

_PINS = (
    "input_artifact_id",
    "input_artifact_revision_id",
    "input_sha256",
    "output_artifact_id",
    "output_artifact_revision_id",
    "output_sha256",
)
_TASK_SIGNATURE = (
    "task_id",
    "task_kind",
    "unit_key",
    "ordinal",
    "attempt",
    "predecessor_task_id",
    "state",
    "execution_lane",
    "workflow_id",
    *_PINS,
)
_REGISTRATION_FIELDS = (
    "item_revision_id",
    "analysis_run_id",
    "solution_analysis_run_id",
    "graph_snapshot_revision_id",
)


def _task_signature(
    tasks: tuple[MaterialLearningTaskRecord, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(tuple(getattr(task, name) for name in _TASK_SIGNATURE) for task in tasks)


class NativeMaterialDiscoveryFinalizationRecoveryService:
    """A closed recovery of completed native discovery, not arbitrary run retry."""

    def __init__(self, engine: Engine, *, settings: CatalogSettings, source_commit: str) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_SOURCE_INVALID")
        self.source_commit = source_commit
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.artifacts = CatalogArtifactService(engine, settings)
        self.sources = MaterialLearningSourceService(engine, settings)

    @staticmethod
    def _source(
        session: Session, command: RecoverNativeMaterialDiscoveryFinalizationCommand
    ) -> tuple[MaterialLearningRunRecord, LearningMaterialRevisionRecord]:
        authorize_material_learning(session, command.actor_id)
        source = session.get(MaterialLearningRunRecord, command.run_id, populate_existing=True)
        revision = (
            session.get(LearningMaterialRevisionRecord, source.material_revision_id)
            if source
            else None
        )
        material = (
            session.get(LearningMaterialRecord, revision.material_id, populate_existing=True)
            if revision
            else None
        )
        if (
            source is None
            or revision is None
            or material is None
            or source.created_by != command.actor_id
            or revision.created_by != command.actor_id
            or material.created_by != command.actor_id
            or material.lifecycle_state != "ACTIVE"
            or material.current_revision_id != revision.material_revision_id
        ):
            raise ValueError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        if source.updated_at != command.expected_updated_at:
            raise ValueError("MATERIAL_LEARNING_STATE_STALE")
        if (
            source.state != "FAILED"
            or source.error_code != "MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID"
            or source.prepared_artifact_id is None
            or source.prepared_artifact_revision_id is None
            or source.prepared_sha256 != command.expected_prepared_sha256
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_PHASE_INVALID")
        if source.lease_expires_at is not None and source.lease_expires_at > datetime.now(UTC):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_LIVE_LEASE")
        return source, revision

    @staticmethod
    def _tasks(
        session: Session, source: MaterialLearningRunRecord, actor_id: str
    ) -> tuple[MaterialLearningTaskRecord, ...]:
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == source.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
                .limit(2002)
            )
        )
        if (
            not 2 <= len(tasks) <= 2001
            or tasks[0].task_kind != "PREPARE"
            or tasks[0].ordinal != 1
            or tasks[0].unit_key != "source-preparation"
            or tuple(task.ordinal for task in tasks) != tuple(range(1, len(tasks) + 1))
            or any(task.execution_lane != "MATERIAL_LEARNING" for task in tasks)
            or any(task.task_kind != "DISCOVER" for task in tasks[1:])
            or any(task.state != "COMPLETED" for task in tasks)
            or any(getattr(task, field) is None for task in tasks for field in _PINS)
            or any(
                getattr(task, field) is not None for task in tasks for field in _REGISTRATION_FIELDS
            )
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_TASKS_INVALID")
        histories = read_material_task_histories(session, tasks)
        workflow_ids = {histories[task.task_id].result_task().workflow_id for task in tasks[1:]}
        workflows = tuple(
            session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
                )
            )
        )
        if (
            {workflow.workflow_id for workflow in workflows} != workflow_ids
            or any(
                workflow.state != "COMPLETED" or workflow.created_actor_id != actor_id
                for workflow in workflows
            )
            or session.scalar(
                select(WorkerLeaseRecord.lease_id)
                .where(
                    WorkerLeaseRecord.workflow_id.in_(workflow_ids),
                    WorkerLeaseRecord.state.in_({"ACTIVE", "RECONCILING"}),
                )
                .limit(1)
            )
        ):
            raise ValueError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        return tasks

    def _checkpoint(
        self,
        session: Session,
        source: MaterialLearningRunRecord,
        revision: LearningMaterialRevisionRecord,
        command: RecoverNativeMaterialDiscoveryFinalizationCommand,
        preparation_task: MaterialLearningTaskRecord,
    ) -> tuple[MaterialNativeLearningIntakeManifest, MaterialArtifactMember]:
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
        if source.prepared_artifact_id is None or source.prepared_artifact_revision_id is None:
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_PHASE_INVALID")
        prepared_pointer = material_prepared_pointer(
            session,
            artifact_id=source.prepared_artifact_id,
            revision_id=source.prepared_artifact_revision_id,
            sha256=command.expected_prepared_sha256,
        )

        def authorize() -> None:
            authorize_material_learning(session, command.actor_id)

        intake = read_material_intake(self.artifacts, intake_pointer, authorize=authorize)
        prepared = read_material_prepared(self.artifacts, prepared_pointer, authorize=authorize)
        if (
            preparation_task.input_artifact_id is None
            or preparation_task.input_artifact_revision_id is None
            or preparation_task.input_sha256 is None
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_NATIVE_CHECKPOINT_REQUIRED")
        preparation_pointer = material_preparation_pointer(
            session,
            artifact_id=preparation_task.input_artifact_id,
            revision_id=preparation_task.input_artifact_revision_id,
            sha256=preparation_task.input_sha256,
        )
        preparation = read_material_preparation(
            self.artifacts, preparation_pointer, authorize=authorize
        )
        if (
            not isinstance(intake, MaterialNativeLearningIntakeManifest)
            or not isinstance(prepared, MaterialNativePreparedArtifact)
            or not isinstance(preparation, MaterialNativePreparationInput)
            or intake.requested_by != command.actor_id
            or intake.material_id != revision.material_id
            or intake.material_revision_id != source.material_revision_id
            or preparation.profile.profile_sha256 != prepared.profile_sha256
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_NATIVE_CHECKPOINT_REQUIRED")
        require_native_material_checkpoint_chain(
            intake, preparation=preparation, prepared=prepared, intake_pointer=intake_pointer
        )
        history = read_material_task_histories(session, (preparation_task,))[
            preparation_task.task_id
        ]
        if not any(
            task.task_id == preparation.task_id
            and (task.input_artifact_id, task.input_artifact_revision_id, task.input_sha256)
            == (
                preparation_pointer.artifact_id,
                preparation_pointer.artifact_revision_id,
                preparation_pointer.sha256,
            )
            for task in history.tasks
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_PREPARATION_OWNER_INVALID")
        self._reauthorize_sources(session, intake, command.actor_id)
        return intake, prepared_pointer

    def _reauthorize_sources(
        self, session: Session, intake: MaterialNativeLearningIntakeManifest, actor_id: str
    ) -> None:
        authorize_material_learning(session, actor_id)
        for selected in intake.sources:
            self.sources.resolve(selected.source_upload, operator_id=actor_id)
        rights = read_material_metadata(
            self.artifacts,
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
            source.source_upload.original.sha256 for source in intake.sources
        ):
            raise ValueError("MATERIAL_LEARNING_RIGHTS_MISMATCH")
        authorize_material_learning(session, actor_id)

    def recover(
        self, command: RecoverNativeMaterialDiscoveryFinalizationCommand
    ) -> NativeMaterialDiscoveryFinalizationRecoveryResult:
        command = RecoverNativeMaterialDiscoveryFinalizationCommand.model_validate(
            command.model_dump(mode="json")
        )
        if command.target_source_commit != self.source_commit:
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_SOURCE_MISMATCH")
        identity = (
            "materialrun_"
            + uuid5(
                NAMESPACE_URL,
                "eom:native-discovery-finalization:"
                + content_sha256(command.model_dump(mode="json")),
            ).hex
        )
        # Validate immutable bytes/results before taking the revision/run locks.
        with self.sessions() as session:
            source, revision = self._source(session, command)
            tasks = self._tasks(session, source, command.actor_id)
            signature = _task_signature(tasks)
            intake, prepared = self._checkpoint(session, source, revision, command, tasks[0])
            revision_pin = (
                revision.manifest_artifact_id,
                revision.manifest_artifact_revision_id,
                revision.manifest_sha256,
            )
            bundle = read_material_native_bundle(
                self.artifacts,
                intake.native_bundle,
                sources=intake.sources,
                operator_id=command.actor_id,
                authorize=lambda: authorize_material_learning(session, command.actor_id),
            )
            plan = read_material_discovery_plan(
                session, self.artifacts, run_id=source.run_id, operator_id=command.actor_id
            )
            bind_native_material_discovery_plan(plan, bundle)
            revision_id = source.material_revision_id
        with self.sessions.begin() as session:
            session.scalar(
                select(LearningMaterialRevisionRecord)
                .where(LearningMaterialRevisionRecord.material_revision_id == revision_id)
                .with_for_update()
            )
            session.scalar(
                select(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.run_id == command.run_id)
                .with_for_update()
            )
            source, revision = self._source(session, command)
            tasks = self._tasks(session, source, command.actor_id)
            if (
                _task_signature(tasks) != signature
                or revision_pin
                != (
                    revision.manifest_artifact_id,
                    revision.manifest_artifact_revision_id,
                    revision.manifest_sha256,
                )
                or (
                    source.prepared_artifact_id,
                    source.prepared_artifact_revision_id,
                    source.prepared_sha256,
                )
                != (prepared.artifact_id, prepared.artifact_revision_id, prepared.sha256)
            ):
                raise ValueError("MATERIAL_NATIVE_FINALIZATION_CHECKPOINT_CHANGED")
            self._reauthorize_sources(session, intake, command.actor_id)
            # Approval and manifest membership can be withdrawn independently of
            # immutable bytes. Recheck only their small metadata under the lock;
            # do not reread or rehash original papers, native files or model output.
            material_intake_pointer(
                session,
                artifact_id=revision.manifest_artifact_id,
                revision_id=revision.manifest_artifact_revision_id,
                sha256=revision.manifest_sha256,
            )
            if (
                material_prepared_pointer(
                    session,
                    artifact_id=prepared.artifact_id,
                    revision_id=prepared.artifact_revision_id,
                    sha256=prepared.sha256,
                )
                != prepared
            ):
                raise ValueError("MATERIAL_NATIVE_FINALIZATION_CHECKPOINT_CHANGED")
            existing = session.get(MaterialLearningRunRecord, identity)
            if existing is not None:
                self._require_successor(session, source, existing, tasks, prepared)
                return self._result(
                    source, existing, intake.material_id, prepared, len(tasks), replayed=True
                )
            if source.attempt >= MAX_MATERIAL_ATTEMPTS or session.scalar(
                select(MaterialLearningRunRecord.run_id)
                .where(
                    MaterialLearningRunRecord.material_revision_id == revision_id,
                    MaterialLearningRunRecord.attempt > source.attempt,
                )
                .limit(1)
            ):
                raise ValueError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
            now = datetime.now(UTC)
            successor = MaterialLearningRunRecord(
                run_id=identity,
                material_revision_id=revision_id,
                attempt=source.attempt + 1,
                predecessor_run_id=source.run_id,
                state="DISCOVERING",
                next_event_sequence=1,
                created_by=command.actor_id,
                prepared_artifact_id=prepared.artifact_id,
                prepared_artifact_revision_id=prepared.artifact_revision_id,
                prepared_sha256=prepared.sha256,
                created_at=now,
                updated_at=now,
            )
            session.add(successor)
            session.flush()
            append_material_event(
                session,
                successor,
                event_type="NATIVE_DISCOVERY_FINALIZATION_RECOVERED",
                prior_state=None,
            )
            clones = tuple(
                MaterialLearningTaskRecord(
                    task_id=self._task_id(identity, task.task_id),
                    run_id=identity,
                    task_kind=task.task_kind,
                    unit_key=task.unit_key,
                    ordinal=task.ordinal,
                    attempt=task.attempt + 1,
                    predecessor_task_id=task.task_id,
                    state="COMPLETED",
                    execution_lane="MATERIAL_LEARNING",
                    created_at=now,
                    updated_at=now,
                    **{name: getattr(task, name) for name in _PINS},
                )
                for task in tasks
            )
            session.add_all(clones)
            session.flush()
            for task in clones:
                append_material_event(
                    session,
                    successor,
                    event_type="MATERIAL_TASK_CHECKPOINT_INHERITED",
                    prior_state=None,
                    task=task,
                )
            read_material_task_histories(session, clones)
            authorize_material_learning(session, command.actor_id)
            return self._result(
                source, successor, intake.material_id, prepared, len(tasks), replayed=False
            )

    @staticmethod
    def _task_id(run_id: str, predecessor_task_id: str) -> str:
        return "materialtask_" + uuid5(NAMESPACE_URL, f"{run_id}:{predecessor_task_id}").hex

    def _require_successor(
        self,
        session: Session,
        source: MaterialLearningRunRecord,
        successor: MaterialLearningRunRecord,
        tasks: tuple[MaterialLearningTaskRecord, ...],
        prepared: MaterialArtifactMember,
    ) -> None:
        if (
            successor.predecessor_run_id != source.run_id
            or successor.material_revision_id != source.material_revision_id
            or successor.created_by != source.created_by
            or successor.attempt != source.attempt + 1
            or (
                successor.prepared_artifact_id,
                successor.prepared_artifact_revision_id,
                successor.prepared_sha256,
            )
            != (prepared.artifact_id, prepared.artifact_revision_id, prepared.sha256)
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_SUCCESSOR_INVALID")
        ids = tuple(self._task_id(successor.run_id, task.task_id) for task in tasks)
        clones = {
            task.task_id: task
            for task in session.scalars(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.task_id.in_(ids)
                )
            )
        }
        if len(clones) != len(tasks):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_SUCCESSOR_INVALID")
        for original, identity in zip(tasks, ids, strict=True):
            clone = clones[identity]
            fields = ("task_kind", "unit_key", "ordinal", *_PINS)
            if (
                clone.run_id != successor.run_id
                or clone.predecessor_task_id != original.task_id
                or clone.attempt != original.attempt + 1
                or clone.state != "COMPLETED"
                or clone.workflow_id is not None
                or any(getattr(clone, field) != getattr(original, field) for field in fields)
            ):
                raise ValueError("MATERIAL_NATIVE_FINALIZATION_SUCCESSOR_INVALID")

    def _result(
        self,
        source: MaterialLearningRunRecord,
        successor: MaterialLearningRunRecord,
        material_id: str,
        prepared: MaterialArtifactMember,
        reused_tasks: int,
        *,
        replayed: bool,
    ) -> NativeMaterialDiscoveryFinalizationRecoveryResult:
        return NativeMaterialDiscoveryFinalizationRecoveryResult(
            predecessor_run_id=source.run_id,
            run_id=successor.run_id,
            material_id=material_id,
            material_revision_id=source.material_revision_id,
            prepared=prepared,
            source_commit=self.source_commit,
            reused_tasks=reused_tasks,
            state=cast(MaterialRunState, successor.state),
            replayed=replayed,
        )

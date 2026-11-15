"""Selective native discovery retry over accepted, unchanged source checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialLearningRights
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningRetryResult,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    MaterialNativePreparedArtifact,
    require_native_material_checkpoint_chain,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import Engine, select, tuple_
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
from eom_catalog_service.material_learning_coordinator import read_material_discovery_plan
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_recovery import (
    clone_material_retry_task,
    quiescent_material_task_workflows,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import append_material_event
from eom_catalog_service.material_native_discovery import incomplete_native_discovery_tasks
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.material_task_history import (
    MAX_MATERIAL_ATTEMPTS,
    read_material_task_histories,
)
from eom_catalog_service.settings import CatalogSettings

_ERROR = "MATERIAL_NATIVE_DISCOVERY_REGION_INCOMPLETE"
_TASK_FIELDS = (
    "task_id",
    "task_kind",
    "unit_key",
    "ordinal",
    "attempt",
    "predecessor_task_id",
    "state",
    "workflow_id",
    "input_artifact_id",
    "input_artifact_revision_id",
    "input_sha256",
    "output_artifact_id",
    "output_artifact_revision_id",
    "output_sha256",
    "item_revision_id",
    "analysis_run_id",
    "solution_analysis_run_id",
    "graph_snapshot_revision_id",
    "execution_lane",
)
_RESULT_FIELDS = (
    "item_revision_id",
    "analysis_run_id",
    "solution_analysis_run_id",
    "graph_snapshot_revision_id",
)


def _task_signature(
    tasks: tuple[MaterialLearningTaskRecord, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(tuple(getattr(task, field) for field in _TASK_FIELDS) for task in tasks)


def _artifact_signature(
    session: Session, keys: frozenset[tuple[str, str]]
) -> tuple[tuple[object, ...], ...]:
    """A bounded metadata fence after strict owner reads, not a permission/content cache."""
    rows = session.execute(
        select(ArtifactRecord, ArtifactRevisionRecord)
        .join(
            ArtifactRevisionRecord,
            ArtifactRevisionRecord.logical_artifact_id == ArtifactRecord.logical_artifact_id,
        )
        .where(
            tuple_(ArtifactRecord.logical_artifact_id, ArtifactRevisionRecord.revision_id).in_(
                tuple(sorted(keys))
            )
        )
        .execution_options(populate_existing=True)
    ).all()
    values = {}
    for artifact, revision in rows:
        key = (artifact.logical_artifact_id, revision.revision_id)
        if (
            not artifact.approved
            or not revision.approved
            or revision.manifest_hash != content_sha256(revision.manifest)
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_ARTIFACT_CHANGED")
        values[key] = (
            *key,
            revision.content_hash,
            revision.content_bytes,
            revision.manifest_hash,
            revision.job_id,
            artifact.artifact_type,
            artifact.job_id,
        )
    if set(values) != keys or len(values) != len(rows):
        raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_ARTIFACT_CHANGED")
    return tuple(values[key] for key in sorted(values))


@dataclass(frozen=True, slots=True)
class _DiscoveryRetrySnapshot:
    intake: MaterialNativeLearningIntakeManifest
    intake_pointer: MaterialArtifactMember
    prepared: MaterialArtifactMember
    selected_task_ids: frozenset[str]
    task_signature: tuple[tuple[object, ...], ...]
    artifact_keys: frozenset[tuple[str, str]]
    artifact_signature: tuple[tuple[object, ...], ...]


class NativeMaterialDiscoveryReanalysisService:
    def __init__(self, engine: Engine, settings: CatalogSettings) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, settings)
        self.sources = MaterialLearningSourceService(engine, settings)

    @staticmethod
    def _source(
        session: Session, command: RetryMaterialLearningRunCommand
    ) -> tuple[MaterialLearningRunRecord, LearningMaterialRevisionRecord]:
        authorize_material_learning(session, command.actor_id)
        source = session.get(MaterialLearningRunRecord, command.run_id, populate_existing=True)
        revision = (
            session.get(
                LearningMaterialRevisionRecord, source.material_revision_id, populate_existing=True
            )
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
            or any(value.created_by != command.actor_id for value in (source, revision, material))
            or material.lifecycle_state != "ACTIVE"
            or material.current_revision_id != revision.material_revision_id
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        if source.updated_at != command.expected_updated_at:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_STATE_STALE")
        if source.state != "FAILED" or source.error_code != _ERROR:
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_PHASE_INVALID")
        if source.lease_expires_at is not None and source.lease_expires_at > datetime.now(UTC):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        return source, revision

    @staticmethod
    def _tasks(
        session: Session, source: MaterialLearningRunRecord
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
            or tasks[0].unit_key != "source-preparation"
            or tuple(task.ordinal for task in tasks) != tuple(range(1, len(tasks) + 1))
            or any(
                task.state != "COMPLETED"
                or task.execution_lane != "MATERIAL_LEARNING"
                or (index > 0 and task.task_kind != "DISCOVER")
                or any(getattr(task, field) is not None for field in _RESULT_FIELDS)
                or any(
                    getattr(task, field) is None
                    for field in (
                        "input_artifact_id",
                        "input_artifact_revision_id",
                        "input_sha256",
                        "output_artifact_id",
                        "output_artifact_revision_id",
                        "output_sha256",
                    )
                )
                for index, task in enumerate(tasks)
            )
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_TASKS_INVALID")
        return tasks

    @staticmethod
    def _owners(
        session: Session, tasks: tuple[MaterialLearningTaskRecord, ...], actor_id: str
    ) -> dict[str, str]:
        histories = read_material_task_histories(session, tasks)
        workflows = quiescent_material_task_workflows(
            session, tuple(row for history in histories.values() for row in history.tasks)
        )
        owners = {}
        for task in tasks[1:]:
            producer = histories[task.task_id].result_task()
            workflow = workflows.get(producer.workflow_id or "")
            if (
                workflow is None
                or workflow.state != "COMPLETED"
                or workflow.created_actor_id != actor_id
                or producer.task_id in owners
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
            owners[producer.task_id] = task.task_id
        return owners

    def _reauthorize(
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
            selected.source_upload.original.sha256 for selected in intake.sources
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RIGHTS_MISMATCH")
        authorize_material_learning(session, actor_id)

    def _capture(
        self, session: Session, command: RetryMaterialLearningRunCommand
    ) -> _DiscoveryRetrySnapshot:
        source, revision = self._source(session, command)
        tasks = self._tasks(session, source)
        owners = self._owners(session, tasks, command.actor_id)
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
        if (
            source.prepared_artifact_id is None
            or source.prepared_artifact_revision_id is None
            or source.prepared_sha256 is None
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_INVALID")
        prepared_pointer = material_prepared_pointer(
            session,
            artifact_id=source.prepared_artifact_id,
            revision_id=source.prepared_artifact_revision_id,
            sha256=source.prepared_sha256,
        )

        def authorize() -> None:
            authorize_material_learning(session, command.actor_id)

        intake = read_material_intake(self.artifacts, intake_pointer, authorize=authorize)
        prepared = read_material_prepared(self.artifacts, prepared_pointer, authorize=authorize)
        preparation_task = tasks[0]
        assert preparation_task.input_artifact_id is not None
        assert (
            preparation_task.input_artifact_revision_id is not None
            and preparation_task.input_sha256 is not None
        )
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
            or (intake.requested_by, intake.material_id, intake.material_revision_id)
            != (command.actor_id, revision.material_id, source.material_revision_id)
            or preparation.profile.profile_sha256 != prepared.profile_sha256
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_INVALID")
        require_native_material_checkpoint_chain(
            intake, preparation=preparation, prepared=prepared, intake_pointer=intake_pointer
        )
        history = read_material_task_histories(session, (preparation_task,))[
            preparation_task.task_id
        ]
        if not any(
            row.task_id == preparation.task_id
            and (row.input_artifact_id, row.input_artifact_revision_id, row.input_sha256)
            == (
                preparation_pointer.artifact_id,
                preparation_pointer.artifact_revision_id,
                preparation_pointer.sha256,
            )
            for row in history.tasks
        ):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_INVALID")
        bundle = read_material_native_bundle(
            self.artifacts,
            intake.native_bundle,
            sources=intake.sources,
            operator_id=command.actor_id,
            authorize=authorize,
        )
        plan = read_material_discovery_plan(
            session, self.artifacts, run_id=source.run_id, operator_id=command.actor_id
        )
        selected = incomplete_native_discovery_tasks(plan, bundle)
        if not selected.issubset(owners):
            raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_OWNER_INVALID")
        keys = {
            (pointer.artifact_id, pointer.artifact_revision_id)
            for pointer in (
                intake_pointer,
                prepared_pointer,
                preparation_pointer,
                intake.native_bundle,
                intake.rights_attestation,
                bundle.workbook.workbook,
                bundle.workbook.parsed_workbook,
                *(
                    pointer
                    for selected_source in intake.sources
                    for pointer in (
                        selected_source.source_upload.manifest,
                        selected_source.source_upload.original,
                    )
                ),
            )
        }
        keys.update(
            (
                getattr(task, prefix + "_artifact_id"),
                getattr(task, prefix + "_artifact_revision_id"),
            )
            for task in tasks
            for prefix in ("input", "output")
        )
        self._reauthorize(session, intake, command.actor_id)
        frozen_keys = frozenset(keys)
        return _DiscoveryRetrySnapshot(
            intake,
            intake_pointer,
            prepared_pointer,
            frozenset(owners[task_id] for task_id in selected),
            _task_signature(tasks),
            frozen_keys,
            _artifact_signature(session, frozen_keys),
        )

    def try_retry(
        self, command: RetryMaterialLearningRunCommand
    ) -> MaterialLearningRetryResult | None:
        command = RetryMaterialLearningRunCommand.model_validate(command.model_dump(mode="json"))
        with self.sessions() as session:
            authorize_material_learning(session, command.actor_id)
            source = session.get(MaterialLearningRunRecord, command.run_id)
            if (
                source is None
                or source.created_by != command.actor_id
                or source.error_code != _ERROR
            ):
                return None
            snapshot = self._capture(session, command)
        identity = (
            "materialrun_"
            + uuid5(
                NAMESPACE_URL,
                "eom:native-discovery-reanalysis:"
                + content_sha256(command.model_dump(mode="json")),
            ).hex
        )
        with self.sessions.begin() as session:
            session.scalar(
                select(LearningMaterialRevisionRecord)
                .where(
                    LearningMaterialRevisionRecord.material_revision_id
                    == snapshot.intake.material_revision_id
                )
                .with_for_update()
            )
            session.scalar(
                select(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.run_id == command.run_id)
                .with_for_update()
            )
            source, revision = self._source(session, command)
            tasks = self._tasks(session, source)
            self._owners(session, tasks, command.actor_id)
            if (
                _task_signature(tasks) != snapshot.task_signature
                or material_intake_pointer(
                    session,
                    artifact_id=revision.manifest_artifact_id,
                    revision_id=revision.manifest_artifact_revision_id,
                    sha256=revision.manifest_sha256,
                )
                != snapshot.intake_pointer
                or (
                    source.prepared_artifact_id,
                    source.prepared_artifact_revision_id,
                    source.prepared_sha256,
                )
                != (
                    snapshot.prepared.artifact_id,
                    snapshot.prepared.artifact_revision_id,
                    snapshot.prepared.sha256,
                )
                or _artifact_signature(session, snapshot.artifact_keys)
                != snapshot.artifact_signature
            ):
                raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_CHANGED")
            self._reauthorize(session, snapshot.intake, command.actor_id)
            existing = session.get(MaterialLearningRunRecord, identity)
            if existing is not None:
                if (
                    existing.predecessor_run_id,
                    existing.material_revision_id,
                    existing.created_by,
                    existing.attempt,
                    existing.prepared_artifact_id,
                    existing.prepared_artifact_revision_id,
                    existing.prepared_sha256,
                ) != (
                    source.run_id,
                    source.material_revision_id,
                    source.created_by,
                    source.attempt + 1,
                    source.prepared_artifact_id,
                    source.prepared_artifact_revision_id,
                    source.prepared_sha256,
                ):
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
                self._require_replay_tasks(session, existing, tasks, snapshot)
                return self._result(source, existing, tasks, snapshot, replayed=True)
            if source.attempt >= MAX_MATERIAL_ATTEMPTS or session.scalar(
                select(MaterialLearningRunRecord.run_id)
                .where(
                    MaterialLearningRunRecord.material_revision_id == source.material_revision_id,
                    MaterialLearningRunRecord.attempt > source.attempt,
                )
                .limit(1)
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
            now = datetime.now(UTC)
            successor = MaterialLearningRunRecord(
                run_id=identity,
                material_revision_id=source.material_revision_id,
                attempt=source.attempt + 1,
                predecessor_run_id=source.run_id,
                state="DISCOVERING",
                next_event_sequence=1,
                created_by=source.created_by,
                prepared_artifact_id=source.prepared_artifact_id,
                prepared_artifact_revision_id=source.prepared_artifact_revision_id,
                prepared_sha256=source.prepared_sha256,
                created_at=now,
                updated_at=now,
            )
            session.add(successor)
            session.flush()
            append_material_event(
                session, successor, event_type="MATERIAL_RETRY_STARTED", prior_state=None
            )
            copies = []
            for task in tasks:
                clone = clone_material_retry_task(
                    task,
                    run_id=identity,
                    now=now,
                    checkpoint_state="PENDING"
                    if task.task_id in snapshot.selected_task_ids
                    else None,
                )
                copies.append(clone)
            session.add_all(copies)
            session.flush()
            for clone in copies:
                append_material_event(
                    session,
                    successor,
                    task=clone,
                    prior_state=None,
                    event_type="MATERIAL_TASK_RETRY_CREATED"
                    if clone.state == "PENDING"
                    else "MATERIAL_TASK_CHECKPOINT_INHERITED",
                )
            session.flush()
            authorize_material_learning(session, command.actor_id)
            if _artifact_signature(session, snapshot.artifact_keys) != snapshot.artifact_signature:
                raise MaterialLearningSourceError("MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_CHANGED")
            return self._result(source, successor, tasks, snapshot, replayed=False)

    @staticmethod
    def _require_replay_tasks(
        session: Session,
        successor: MaterialLearningRunRecord,
        tasks: tuple[MaterialLearningTaskRecord, ...],
        snapshot: _DiscoveryRetrySnapshot,
    ) -> None:
        rows = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(
                    MaterialLearningTaskRecord.run_id == successor.run_id,
                    MaterialLearningTaskRecord.ordinal <= len(tasks),
                )
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        if len(rows) != len(tasks):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
        for original, actual in zip(tasks, rows, strict=True):
            expected = clone_material_retry_task(
                original,
                run_id=successor.run_id,
                now=successor.created_at,
                checkpoint_state="PENDING"
                if original.task_id in snapshot.selected_task_ids
                else None,
            )
            if any(
                getattr(expected, field) != getattr(actual, field)
                for field in (
                    "task_id",
                    "task_kind",
                    "unit_key",
                    "ordinal",
                    "attempt",
                    "predecessor_task_id",
                    "execution_lane",
                )
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
            if original.task_id not in snapshot.selected_task_ids:
                if any(
                    getattr(expected, field) != getattr(actual, field) for field in _TASK_FIELDS
                ):
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
            elif any(
                getattr(actual, field) is not None
                and getattr(actual, field) == getattr(original, field)
                for field in ("input_artifact_revision_id", "output_artifact_revision_id")
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")

    @staticmethod
    def _result(
        source: MaterialLearningRunRecord,
        successor: MaterialLearningRunRecord,
        tasks: tuple[MaterialLearningTaskRecord, ...],
        snapshot: _DiscoveryRetrySnapshot,
        *,
        replayed: bool,
    ) -> MaterialLearningRetryResult:
        return MaterialLearningRetryResult.model_validate(
            {
                "predecessor_run_id": source.run_id,
                "run_id": successor.run_id,
                "state": successor.state,
                "reused_tasks": len(tasks) - len(snapshot.selected_task_ids),
                "retried_tasks": len(snapshot.selected_task_ids),
                "replayed": replayed,
            }
        )

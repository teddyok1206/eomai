"""Explicit quiescent preparation successor through existing Catalog owners."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialLearningRights,
    SourceRole,
)
from eom_catalog_contracts.material_learning_intake import MaterialRunState
from eom_catalog_contracts.material_learning_preparation import MaterialPreparationProfile
from eom_catalog_contracts.material_native_intake import (
    MaterialIntake,
    MaterialNativePreparationInput,
    MaterialPreparation,
    require_native_material_checkpoint_chain,
)
from eom_catalog_contracts.material_preparation_recovery import (
    MaterialPreparationRecoveryResult,
    RecoverMaterialPreparationCommand,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import JobRecord
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService, normalize_catalog_idempotency_key
from eom_catalog_service.educational_material_registration import material_document_identity
from eom_catalog_service.material_intake_read import (
    material_intake_pointer,
    material_preparation_pointer,
    read_material_intake,
    read_material_preparation,
)
from eom_catalog_service.material_learning_artifacts import (
    publish_material_metadata,
    read_material_metadata,
)
from eom_catalog_service.material_learning_coordinator import build_material_preparation_input
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
from eom_catalog_service.material_learning_store import (
    append_material_event,
    transition_material_run,
    transition_material_task,
)
from eom_catalog_service.material_task_history import MAX_MATERIAL_ATTEMPTS
from eom_catalog_service.models import EducationalDocumentRevisionRecord
from eom_catalog_service.settings import CatalogSettings


class MaterialPreparationDrain(Protocol):
    def require_quiescent(self) -> None: ...


class MaterialPreparationRecoveryService:
    """One preparation-only use case, not a general retry or administrative override."""

    def __init__(
        self,
        engine: Engine,
        *,
        settings: CatalogSettings,
        target_profile: MaterialPreparationProfile,
        drain: MaterialPreparationDrain,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.artifacts = CatalogArtifactService(engine, settings)
        self.sources = MaterialLearningSourceService(engine, settings)
        self.profile = MaterialPreparationProfile.model_validate(
            target_profile.model_dump(mode="json")
        )
        self.drain = drain

    def _rows(
        self, session: Session, command: RecoverMaterialPreparationCommand
    ) -> tuple[
        MaterialLearningRunRecord, LearningMaterialRevisionRecord, MaterialLearningTaskRecord
    ]:
        authorize_material_learning(session, command.actor_id)
        observed = session.get(MaterialLearningRunRecord, command.run_id)
        if observed is None or observed.created_by != command.actor_id:
            raise ValueError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        revision = session.scalar(
            select(LearningMaterialRevisionRecord)
            .where(
                LearningMaterialRevisionRecord.material_revision_id == observed.material_revision_id
            )
            .with_for_update()
        )
        source = session.scalar(
            select(MaterialLearningRunRecord)
            .where(MaterialLearningRunRecord.run_id == command.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        material = session.get(LearningMaterialRecord, revision.material_id) if revision else None
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
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == source.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        if (
            len(tasks) != 1
            or tasks[0].task_kind != "PREPARE"
            or tasks[0].unit_key != "source-preparation"
            or tasks[0].ordinal != 1
        ):
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_PHASE_INVALID")
        return source, revision, tasks[0]

    def _work(
        self,
        session: Session,
        command: RecoverMaterialPreparationCommand,
        revision: LearningMaterialRevisionRecord,
        task: MaterialLearningTaskRecord,
    ) -> tuple[MaterialIntake, MaterialArtifactMember, MaterialArtifactMember, MaterialPreparation]:
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
        if (
            task.input_artifact_id is None
            or task.input_artifact_revision_id is None
            or task.input_sha256 is None
        ):
            raise ValueError("MATERIAL_LEARNING_CHECKPOINT_MISSING")
        pointer = material_preparation_pointer(
            session,
            artifact_id=task.input_artifact_id,
            revision_id=task.input_artifact_revision_id,
            sha256=task.input_sha256,
        )

        def authorize() -> None:
            authorize_material_learning(session, command.actor_id)

        intake = read_material_intake(self.artifacts, intake_pointer, authorize=authorize)
        work = read_material_preparation(self.artifacts, pointer, authorize=authorize)
        require_native_material_checkpoint_chain(
            intake, preparation=work, intake_pointer=intake_pointer
        )
        for selected in intake.sources:
            self.sources.resolve(selected.source_upload, operator_id=command.actor_id)
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
            command.actor_id,
        ) or rights.source_hashes != tuple(
            selected.source_upload.original.sha256 for selected in intake.sources
        ):
            raise ValueError("MATERIAL_LEARNING_RIGHTS_MISMATCH")
        authorize()
        if (
            pointer.sha256 != command.expected_input_sha256
            or intake.requested_by != command.actor_id
            or work.task_id != task.task_id
            or work.material_id != revision.material_id
            or work.material_revision_id != revision.material_revision_id
            or work.profile.profile_sha256 == self.profile.profile_sha256
        ):
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_INPUT_MISMATCH")
        return intake, intake_pointer, pointer, work

    @staticmethod
    def _eligible(
        session: Session,
        command: RecoverMaterialPreparationCommand,
        source: MaterialLearningRunRecord,
        task: MaterialLearningTaskRecord,
    ) -> None:
        now = datetime.now(UTC)
        if source.updated_at != command.expected_updated_at:
            raise ValueError("MATERIAL_LEARNING_STATE_STALE")
        if (
            source.state not in {"PREPARING", "FAILED"}
            or task.state not in {"PREPARING", "FAILED"}
            or any(
                getattr(source, name) is not None
                for name in (
                    "prepared_artifact_id",
                    "prepared_artifact_revision_id",
                    "prepared_sha256",
                )
            )
            or any(
                getattr(task, name) is not None
                for name in (
                    "output_artifact_id",
                    "output_artifact_revision_id",
                    "output_sha256",
                    "workflow_id",
                    "analysis_run_id",
                    "solution_analysis_run_id",
                    "item_revision_id",
                    "graph_snapshot_revision_id",
                )
            )
        ):
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_PHASE_INVALID")
        if (source.state == "FAILED" and source.error_code != command.error_code) or (
            task.state == "FAILED" and task.error_code != command.error_code
        ):
            raise ValueError("MATERIAL_PREPARATION_FAILED_HISTORY_MISMATCH")
        if source.lease_expires_at is not None and source.lease_expires_at > now:
            raise ValueError("MATERIAL_PREPARATION_LIVE_LEASE")
        if source.attempt >= MAX_MATERIAL_ATTEMPTS or task.attempt != source.attempt:
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_ATTEMPT_INVALID")
        if session.scalar(
            select(MaterialLearningRunRecord.run_id)
            .where(
                MaterialLearningRunRecord.material_revision_id == source.material_revision_id,
                MaterialLearningRunRecord.attempt > source.attempt,
            )
            .limit(1)
        ):
            raise ValueError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
        # MAIN may already have been registered before SOLUTIONS preparation failed.
        # Reusing its deterministic document identity with a new profile is not safe.
        roles: tuple[SourceRole, ...] = ("MAIN", "SOLUTIONS")
        documents = tuple(
            material_document_identity(source.material_revision_id, role)[1] for role in roles
        )
        if session.scalar(
            select(EducationalDocumentRevisionRecord.document_revision_id)
            .where(EducationalDocumentRevisionRecord.document_revision_id.in_(documents))
            .limit(1)
        ):
            raise ValueError("MATERIAL_PREPARATION_PARTIAL_PUBLICATION_REQUIRES_REVIEW")
        if session.scalar(
            select(JobRecord.job_id)
            .where(
                JobRecord.idempotency_key.in_(
                    tuple(
                        normalize_catalog_idempotency_key("material-document:" + identity)
                        for identity in documents
                    )
                )
            )
            .limit(1)
        ):
            raise ValueError("MATERIAL_PREPARATION_PARTIAL_PUBLICATION_REQUIRES_REVIEW")

    def _result(
        self,
        session: Session,
        source: MaterialLearningRunRecord,
        revision: LearningMaterialRevisionRecord,
        old_task: MaterialLearningTaskRecord,
        old_pointer: MaterialArtifactMember,
        old_work: MaterialPreparation,
        successor: MaterialLearningRunRecord,
        task_id: str,
        *,
        replayed: bool,
    ) -> MaterialPreparationRecoveryResult:
        new_task = session.get(MaterialLearningTaskRecord, task_id)
        if (
            source.state != "FAILED"
            or old_task.state != "FAILED"
            or successor.predecessor_run_id != source.run_id
            or successor.created_by != source.created_by
            or successor.material_revision_id != source.material_revision_id
            or successor.attempt != source.attempt + 1
            or new_task is None
            or new_task.run_id != successor.run_id
            or new_task.predecessor_task_id != old_task.task_id
            or new_task.attempt != old_task.attempt + 1
            or new_task.task_kind != "PREPARE"
            or new_task.ordinal != 1
            or new_task.unit_key != old_task.unit_key
        ):
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_REPLAY_INVALID")
        if (
            new_task.input_artifact_id is None
            or new_task.input_artifact_revision_id is None
            or new_task.input_sha256 is None
        ):
            raise ValueError("MATERIAL_LEARNING_CHECKPOINT_MISSING")
        new_pointer = material_preparation_pointer(
            session,
            artifact_id=new_task.input_artifact_id,
            revision_id=new_task.input_artifact_revision_id,
            sha256=new_task.input_sha256,
        )
        new_work = read_material_preparation(
            self.artifacts,
            new_pointer,
            authorize=lambda: authorize_material_learning(session, source.created_by),
        )
        expected = build_material_preparation_input(
            read_material_intake(
                self.artifacts,
                old_work.intake_manifest,
                authorize=lambda: authorize_material_learning(session, source.created_by),
            ),
            intake_pointer=old_work.intake_manifest,
            task_id=task_id,
            profile=self.profile,
        )
        if new_work != expected:
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_REPLAY_INVALID")
        return MaterialPreparationRecoveryResult(
            predecessor_run_id=source.run_id,
            run_id=successor.run_id,
            predecessor_task_id=old_task.task_id,
            task_id=task_id,
            material_id=revision.material_id,
            material_revision_id=source.material_revision_id,
            old_input=old_pointer,
            new_input=new_pointer,
            old_profile_sha256=old_work.profile.profile_sha256,
            new_profile_sha256=self.profile.profile_sha256,
            state=cast(MaterialRunState, successor.state),
            replayed=replayed,
        )

    def recover(
        self, command: RecoverMaterialPreparationCommand
    ) -> MaterialPreparationRecoveryResult:
        command = RecoverMaterialPreparationCommand.model_validate(command.model_dump(mode="json"))
        if command.target_profile_sha256 != self.profile.profile_sha256:
            raise ValueError("MATERIAL_PREPARATION_TARGET_PROFILE_MISMATCH")
        identity = (
            "materialrun_"
            + uuid5(
                NAMESPACE_URL,
                "eom:material-preparation-recovery:"
                + content_sha256(command.model_dump(mode="json")),
            ).hex
        )
        with self.sessions.begin() as session:
            source, revision, task = self._rows(session, command)
            intake, intake_pointer, old_pointer, old_work = self._work(
                session, command, revision, task
            )
            task_id = "materialtask_" + uuid5(NAMESPACE_URL, f"{identity}:{task.task_id}").hex
            successor = session.get(MaterialLearningRunRecord, identity)
            if successor is not None:
                return self._result(
                    session,
                    source,
                    revision,
                    task,
                    old_pointer,
                    old_work,
                    successor,
                    task_id,
                    replayed=True,
                )
            self.drain.require_quiescent()
            self._eligible(session, command, source, task)
        work = build_material_preparation_input(
            intake, intake_pointer=intake_pointer, task_id=task_id, profile=self.profile
        )
        pointer = publish_material_metadata(
            self.artifacts,
            self.settings,
            work,
            member_path="material/preparation-input.json",
            schema_ref="eom://schemas/material-learning/preparation-input/2.0"
            if isinstance(work, MaterialNativePreparationInput)
            else "eom://schemas/material-learning/preparation-input/1.0",
            artifact_type="material-learning-preparation-input",
            idempotency_key="material-prepare-input:" + task_id,
        )
        with self.sessions.begin() as session:
            source, revision, task = self._rows(session, command)
            _, _, current_pointer, current_work = self._work(session, command, revision, task)
            if current_pointer != old_pointer or current_work != old_work:
                raise ValueError("MATERIAL_PREPARATION_RECOVERY_INPUT_MISMATCH")
            successor = session.get(MaterialLearningRunRecord, identity)
            if successor is not None:
                return self._result(
                    session,
                    source,
                    revision,
                    task,
                    old_pointer,
                    old_work,
                    successor,
                    task_id,
                    replayed=True,
                )
            self.drain.require_quiescent()
            self._eligible(session, command, source, task)
            now = datetime.now(UTC)
            if task.state != "FAILED":
                transition_material_task(
                    session,
                    source,
                    task,
                    MaterialTaskState.FAILED,
                    now=now,
                    error_code=command.error_code,
                )
            if source.state != "FAILED":
                transition_material_run(
                    session,
                    source,
                    MaterialLearningState.FAILED,
                    now=now,
                    error_code=command.error_code,
                )
            session.flush()
            successor = MaterialLearningRunRecord(
                run_id=identity,
                material_revision_id=source.material_revision_id,
                attempt=source.attempt + 1,
                predecessor_run_id=source.run_id,
                state="RECEIVED",
                next_event_sequence=1,
                created_by=source.created_by,
                created_at=now,
                updated_at=now,
            )
            session.add(successor)
            session.flush()
            append_material_event(
                session,
                successor,
                event_type="MATERIAL_PREPARATION_RECOVERY_STARTED",
                prior_state=None,
            )
            new_task = MaterialLearningTaskRecord(
                task_id=task_id,
                run_id=identity,
                task_kind="PREPARE",
                unit_key=task.unit_key,
                ordinal=task.ordinal,
                attempt=task.attempt + 1,
                predecessor_task_id=task.task_id,
                state="PENDING",
                execution_lane="MATERIAL_LEARNING",
                input_artifact_id=pointer.artifact_id,
                input_artifact_revision_id=pointer.artifact_revision_id,
                input_sha256=pointer.sha256,
                created_at=now,
                updated_at=now,
            )
            session.add(new_task)
            session.flush()
            append_material_event(
                session,
                successor,
                event_type="MATERIAL_PREPARATION_INPUT_SUCCESSOR_CREATED",
                prior_state=None,
                task=new_task,
            )
            authorize_material_learning(session, command.actor_id)
            return self._result(
                session,
                source,
                revision,
                task,
                old_pointer,
                old_work,
                successor,
                task_id,
                replayed=False,
            )

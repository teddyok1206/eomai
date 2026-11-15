"""Selective source-score re-extraction using existing linked tasks and publishers.

No source row/result is repaired in place. One small proof per selected question
is resolved by the existing indexed publication owner; models cannot select it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.assessment_item import AssessmentItemContent, AssessmentItemContentV1_1
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialExtractionResult,
    MaterialExtractionWork,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningRetryResult
from eom_catalog_contracts.material_native_item_read import MaterialNativeItemReadRequest
from eom_catalog_contracts.material_native_score_reanalysis import (
    NATIVE_SCORE_REANALYSIS_ARTIFACT,
    NATIVE_SCORE_REANALYSIS_EVENT,
    NATIVE_SCORE_REANALYSIS_MEMBER,
    NATIVE_SCORE_REANALYSIS_REF,
    NativeScorePriorItem,
    NativeScoreReanalysisTarget,
    ReanalyzeNativeMaterialScoresCommand,
    native_score_reanalysis_run_id,
    native_score_reanalysis_target_key,
)
from eom_catalog_contracts.source_score import PrintedSourceScoreV2, source_score_decimal
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.models import MaterialLearningRoleResultV3
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_intake_read import material_prepared_pointer
from eom_catalog_service.material_learning_artifacts import (
    find_material_publication,
    pin_material_primary,
    read_material_metadata,
)
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_recovery import (
    clone_material_retry_task,
    quiescent_material_task_workflows,
)
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_learning_store import append_material_event
from eom_catalog_service.material_native_item_read import MaterialNativeItemReadService
from eom_catalog_service.material_native_item_registration import (
    resolve_native_material_registration_binding,
)
from eom_catalog_service.material_native_score import (
    expected_native_source_score,
    read_native_question_score,
)
from eom_catalog_service.material_task_history import (
    MAX_MATERIAL_ATTEMPTS,
    read_material_task_histories,
)
from eom_catalog_service.material_task_results import (
    ResolvedMaterialTask,
    resolve_completed_material_task,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings

_TARGET_EVENT = "MATERIAL_NATIVE_SCORE_TARGET_CREATED"
_TASK_FIELDS = (
    "task_id",
    "task_kind",
    "unit_key",
    "ordinal",
    "attempt",
    "predecessor_task_id",
    "state",
    "error_code",
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


def native_score_task_checkpoint_sha256(tasks: tuple[MaterialLearningTaskRecord, ...]) -> str:
    return content_sha256([tuple(getattr(row, field) for field in _TASK_FIELDS) for row in tasks])


@dataclass(frozen=True, slots=True)
class ResolvedNativeScoreTarget:
    target: NativeScoreReanalysisTarget
    evidence: MaterialArtifactMember


@dataclass(frozen=True, slots=True)
class _ScoreSnapshot:
    targets: tuple[NativeScoreReanalysisTarget, ...]
    tasks_sha256: str
    prepared: MaterialArtifactMember


class NativeMaterialScoreReanalysisService:
    """Source/Registry fidelity repair, not ordinary retry or runtime activation."""

    def __init__(
        self,
        engine: Engine,
        *,
        publisher: ControlFileSetPublisher,
        source_commit: str,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.sources = CatalogMaterialLearningSourceAuthorizer(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)
        self.native_reads = MaterialNativeItemReadService(engine, self.settings)
        self.publisher, self.source_commit = publisher, source_commit

    @staticmethod
    def _source(
        session: Session,
        command: ReanalyzeNativeMaterialScoresCommand,
    ) -> tuple[MaterialLearningRunRecord, LearningMaterialRevisionRecord]:
        authorize_material_learning(session, command.actor_id)
        run = session.get(MaterialLearningRunRecord, command.run_id, populate_existing=True)
        revision = (
            session.get(LearningMaterialRevisionRecord, run.material_revision_id) if run else None
        )
        material = session.get(LearningMaterialRecord, revision.material_id) if revision else None
        if (
            run is None
            or revision is None
            or material is None
            or any(row.created_by != command.actor_id for row in (run, revision, material))
            or material.lifecycle_state != "ACTIVE"
            or material.current_revision_id != revision.material_revision_id
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SOURCE_INVALID")
        if run.updated_at != command.expected_updated_at:
            raise ValueError("MATERIAL_LEARNING_STATE_STALE")
        if run.state not in {"COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED"}:
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_PHASE_INVALID")
        if run.lease_expires_at is not None and run.lease_expires_at > datetime.now(UTC):
            raise ValueError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        return run, revision

    @staticmethod
    def _tasks(
        session: Session, run: MaterialLearningRunRecord
    ) -> tuple[MaterialLearningTaskRecord, ...]:
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
                .limit(2002)
            )
        )
        if not 2 <= len(tasks) <= 2001 or any(
            row.state not in {"COMPLETED", "FAILED", "EXCEPTION", "CANCELLED"}
            or row.execution_lane != "MATERIAL_LEARNING"
            for row in tasks
        ):
            raise ValueError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        if tuple(row.ordinal for row in tasks) != tuple(range(1, len(tasks) + 1)):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_TASKS_INVALID")
        histories = read_material_task_histories(session, tasks)
        workflows = quiescent_material_task_workflows(
            session, tuple(row for history in histories.values() for row in history.tasks)
        )
        if any(row.created_actor_id != run.created_by for row in workflows.values()):
            raise ValueError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        return tasks

    def _prior_item(
        self,
        session: Session,
        task: MaterialLearningTaskRecord,
        resolved: ResolvedMaterialTask,
        question: MaterialArtifactMember,
    ) -> NativeScorePriorItem | None:
        if task.item_revision_id is None:
            return None
        original = session.get(ItemRevisionRecord, task.item_revision_id)
        item = session.get(ItemRecord, original.item_id) if original else None
        # This explicit preparation-time current reference is frozen below. A later
        # change must fail CAS, never resolve a different latest at registration.
        current = (
            session.get(ItemRevisionRecord, item.current_revision_id)
            if item and item.current_revision_id
            else None
        )
        if (
            current is None
            or item is None
            or item.lifecycle_state != "ACTIVE"
            or current.revision_state != "APPROVED"
            or current.created_by != resolved.operator_id
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_STALE")
        source = self.native_reads.read_source(
            MaterialNativeItemReadRequest(
                operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
                actor_id=resolved.operator_id,
                item_revision_id=current.item_revision_id,
                item_manifest_sha256=current.manifest_sha256,
            )
        )
        if (
            source.question != question
            or source.metadata.material_revision_id != resolved.work.material_revision_id
            or source.metadata.unit_key != resolved.unit_key
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_SOURCE_MISMATCH")
        component = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == current.item_revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
                ItemComponentRecord.ordinal == 0,
            )
        )
        canonical = self.registry.load_item_content(current.item_revision_id)
        if (
            not isinstance(canonical, (AssessmentItemContent, AssessmentItemContentV1_1))
            or component is None
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_CONTENT_INVALID")
        if component.sha256 != content_sha256(canonical.model_dump(mode="json")):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_CONTENT_INVALID")
        return NativeScorePriorItem(
            item_id=current.item_id,
            item_revision_id=current.item_revision_id,
            manifest_sha256=current.manifest_sha256,
            points=canonical.score.points,
            content=ArtifactMemberPointer(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path=component.logical_name,
                schema_ref=component.schema_ref,
                media_type=component.media_type,
                sha256=component.sha256,
            ),
        )

    def _capture(
        self,
        session: Session,
        command: ReanalyzeNativeMaterialScoresCommand,
    ) -> _ScoreSnapshot:
        source, revision = self._source(session, command)
        tasks = self._tasks(session, source)
        if (
            not source.prepared_artifact_id
            or not source.prepared_artifact_revision_id
            or not source.prepared_sha256
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_PREPARED_REQUIRED")
        prepared = material_prepared_pointer(
            session,
            artifact_id=source.prepared_artifact_id,
            revision_id=source.prepared_artifact_revision_id,
            sha256=source.prepared_sha256,
        )
        checksum = native_score_task_checkpoint_sha256(tasks)
        targets = []
        for task in tasks:
            if task.task_kind != "QUESTION" or task.state == "CANCELLED":
                continue
            if task.item_revision_id is None and task.error_code not in {
                "MATERIAL_ITEM_SOURCE_UNREADABLE",
                "MATERIAL_NATIVE_SCORE_REANALYSIS_REQUIRED",
            }:
                # Independent execution/analysis failures retain ordinary recovery.
                continue
            resolved = resolve_completed_material_task(
                session,
                self.artifacts,
                task_id=task.task_id,
                operator_id=command.actor_id,
            )
            if not isinstance(resolved.work, MaterialExtractionWork):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_QUESTION_REQUIRED")
            if isinstance(resolved.role, MaterialLearningRoleResultV3):
                continue  # Existing supported results are not reinterpreted as legacy repairs.
            authorize = self._authorize_work(session, resolved)
            binding = resolve_native_material_registration_binding(
                session,
                self.artifacts,
                resolved,
                authorize=authorize,
            )
            if binding is None:
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_NATIVE_REQUIRED")
            expected = expected_native_source_score(
                read_native_question_score(
                    self.artifacts,
                    binding.question,
                    authorize=authorize,
                )
            )
            prior = self._prior_item(session, task, resolved, binding.question.document)
            if prior is not None:
                if source_score_decimal(
                    PrintedSourceScoreV2(state="PRINTED", points=prior.points)
                ) == source_score_decimal(expected):
                    continue
                reason = "REGISTERED_SCORE_MISMATCH"
            elif task.error_code in {
                "MATERIAL_ITEM_SOURCE_UNREADABLE",
                "MATERIAL_NATIVE_SCORE_REANALYSIS_REQUIRED",
            }:
                observation = resolved.role.output.learning_result
                if not isinstance(observation, MaterialExtractionResult):
                    raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_QUESTION_REQUIRED")
                if task.error_code == "MATERIAL_ITEM_SOURCE_UNREADABLE" and (
                    not isinstance(expected.points, str)
                    or observation.proposal is not None
                    or not any(
                        entry.conflict_code == "UNSUPPORTED_STRUCTURE"
                        for entry in observation.conflicts
                    )
                ):
                    continue
                reason = "LEGACY_SCORE_CONTRACT"
            else:
                continue
            body = dict(
                schema_version="material-native-score-reanalysis-target/1.0",
                command=command.model_dump(mode="json"),
                material_id=revision.material_id,
                material_revision_id=source.material_revision_id,
                successor_run_id=native_score_reanalysis_run_id(command),
                prepared=prepared.model_dump(mode="json"),
                source_tasks_sha256=checksum,
                source_task_id=task.task_id,
                unit_key=task.unit_key,
                native_binding_sha256=binding.binding_sha256,
                question=binding.question.document.model_dump(mode="json"),
                expected_score=expected.model_dump(mode="json"),
                source_work=resolved.work_pointer.model_dump(mode="json"),
                source_result=resolved.result_pointer.model_dump(mode="json"),
                prior_item=prior.model_dump(mode="json") if prior else None,
                reason=reason,
            )
            targets.append(
                NativeScoreReanalysisTarget.model_validate(
                    {**body, "target_sha256": content_sha256(body)}
                )
            )
        if not targets:
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_NO_TARGETS")
        return _ScoreSnapshot(tuple(targets), checksum, prepared)

    def _publish(self, target: NativeScoreReanalysisTarget) -> None:
        # A transaction may roll back after publication. Reuse the validated
        # original proof across SDK releases, preserving its original provenance.
        existing = find_material_publication(
            self.publisher,
            idempotency_key=native_score_reanalysis_target_key(
                target.successor_run_id, target.source_task_id
            ),
            artifact_type=NATIVE_SCORE_REANALYSIS_ARTIFACT,
        )
        if existing is not None:
            with self.sessions() as session:
                pointer = pin_material_primary(session, existing).pointer
            original = read_material_metadata(
                self.artifacts,
                pointer,
                NativeScoreReanalysisTarget,
                schema_ref=NATIVE_SCORE_REANALYSIS_REF,
                member_path=NATIVE_SCORE_REANALYSIS_MEMBER,
            )
            if original != target:
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_CHECKPOINT_CHANGED")
            return
        raw = canonical_json_bytes(target.model_dump(mode="json"))
        with TemporaryDirectory(
            prefix="native-score-target.", dir=self.settings.staging_root
        ) as temporary:
            path = Path(temporary) / NATIVE_SCORE_REANALYSIS_MEMBER
            with path.open("xb") as stream:
                stream.write(raw)
            self.publisher.publish_first_observation(
                members=(
                    ControlFileSetMember(
                        NATIVE_SCORE_REANALYSIS_MEMBER,
                        path,
                        sha256_bytes(raw),
                        len(raw),
                        NATIVE_SCORE_REANALYSIS_REF,
                        "application/json",
                    ),
                ),
                primary_file=NATIVE_SCORE_REANALYSIS_MEMBER,
                artifact_type=NATIVE_SCORE_REANALYSIS_ARTIFACT,
                manifest_version=target.schema_version,
                idempotency_key=native_score_reanalysis_target_key(
                    target.successor_run_id, target.source_task_id
                ),
                source_commit=self.source_commit,
            )

    def _authorize_work(
        self, session: Session, resolved: ResolvedMaterialTask
    ) -> Callable[[], None]:
        def authorize() -> None:
            self.sources.reauthorize(session, operator_id=resolved.operator_id, work=resolved.work)

        return authorize

    def reanalyze(
        self, command: ReanalyzeNativeMaterialScoresCommand
    ) -> MaterialLearningRetryResult:
        command = ReanalyzeNativeMaterialScoresCommand.model_validate(
            command.model_dump(mode="json")
        )
        identity = native_score_reanalysis_run_id(command)
        with self.sessions() as session:
            source, _ = self._source(session, command)
            existing = session.get(MaterialLearningRunRecord, identity)
            if existing is not None:
                return self._reply(session, source, existing, replayed=True)
            snapshot = self._capture(session, command)
        for target in snapshot.targets:
            self._publish(target)
        with self.sessions.begin() as session:
            session.scalar(
                select(LearningMaterialRevisionRecord)
                .where(
                    LearningMaterialRevisionRecord.material_revision_id
                    == snapshot.targets[0].material_revision_id
                )
                .with_for_update()
            )
            session.scalar(
                select(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.run_id == command.run_id)
                .with_for_update()
            )
            source, _ = self._source(session, command)
            tasks = self._tasks(session, source)
            existing = session.get(MaterialLearningRunRecord, identity)
            if existing is not None:
                return self._reply(session, source, existing, replayed=True)
            if native_score_task_checkpoint_sha256(tasks) != snapshot.tasks_sha256 or (
                source.prepared_artifact_id,
                source.prepared_artifact_revision_id,
                source.prepared_sha256,
            ) != (
                snapshot.prepared.artifact_id,
                snapshot.prepared.artifact_revision_id,
                snapshot.prepared.sha256,
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_CHECKPOINT_CHANGED")
            if source.attempt >= MAX_MATERIAL_ATTEMPTS or session.scalar(
                select(MaterialLearningRunRecord.run_id)
                .where(
                    MaterialLearningRunRecord.material_revision_id == source.material_revision_id,
                    MaterialLearningRunRecord.attempt > source.attempt,
                )
                .limit(1)
            ):
                raise ValueError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
            by_task = {target.source_task_id: target for target in snapshot.targets}
            for target in snapshot.targets:
                self.validate_target(session, target, require_current=True)
            now = datetime.now(UTC)
            successor = MaterialLearningRunRecord(
                run_id=identity,
                material_revision_id=source.material_revision_id,
                attempt=source.attempt + 1,
                predecessor_run_id=source.run_id,
                state="PROCESSING",
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
                session, successor, event_type=NATIVE_SCORE_REANALYSIS_EVENT, prior_state=None
            )
            for task in tasks:
                selected = task.task_id in by_task
                clone = clone_material_retry_task(
                    task,
                    run_id=identity,
                    now=now,
                    checkpoint_state="PENDING" if selected else None,
                )
                # Accepted analyses have one child-task owner. Completed tasks
                # resolve those pins through their immutable predecessor history.
                session.add(clone)
                session.flush()
                append_material_event(
                    session,
                    successor,
                    task=clone,
                    prior_state=None,
                    event_type=_TARGET_EVENT if selected else "MATERIAL_TASK_CHECKPOINT_INHERITED",
                )
            authorize_material_learning(session, command.actor_id)
            return self._reply(session, source, successor, replayed=False)

    def _reply(
        self,
        session: Session,
        source: MaterialLearningRunRecord,
        run: MaterialLearningRunRecord,
        *,
        replayed: bool,
    ) -> MaterialLearningRetryResult:
        event = session.scalar(
            select(MaterialLearningEventRecord).where(
                MaterialLearningEventRecord.run_id == run.run_id,
                MaterialLearningEventRecord.sequence == 1,
            )
        )
        if (
            run.predecessor_run_id != source.run_id
            or run.material_revision_id != source.material_revision_id
            or run.created_by != source.created_by
            or run.attempt != source.attempt + 1
            or event is None
            or event.event_type != NATIVE_SCORE_REANALYSIS_EVENT
        ):
            raise ValueError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
        count = (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == run.run_id)
            )
            or 0
        )
        selected = (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningEventRecord)
                .where(
                    MaterialLearningEventRecord.run_id == run.run_id,
                    MaterialLearningEventRecord.event_type == _TARGET_EVENT,
                )
            )
            or 0
        )
        authorize_material_learning(session, run.created_by)
        if not 1 <= selected <= count:
            raise ValueError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
        if replayed:
            selected_ids = tuple(
                session.scalars(
                    select(MaterialLearningEventRecord.task_id).where(
                        MaterialLearningEventRecord.run_id == run.run_id,
                        MaterialLearningEventRecord.event_type == _TARGET_EVENT,
                    )
                )
            )
            if len(selected_ids) != len(set(selected_ids)):
                raise ValueError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
            for task_id in selected_ids:
                if task_id is None:
                    raise ValueError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
                self.registration_target(session, task_id=task_id, operator_id=run.created_by)
        return MaterialLearningRetryResult.model_validate(
            dict(
                predecessor_run_id=source.run_id,
                run_id=run.run_id,
                state=run.state,
                reused_tasks=count - selected,
                retried_tasks=selected,
                replayed=replayed,
            )
        )

    def validate_target(
        self,
        session: Session,
        target: NativeScoreReanalysisTarget,
        *,
        require_current: bool,
    ) -> None:
        target = NativeScoreReanalysisTarget.model_validate(target.model_dump(mode="json"))
        source, _ = self._source(session, target.command)
        task = session.get(
            MaterialLearningTaskRecord, target.source_task_id, populate_existing=True
        )
        if task is None or task.run_id != source.run_id or task.unit_key != target.unit_key:
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SCOPE_INVALID")
        resolved = resolve_completed_material_task(
            session,
            self.artifacts,
            task_id=task.task_id,
            operator_id=target.command.actor_id,
        )
        if (resolved.work_pointer, resolved.result_pointer) != (
            target.source_work,
            target.source_result,
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_CHECKPOINT_CHANGED")
        authorize = self._authorize_work(session, resolved)
        binding = resolve_native_material_registration_binding(
            session, self.artifacts, resolved, authorize=authorize
        )
        if (
            binding is None
            or binding.binding_sha256 != target.native_binding_sha256
            or binding.question.document != target.question
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_NATIVE_CHANGED")
        if (
            expected_native_source_score(
                read_native_question_score(self.artifacts, binding.question, authorize=authorize)
            )
            != target.expected_score
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SCORE_CHANGED")
        prior = target.prior_item
        if prior is not None:
            item = session.get(ItemRecord, prior.item_id, populate_existing=True)
            revision = session.get(
                ItemRevisionRecord, prior.item_revision_id, populate_existing=True
            )
            if (
                item is None
                or item.lifecycle_state != "ACTIVE"
                or revision is None
                or revision.item_id != item.item_id
                or revision.manifest_sha256 != prior.manifest_sha256
                or (
                    require_current
                    and (
                        item.current_revision_id != prior.item_revision_id
                        or revision.revision_state != "APPROVED"
                    )
                )
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_STALE")
            if (
                require_current
                and self._prior_item(session, task, resolved, target.question) != prior
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_STALE")
            if not require_current:
                canonical = self.registry.load_item_content(prior.item_revision_id)
                if (
                    not isinstance(canonical, (AssessmentItemContent, AssessmentItemContentV1_1))
                    or content_sha256(canonical.model_dump(mode="json")) != prior.content.sha256
                    or canonical.score.points != prior.points
                ):
                    raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_STALE")
                native_source = self.native_reads.read_source(
                    MaterialNativeItemReadRequest(
                        operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
                        actor_id=target.command.actor_id,
                        item_revision_id=prior.item_revision_id,
                        item_manifest_sha256=prior.manifest_sha256,
                    )
                )
                if native_source.question != target.question:
                    raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_ITEM_SOURCE_MISMATCH")
            self.artifacts.verify_member(
                artifact_id=prior.content.artifact_id,
                revision_id=prior.content.artifact_revision_id,
                member_path=prior.content.member_path,
                schema_ref=prior.content.schema_ref,
                media_type=prior.content.media_type,
                sha256=prior.content.sha256,
                max_bytes=2 * 1024 * 1024,
            )
        authorize()

    def registration_target(
        self,
        session: Session,
        *,
        task_id: str,
        operator_id: str,
    ) -> ResolvedNativeScoreTarget | None:
        task = session.get(MaterialLearningTaskRecord, task_id, populate_existing=True)
        run = session.get(MaterialLearningRunRecord, task.run_id) if task else None
        if task is None or run is None or run.created_by != operator_id:
            raise ValueError("MATERIAL_LEARNING_TASK_SOURCE_INELIGIBLE")
        event = session.scalar(
            select(MaterialLearningEventRecord).where(
                MaterialLearningEventRecord.run_id == run.run_id,
                MaterialLearningEventRecord.sequence == 1,
            )
        )
        if event is None or event.event_type != NATIVE_SCORE_REANALYSIS_EVENT:
            return None
        if task.predecessor_task_id is None:
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SCOPE_INVALID")
        pointer = find_material_publication(
            self.publisher,
            idempotency_key=native_score_reanalysis_target_key(
                run.run_id, task.predecessor_task_id
            ),
            artifact_type=NATIVE_SCORE_REANALYSIS_ARTIFACT,
        )
        if pointer is None:
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_TARGET_MISSING")
        evidence = pin_material_primary(session, pointer).pointer
        target = read_material_metadata(
            self.artifacts,
            evidence,
            NativeScoreReanalysisTarget,
            schema_ref=NATIVE_SCORE_REANALYSIS_REF,
            member_path=NATIVE_SCORE_REANALYSIS_MEMBER,
            maximum_bytes=64 * 1024,
        )
        if (
            target.command.actor_id != operator_id
            or target.command.run_id != run.predecessor_run_id
            or target.successor_run_id != run.run_id
            or target.source_task_id != task.predecessor_task_id
            or target.material_revision_id != run.material_revision_id
            or target.unit_key != task.unit_key
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SCOPE_INVALID")
        self.validate_target(session, target, require_current=False)
        return ResolvedNativeScoreTarget(target, evidence)

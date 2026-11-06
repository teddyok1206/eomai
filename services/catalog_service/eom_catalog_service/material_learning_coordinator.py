"""Resume one uploaded material through existing preparation and Workflow owners.

The DB queue stores small task pointers. A single in-process immutable discovery
map avoids rereading every completed discovery for each question (O(total units)
per book/restart, O(1) lookup per task). It is not source/execution authority;
every use is reauthorized. Model commands remain with the existing runner.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialDiscoveryResult,
    MaterialDiscoveryWork,
    MaterialExtractionWork,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPreparationInput,
    MaterialPreparationProfile,
    MaterialPreparedArtifact,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.material_learning_plan import (
    DiscoveredMaterialRange,
    MaterialDiscoveryWindow,
    PlannedMaterialUnit,
    material_discovery_windows,
    plan_material_learning_units,
)
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from eom_workflow_runner.material_learning_start import submit_material_learning_workflow
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_claim_renewal import maintain_material_claim
from eom_catalog_service.material_learning_artifacts import (
    publish_material_metadata,
    read_material_metadata,
)
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_learning_store import (
    MaterialRunClaim,
    add_material_task,
    claim_next_material_run,
    lock_material_run,
    next_material_task,
    release_material_claim,
    renew_material_claim,
    transition_material_run,
    transition_material_task,
)
from eom_catalog_service.material_learning_work import MaterialLearningWorkService
from eom_catalog_service.material_task_results import resolve_completed_material_task
from eom_catalog_service.settings import CatalogSettings

_TERMINAL_TASKS = frozenset({"COMPLETED", "FAILED", "EXCEPTION", "CANCELLED"})
_LEASE = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class MaterialCoordinatorProgress:
    run_id: str | None
    task_id: str | None
    phase: str
    workflow_to_drive: str | None = None


@dataclass(frozen=True, slots=True)
class MaterialProcessingContext:
    run_id: str
    operator_id: str
    intake: MaterialLearningIntakeManifest
    prepared: MaterialPreparedArtifact


@dataclass(frozen=True, slots=True)
class MaterialDiscoveryPlan:
    run_id: str
    ranges: tuple[DiscoveredMaterialRange, ...]
    by_unit: Mapping[str, PlannedMaterialUnit]
    by_task: Mapping[str, DiscoveredMaterialRange]


def read_material_discovery_plan(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    run_id: str,
    operator_id: str,
) -> MaterialDiscoveryPlan:
    """The same source/coverage plan for execution and explicit exception lookup."""
    authorize_material_learning(session, operator_id)
    run = session.get(MaterialLearningRunRecord, run_id)
    if run is None or run.created_by != operator_id or run.state == "CANCELLED":
        raise ValueError("MATERIAL_LEARNING_RUN_NOT_FOUND")
    tasks = tuple(
        session.scalars(
            select(MaterialLearningTaskRecord)
            .where(
                MaterialLearningTaskRecord.run_id == run_id,
                MaterialLearningTaskRecord.task_kind == "DISCOVER",
            )
            .order_by(MaterialLearningTaskRecord.ordinal)
        )
    )
    if not tasks or any(task.state != "COMPLETED" for task in tasks):
        raise ValueError("MATERIAL_LEARNING_DISCOVERY_INCOMPLETE")
    ranges = []
    for task in tasks:
        resolved = resolve_completed_material_task(
            session, artifacts, task_id=task.task_id, operator_id=operator_id
        )
        if (
            not isinstance(resolved.work, MaterialDiscoveryWork)
            or not isinstance(resolved.role.output.learning_result, MaterialDiscoveryResult)
            or resolved.work.material_revision_id != run.material_revision_id
        ):
            raise ValueError("MATERIAL_LEARNING_DISCOVERY_TYPE_INVALID")
        ranges.append(DiscoveredMaterialRange(resolved.work, resolved.role.output.learning_result))
    units = plan_material_learning_units(tuple(ranges))
    return MaterialDiscoveryPlan(
        run_id,
        tuple(ranges),
        MappingProxyType({unit.unit_key: unit for unit in units}),
        MappingProxyType({value.work.task_id: value for value in ranges}),
    )


class MaterialLearningCoordinator:
    def __init__(
        self,
        engine: Engine,
        *,
        settings: CatalogSettings,
        preparation: MaterialPagePreparationService,
        profile: MaterialPreparationProfile,
        preset: ExecutionPresetRevision,
        definition_id: str,
        owner_id: str,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings, self.preparation, self.profile = settings, preparation, profile
        self.preset, self.definition_id, self.owner_id = preset, definition_id, owner_id
        self.artifacts = CatalogArtifactService(engine, settings)
        self.authorizer = CatalogMaterialLearningSourceAuthorizer(engine, settings)
        self.work = MaterialLearningWorkService(self.artifacts, settings)
        self._plan: MaterialDiscoveryPlan | None = None
        self._windows: tuple[str, Mapping[str, MaterialDiscoveryWindow]] | None = None

    def claim(self) -> MaterialRunClaim | None:
        with self.sessions.begin() as session:
            return claim_next_material_run(
                session,
                lease_owner=self.owner_id,
                now=datetime.now(UTC),
                lease_duration=_LEASE,
            )

    def release(self, claim: MaterialRunClaim) -> None:
        with self.sessions.begin() as session:
            row = session.get(MaterialLearningRunRecord, claim.run_id)
            now = datetime.now(UTC)
            if (
                row is not None
                and row.lease_token == claim.lease_token
                and row.lease_expires_at is not None
                and row.lease_expires_at > now
            ):
                release_material_claim(session, claim, now=now)

    def maintain_claim(self, claim: MaterialRunClaim) -> AbstractContextManager[None]:
        return maintain_material_claim(self.sessions, claim, lease_duration=_LEASE)

    def authorize(self, claim: MaterialRunClaim) -> None:
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            authorize_material_learning(session, run.created_by)
            revision = session.get(LearningMaterialRevisionRecord, run.material_revision_id)
            material = (
                session.get(LearningMaterialRecord, revision.material_id) if revision else None
            )
            if (
                revision is None
                or material is None
                or material.lifecycle_state != "ACTIVE"
                or material.current_revision_id != revision.material_revision_id
                or revision.created_by != run.created_by
            ):
                raise ValueError("MATERIAL_LEARNING_SOURCE_STALE")
            renew_material_claim(session, claim, now=datetime.now(UTC), lease_duration=_LEASE)

    def intake(
        self, claim: MaterialRunClaim
    ) -> tuple[MaterialLearningIntakeManifest, MaterialArtifactMember]:
        with self.sessions() as session:
            run = session.get(MaterialLearningRunRecord, claim.run_id)
            if run is None:
                raise ValueError("MATERIAL_LEARNING_RUN_NOT_FOUND")
            revision = session.get(LearningMaterialRevisionRecord, run.material_revision_id)
            if revision is None:
                raise ValueError("MATERIAL_LEARNING_REVISION_NOT_FOUND")
            pointer = self.metadata_pointer(
                session,
                revision.manifest_artifact_id,
                revision.manifest_artifact_revision_id,
                revision.manifest_sha256,
                "material/intake.json",
                "eom://schemas/material-learning/intake/1.0",
            )
        value = read_material_metadata(
            self.artifacts,
            pointer,
            MaterialLearningIntakeManifest,
            schema_ref=pointer.schema_ref,
            member_path=pointer.member_path,
        )
        # Polling reads only this small immutable manifest. Actual preparation,
        # execution and registration use their source owners' byte/hash checks;
        # do not stream every original book again for each status checkpoint.
        return value, pointer

    @staticmethod
    def metadata_pointer(
        session: Session,
        artifact_id: str | None,
        revision_id: str | None,
        digest: str | None,
        member: str,
        schema_ref: str,
    ) -> MaterialArtifactMember:
        revision = session.get(ArtifactRevisionRecord, revision_id) if revision_id else None
        if artifact_id is None or revision_id is None or digest is None or revision is None:
            raise ValueError("MATERIAL_LEARNING_CHECKPOINT_MISSING")
        return MaterialArtifactMember(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path=member,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=digest,
            bytes=revision.content_bytes,
        )

    def context(self, claim: MaterialRunClaim) -> MaterialProcessingContext:
        intake, _ = self.intake(claim)
        with self.sessions() as session:
            run = session.get(MaterialLearningRunRecord, claim.run_id)
            if run is None:
                raise ValueError("MATERIAL_LEARNING_RUN_NOT_FOUND")
            pointer = self.metadata_pointer(
                session,
                run.prepared_artifact_id,
                run.prepared_artifact_revision_id,
                run.prepared_sha256,
                "material/prepared.json",
                "eom://schemas/material-learning/prepared/1.0",
            )
        prepared = read_material_metadata(
            self.artifacts,
            pointer,
            MaterialPreparedArtifact,
            schema_ref=pointer.schema_ref,
            member_path=pointer.member_path,
        )
        if (prepared.material_id, prepared.material_revision_id) != (
            intake.material_id,
            intake.material_revision_id,
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARED_SOURCE_CHANGED")
        return MaterialProcessingContext(claim.run_id, intake.requested_by, intake, prepared)

    def prepare(self, claim: MaterialRunClaim) -> MaterialCoordinatorProgress:
        self.authorize(claim)
        intake, intake_pointer = self.intake(claim)
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            if run.state == "RECEIVED":
                transition_material_run(
                    session, run, MaterialLearningState.PREPARING, now=datetime.now(UTC)
                )
            if run.state != "PREPARING":
                raise ValueError("MATERIAL_LEARNING_PREPARATION_PHASE_INVALID")
            task, _ = add_material_task(
                session, run, task_kind="PREPARE", unit_key="source-preparation", ordinal=1
            )
            task_id = task.task_id
            if task.state == "PENDING":
                transition_material_task(
                    session, run, task, MaterialTaskState.PREPARING, now=datetime.now(UTC)
                )
            input_pointer = (
                self.metadata_pointer(
                    session,
                    task.input_artifact_id,
                    task.input_artifact_revision_id,
                    task.input_sha256,
                    "material/preparation-input.json",
                    "eom://schemas/material-learning/preparation-input/1.0",
                )
                if task.input_artifact_revision_id
                else None
            )
        if input_pointer is None:
            value = dict(
                schema_version="material-learning-preparation-input/1.0",
                task_id=task_id,
                material_id=intake.material_id,
                material_revision_id=intake.material_revision_id,
                intake_manifest=intake_pointer.model_dump(mode="json"),
                profile=self.profile.model_dump(mode="json"),
            )
            work = MaterialPreparationInput.model_validate(
                {**value, "input_sha256": content_sha256(value)}
            )
            input_pointer = publish_material_metadata(
                self.artifacts,
                self.settings,
                work,
                member_path="material/preparation-input.json",
                schema_ref="eom://schemas/material-learning/preparation-input/1.0",
                artifact_type="material-learning-preparation-input",
                idempotency_key="material-prepare-input:" + task_id,
            )
            with self.sessions.begin() as session:
                lock_material_run(session, claim, now=datetime.now(UTC))
                checkpoint = session.get(MaterialLearningTaskRecord, task_id)
                assert checkpoint is not None
                self.pin_input(checkpoint, input_pointer)
        else:
            work = read_material_metadata(
                self.artifacts,
                input_pointer,
                MaterialPreparationInput,
                schema_ref=input_pointer.schema_ref,
                member_path=input_pointer.member_path,
            )
        outcome = self.preparation.prepare(
            work,
            operator_id=intake.requested_by,
            authorize=lambda: self.authorize(claim),
        )
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            checkpoint = session.get(MaterialLearningTaskRecord, task_id)
            assert checkpoint is not None
            task = checkpoint
            self.pin_output(task, outcome.pointer)
            run.prepared_artifact_id = outcome.pointer.artifact_id
            run.prepared_artifact_revision_id = outcome.pointer.artifact_revision_id
            run.prepared_sha256 = outcome.pointer.sha256
            if task.state == "PREPARING":
                transition_material_task(
                    session, run, task, MaterialTaskState.RESULT_READY, now=datetime.now(UTC)
                )
            if task.state == "RESULT_READY":
                transition_material_task(
                    session, run, task, MaterialTaskState.COMPLETED, now=datetime.now(UTC)
                )
            ordinal = 2
            for source in outcome.prepared.sources:
                for window in material_discovery_windows(source.source_role, source.page_count):
                    add_material_task(
                        session,
                        run,
                        task_kind="DISCOVER",
                        unit_key=discovery_window_key(window),
                        ordinal=ordinal,
                    )
                    ordinal += 1
            transition_material_run(
                session, run, MaterialLearningState.DISCOVERING, now=datetime.now(UTC)
            )
        return MaterialCoordinatorProgress(claim.run_id, task_id, "PREPARED")

    @staticmethod
    def pin_input(task: MaterialLearningTaskRecord, pointer: MaterialArtifactMember) -> None:
        actual = (pointer.artifact_id, pointer.artifact_revision_id, pointer.sha256)
        if (
            task.input_artifact_revision_id is not None
            and (task.input_artifact_id, task.input_artifact_revision_id, task.input_sha256)
            != actual
        ):
            raise ValueError("MATERIAL_LEARNING_INPUT_CHANGED")
        task.input_artifact_id, task.input_artifact_revision_id, task.input_sha256 = actual

    @staticmethod
    def pin_output(
        task: MaterialLearningTaskRecord,
        pointer: MaterialArtifactMember | ArtifactMemberPointer,
    ) -> None:
        actual = (pointer.artifact_id, pointer.artifact_revision_id, pointer.sha256)
        if (
            task.output_artifact_revision_id is not None
            and (task.output_artifact_id, task.output_artifact_revision_id, task.output_sha256)
            != actual
        ):
            raise ValueError("MATERIAL_LEARNING_OUTPUT_CHANGED")
        task.output_artifact_id, task.output_artifact_revision_id, task.output_sha256 = actual

    def read_task_input(
        self, task: MaterialLearningTaskRecord
    ) -> MaterialDiscoveryWork | MaterialExtractionWork:
        model = MaterialDiscoveryWork if task.task_kind == "DISCOVER" else MaterialExtractionWork
        kind = "discovery-work" if task.task_kind == "DISCOVER" else "extraction-work"
        with self.sessions() as session:
            pointer = self.metadata_pointer(
                session,
                task.input_artifact_id,
                task.input_artifact_revision_id,
                task.input_sha256,
                "material/work.json",
                f"eom://schemas/material-learning/{kind}/1.0",
            )
        work = read_material_metadata(
            self.artifacts,
            pointer,
            model,
            schema_ref=pointer.schema_ref,
            member_path=pointer.member_path,
        )
        if not isinstance(work, (MaterialDiscoveryWork, MaterialExtractionWork)):
            raise ValueError("MATERIAL_LEARNING_WORK_TYPE_INVALID")
        return work

    def advance_learning_task(
        self,
        claim: MaterialRunClaim,
        context: MaterialProcessingContext,
        task: MaterialLearningTaskRecord,
        work: MaterialDiscoveryWork | MaterialExtractionWork | None,
    ) -> MaterialCoordinatorProgress:
        if task.state in {"PENDING", "PREPARING"}:
            with self.sessions.begin() as session:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                current = session.get(MaterialLearningTaskRecord, task.task_id)
                assert current is not None
                if current.state == "PENDING":
                    transition_material_task(
                        session, run, current, MaterialTaskState.PREPARING, now=datetime.now(UTC)
                    )
            if work is None:
                raise ValueError("MATERIAL_LEARNING_TASK_WORK_REQUIRED")
            pointer = self.work.publish(work, authorize=lambda: self.authorize(claim))
            with self.sessions.begin() as session:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                current = session.get(MaterialLearningTaskRecord, task.task_id)
                assert current is not None
                self.pin_input(current, pointer)
                transition_material_task(
                    session, run, current, MaterialTaskState.READY, now=datetime.now(UTC)
                )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "READY")
        if task.state == "READY":
            exact = self.read_task_input(task)
            with self.sessions.begin() as session:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                current = session.get(MaterialLearningTaskRecord, task.task_id)
                assert current is not None
                if not transition_material_task(
                    session, run, current, MaterialTaskState.RUNNING, now=datetime.now(UTC)
                ):
                    return MaterialCoordinatorProgress(
                        claim.run_id, task.task_id, "WAITING_FOR_CAPACITY"
                    )
                definition = session.get(WorkflowDefinitionRecord, self.definition_id)
                if definition is None:
                    raise ValueError("MATERIAL_LEARNING_DEFINITION_NOT_INSTALLED")
                submitted = submit_material_learning_workflow(
                    session,
                    definition=definition,
                    work=exact,
                    operator_id=context.operator_id,
                    idempotency_key="material-child:" + task.task_id,
                    source_authorizer=self.authorizer,
                    expected_preset=self.preset,
                )
                current.workflow_id = submitted.workflow_id
            return MaterialCoordinatorProgress(
                claim.run_id, task.task_id, "RUNNING", submitted.workflow_id
            )
        if task.state == "RUNNING":
            with self.sessions() as session:
                workflow = session.get(WorkflowInstanceRecord, task.workflow_id)
                if workflow is None:
                    raise ValueError("MATERIAL_LEARNING_CHILD_MISSING")
                state = workflow.state
            if state in {"FAILED", "CANCELLED"}:
                self.fail_task(claim, task.task_id, "MATERIAL_LEARNING_WORKER_TERMINAL_FAILURE")
                return MaterialCoordinatorProgress(claim.run_id, task.task_id, "FAILED")
            if state != "COMPLETED":
                return MaterialCoordinatorProgress(
                    claim.run_id, task.task_id, "RUNNING", task.workflow_id
                )
            with self.sessions.begin() as session:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                current = session.get(MaterialLearningTaskRecord, task.task_id)
                assert current is not None
                completed = resolve_completed_material_task(
                    session,
                    self.artifacts,
                    task_id=task.task_id,
                    operator_id=context.operator_id,
                )
                self.pin_output(current, completed.result_pointer)
                transition_material_task(
                    session, run, current, MaterialTaskState.RESULT_READY, now=datetime.now(UTC)
                )
                if task.task_kind == "DISCOVER":
                    transition_material_task(
                        session, run, current, MaterialTaskState.COMPLETED, now=datetime.now(UTC)
                    )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "RESULT_READY")
        return MaterialCoordinatorProgress(claim.run_id, task.task_id, task.state)

    def fail_task(self, claim: MaterialRunClaim, task_id: str, code: str) -> None:
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            task = session.get(MaterialLearningTaskRecord, task_id)
            if task is None:
                raise ValueError("MATERIAL_LEARNING_TASK_MISSING")
            transition_material_task(
                session, run, task, MaterialTaskState.FAILED, now=datetime.now(UTC), error_code=code
            )

    def discovery_plan(
        self, claim: MaterialRunClaim, context: MaterialProcessingContext
    ) -> MaterialDiscoveryPlan:
        self.authorize(claim)
        if self._plan is not None and self._plan.run_id == claim.run_id:
            return self._plan
        with self.sessions() as session:
            self._plan = read_material_discovery_plan(
                session, self.artifacts, run_id=claim.run_id, operator_id=context.operator_id
            )
        return self._plan

    def discovery_step(
        self, claim: MaterialRunClaim, context: MaterialProcessingContext
    ) -> MaterialCoordinatorProgress:
        with self.sessions() as session:
            task = next_material_task(session, claim.run_id)
            if task is not None:
                session.expunge(task)
        if task is not None:
            if task.task_kind != "DISCOVER":
                raise ValueError("MATERIAL_LEARNING_DISCOVERY_ORDER_INVALID")
            work = None
            if task.state in {"PENDING", "PREPARING"}:
                if self._windows is None or self._windows[0] != claim.run_id:
                    self._windows = (
                        claim.run_id,
                        MappingProxyType(
                            {
                                discovery_window_key(window): window
                                for source in context.prepared.sources
                                for window in material_discovery_windows(
                                    source.source_role, source.page_count
                                )
                            }
                        ),
                    )
                work = self.work.discovery(
                    task_id=task.task_id,
                    prepared=context.prepared,
                    intake=context.intake,
                    window=self._windows[1][task.unit_key],
                )
            return self.advance_learning_task(claim, context, task, work)
        with self.sessions.begin() as session:
            failed = session.scalar(
                select(MaterialLearningTaskRecord.task_id)
                .where(
                    MaterialLearningTaskRecord.run_id == claim.run_id,
                    MaterialLearningTaskRecord.task_kind == "DISCOVER",
                    MaterialLearningTaskRecord.state.in_({"FAILED", "EXCEPTION", "CANCELLED"}),
                )
                .limit(1)
            )
            if failed is not None:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                transition_material_run(
                    session,
                    run,
                    MaterialLearningState.FAILED,
                    now=datetime.now(UTC),
                    error_code="MATERIAL_LEARNING_DISCOVERY_INCOMPLETE",
                )
                return MaterialCoordinatorProgress(claim.run_id, failed, "FAILED")
        plan = self.discovery_plan(claim, context)
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            ordinal = 2 + len(plan.ranges)
            for unit in plan.by_unit.values():
                if unit.unit.kind == "QUESTION":
                    added, _ = add_material_task(
                        session, run, task_kind="QUESTION", unit_key=unit.unit_key, ordinal=ordinal
                    )
                    ordinal += 1
                    fatal = set(unit.issue_codes) - {
                        "NO_SOURCE_SOLUTION_INDEPENDENT_SOLUTION_REQUIRED"
                    }
                    if fatal:
                        transition_material_task(
                            session,
                            run,
                            added,
                            MaterialTaskState.EXCEPTION,
                            now=datetime.now(UTC),
                            error_code=sorted(fatal)[0],
                        )
            for discovered in plan.ranges:
                core = {
                    (page.source_role, page.physical_page) for page in discovered.work.core_pages
                }
                if any(
                    unit.kind == "EXPLANATION"
                    and any(
                        (anchor.source_role, anchor.physical_page) in core
                        for anchor in unit.anchors
                    )
                    for unit in discovered.result.units
                ):
                    add_material_task(
                        session,
                        run,
                        task_kind="EXPLANATION",
                        unit_key="explanation:" + discovered.work.task_id,
                        ordinal=ordinal,
                    )
                    ordinal += 1
            transition_material_run(
                session, run, MaterialLearningState.PROCESSING, now=datetime.now(UTC)
            )
        return MaterialCoordinatorProgress(claim.run_id, None, "PROCESSING")


def discovery_window_key(window: MaterialDiscoveryWindow) -> str:
    return f"discovery:{window.source_role}:{window.first_core_page}:{window.last_core_page}"

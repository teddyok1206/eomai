"""One material AI lane, durable question/knowledge checkpoints and official Graph handoff."""

from datetime import UTC, datetime

from eom_catalog_contracts import KnowledgeAnalysisApplicationResult
from eom_catalog_contracts.material_knowledge_analysis import (
    CreateMaterialKnowledgeAnalysisCommand,
    MaterialKnowledgeAnalysisSelection,
)
from eom_catalog_contracts.material_learning_preparation import (
    material_document_kind,
    material_document_source_class,
)
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow.material_learning_state import MaterialLearningState, MaterialTaskState
from sqlalchemy import select

from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_catalog_service.material_graph_learning import MaterialGraphLearningService
from eom_catalog_service.material_item_registration import MaterialItemRegistrationService
from eom_catalog_service.material_learning_artifacts import (
    publish_material_metadata,
    read_material_metadata,
)
from eom_catalog_service.material_learning_coordinator import (
    MaterialCoordinatorProgress,
    MaterialDiscoveryPlan,
    MaterialLearningCoordinator,
    MaterialProcessingContext,
)
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_learning_store import (
    MaterialRunClaim,
    lock_material_run,
    next_material_task,
    transition_material_run,
    transition_material_task,
)
from eom_catalog_service.material_task_history import read_material_task_histories

_ANALYSIS_FAILURES = frozenset({"FAILED", "REJECTED", "CANCELLED"})
_REGISTRATION_SOURCE_EXCEPTIONS = frozenset(
    {"MATERIAL_ITEM_SOURCE_UNREADABLE", "MATERIAL_NATIVE_METADATA_UPDATE_REQUIRED"}
)
_KNOWLEDGE_COMMAND_REF = "eom://schemas/knowledge/create-material-knowledge-analysis/1.0"
_TERMINAL_SOURCE_LIMITS = frozenset(
    {
        "MATERIAL_LEARNING_PDF_ENCRYPTED",
        "MATERIAL_LEARNING_SOURCE_PAGE_LIMIT",
        "MATERIAL_LEARNING_SOURCE_RENDER_LIMIT",
    }
)


class MaterialLearningProcessingService:
    def __init__(
        self,
        coordinator: MaterialLearningCoordinator,
        *,
        registration: MaterialItemRegistrationService,
        graph: MaterialGraphLearningService,
    ) -> None:
        self.coordinator, self.registration, self.graph = coordinator, registration, graph
        self.sessions = coordinator.sessions

    def advance_once(self) -> MaterialCoordinatorProgress:
        claim = self.coordinator.claim()
        if claim is None:
            return MaterialCoordinatorProgress(None, None, "IDLE")
        try:
            self.coordinator.authorize(claim)
            with self.sessions() as session:
                run = session.get(MaterialLearningRunRecord, claim.run_id)
                assert run is not None
                phase = run.state
            if phase in {"RECEIVED", "PREPARING"}:
                try:
                    return self.coordinator.prepare(claim)
                except MaterialLearningSourceError as error:
                    if error.code not in _TERMINAL_SOURCE_LIMITS:
                        raise  # Infrastructure/profile/pointer failures are not source quality.
                    with self.sessions.begin() as session:
                        run = lock_material_run(session, claim, now=datetime.now(UTC))
                        task = session.scalar(
                            select(MaterialLearningTaskRecord).where(
                                MaterialLearningTaskRecord.run_id == run.run_id,
                                MaterialLearningTaskRecord.task_kind == "PREPARE",
                            )
                        )
                        if task is None or task.state != "PREPARING":
                            raise
                        transition_material_task(
                            session,
                            run,
                            task,
                            MaterialTaskState.FAILED,
                            now=datetime.now(UTC),
                            error_code=error.code,
                        )
                        transition_material_run(
                            session,
                            run,
                            MaterialLearningState.FAILED,
                            now=datetime.now(UTC),
                            error_code=error.code,
                        )
                        return MaterialCoordinatorProgress(run.run_id, task.task_id, "FAILED")
            context = self.coordinator.context(claim)
            if phase == "DISCOVERING":
                return self.coordinator.discovery_step(claim, context)
            if phase == "PAUSED":
                with self.sessions() as session:
                    task = session.scalar(
                        select(MaterialLearningTaskRecord)
                        .where(
                            MaterialLearningTaskRecord.run_id == claim.run_id,
                            MaterialLearningTaskRecord.state.in_({"RUNNING", "ANALYZING"}),
                        )
                        .limit(1)
                    )
                    if task is not None:
                        session.expunge(task)
                if task is None:
                    return MaterialCoordinatorProgress(claim.run_id, None, "PAUSED")
            else:
                with self.sessions() as session:
                    task = next_material_task(session, claim.run_id)
                    if task is not None:
                        session.expunge(task)
            if task is None:
                return self._finish(claim)
            if task.task_kind == "DISCOVER":
                return self.coordinator.advance_learning_task(claim, context, task, None)
            plan = self.coordinator.discovery_plan(claim, context)
            if task.task_kind == "QUESTION":
                return self._question(claim, context, plan, task)
            if task.task_kind == "EXPLANATION":
                return self._explanation(claim, context, plan, task)
            raise ValueError("MATERIAL_LEARNING_PROCESSING_TASK_INVALID")
        finally:
            self.coordinator.release(claim)

    def _finish(self, claim: MaterialRunClaim) -> MaterialCoordinatorProgress:
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            issues = session.scalar(
                select(MaterialLearningTaskRecord.task_id)
                .where(
                    MaterialLearningTaskRecord.run_id == run.run_id,
                    MaterialLearningTaskRecord.state.in_({"FAILED", "EXCEPTION", "CANCELLED"}),
                )
                .limit(1)
            )
            target = (
                MaterialLearningState.COMPLETED_WITH_EXCEPTIONS
                if issues
                else MaterialLearningState.COMPLETED
            )
            transition_material_run(session, run, target, now=datetime.now(UTC))
        return MaterialCoordinatorProgress(claim.run_id, None, target.value)

    def _set_state(
        self,
        claim: MaterialRunClaim,
        task_id: str,
        state: MaterialTaskState,
        *,
        item_revision_id: str | None = None,
        graph_revision: str | None = None,
    ) -> bool:
        with self.sessions.begin() as session:
            run = lock_material_run(session, claim, now=datetime.now(UTC))
            task = session.get(MaterialLearningTaskRecord, task_id)
            assert task is not None
            if item_revision_id is not None:
                if task.item_revision_id is not None and task.item_revision_id != item_revision_id:
                    raise ValueError("MATERIAL_LEARNING_ITEM_PIN_CHANGED")
                task.item_revision_id = item_revision_id
            if graph_revision is not None:
                if (
                    task.graph_snapshot_revision_id is not None
                    and task.graph_snapshot_revision_id != graph_revision
                ):
                    raise ValueError("MATERIAL_LEARNING_GRAPH_PIN_CHANGED")
                task.graph_snapshot_revision_id = graph_revision
            return transition_material_task(session, run, task, state, now=datetime.now(UTC))

    def _paused(self, claim: MaterialRunClaim) -> bool:
        with self.sessions() as session:
            run = session.get(MaterialLearningRunRecord, claim.run_id)
            return run is None or run.state == "PAUSED"

    def _question(
        self,
        claim: MaterialRunClaim,
        context: MaterialProcessingContext,
        plan: MaterialDiscoveryPlan,
        task: MaterialLearningTaskRecord,
    ) -> MaterialCoordinatorProgress:
        if task.state in {"PENDING", "PREPARING", "READY", "RUNNING"}:
            work = None
            if task.state in {"PENDING", "PREPARING"}:
                question = plan.by_unit[task.unit_key]
                work = self.coordinator.work.extraction(
                    task_id=task.task_id,
                    prepared=context.prepared,
                    intake=context.intake,
                    question=question,
                    solutions=tuple(plan.by_unit[key].unit for key in question.solution_unit_keys),
                )
            return self.coordinator.advance_learning_task(claim, context, task, work)
        if task.state == "RESULT_READY":
            try:
                registered = self.registration.register_completed(
                    task_id=task.task_id, operator_id=context.operator_id
                )
            except ValueError as error:
                if str(error) not in _REGISTRATION_SOURCE_EXCEPTIONS:
                    raise
                with self.sessions.begin() as session:
                    run = lock_material_run(session, claim, now=datetime.now(UTC))
                    current = session.get(MaterialLearningTaskRecord, task.task_id)
                    assert current is not None
                    transition_material_task(
                        session,
                        run,
                        current,
                        MaterialTaskState.EXCEPTION,
                        now=datetime.now(UTC),
                        error_code=str(error),
                    )
                return MaterialCoordinatorProgress(claim.run_id, task.task_id, "EXCEPTION")
            self._set_state(
                claim,
                task.task_id,
                MaterialTaskState.REGISTERED,
                item_revision_id=registered.item_revision_id,
            )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "REGISTERED")
        if task.state == "REGISTERED":
            accepted = self._set_state(claim, task.task_id, MaterialTaskState.ANALYZING)
            return MaterialCoordinatorProgress(
                claim.run_id, task.task_id, "ANALYZING" if accepted else "WAITING_FOR_CAPACITY"
            )
        if task.state == "ANALYZING":
            assert task.item_revision_id is not None
            base_id, solution_id = self._analysis_pins(task.task_id)
            if base_id is None and self._paused(claim):
                return MaterialCoordinatorProgress(claim.run_id, task.task_id, "PAUSED")
            base = self.graph.advance_item_analysis(
                task_id=task.task_id,
                item_revision_id=task.item_revision_id,
                operator_id=context.operator_id,
            )
            self._pin_analysis(claim, task.task_id, base, solution=False)
            if base.state != "ACCEPTED":
                return self._analysis_progress(claim, task.task_id, base)
            if solution_id is None and self._paused(claim):
                return MaterialCoordinatorProgress(claim.run_id, task.task_id, "PAUSED")
            solution = self.graph.advance_item_solution(
                base_analysis_run_id=base.analysis_run_id,
                task_id=task.task_id,
                operator_id=context.operator_id,
            )
            self._pin_analysis(claim, task.task_id, solution, solution=True)
            if solution.state != "ACCEPTED":
                return self._analysis_progress(claim, task.task_id, solution)
            self._set_state(claim, task.task_id, MaterialTaskState.PUBLISHING)
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "PUBLISHING")
        if task.state == "PUBLISHING":
            base_id, _solution_id = self._analysis_pins(task.task_id)
            assert task.item_revision_id is not None and base_id is not None
            with self.coordinator.maintain_claim(claim):
                revision = self.graph.publish_item(
                    task_id=task.task_id,
                    analysis_run_id=base_id,
                    item_revision_id=task.item_revision_id,
                    operator_id=context.operator_id,
                )
            self._set_state(
                claim, task.task_id, MaterialTaskState.GRAPH_READY, graph_revision=revision
            )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "GRAPH_READY")
        if task.state == "GRAPH_READY":
            self._set_state(claim, task.task_id, MaterialTaskState.COMPLETED)
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "COMPLETED")
        raise ValueError("MATERIAL_LEARNING_QUESTION_PHASE_INVALID")

    def _pin_analysis(
        self,
        claim: MaterialRunClaim,
        task_id: str,
        analysis: KnowledgeAnalysisApplicationResult,
        *,
        solution: bool,
    ) -> None:
        with self.sessions.begin() as session:
            lock_material_run(session, claim, now=datetime.now(UTC))
            task = session.get(MaterialLearningTaskRecord, task_id)
            assert task is not None
            previous = task.solution_analysis_run_id if solution else task.analysis_run_id
            if previous is None and task.predecessor_task_id is not None:
                history = read_material_task_histories(session, (task,))[task.task_id]
                owner = history.analysis_owner(solution=solution)
                inherited = (
                    (owner.solution_analysis_run_id if solution else owner.analysis_run_id)
                    if owner
                    else None
                )
                if inherited == analysis.analysis_run_id:
                    return  # Keep the original unique child owner and exact accepted result.
                prior = session.get(KnowledgeAnalysisRunRecord, inherited) if inherited else None
                if prior is not None and prior.state not in _ANALYSIS_FAILURES:
                    raise ValueError("MATERIAL_LEARNING_ANALYSIS_PIN_CHANGED")
            if previous is not None and previous != analysis.analysis_run_id:
                raise ValueError("MATERIAL_LEARNING_ANALYSIS_PIN_CHANGED")
            if solution:
                task.solution_analysis_run_id = analysis.analysis_run_id
            else:
                task.analysis_run_id = analysis.analysis_run_id

    def _analysis_pins(self, task_id: str) -> tuple[str | None, str | None]:
        with self.sessions() as session:
            task = session.get(MaterialLearningTaskRecord, task_id)
            if task is None:
                raise ValueError("MATERIAL_LEARNING_TASK_MISSING")
            if task.predecessor_task_id is None:
                return task.analysis_run_id, task.solution_analysis_run_id
            history = read_material_task_histories(session, (task,))[task_id]
            base, solution = history.analysis_owner(), history.analysis_owner(solution=True)
            return (
                base.analysis_run_id if base else None,
                solution.solution_analysis_run_id if solution else None,
            )

    def _analysis_progress(
        self, claim: MaterialRunClaim, task_id: str, analysis: KnowledgeAnalysisApplicationResult
    ) -> MaterialCoordinatorProgress:
        if analysis.state in _ANALYSIS_FAILURES:
            self.coordinator.fail_task(
                claim, task_id, "MATERIAL_LEARNING_ANALYSIS_TERMINAL_FAILURE"
            )
            return MaterialCoordinatorProgress(claim.run_id, task_id, "FAILED")
        return MaterialCoordinatorProgress(claim.run_id, task_id, "ANALYZING", analysis.workflow_id)

    def _knowledge_command(
        self,
        context: MaterialProcessingContext,
        plan: MaterialDiscoveryPlan,
        task: MaterialLearningTaskRecord,
    ) -> CreateMaterialKnowledgeAnalysisCommand:
        discovered = plan.by_task.get(task.unit_key.removeprefix("explanation:"))
        if discovered is None:
            raise ValueError("MATERIAL_KNOWLEDGE_DISCOVERY_TASK_MISSING")
        core = {(page.source_role, page.physical_page) for page in discovered.work.core_pages}
        regions = {
            anchor.model_dump_json(): anchor
            for unit in discovered.result.units
            if unit.kind == "EXPLANATION"
            for anchor in unit.anchors
            if (anchor.source_role, anchor.physical_page) in core
        }
        anchors = tuple(
            sorted(
                regions.values(),
                key=lambda anchor: (
                    anchor.physical_page,
                    anchor.bounding_box.top,
                    anchor.bounding_box.left,
                ),
            )
        )
        if not anchors:
            raise ValueError("MATERIAL_KNOWLEDGE_EXPLANATION_REQUIRED")
        source = next(
            source
            for source in context.prepared.sources
            if source.source_role == anchors[0].source_role
        )
        known_keys = {
            unit.unit_code
            for unit in integrated_science_curriculum_units()
            if unit.unit_level == "MINOR"
        }
        return CreateMaterialKnowledgeAnalysisCommand(
            material_task_id=task.task_id,
            source=MaterialKnowledgeAnalysisSelection(
                source_class=material_document_source_class(
                    material_document_kind(context.intake.upload.material_kind)
                ),
                document_revision_id=source.document_revision_id,
                first_physical_page=anchors[0].physical_page,
                last_physical_page=anchors[-1].physical_page,
                selected_regions=anchors,
                curriculum_unit_keys=tuple(
                    sorted(
                        set(context.intake.upload.curriculum_unit_hints).intersection(known_keys)
                    )
                ),
            ),
            preset_key="material-knowledge-analysis",
            risk_policy_revision_id=self.graph.controls.risk_policy_revision_id,
            requested_by=context.operator_id,
            idempotency_key="material-knowledge:" + task.task_id,
        )

    def _explanation(
        self,
        claim: MaterialRunClaim,
        context: MaterialProcessingContext,
        plan: MaterialDiscoveryPlan,
        task: MaterialLearningTaskRecord,
    ) -> MaterialCoordinatorProgress:
        if task.state in {"PENDING", "PREPARING"}:
            if task.state == "PENDING":
                self._set_state(claim, task.task_id, MaterialTaskState.PREPARING)
            command = self._knowledge_command(context, plan, task)
            pointer = publish_material_metadata(
                self.coordinator.artifacts,
                self.coordinator.settings,
                command,
                member_path="material/knowledge-command.json",
                schema_ref=_KNOWLEDGE_COMMAND_REF,
                artifact_type="material-knowledge-command",
                idempotency_key="material-knowledge-input:" + task.task_id,
            )
            with self.sessions.begin() as session:
                run = lock_material_run(session, claim, now=datetime.now(UTC))
                current = session.get(MaterialLearningTaskRecord, task.task_id)
                assert current is not None
                self.coordinator.pin_input(current, pointer)
                transition_material_task(
                    session, run, current, MaterialTaskState.READY, now=datetime.now(UTC)
                )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "READY")
        if task.state == "READY":
            accepted = self._set_state(claim, task.task_id, MaterialTaskState.ANALYZING)
            return MaterialCoordinatorProgress(
                claim.run_id, task.task_id, "ANALYZING" if accepted else "WAITING_FOR_CAPACITY"
            )
        if task.state == "ANALYZING":
            if task.analysis_run_id is None and self._paused(claim):
                return MaterialCoordinatorProgress(claim.run_id, task.task_id, "PAUSED")
            # The immutable command is the restart source, not a freshly generated
            # interpretation of all discovery results under a changed runtime.
            with self.sessions() as session:
                pointer = self.coordinator.metadata_pointer(
                    session,
                    task.input_artifact_id,
                    task.input_artifact_revision_id,
                    task.input_sha256,
                    "material/knowledge-command.json",
                    _KNOWLEDGE_COMMAND_REF,
                )
            command = read_material_metadata(
                self.coordinator.artifacts,
                pointer,
                CreateMaterialKnowledgeAnalysisCommand,
                schema_ref=_KNOWLEDGE_COMMAND_REF,
                member_path=pointer.member_path,
            )
            analysis = self.graph.advance_document_analysis(
                task_id=task.task_id,
                selection=command.source,
                operator_id=context.operator_id,
            )
            self._pin_analysis(claim, task.task_id, analysis, solution=False)
            if analysis.state != "ACCEPTED":
                return self._analysis_progress(claim, task.task_id, analysis)
            self._set_state(claim, task.task_id, MaterialTaskState.PUBLISHING)
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "PUBLISHING")
        if task.state == "PUBLISHING":
            assert task.analysis_run_id is not None
            with self.coordinator.maintain_claim(claim):
                revision = self.graph.publish_document(
                    analysis_run_id=task.analysis_run_id, operator_id=context.operator_id
                )
            self._set_state(
                claim, task.task_id, MaterialTaskState.GRAPH_READY, graph_revision=revision
            )
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "GRAPH_READY")
        if task.state == "GRAPH_READY":
            self._set_state(claim, task.task_id, MaterialTaskState.COMPLETED)
            return MaterialCoordinatorProgress(claim.run_id, task.task_id, "COMPLETED")
        raise ValueError("MATERIAL_LEARNING_EXPLANATION_PHASE_INVALID")

"""One-at-a-time advancement over existing Workflow, Registry and Graph owners."""

from dataclasses import dataclass

from eom_catalog_contracts.creative_learning_cohort import (
    CreativeCohortTarget,
    CreativeLearningCohort,
)
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
)
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.preset_model_selection import (
    resolve_released_capacity_policy,
    validated_preset,
)
from eom_orchestrator.settings import Settings
from eom_protocol.general_chat_grounding import ChatKnowledgeCatalogRequest
from eom_workflow.models import ExternalItemLearningWorkerRequest
from eom_workflow_runner.external_item_learning_start import start_prepared_external_item_learning
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import load_persisted_workflow_request
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
)
from eom_catalog_service.chat_knowledge_resolution import ChatKnowledgeResolutionService
from eom_catalog_service.creative_cohort_preparation import CreativeCohortPreparationService
from eom_catalog_service.creative_item_graph_learning import (
    CreativeGraphLearningProgress,
    CreativeItemGraphLearningService,
)
from eom_catalog_service.creative_item_registration import (
    CreativeItemRegistrationService,
    RegisteredCreativeItem,
    creative_registration_key,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeGraphSnapshotRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class CreativeCohortProgress:
    cohort_id: str
    target_count: int
    verified_count: int
    external_number: str | None
    state: str
    workflow_id: str | None
    item_revision_id: str | None
    analysis_run_id: str | None
    graph_snapshot_revision_id: str | None
    active_sources: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True)
class CreativeSourceExecution:
    """Ephemeral cursor; every identity is recovered through the canonical owners."""

    target: CreativeCohortTarget
    selection: ExternalItemLearningRoleSelection | None = None
    started: bool = False
    registered: RegisteredCreativeItem | None = None
    analysis: CreativeGraphLearningProgress | None = None
    state: str = "PREPARING"


def pending_first_targets(
    targets: tuple[CreativeCohortTarget, ...], published_keys: frozenset[str]
) -> tuple[CreativeCohortTarget, ...]:
    """O(N) stable scheduling hint; no target is omitted or marked complete."""
    pending: list[CreativeCohortTarget] = []
    history: list[CreativeCohortTarget] = []
    for target in targets:
        destination = (
            history if creative_registration_key(target.source_id) in published_keys else pending
        )
        destination.append(target)
    return (*pending, *history)


class CreativeCohortExecutionService:
    """In-memory cursor is only a cache; restart reconstructs exact stored identities.

    Source metadata is pinned in the admitted Artifact. Existing unique Workflow
    keys, command keys, registration keys and analysis keys own recovery. Neither
    a local status file nor a progress number can mark an Item complete.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        cohort: CreativeLearningCohort,
        settings: Settings,
        catalog_settings: CatalogSettings,
        scope: CreativeLearningExecutionScope | None = None,
    ) -> None:
        self.cohort = cohort
        self.scope = scope or CreativeLearningExecutionScope(cohort)
        if self.scope.cohort != cohort:
            raise ValueError("CREATIVE_COHORT_SCOPE_MISMATCH")
        self.sessions = build_session_factory(engine)
        self.publisher = ControlFileSetPublisher(engine, settings)
        self.preparation = CreativeCohortPreparationService(
            engine,
            cohort=cohort,
            settings=settings,
            catalog_settings=catalog_settings,
            scope=self.scope,
        )
        self.registration = CreativeItemRegistrationService(
            engine,
            content_pack_release_id=self.scope.content_pack_release_id,
            publisher=self.publisher,
            source_commit=self.scope.source_commit,
            settings=catalog_settings,
        )
        self.learning_by_scope = {
            entry.cohort_id: CreativeItemGraphLearningService(
                engine,
                access_policy_revision_id=cohort.access_policy_revision_id,
                preset_key=entry.analysis_preset_key,
                preset_id=entry.analysis_preset.preset_id,
                preset_revision_id=entry.analysis_preset.preset_revision_id,
                risk_policy_revision_id=cohort.risk_policy_revision_id,
                settings=catalog_settings,
            )
            for entry in self.scope.history_scopes
        }
        self.learning = self.learning_by_scope[self.scope.cohort_id]
        self.read = ChatKnowledgeResolutionService(engine)
        self._require_pins()
        indexed = {target.external_number: target for target in cohort.targets}
        seed = indexed[cohort.seed_external_number]
        self.targets = (seed, *(target for target in cohort.targets if target != seed))
        self.cursor = 0
        self.current: CreativeSourceExecution | None = None

    def _require_pins(self) -> None:
        with self.sessions() as session:
            for scope in self.scope.history_scopes:
                self._require_scope_pins(session, scope)
            if isinstance(self.scope.continuation, CreativeLearningParallelContinuation):
                pin = self.scope.continuation.capacity_policy
                capacity = resolve_released_capacity_policy(
                    session, pin.capacity_policy_revision_id
                )
                if (
                    capacity.capacity_policy_id != pin.capacity_policy_id
                    or capacity.schema_version != "worker-capacity-policy/1.4"
                    or capacity.content_sha256 != pin.sha256
                ):
                    raise ValueError("CREATIVE_COHORT_PRESET_PIN_MISMATCH")
            risk = KnowledgeAnalysisApplicationService.risk_policy(
                session, self.cohort.risk_policy_revision_id
            )
            if risk.content_sha256 != self.cohort.risk_policy_sha256:
                raise ValueError("CREATIVE_COHORT_RISK_POLICY_PIN_MISMATCH")
        if self.learning.access_policy_sha256 != self.cohort.access_policy_sha256:
            raise ValueError("CREATIVE_COHORT_ACCESS_POLICY_PIN_MISMATCH")

    def pending_first_targets(self) -> tuple[CreativeCohortTarget, ...]:
        """Use canonical membership for priority only; execution still reauthorizes each source."""
        context = self.learning.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
        keys = tuple(creative_registration_key(target.source_id) for target in self.targets)
        with self.sessions() as session:
            published = frozenset(
                key
                for key in session.scalars(
                    select(ItemRevisionRecord.registration_key)
                    .join(
                        KnowledgeSnapshotAnalysisRecord,
                        KnowledgeSnapshotAnalysisRecord.source_revision_id
                        == ItemRevisionRecord.item_revision_id,
                    )
                    .join(
                        KnowledgeAnalysisRunRecord,
                        KnowledgeAnalysisRunRecord.analysis_run_id
                        == KnowledgeSnapshotAnalysisRecord.analysis_run_id,
                    )
                    .where(
                        ItemRevisionRecord.registration_key.in_(keys),
                        KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                        == context.graph_snapshot_revision_id,
                        KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
                        KnowledgeAnalysisRunRecord.state == "ACCEPTED",
                    )
                )
                if key is not None
            )
        return pending_first_targets(self.targets, published)

    @staticmethod
    def _require_scope_pins(session: Session, scope: CreativeLearningExecutionScope) -> None:
        for pin, purpose in (
            (scope.extraction_preset, scope.extraction_preset_key),
            (scope.analysis_preset, scope.analysis_preset_key),
        ):
            row = session.get(ExecutionPresetRevisionRecord, pin.preset_revision_id)
            preset = validated_preset(row) if row else None
            logical = session.get(ExecutionPresetRecord, pin.preset_id)
            if (
                preset is None
                or preset.state != "RELEASED"
                or preset.preset_id != pin.preset_id
                or preset.content_sha256 != pin.sha256
                or preset.capacity_policy_revision_id != scope.capacity_policy_revision_id
                or logical is None
                or logical.state != "ACTIVE"
                or logical.preset_key != purpose
            ):
                raise ValueError("CREATIVE_COHORT_PRESET_PIN_MISMATCH")

    def _learning_for_registered(
        self, registered: RegisteredCreativeItem
    ) -> CreativeItemGraphLearningService:
        """Original source plan selects its original analysis, never a latest preset."""
        selection = registered.lineage.selection
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, selection.workflow_id)
            row = session.get(ResolvedExecutionPlanRecord, selection.plan_id)
            if workflow is None or row is None:
                raise ValueError("CREATIVE_COHORT_WORKFLOW_MISSING")
            request = load_persisted_workflow_request(workflow.initial_request).worker_request()
            if not isinstance(request, ExternalItemLearningWorkerRequest):
                raise ValueError("CREATIVE_COHORT_WORKFLOW_TYPE_MISMATCH")
            plan = validate_external_item_learning_execution_plan(
                row, workflow_id=selection.workflow_id, step_key="extract", request=request
            )
            if plan.plan_sha256 != selection.plan_sha256:
                raise ValueError("CREATIVE_COHORT_WORKFLOW_POLICY_MISMATCH")
        for scope in self.scope.history_scopes:
            if (
                plan.preset_id == scope.extraction_preset.preset_id
                and plan.preset_revision_id == scope.extraction_preset.preset_revision_id
                and plan.preset_sha256 == scope.extraction_preset.sha256
                and plan.capacity_policy_revision_id == scope.capacity_policy_revision_id
                and plan.workflow_definition_sha256 == scope.workflow_definition_sha256
            ):
                return self.learning_by_scope[scope.cohort_id]
        raise ValueError("CREATIVE_COHORT_WORKFLOW_POLICY_MISMATCH")

    def advance_once(self) -> CreativeCohortProgress:
        if self.cursor == len(self.targets):
            return self.progress("COMPLETED", None, self.cursor)
        if self.current is None:
            self.current = CreativeSourceExecution(self.targets[self.cursor])
        current = self.current
        self.advance_report(current)
        if current.state != "READY_TO_PUBLISH":
            return self.progress(current.state, current, self.cursor)
        self.publish_sources((current,))
        self.cursor += 1
        result = self.progress("VERIFIED", current, self.cursor)
        self.current = None
        return result

    def close(self) -> None:
        """Serial owner has no in-process background work to drain."""

    def advance_report(self, current: CreativeSourceExecution) -> None:
        target = current.target
        if current.selection is None:
            registered = self.registration.find_registered_source(
                target, requested_by_operator_id=self.cohort.requested_by_operator_id
            )
            if registered is not None:
                if registered.lineage.import_id != self.cohort.import_id:
                    raise ValueError("CREATIVE_COHORT_REGISTERED_IMPORT_MISMATCH")
                current.registered = registered
                current.selection = registered.lineage.selection
            else:
                current.selection = self.preparation.prepare(target)
        selection = current.selection
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, selection.workflow_id)
            if workflow is None:
                raise ValueError("CREATIVE_COHORT_WORKFLOW_MISSING")
            state = workflow.state
        if state in {"FAILED", "CANCELLED"}:
            raise ValueError("CREATIVE_COHORT_EXTRACTION_TERMINAL_FAILURE")
        if state != "COMPLETED":
            if not current.started:
                with self.sessions.begin() as session:
                    start_prepared_external_item_learning(
                        session,
                        selection=selection,
                        operator_id=self.cohort.requested_by_operator_id,
                        source_authorizer=self.preparation.source,
                        page_publisher=self.publisher,
                    )
                current.started = True
            current.state = "EXTRACTING"
            return
        if current.registered is None:
            current.registered = self.registration.register_completed(
                selection, requested_by_operator_id=self.cohort.requested_by_operator_id
            )
        if current.analysis is not None:
            with self.sessions() as session:
                run = session.get(KnowledgeAnalysisRunRecord, current.analysis.analysis_run_id)
                if run is None:
                    raise ValueError("CREATIVE_COHORT_ANALYSIS_MISSING")
                if run.state in {"FAILED", "REJECTED", "CANCELLED"}:
                    raise ValueError("CREATIVE_COHORT_ANALYSIS_TERMINAL_FAILURE")
                if run.state not in {"ACCEPTED", "NEEDS_REVIEW", "VALIDATING"}:
                    workflow = session.get(WorkflowInstanceRecord, run.workflow_id)
                    if workflow is not None and workflow.state not in {
                        "COMPLETED",
                        "FAILED",
                        "CANCELLED",
                    }:
                        current.state = "ANALYZING"
                        return
        learning = self._learning_for_registered(current.registered)
        progress = learning.advance_analysis(
            item_revision_id=current.registered.item_revision_id,
            requested_by_operator_id=self.cohort.requested_by_operator_id,
        )
        current.analysis = progress
        if progress.analysis_state in {"FAILED", "REJECTED", "CANCELLED"}:
            raise ValueError("CREATIVE_COHORT_ANALYSIS_TERMINAL_FAILURE")
        current.state = "READY_TO_PUBLISH" if progress.analysis_state == "ACCEPTED" else "ANALYZING"

    def publish_sources(self, sources: tuple[CreativeSourceExecution, ...]) -> None:
        if not sources or any(
            entry.state != "READY_TO_PUBLISH" or entry.analysis is None or entry.registered is None
            for entry in sources
        ):
            raise ValueError("CREATIVE_COHORT_PUBLICATION_NOT_READY")
        published = self.learning.publish_accepted(
            tuple(entry.analysis for entry in sources if entry.analysis is not None),
            requested_by_operator_id=self.cohort.requested_by_operator_id,
        )
        by_revision = {entry.item_revision_id: entry for entry in published}
        if len(by_revision) != len(sources):
            raise ValueError("CREATIVE_COHORT_PUBLICATION_MISMATCH")
        for entry in sources:
            assert entry.registered is not None
            progress = by_revision.get(entry.registered.item_revision_id)
            if progress is None or progress.graph_snapshot_revision_id is None:
                raise ValueError("CREATIVE_COHORT_PUBLICATION_MISMATCH")
            self._verify_read(entry.registered, progress.graph_snapshot_revision_id)
            entry.analysis = progress
            entry.state = "VERIFIED"

    def _verify_read(self, registered: RegisteredCreativeItem, graph_revision: str) -> None:
        with self.sessions() as session:
            revision = session.get(ItemRevisionRecord, registered.item_revision_id)
            snapshot = session.get(KnowledgeGraphSnapshotRecord, graph_revision)
            if revision is None or snapshot is None:
                raise ValueError("CREATIVE_COHORT_READ_POINTER_MISSING")
            request = ChatKnowledgeCatalogRequest.model_validate(
                {
                    "actor_id": self.cohort.requested_by_operator_id,
                    "purpose": "MATERIALIZE",
                    "selection": {
                        "references": [
                            {
                                "item_id": revision.item_id,
                                "item_revision_id": revision.item_revision_id,
                                "manifest_sha256": revision.manifest_sha256,
                            }
                        ],
                        "snapshot": {
                            "graph_snapshot_revision_id": graph_revision,
                            "sha256": snapshot.snapshot_sha256,
                        },
                    },
                }
            )
        reply = self.read.resolve(request)
        reports = (
            [source for source in reply.context.sources if source.kind == "SOLUTION_REPORT"]
            if reply.context
            else []
        )
        if (
            len(reports) != 1
            or reports[0].pointer != registered.lineage.role_result
            or any(code not in reports[0].text for code in registered.lineage.warning_codes)
        ):
            raise ValueError("CREATIVE_COHORT_READ_NOTES_MISSING")

    def progress(
        self,
        state: str,
        current: CreativeSourceExecution | None,
        verified_count: int,
        *,
        active_sources: tuple[tuple[str, str], ...] = (),
    ) -> CreativeCohortProgress:
        return CreativeCohortProgress(
            self.scope.cohort_id,
            len(self.targets),
            verified_count,
            current.target.external_number if current else None,
            state,
            current.selection.workflow_id if current and current.selection else None,
            current.registered.item_revision_id if current and current.registered else None,
            current.analysis.analysis_run_id if current and current.analysis else None,
            current.analysis.graph_snapshot_revision_id if current and current.analysis else None,
            active_sources,
        )

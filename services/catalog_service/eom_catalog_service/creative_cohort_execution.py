"""One-at-a-time advancement over existing Workflow, Registry and Graph owners."""

from dataclasses import dataclass

from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_catalog_contracts.creative_learning_continuation import CreativeLearningExecutionScope
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.preset_model_selection import validated_preset
from eom_orchestrator.settings import Settings
from eom_protocol.general_chat_grounding import ChatKnowledgeCatalogRequest
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow_runner.external_item_learning_start import start_prepared_external_item_learning
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Engine

from eom_catalog_service.chat_knowledge_resolution import ChatKnowledgeResolutionService
from eom_catalog_service.creative_cohort_preparation import CreativeCohortPreparationService
from eom_catalog_service.creative_item_graph_learning import CreativeItemGraphLearningService
from eom_catalog_service.creative_item_registration import (
    CreativeItemRegistrationService,
    RegisteredCreativeItem,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
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
        self.learning = CreativeItemGraphLearningService(
            engine,
            access_policy_revision_id=cohort.access_policy_revision_id,
            preset_key="creative-knowledge-analysis",
            preset_id=cohort.analysis_preset.preset_id,
            preset_revision_id=cohort.analysis_preset.preset_revision_id,
            risk_policy_revision_id=cohort.risk_policy_revision_id,
            settings=catalog_settings,
        )
        self.read = ChatKnowledgeResolutionService(engine)
        self._require_pins()
        indexed = {target.external_number: target for target in cohort.targets}
        seed = indexed[cohort.seed_external_number]
        self.targets = (seed, *(target for target in cohort.targets if target != seed))
        self.cursor = 0
        self.selection: ExternalItemLearningRoleSelection | None = None
        self.started = False
        self.registered: RegisteredCreativeItem | None = None
        self.analysis_run_id: str | None = None

    def _require_pins(self) -> None:
        with self.sessions() as session:
            for pin, purpose in (
                (
                    self.scope.extraction_preset,
                    creative_learning_profile(self.scope.workflow_definition_version).preset_key,
                ),
                (self.cohort.analysis_preset, "creative-knowledge-analysis"),
            ):
                row = session.get(ExecutionPresetRevisionRecord, pin.preset_revision_id)
                preset = validated_preset(row) if row else None
                logical = session.get(ExecutionPresetRecord, pin.preset_id)
                if (
                    preset is None
                    or preset.state != "RELEASED"
                    or preset.preset_id != pin.preset_id
                    or preset.content_sha256 != pin.sha256
                    or preset.capacity_policy_revision_id != self.cohort.capacity_policy_revision_id
                    or logical is None
                    or logical.state != "ACTIVE"
                    or logical.preset_key != purpose
                ):
                    raise ValueError("CREATIVE_COHORT_PRESET_PIN_MISMATCH")
            risk = KnowledgeAnalysisApplicationService.risk_policy(
                session, self.cohort.risk_policy_revision_id
            )
            if risk.content_sha256 != self.cohort.risk_policy_sha256:
                raise ValueError("CREATIVE_COHORT_RISK_POLICY_PIN_MISMATCH")
        if self.learning.access_policy_sha256 != self.cohort.access_policy_sha256:
            raise ValueError("CREATIVE_COHORT_ACCESS_POLICY_PIN_MISMATCH")

    def advance_once(self) -> CreativeCohortProgress:
        if self.cursor == len(self.targets):
            return self._progress("COMPLETED", None)
        target = self.targets[self.cursor]
        if self.selection is None:
            registered = self.registration.find_registered_source(
                target, requested_by_operator_id=self.cohort.requested_by_operator_id
            )
            if registered is not None:
                if registered.lineage.import_id != self.cohort.import_id:
                    raise ValueError("CREATIVE_COHORT_REGISTERED_IMPORT_MISMATCH")
                self.registered = registered
                self.selection = registered.lineage.selection
            else:
                self.selection = self.preparation.prepare(target)
        selection = self.selection
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, selection.workflow_id)
            if workflow is None:
                raise ValueError("CREATIVE_COHORT_WORKFLOW_MISSING")
            state = workflow.state
        if state in {"FAILED", "CANCELLED"}:
            raise ValueError("CREATIVE_COHORT_EXTRACTION_TERMINAL_FAILURE")
        if state != "COMPLETED":
            if not self.started:
                with self.sessions.begin() as session:
                    start_prepared_external_item_learning(
                        session,
                        selection=selection,
                        operator_id=self.cohort.requested_by_operator_id,
                        source_authorizer=self.preparation.source,
                        page_publisher=self.publisher,
                    )
                self.started = True
            return self._progress("EXTRACTING", target.external_number)
        if self.registered is None:
            self.registered = self.registration.register_completed(
                selection, requested_by_operator_id=self.cohort.requested_by_operator_id
            )
        if self.analysis_run_id is not None:
            with self.sessions() as session:
                run = session.get(KnowledgeAnalysisRunRecord, self.analysis_run_id)
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
                        return self._progress("ANALYZING", target.external_number)
        progress = self.learning.advance(
            item_revision_id=self.registered.item_revision_id,
            requested_by_operator_id=self.cohort.requested_by_operator_id,
        )
        self.analysis_run_id = progress.analysis_run_id
        if progress.analysis_state in {"FAILED", "REJECTED", "CANCELLED"}:
            raise ValueError("CREATIVE_COHORT_ANALYSIS_TERMINAL_FAILURE")
        if progress.graph_snapshot_revision_id is None:
            return self._progress("ANALYZING", target.external_number)
        self._verify_read(progress.graph_snapshot_revision_id)
        self.cursor += 1
        verified = self._progress(
            "VERIFIED", target.external_number, graph_revision=progress.graph_snapshot_revision_id
        )
        self.selection, self.registered, self.analysis_run_id = None, None, None
        self.started = False
        return verified

    def _verify_read(self, graph_revision: str) -> None:
        registered = self.registered
        if registered is None:
            raise ValueError("CREATIVE_COHORT_REGISTERED_ITEM_MISSING")
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

    def _progress(
        self, state: str, number: str | None, *, graph_revision: str | None = None
    ) -> CreativeCohortProgress:
        return CreativeCohortProgress(
            self.scope.cohort_id,
            len(self.targets),
            self.cursor,
            number,
            state,
            self.selection.workflow_id if self.selection else None,
            self.registered.item_revision_id if self.registered else None,
            self.analysis_run_id,
            graph_revision,
        )

"""Connect uploaded material tasks to the existing analysis and shared Graph owners."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    ApprovedItemKnowledgeSourceV2,
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    KnowledgeAnalysisApplicationResult,
    PublishKnowledgeGraphSnapshotCommand,
    PublishKnowledgeGraphSnapshotCommandV2,
    PublishKnowledgeGraphSnapshotCommandV3,
    PublishKnowledgeGraphSnapshotCommandV4,
    PublishKnowledgeGraphSnapshotCommandV5,
    PublishKnowledgeGraphSnapshotCommandV6,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_knowledge_analysis import (
    CreateMaterialKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeSourceV5,
    KnowledgeAnalysisRequestV12,
    MaterialKnowledgeAnalysisSelection,
)
from eom_identifiers import content_sha256
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow.control_plane import ExecutionPresetRevision
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
)
from eom_catalog_service.curriculum_graph_structure import (
    extend_integrated_science_structure_with_documents,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_graph_projection import (
    CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
    AcceptedAnalysisProposal,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_models import MaterialLearningTaskRecord
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_task_history import read_material_task_histories
from eom_catalog_service.material_task_results import resolve_completed_material_task
from eom_catalog_service.settings import CatalogSettings

_STRUCTURE_PUBLICATION: Mapping[str, type[PublishKnowledgeGraphSnapshotCommand]] = MappingProxyType(
    {
        f"eom://schemas/knowledge/knowledge-graph-structure-manifest/{version}.0": model
        for version, model in (
            (2, PublishKnowledgeGraphSnapshotCommandV2),
            (3, PublishKnowledgeGraphSnapshotCommandV3),
            (4, PublishKnowledgeGraphSnapshotCommandV4),
            (5, PublishKnowledgeGraphSnapshotCommandV5),
            (6, PublishKnowledgeGraphSnapshotCommandV6),
        )
    }
)


@dataclass(frozen=True, slots=True)
class MaterialAnalysisControls:
    item: ExecutionPresetRevision
    document: ExecutionPresetRevision
    solution: ExecutionPresetRevision
    risk_policy_revision_id: str
    access_policy_revision_id: str


class MaterialGraphLearningService:
    """No fabricated old analysis receipt, parallel Graph, or direct INDEX mutation."""

    def __init__(
        self,
        engine: Engine,
        *,
        controls: MaterialAnalysisControls,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.controls = controls
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.analyses = KnowledgeAnalysisApplicationService(engine, self.settings)
        self.publication = KnowledgeGraphPublicationService(engine, self.settings)
        self.sources = CatalogMaterialLearningSourceAuthorizer(engine, self.settings)
        self.automatic = AutomaticItemGraphPublicationService(
            engine,
            access_policy_revision_id=controls.access_policy_revision_id,
            publication=self.publication,
            retrieval=KnowledgeRetrievalApplicationService(engine, self.settings),
        )

    def advance_item_analysis(
        self, *, task_id: str, item_revision_id: str, operator_id: str
    ) -> KnowledgeAnalysisApplicationResult:
        with self.sessions() as session:
            resolved = resolve_completed_material_task(
                session, self.artifacts, task_id=task_id, operator_id=operator_id
            )
            self.sources.reauthorize(session, operator_id=operator_id, work=resolved.work)
            task = session.get(MaterialLearningTaskRecord, task_id)
            if task is None or task.item_revision_id != item_revision_id:
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
            history = read_material_task_histories(session, (task,))[task.task_id]
            previous = history.analysis_owner()
            prior = (
                session.get(KnowledgeAnalysisRunRecord, previous.analysis_run_id)
                if previous
                else None
            )
            predecessor = None
            if prior is not None:
                assert previous is not None
                if (
                    prior.canonical_request.get("source", {}).get("item_revision_id")
                    != item_revision_id
                ):
                    raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
                if (
                    prior.state not in {"FAILED", "REJECTED", "CANCELLED"}
                    or previous.task_id == task.task_id
                ):
                    return self._reconcile(prior.analysis_run_id, operator_id)
                predecessor = prior.analysis_run_id
        preset = self.controls.item
        run = self.analyses.create_with_pinned_preset(
            CreateKnowledgeAnalysisCommand(
                source=ApprovedItemKnowledgeAnalysisSelection(
                    source_class="APPROVED_ITEM",
                    item_revision_id=item_revision_id,
                ),
                preset_key="material-item-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id=self.controls.risk_policy_revision_id,
                requested_by=operator_id,
                idempotency_key="material-base:" + task_id,
                predecessor_analysis_run_id=predecessor,
            ),
            preset_id=preset.preset_id,
            preset_revision_id=preset.preset_revision_id,
        )
        return self._advance(run, operator_id)

    def advance_item_solution(
        self, *, base_analysis_run_id: str, task_id: str, operator_id: str
    ) -> KnowledgeAnalysisApplicationResult:
        preset = self.controls.solution
        with self.sessions() as session:
            authorize_material_learning(session, operator_id)
            task = session.get(MaterialLearningTaskRecord, task_id)
            if task is None:
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
            history = read_material_task_histories(session, (task,))[task.task_id]
            base = history.analysis_owner()
            if base is None or base.analysis_run_id != base_analysis_run_id:
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
            previous = history.analysis_owner(solution=True)
            prior = (
                session.get(KnowledgeAnalysisRunRecord, previous.solution_analysis_run_id)
                if previous
                else None
            )
            if (
                previous is not None
                and prior is not None
                and (
                    prior.state not in {"FAILED", "REJECTED", "CANCELLED"}
                    or previous.task_id == task.task_id
                )
            ):
                if prior.predecessor_analysis_run_id != base_analysis_run_id:
                    raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
                return self._reconcile(prior.analysis_run_id, operator_id)
        run = self.analyses.create_solution_with_pinned_preset(
            CreateKnowledgeSolutionAnalysisCommand(
                base_analysis_run_id=base_analysis_run_id,
                requested_by=operator_id,
                idempotency_key="material-solution:" + task_id,
            ),
            preset_id=preset.preset_id,
            preset_revision_id=preset.preset_revision_id,
        )
        return self._advance(run, operator_id)

    def _reconcile(
        self, analysis_run_id: str, operator_id: str
    ) -> KnowledgeAnalysisApplicationResult:
        run = self.analyses.reconcile(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=analysis_run_id, requested_by=operator_id
            )
        )
        return self._advance(run, operator_id)

    def advance_document_analysis(
        self,
        *,
        task_id: str,
        selection: MaterialKnowledgeAnalysisSelection,
        operator_id: str,
    ) -> KnowledgeAnalysisApplicationResult:
        preset = self.controls.document
        run = self.analyses.create_material_with_pinned_preset(
            CreateMaterialKnowledgeAnalysisCommand(
                material_task_id=task_id,
                source=selection,
                preset_key="material-knowledge-analysis",
                risk_policy_revision_id=self.controls.risk_policy_revision_id,
                requested_by=operator_id,
                idempotency_key="material-knowledge:" + task_id,
            ),
            preset_id=preset.preset_id,
            preset_revision_id=preset.preset_revision_id,
        )
        return self._advance(run, operator_id)

    def _advance(
        self, run: KnowledgeAnalysisApplicationResult, operator_id: str
    ) -> KnowledgeAnalysisApplicationResult:
        if run.state in {"VALIDATING", "NEEDS_REVIEW"}:
            return self.analyses.accept_validated_without_review(
                analysis_run_id=run.analysis_run_id,
                requested_by=operator_id,
            )
        if run.state not in {"ACCEPTED", "FAILED", "REJECTED", "CANCELLED"}:
            run = self.analyses.reconcile(
                ReconcileKnowledgeAnalysisCommand(
                    analysis_run_id=run.analysis_run_id,
                    requested_by=operator_id,
                )
            )
            if run.state in {"VALIDATING", "NEEDS_REVIEW"}:
                return self.analyses.accept_validated_without_review(
                    analysis_run_id=run.analysis_run_id,
                    requested_by=operator_id,
                )
        return run

    def publish_item(
        self, *, task_id: str, analysis_run_id: str, item_revision_id: str, operator_id: str
    ) -> str:
        def validate(session: Session, analyses: tuple[AcceptedAnalysisProposal, ...]) -> None:
            self._authorize_publication(session, operator_id)
            resolved = resolve_completed_material_task(
                session, self.artifacts, task_id=task_id, operator_id=operator_id
            )
            self.sources.reauthorize(session, operator_id=operator_id, work=resolved.work)
            if (
                len(analyses) != 1
                or analyses[0].analysis_run_id != analysis_run_id
                or not isinstance(analyses[0].source, ApprovedItemKnowledgeSourceV2)
                or analyses[0].source.item_revision_id != item_revision_id
                or analyses[0].source.source_class != "APPROVED_ITEM"
            ):
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")

        for _ in range(3):
            context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
            with self.sessions() as session:
                exact = (
                    self.publication.resolve_accepted_analyses(session, (analysis_run_id,))[
                        analysis_run_id
                    ].analysis,
                )
                validate(session, exact)
            if analysis_run_id in context.accepted_analysis_run_ids:
                return context.graph_snapshot_revision_id
            try:
                receipt = self.automatic.publish(
                    (
                        AutomaticItemGraphCandidate(
                            analysis_run_id, operator_id, context.graph_snapshot_revision_id
                        ),
                    ),
                    required_source_class="APPROVED_ITEM",
                    retrieval_idempotency_namespace="material-item-align",
                    publication_idempotency_namespace="material-item-graph",
                    publisher_version=CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
                    analysis_validator=validate,
                )
                return receipt.graph_publication.graph_snapshot.graph_snapshot_revision_id
            except KnowledgeGraphPublicationError as error:
                if error.code != "KNOWLEDGE_GRAPH_STALE_CURRENT":
                    raise
        raise ValueError("MATERIAL_GRAPH_PUBLICATION_BUSY")

    def publish_document(self, *, analysis_run_id: str, operator_id: str) -> str:
        for _ in range(3):
            context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
            with self.sessions() as session:
                analyses = (
                    self.publication.resolve_accepted_analyses(session, (analysis_run_id,))[
                        analysis_run_id
                    ].analysis,
                )
                if not isinstance(analyses[0].source, EducationalDocumentKnowledgeSourceV5):
                    raise ValueError("MATERIAL_GRAPH_DOCUMENT_SOURCE_MISMATCH")
                self._authorize_publication(session, operator_id)
                run = session.get(KnowledgeAnalysisRunRecord, analysis_run_id)
                if (
                    run is None
                    or run.created_by_operator_id != operator_id
                    or run.state != "ACCEPTED"
                ):
                    raise ValueError("MATERIAL_GRAPH_DOCUMENT_OWNER_MISMATCH")
                request = KnowledgeAnalysisRequestV12.model_validate(run.canonical_request)
                if request.source != analyses[0].source:
                    raise ValueError("MATERIAL_GRAPH_DOCUMENT_SOURCE_MISMATCH")
                authorized_at = run.completed_at or run.created_at
            if analysis_run_id in context.accepted_analysis_run_ids:
                return context.graph_snapshot_revision_id
            structure = extend_integrated_science_structure_with_documents(
                context.structure,
                analyses,
                created_at=max(authorized_at, context.structure.created_at),
            )
            pointer = self.publication.commit_structure_manifest(
                structure,
                reviewed_base_snapshot_revision_id=context.graph_snapshot_revision_id,
            )
            value = dict(
                schema_version="knowledge-graph-publication/"
                + structure.schema_version.rsplit("/", 1)[1],
                corpus_key=context.corpus_key,
                display_name=context.display_name,
                accepted_analysis_run_ids=list(structure.source_analysis_run_ids),
                structure_manifest=pointer.model_dump(mode="json"),
                expected_current_snapshot_revision_id=context.graph_snapshot_revision_id,
                publisher_version=CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
                published_by_operator_id=operator_id,
                idempotency_key="material-document-graph:"
                + content_sha256(
                    {
                        "prior": context.graph_snapshot_revision_id,
                        "analysis": analysis_run_id,
                    }
                )[7:],
                requested_at=structure.created_at.isoformat().replace("+00:00", "Z"),
            )
            publication_type = _STRUCTURE_PUBLICATION.get(pointer.schema_ref)
            if publication_type is None:
                raise ValueError("MATERIAL_GRAPH_STRUCTURE_UNSUPPORTED")
            command = publication_type.model_validate(
                {
                    **value,
                    "request_sha256": content_sha256(value),
                }
            )
            try:
                result = self.publication.publish(command, authorized_at=datetime.now(UTC))
                return result.graph_snapshot.graph_snapshot_revision_id
            except KnowledgeGraphPublicationError as error:
                if error.code != "KNOWLEDGE_GRAPH_STALE_CURRENT":
                    raise
        raise ValueError("MATERIAL_GRAPH_PUBLICATION_BUSY")

    @staticmethod
    def _authorize_publication(session: Session, operator_id: str) -> None:
        authorize_material_learning(session, operator_id)
        required = {
            PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
            PermissionKey.KNOWLEDGE_GRAPH_READ,
            PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
        }
        if not required.issubset(effective_permissions(session, operator_id)):
            raise ValueError("MATERIAL_GRAPH_PERMISSION_DENIED")

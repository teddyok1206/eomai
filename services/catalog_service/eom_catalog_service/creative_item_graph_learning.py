"""Source-bound creative analyses append to the existing shared education Graph."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    ApprovedItemKnowledgeSourceV2,
    CreateKnowledgeAnalysisCommand,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.creative_knowledge_controls import release_creative_knowledge_controls
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.settings import Settings
from eom_workflow.control_plane import ExecutionPresetRevision
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
)
from eom_catalog_service.creative_registered_report import (
    RegisteredCreativeReport,
    load_registered_creative_report,
)
from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.knowledge_graph_models import KnowledgeSnapshotAnalysisRecord
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import KnowledgeGraphPublicationService
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.settings import CatalogSettings

_PERMISSIONS = frozenset(
    {
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
        PermissionKey.KNOWLEDGE_GRAPH_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
    }
)


@dataclass(frozen=True, slots=True)
class CreativeGraphLearningProgress:
    item_revision_id: str
    analysis_run_id: str
    analysis_state: str
    graph_snapshot_revision_id: str | None


def prepare_creative_analysis_controls(
    engine: Engine,
    *,
    selection: ExternalItemLearningRoleSelection,
    baseline_revision_id: str,
    source_commit: str,
    settings: CatalogSettings,
) -> ExecutionPresetRevision:
    """An admitted source owner may bind analysis to the same support-05 capacity."""
    sessions = build_session_factory(engine)
    artifacts = CatalogArtifactService(engine, settings)
    authorizer = CatalogExternalItemLearningSourceAuthorizer(
        ExternalItemPreviewProjectionService(engine, settings=settings)
    )
    from eom_catalog_service.creative_learning_proposal import (
        resolve_completed_creative_learning_proposal,
    )

    with sessions() as session:
        resolved = resolve_completed_creative_learning_proposal(session, artifacts, selection)
        plan = session.get(ResolvedExecutionPlanRecord, selection.plan_id)
        if plan is None:
            raise ValueError("CREATIVE_GRAPH_PLAN_MISSING")
        capacity_revision_id = plan.capacity_policy_revision_id

    def authorize(operator_id: str) -> None:
        if operator_id != resolved.operator_id:
            raise ValueError("CREATIVE_GRAPH_PERMISSION_DENIED")
        with sessions() as session:
            authorizer.reauthorize(session, operator_id=operator_id, source=resolved.work.source)
            if PermissionKey.EXECUTION_PRESET_MANAGE not in effective_permissions(
                session, operator_id
            ):
                raise ValueError("CREATIVE_GRAPH_PERMISSION_DENIED")

    return release_creative_knowledge_controls(
        sessions,
        ControlArtifactPublisher(engine, Settings.from_environment()),
        baseline_revision_id=baseline_revision_id,
        capacity_revision_id=capacity_revision_id,
        operator_id=resolved.operator_id,
        source_commit=source_commit,
        authorize=authorize,
    )


class CreativeItemGraphLearningService:
    """No duplicate Graph, invented exam occurrence, or rewritten failed analysis."""

    def __init__(
        self,
        engine: Engine,
        *,
        access_policy_revision_id: str,
        preset_key: str,
        preset_id: str,
        preset_revision_id: str,
        risk_policy_revision_id: str,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.analyses = KnowledgeAnalysisApplicationService(engine, self.settings)
        self.publication = KnowledgeGraphPublicationService(engine, self.settings)
        self.automatic = AutomaticItemGraphPublicationService(
            engine,
            access_policy_revision_id=access_policy_revision_id,
            publication=self.publication,
            retrieval=KnowledgeRetrievalApplicationService(engine, self.settings),
        )
        self.source = CatalogExternalItemLearningSourceAuthorizer(
            ExternalItemPreviewProjectionService(engine, settings=self.settings)
        )
        self.preset_key, self.preset_id, self.preset_revision_id = (
            preset_key,
            preset_id,
            preset_revision_id,
        )
        self.risk_policy_revision_id = risk_policy_revision_id

    def _validate_source(
        self, session: Session, revision: ItemRevisionRecord, operator_id: str
    ) -> RegisteredCreativeReport:
        report = load_registered_creative_report(session, self.artifacts, revision)
        if report.lineage.requested_by_operator_id != operator_id or not _PERMISSIONS.issubset(
            effective_permissions(session, operator_id)
        ):
            raise ValueError("CREATIVE_GRAPH_PERMISSION_DENIED")
        self.source.reauthorize(
            session, operator_id=operator_id, source=report.proposal.work.source
        )
        return report

    def advance(
        self, *, item_revision_id: str, requested_by_operator_id: str
    ) -> CreativeGraphLearningProgress:
        with self.sessions() as session:
            revision = session.get(ItemRevisionRecord, item_revision_id)
            if revision is None or revision.revision_state != "APPROVED":
                raise ValueError("CREATIVE_GRAPH_SOURCE_UNAVAILABLE")
            report = self._validate_source(session, revision, requested_by_operator_id)
        run = self.analyses.create_with_pinned_preset(
            CreateKnowledgeAnalysisCommand(
                source=ApprovedItemKnowledgeAnalysisSelection(
                    source_class="APPROVED_ITEM", item_revision_id=item_revision_id
                ),
                preset_key=self.preset_key,
                general_knowledge_mode="AUXILIARY_UNATTRIBUTED",
                risk_policy_revision_id=self.risk_policy_revision_id,
                requested_by=requested_by_operator_id,
                idempotency_key="creative-analysis:" + report.lineage.lineage_sha256[7:],
            ),
            preset_id=self.preset_id,
            preset_revision_id=self.preset_revision_id,
        )
        if run.state in {"VALIDATING", "NEEDS_REVIEW"}:
            run = self.analyses.accept_validated_without_review(
                analysis_run_id=run.analysis_run_id, requested_by=requested_by_operator_id
            )
        elif run.state not in {"ACCEPTED", "FAILED", "REJECTED", "CANCELLED"}:
            run = self.analyses.reconcile(
                ReconcileKnowledgeAnalysisCommand(
                    analysis_run_id=run.analysis_run_id, requested_by=requested_by_operator_id
                )
            )
        if run.state != "ACCEPTED":
            return CreativeGraphLearningProgress(
                item_revision_id, run.analysis_run_id, run.state, None
            )
        context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)

        def validate(session: Session, analyses: tuple[AcceptedAnalysisProposal, ...]) -> None:
            current = session.get(ItemRevisionRecord, item_revision_id, populate_existing=True)
            if current is None or len(analyses) != 1:
                raise ValueError("CREATIVE_GRAPH_ANALYSIS_INVALID")
            exact = self._validate_source(session, current, requested_by_operator_id)
            analysis = analyses[0]
            source = analysis.source
            if (
                analysis.analysis_run_id != run.analysis_run_id
                or not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or source.source_class != "APPROVED_ITEM"
                or source.item_revision_id != item_revision_id
                or source.item_id != current.item_id
                or source.artifact_member.sha256 != exact.lineage.registered_content_sha256
            ):
                raise ValueError("CREATIVE_GRAPH_ANALYSIS_SOURCE_MISMATCH")

        if run.analysis_run_id in context.accepted_analysis_run_ids:
            with self.sessions() as session:
                bound = session.scalar(
                    select(KnowledgeSnapshotAnalysisRecord).where(
                        KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                        == context.graph_snapshot_revision_id,
                        KnowledgeSnapshotAnalysisRecord.analysis_run_id == run.analysis_run_id,
                    )
                )
                if bound is None or bound.source_revision_id != item_revision_id:
                    raise ValueError("CREATIVE_GRAPH_REPLAY_MISMATCH")
            graph_revision = context.graph_snapshot_revision_id
        else:
            published = self.automatic.publish(
                (
                    AutomaticItemGraphCandidate(
                        run.analysis_run_id,
                        requested_by_operator_id,
                        context.graph_snapshot_revision_id,
                    ),
                ),
                required_source_class="APPROVED_ITEM",
                retrieval_idempotency_namespace="creative-item-align",
                publication_idempotency_namespace="creative-item-graph",
                publisher_version="1.9.0",
                analysis_validator=validate,
            )
            graph_revision = published.graph_publication.graph_snapshot.graph_snapshot_revision_id
        return CreativeGraphLearningProgress(
            item_revision_id, run.analysis_run_id, run.state, graph_revision
        )

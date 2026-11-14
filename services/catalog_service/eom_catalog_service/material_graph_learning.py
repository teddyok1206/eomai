"""Connect uploaded material tasks to the existing analysis and shared Graph owners."""

import re
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
from eom_orchestrator.preset_model_selection import current_model_preset
from eom_workflow.control_plane import ExecutionPresetRevision
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    MAX_AUTOMATIC_GRAPH_BATCH_SIZE,
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
from eom_catalog_service.material_learning_models import (
    MaterialLearningEventRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_registered_base_recovery import (
    REGISTERED_BASE_RECOVERY_CODES,
    CreateMaterialBaseRecoveryCommand,
)
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


@dataclass(frozen=True, slots=True)
class MaterialItemGraphPublicationTarget:
    task_id: str
    analysis_run_id: str
    item_revision_id: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or re.fullmatch(prefix + r"[0-9a-f]{32}", value) is None
            for prefix, value in (
                ("materialtask_", self.task_id),
                ("analysisrun_", self.analysis_run_id),
                ("itemrev_", self.item_revision_id),
            )
        ):
            raise ValueError("MATERIAL_GRAPH_ITEM_TARGET_INVALID")


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
            base_recovery = None
            if prior is not None:
                assert previous is not None
                if (
                    prior.canonical_request.get("source", {}).get("item_revision_id")
                    != item_revision_id
                ):
                    raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
                if (
                    prior.state == "ACCEPTED"
                    and previous.task_id != task.task_id
                    and previous.state == "FAILED"
                    and previous.error_code in REGISTERED_BASE_RECOVERY_CODES
                    and session.scalar(
                        select(MaterialLearningEventRecord.event_id).where(
                            MaterialLearningEventRecord.run_id == task.run_id,
                            MaterialLearningEventRecord.sequence == 1,
                            MaterialLearningEventRecord.event_type
                            == "MATERIAL_NATIVE_REFERENCE_RETRY_STARTED",
                        )
                    )
                    is not None
                ):
                    base_recovery = CreateMaterialBaseRecoveryCommand(
                        task.task_id, prior.analysis_run_id, operator_id
                    )
                elif (
                    prior.state not in {"FAILED", "REJECTED", "CANCELLED"}
                    or previous.task_id == task.task_id
                ):
                    return self._reconcile(prior.analysis_run_id, operator_id)
                predecessor = prior.analysis_run_id
            if base_recovery is not None:
                preset = None
            else:
                preset = current_model_preset(session, self.controls.item)
        if base_recovery is not None:
            return self._advance(
                self.analyses.create_material_base_recovery(base_recovery), operator_id
            )
        assert preset is not None
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
            preset = current_model_preset(session, self.controls.solution)
        run = self.analyses.create_material_solution_with_pinned_preset(
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
        with self.sessions() as session:
            authorize_material_learning(session, operator_id)
            task = session.get(MaterialLearningTaskRecord, task_id)
            if task is None:
                raise ValueError("MATERIAL_GRAPH_DOCUMENT_SOURCE_MISMATCH")
            history = read_material_task_histories(session, (task,))[task.task_id]
            previous = history.analysis_owner()
            if previous is not None and previous.analysis_run_id is not None:
                return self._reconcile(previous.analysis_run_id, operator_id)
            preset = current_model_preset(session, self.controls.document)
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
        return self.publish_items(
            targets=(
                MaterialItemGraphPublicationTarget(task_id, analysis_run_id, item_revision_id),
            ),
            operator_id=operator_id,
        )

    def publish_items(
        self, *, targets: tuple[MaterialItemGraphPublicationTarget, ...], operator_id: str
    ) -> str:
        """Append one bounded exact set, retaining every task/source fence on replay."""
        if (
            type(targets) is not tuple
            or not 1 <= len(targets) <= MAX_AUTOMATIC_GRAPH_BATCH_SIZE
            or any(type(target) is not MaterialItemGraphPublicationTarget for target in targets)
            or any(
                len({getattr(target, attribute) for target in targets}) != len(targets)
                for attribute in ("task_id", "analysis_run_id", "item_revision_id")
            )
        ):
            raise ValueError("MATERIAL_GRAPH_ITEM_TARGETS_INVALID")
        analysis_ids = tuple(target.analysis_run_id for target in targets)

        def validate(
            session: Session,
            analyses: tuple[AcceptedAnalysisProposal, ...],
            expected: tuple[MaterialItemGraphPublicationTarget, ...],
        ) -> None:
            self._authorize_publication(session, operator_id)
            task_ids = tuple(target.task_id for target in targets)
            tasks_by_id = {
                task.task_id: task
                for task in session.scalars(
                    select(MaterialLearningTaskRecord)
                    .where(MaterialLearningTaskRecord.task_id.in_(task_ids))
                    .execution_options(populate_existing=True)
                )
            }
            if set(tasks_by_id) != set(task_ids):
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
            tasks = tuple(tasks_by_id[task_id] for task_id in task_ids)
            histories = read_material_task_histories(session, tasks)
            for target, task in zip(targets, tasks, strict=True):
                owner = histories[target.task_id].analysis_owner()
                if (
                    task.item_revision_id != target.item_revision_id
                    or owner is None
                    or owner.analysis_run_id != target.analysis_run_id
                ):
                    raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
                resolved = resolve_completed_material_task(
                    session, self.artifacts, task_id=target.task_id, operator_id=operator_id
                )
                self.sources.reauthorize(session, operator_id=operator_id, work=resolved.work)
            by_id = {analysis.analysis_run_id: analysis for analysis in analyses}
            if len(by_id) != len(analyses) or set(by_id) != {
                target.analysis_run_id for target in expected
            }:
                raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")
            for target in expected:
                source = by_id[target.analysis_run_id].source
                if (
                    not isinstance(source, ApprovedItemKnowledgeSourceV2)
                    or source.item_revision_id != target.item_revision_id
                    or source.source_class != "APPROVED_ITEM"
                ):
                    raise ValueError("MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH")

        for _ in range(3):
            context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
            with self.sessions() as session:
                accepted = {}
                # Preserve the public accepted-reader's released three-ID bound.
                for offset in range(0, len(analysis_ids), 3):
                    accepted.update(
                        self.publication.resolve_accepted_analyses(
                            session, analysis_ids[offset : offset + 3]
                        )
                    )
                exact = tuple(accepted[identity].analysis for identity in analysis_ids)
                validate(session, exact, targets)
            included = set(context.accepted_analysis_run_ids)
            pending = tuple(target for target in targets if target.analysis_run_id not in included)
            if not pending:
                return context.graph_snapshot_revision_id

            def validate_pending(
                session: Session,
                analyses: tuple[AcceptedAnalysisProposal, ...],
                expected: tuple[MaterialItemGraphPublicationTarget, ...] = pending,
            ) -> None:
                # The publisher passes only new candidates; existing members still
                # retain the original Material authority and checkpoint checks.
                validate(session, analyses, expected)

            try:
                receipt = self.automatic.publish(
                    tuple(
                        AutomaticItemGraphCandidate(
                            target.analysis_run_id,
                            operator_id,
                            context.graph_snapshot_revision_id,
                        )
                        for target in pending
                    ),
                    required_source_class="APPROVED_ITEM",
                    retrieval_idempotency_namespace="material-item-align",
                    publication_idempotency_namespace="material-item-graph",
                    publisher_version=CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
                    analysis_validator=validate_pending,
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

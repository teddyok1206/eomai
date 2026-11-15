"""Fresh analysis/public solution/Graph for one verified Native image-only successor.

There is no new queue or persistent progress row. Exact receipt-derived keys use
the existing analysis UNIQUE index; polls reconcile those same runs. A failed
run is returned unchanged, never silently replaced with a new paid execution.
"""

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    ApprovedItemKnowledgeSourceV2,
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    KnowledgeAnalysisApplicationResult,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV11,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.material_native_visual_correction import (
    MaterialNativeVisualCorrectionResult,
)
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.preset_model_selection import current_model_preset
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.automatic_item_graph_publication_service import (
    INTEGRATED_SCIENCE_CORPUS_KEY,
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
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
from eom_catalog_service.material_graph_learning import MaterialAnalysisControls
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_native_visual_correction import (
    MaterialNativeVisualCorrectionService,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.solution_evidence_resolution import (
    resolve_registered_solution_evidence_by_base_run,
)

_FAILED = frozenset({"FAILED", "REJECTED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class MaterialNativeVisualCorrectionLearningProgress:
    """Small application value, not a new persistent or worker protocol."""

    state: Literal["BASE_PENDING", "PUBLIC_PENDING", "BASE_FAILED", "PUBLIC_FAILED", "PUBLISHED"]
    correction_receipt_sha256: str
    item_revision_id: str
    base_analysis: KnowledgeAnalysisApplicationResult
    public_analysis: KnowledgeAnalysisApplicationResult | None = None
    graph_snapshot_revision_id: str | None = None


def native_visual_correction_analysis_key(
    receipt: MaterialNativeVisualCorrectionResult, *, kind: Literal["BASE", "PUBLIC"]
) -> str:
    """Indexed immutable receipt identity, not a source/permission claim."""
    prefix = {"PUBLIC": "native-visual-public:", "BASE": "native-visual-base:"}[kind]
    return prefix + receipt.receipt_sha256.removeprefix("sha256:")


class MaterialNativeVisualCorrectionLearningService:
    def __init__(
        self,
        engine: Engine,
        *,
        corrections: MaterialNativeVisualCorrectionService,
        controls: MaterialAnalysisControls,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.corrections = corrections
        self.controls = controls
        self.analyses = KnowledgeAnalysisApplicationService(engine, self.settings)
        self.publication = KnowledgeGraphPublicationService(engine, self.settings)
        self.automatic = AutomaticItemGraphPublicationService(
            engine,
            access_policy_revision_id=controls.access_policy_revision_id,
            publication=self.publication,
            retrieval=KnowledgeRetrievalApplicationService(engine, self.settings),
        )

    def advance(
        self, correction: MaterialNativeVisualCorrectionResult, *, operator_id: str
    ) -> MaterialNativeVisualCorrectionLearningProgress:
        correction = MaterialNativeVisualCorrectionResult.model_validate(
            correction.model_dump(mode="json")
        )
        self.corrections.validate_applied(correction, actor_id=operator_id)
        with self.sessions() as session:
            self._authorize(session, operator_id)
            base_key = native_visual_correction_analysis_key(correction, kind="BASE")
            base_id = self._existing(session, correction, operator_id, base_key)
            preset = current_model_preset(session, self.controls.item) if base_id is None else None
        if base_id is None:
            assert preset is not None
            base = self.analyses.create_with_pinned_preset(
                CreateKnowledgeAnalysisCommand(
                    source=ApprovedItemKnowledgeAnalysisSelection(
                        source_class="APPROVED_ITEM", item_revision_id=correction.item_revision_id
                    ),
                    preset_key="material-item-analysis",
                    general_knowledge_mode="DISABLED",
                    risk_policy_revision_id=self.controls.risk_policy_revision_id,
                    requested_by=operator_id,
                    idempotency_key=base_key,
                ),
                preset_id=preset.preset_id,
                preset_revision_id=preset.preset_revision_id,
            )
            base_id = base.analysis_run_id
        base = self._advance_analysis(base_id, operator_id)
        with self.sessions() as session:
            self._require_analysis(session, correction, operator_id, base_id, base_key)
        self.corrections.validate_applied(correction, actor_id=operator_id)
        if base.state != "ACCEPTED":
            return self._progress(
                correction, "BASE_FAILED" if base.state in _FAILED else "BASE_PENDING", base
            )
        public_key = native_visual_correction_analysis_key(correction, kind="PUBLIC")
        with self.sessions() as session:
            self._authorize(session, operator_id)
            public_id = self._existing(
                session, correction, operator_id, public_key, base_id=base_id
            )
            preset = (
                current_model_preset(session, self.controls.solution) if public_id is None else None
            )
        if public_id is None:
            assert preset is not None
            public = self.analyses.create_material_solution_with_pinned_preset(
                CreateKnowledgeSolutionAnalysisCommand(
                    base_analysis_run_id=base_id,
                    requested_by=operator_id,
                    idempotency_key=public_key,
                ),
                preset_id=preset.preset_id,
                preset_revision_id=preset.preset_revision_id,
            )
            public_id = public.analysis_run_id
        public = self._advance_analysis(public_id, operator_id)
        with self.sessions() as session:
            self._require_analysis(
                session, correction, operator_id, public_id, public_key, base_id=base_id
            )
        self.corrections.validate_applied(correction, actor_id=operator_id)
        if public.state != "ACCEPTED":
            return self._progress(
                correction,
                "PUBLIC_FAILED" if public.state in _FAILED else "PUBLIC_PENDING",
                base,
                public,
            )
        graph = self._publish(correction, operator_id, base_id, public_id)
        return self._progress(correction, "PUBLISHED", base, public, graph)

    @staticmethod
    def _progress(
        correction: MaterialNativeVisualCorrectionResult,
        state: Literal[
            "BASE_PENDING", "PUBLIC_PENDING", "BASE_FAILED", "PUBLIC_FAILED", "PUBLISHED"
        ],
        base: KnowledgeAnalysisApplicationResult,
        public: KnowledgeAnalysisApplicationResult | None = None,
        graph: str | None = None,
    ) -> MaterialNativeVisualCorrectionLearningProgress:
        return MaterialNativeVisualCorrectionLearningProgress(
            state, correction.receipt_sha256, correction.item_revision_id, base, public, graph
        )

    def _advance_analysis(
        self, analysis_run_id: str, operator_id: str
    ) -> KnowledgeAnalysisApplicationResult:
        run = self.analyses.reconcile(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=analysis_run_id, requested_by=operator_id
            )
        )
        if run.state in {"VALIDATING", "NEEDS_REVIEW"}:
            return self.analyses.accept_validated_without_review(
                analysis_run_id=run.analysis_run_id, requested_by=operator_id
            )
        return run

    def _existing(
        self,
        session: Session,
        correction: MaterialNativeVisualCorrectionResult,
        operator_id: str,
        key: str,
        *,
        base_id: str | None = None,
    ) -> str | None:
        row = session.scalar(
            select(KnowledgeAnalysisRunRecord)
            .where(KnowledgeAnalysisRunRecord.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        self._validate_analysis_row(correction, operator_id, row, key, base_id=base_id)
        return row.analysis_run_id

    def _require_analysis(
        self,
        session: Session,
        correction: MaterialNativeVisualCorrectionResult,
        operator_id: str,
        analysis_run_id: str,
        key: str,
        *,
        base_id: str | None = None,
    ) -> KnowledgeAnalysisRunRecord:
        row = session.get(KnowledgeAnalysisRunRecord, analysis_run_id, populate_existing=True)
        if row is None:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_MISMATCH")
        self._validate_analysis_row(correction, operator_id, row, key, base_id=base_id)
        return row

    def _validate_analysis_row(
        self,
        correction: MaterialNativeVisualCorrectionResult,
        operator_id: str,
        row: KnowledgeAnalysisRunRecord,
        key: str,
        *,
        base_id: str | None,
    ) -> None:
        request = (
            KnowledgeAnalysisRequestV2.model_validate(row.canonical_request)
            if base_id is None
            else KnowledgeAnalysisRequestV11.model_validate(row.canonical_request)
        )
        expected_preset = self.controls.item if base_id is None else self.controls.solution
        if (
            row.idempotency_key != key
            or row.created_by_operator_id != operator_id
            or row.item_revision_id != correction.item_revision_id
            or row.item_id != correction.prepared.item_id
            or row.request_sha256 != request.request_sha256
            or row.analysis_request_id != request.analysis_request_id
            or row.predecessor_analysis_run_id != base_id
            or row.preset_id != expected_preset.preset_id
            or row.preset_revision_id != request.execution_preset_revision_id
            or row.preset_id != request.execution_preset_id
            or row.risk_policy_revision_id != self.controls.risk_policy_revision_id
            or row.risk_policy_revision_id != request.risk_policy_revision_id
            or row.source_sha256 != correction.content.sha256
            or row.source_artifact_id != correction.content.artifact_id
            or row.source_artifact_revision_id != correction.content.artifact_revision_id
            or request.general_knowledge_mode != "DISABLED"
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_MISMATCH")
        self._require_source(correction, request.source)

    @staticmethod
    def _require_source(correction: MaterialNativeVisualCorrectionResult, source: object) -> None:
        if not isinstance(source, ApprovedItemKnowledgeSourceV2):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_MISMATCH")
        actual = source.artifact_member
        expected = correction.content
        if (
            source.source_class != "APPROVED_ITEM"
            or source.item_id != correction.prepared.item_id
            or source.item_revision_id != correction.item_revision_id
            or any(
                getattr(actual, field) != getattr(expected, field)
                for field in (
                    "artifact_id",
                    "artifact_revision_id",
                    "member_path",
                    "schema_ref",
                    "media_type",
                    "sha256",
                )
            )
            or actual.bytes != correction.prepared.corrected_content_bytes
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_MISMATCH")

    @staticmethod
    def _authorize(session: Session, operator_id: str) -> None:
        authorize_material_learning(session, operator_id)
        required = {
            PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
            PermissionKey.KNOWLEDGE_GRAPH_READ,
            PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
        }
        if not required.issubset(effective_permissions(session, operator_id)):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_DENIED")

    def _publish(
        self,
        correction: MaterialNativeVisualCorrectionResult,
        operator_id: str,
        base_id: str,
        public_id: str,
    ) -> str:
        def validate(session: Session, analyses: tuple[AcceptedAnalysisProposal, ...]) -> None:
            self._authorize(session, operator_id)
            self.corrections.validate_applied(correction, actor_id=operator_id)
            base = self._require_analysis(
                session,
                correction,
                operator_id,
                base_id,
                native_visual_correction_analysis_key(correction, kind="BASE"),
            )
            public = self._require_analysis(
                session,
                correction,
                operator_id,
                public_id,
                native_visual_correction_analysis_key(correction, kind="PUBLIC"),
                base_id=base_id,
            )
            if (
                base.state != "ACCEPTED"
                or public.state != "ACCEPTED"
                or len(analyses) != 1
                or analyses[0].analysis_run_id != base_id
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ANALYSIS_MISMATCH")
            accepted = analyses[0]
            self._require_source(correction, accepted.source)
            evidence = resolve_registered_solution_evidence_by_base_run(
                session, self.publication.artifacts, base_analysis_run_ids=(base_id,)
            ).get(base_id)
            if (
                evidence is None
                or evidence.source != accepted.source
                or evidence.pointer.solution_analysis_run_id != public_id
                or evidence.pointer.accepted_result_artifact.artifact_revision_id
                != public.accepted_result_artifact_revision_id
                or evidence.pointer.accepted_result_artifact.sha256 != public.accepted_result_sha256
                or evidence.base_accepted_result.artifact_revision_id
                != accepted.accepted_result.artifact_revision_id
                or evidence.base_accepted_result.sha256 != accepted.accepted_result.sha256
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PUBLIC_EVIDENCE_MISMATCH")

        for _ in range(3):
            context = self.publication.current_structure_context(INTEGRATED_SCIENCE_CORPUS_KEY)
            with self.sessions() as session:
                accepted = self.publication.resolve_accepted_analyses(session, (base_id,))[base_id]
                validate(session, (accepted.analysis,))
            if base_id in context.accepted_analysis_run_ids:
                return context.graph_snapshot_revision_id
            try:
                receipt = self.automatic.publish(
                    (
                        AutomaticItemGraphCandidate(
                            base_id, operator_id, context.graph_snapshot_revision_id
                        ),
                    ),
                    required_source_class="APPROVED_ITEM",
                    retrieval_idempotency_namespace="native-visual-align",
                    publication_idempotency_namespace="native-visual-graph",
                    publisher_version=CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
                    analysis_validator=validate,
                )
                return receipt.graph_publication.graph_snapshot.graph_snapshot_revision_id
            except KnowledgeGraphPublicationError as error:
                if error.code != "KNOWLEDGE_GRAPH_STALE_CURRENT":
                    raise
        raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_GRAPH_BUSY")

"""Idempotent bridge from accepted legacy extraction to Item and Graph learning."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
    CreateKnowledgeSolutionAnalysisCommand,
    LegacyItemPromotionRequest,
    ReconcileKnowledgeAnalysisCommand,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, case, literal, select
from sqlalchemy.orm import aliased

from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_assessment_models import (
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_graph_learning_service import (
    MAX_AUTOMATIC_GRAPH_BATCH_SIZE,
    LegacyItemGraphLearningService,
)
from eom_catalog_service.legacy_item_learning_service import (
    LegacyItemLearningCoordinator,
    LegacyItemLearningError,
    LegacyItemLearningPresetPin,
)
from eom_catalog_service.models import ItemRevisionRecord

ACTIVE_ANALYSIS_STATES = (
    "REQUESTED",
    "RESOLVED",
    "QUEUED",
    "RUNNING",
    "VALIDATING",
    "NEEDS_REVIEW",
)

# The exact pinned worker-capacity-policy/1.1 contract admits two knowledge-analysis
# leases on support slots 05 and 06.  The capacity controller remains authoritative
# for the global-three, pool-two, and per-slot-one lease limits.
MAX_AUTOMATIC_ACTIVE_ANALYSES = 2


@dataclass(frozen=True)
class _LearningCandidate:
    acceptance_id: str
    acceptance_sha256: str
    item_proposal_id: str
    item_number: int
    requested_by: str


class LegacyItemAutomaticLearningService:
    """Advance active runs and refill the exact pinned two-analysis capacity."""

    def __init__(
        self,
        engine: Engine,
        *,
        extraction_batch_ids: tuple[str, ...],
        retry_analysis_run_ids: tuple[str, ...] = (),
        content_pack_release_id: str,
        risk_policy_revision_id: str,
        preset_pin: LegacyItemLearningPresetPin,
        graph: LegacyItemGraphLearningService | None = None,
        graph_batch_size: int = 16,
        learning: LegacyItemLearningCoordinator,
        analyses: KnowledgeAnalysisApplicationService,
    ) -> None:
        if not extraction_batch_ids or len(extraction_batch_ids) != len(set(extraction_batch_ids)):
            raise ValueError("automation batch identities must be non-empty and unique")
        if len(retry_analysis_run_ids) != len(set(retry_analysis_run_ids)):
            raise ValueError("analysis retry identities must be unique")
        if graph_batch_size < 1 or graph_batch_size > MAX_AUTOMATIC_GRAPH_BATCH_SIZE:
            raise ValueError("Graph publication batch size must be within 1..16")
        self.sessions = build_session_factory(engine)
        self.extraction_batch_ids = extraction_batch_ids
        self.retry_analysis_run_ids = retry_analysis_run_ids
        self.content_pack_release_id = content_pack_release_id
        self.risk_policy_revision_id = risk_policy_revision_id
        self.preset_pin = preset_pin
        self.graph = graph
        self.graph_batch_size = graph_batch_size
        self.learning = learning
        self.analyses = analyses

    def advance_once(self) -> bool:
        """Reconcile first; otherwise promote and schedule one not-yet-learned proposal."""

        # One shared-lock guard covers the complete step.  Mutable preset/capacity pointers
        # cannot move after validation and before a Graph, retry, or promotion side effect.
        with self.learning.preset_pin_guard(self.preset_pin):
            return self._advance_pinned_once()

    def _advance_pinned_once(self) -> bool:
        terminal = self._terminal_analysis()
        if terminal is not None:
            raise LegacyItemLearningError(
                "LEGACY_ITEM_AUTOMATION_TERMINAL_ANALYSIS",
                "automatic learning stopped at a terminal leaf analysis",
            )

        active_analyses = self._active_analyses()
        progressed = False
        for active in active_analyses:
            analysis_run_id, requested_by, state = active
            if state == "NEEDS_REVIEW":
                self.analyses.accept_validated_without_review(
                    analysis_run_id=analysis_run_id,
                    requested_by=requested_by,
                )
            else:
                self.analyses.reconcile(
                    ReconcileKnowledgeAnalysisCommand(
                        analysis_run_id=analysis_run_id,
                        requested_by=requested_by,
                    )
                )
            progressed = True
            terminal = self._terminal_analysis()
            if terminal is not None:
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_AUTOMATION_TERMINAL_ANALYSIS",
                    "automatic learning stopped at a terminal leaf analysis",
                )
        if len(active_analyses) == MAX_AUTOMATIC_ACTIVE_ANALYSES:
            return progressed
        solution_candidate = self._solution_candidate()
        if solution_candidate is not None:
            analysis_run_id, requested_by = solution_candidate
            self.analyses.create_solution(
                CreateKnowledgeSolutionAnalysisCommand(
                    base_analysis_run_id=analysis_run_id,
                    requested_by=requested_by,
                    idempotency_key=f"legacy-item-solution:{analysis_run_id}",
                )
            )
            return True
        graph_candidates = (
            self.graph.pending_candidates(limit=self.graph_batch_size)
            if self.graph is not None
            else ()
        )
        if self.graph is not None and len(graph_candidates) == self.graph_batch_size:
            self.graph.publish(graph_candidates)
            return True
        retry = self._retryable_analysis()
        if retry is not None:
            analysis_run_id, requested_by = retry
            self.learning.retry_failed_analysis(
                predecessor_analysis_run_id=analysis_run_id,
                requested_by=requested_by,
            )
            return True
        candidate = self._candidate()
        if candidate is None:
            if self.graph is not None and graph_candidates and not self._source_work_remaining():
                self.graph.publish(graph_candidates)
                return True
            return progressed
        command = self._promotion_request(
            candidate,
            content_pack_release_id=self.content_pack_release_id,
        )
        self.learning.promote_and_schedule(
            command,
            risk_policy_revision_id=self.risk_policy_revision_id,
            preset_pin=self.preset_pin,
        )
        return True

    def _terminal_analysis(self) -> tuple[str, str] | None:
        successor = aliased(KnowledgeAnalysisRunRecord)
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionDecisionRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        terminal_filters = [
            LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                self.extraction_batch_ids
            ),
            KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
            KnowledgeAnalysisRunRecord.state.in_(("FAILED", "REJECTED", "CANCELLED")),
            successor.analysis_run_id.is_(None),
        ]
        if self.retry_analysis_run_ids:
            # Exact retry predecessors are intentionally terminal until their one allowed
            # successor is created.  Every other terminal leaf remains an immediate fail-stop.
            terminal_filters.append(
                KnowledgeAnalysisRunRecord.analysis_run_id.not_in(self.retry_analysis_run_ids)
            )
        with self.sessions() as session:
            row = session.execute(
                select(
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                    KnowledgeAnalysisRunRecord.state,
                )
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeAnalysisRunRecord.source_revision_id,
                )
                .join(
                    LegacyItemExtractionDecisionRecord,
                    ItemRevisionRecord.registration_key == registration_key,
                )
                .join(
                    LegacyItemExtractionBatchWorkUnitRecord,
                    LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                    == LegacyItemExtractionDecisionRecord.acceptance_id,
                )
                .outerjoin(
                    successor,
                    successor.predecessor_analysis_run_id
                    == KnowledgeAnalysisRunRecord.analysis_run_id,
                )
                .where(*terminal_filters)
                .order_by(
                    KnowledgeAnalysisRunRecord.created_at,
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                )
                .limit(1)
            ).one_or_none()
        if row is None:
            return None
        return str(row.analysis_run_id), str(row.state)

    def _solution_candidate(self) -> tuple[str, str] | None:
        """Select one accepted V9 base with no additive V10 successor."""

        successor = aliased(KnowledgeAnalysisRunRecord)
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionDecisionRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        with self.sessions() as session:
            row = session.execute(
                select(
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                    KnowledgeAnalysisRunRecord.created_by_operator_id,
                )
                .distinct()
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeAnalysisRunRecord.source_revision_id,
                )
                .join(
                    LegacyItemExtractionDecisionRecord,
                    ItemRevisionRecord.registration_key == registration_key,
                )
                .join(
                    LegacyItemExtractionBatchWorkUnitRecord,
                    LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                    == LegacyItemExtractionDecisionRecord.acceptance_id,
                )
                .outerjoin(
                    successor,
                    (
                        successor.predecessor_analysis_run_id
                        == KnowledgeAnalysisRunRecord.analysis_run_id
                    )
                    & (
                        successor.canonical_request["schema_version"].astext
                        == "knowledge-analysis-request/10.0"
                    ),
                )
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                        self.extraction_batch_ids
                    ),
                    KnowledgeAnalysisRunRecord.state == "ACCEPTED",
                    KnowledgeAnalysisRunRecord.canonical_request["schema_version"].astext
                    == PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
                    successor.analysis_run_id.is_(None),
                )
                .order_by(
                    KnowledgeAnalysisRunRecord.created_at,
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                )
                .limit(1)
            ).one_or_none()
        if row is None:
            return None
        return str(row.analysis_run_id), str(row.created_by_operator_id)

    def _source_work_remaining(self) -> bool:
        with self.sessions() as session:
            return (
                session.scalar(
                    select(LegacyItemExtractionBatchWorkUnitRecord.work_unit_id)
                    .where(
                        LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                            self.extraction_batch_ids
                        ),
                        LegacyItemExtractionBatchWorkUnitRecord.state.in_(
                            ("PENDING", "SUBMITTED", "RUNNING")
                        ),
                    )
                    .limit(1)
                )
                is not None
            )

    def _active_analyses(self) -> tuple[tuple[str, str, str], ...]:
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionDecisionRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        with self.sessions() as session:
            rows = tuple(
                session.execute(
                    select(
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                        KnowledgeAnalysisRunRecord.created_by_operator_id,
                        KnowledgeAnalysisRunRecord.state,
                        KnowledgeAnalysisRunRecord.created_at,
                    )
                    .distinct()
                    .join(
                        ItemRevisionRecord,
                        ItemRevisionRecord.item_revision_id
                        == KnowledgeAnalysisRunRecord.source_revision_id,
                    )
                    .join(
                        LegacyItemExtractionDecisionRecord,
                        ItemRevisionRecord.registration_key == registration_key,
                    )
                    .join(
                        LegacyItemExtractionBatchWorkUnitRecord,
                        LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                        == LegacyItemExtractionDecisionRecord.acceptance_id,
                    )
                    .where(
                        LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                            self.extraction_batch_ids
                        ),
                        KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
                        KnowledgeAnalysisRunRecord.state.in_(ACTIVE_ANALYSIS_STATES),
                    )
                    .order_by(
                        KnowledgeAnalysisRunRecord.created_at,
                        KnowledgeAnalysisRunRecord.analysis_run_id,
                    )
                    .limit(MAX_AUTOMATIC_ACTIVE_ANALYSES)
                )
            )
            return tuple(
                (str(row.analysis_run_id), str(row.created_by_operator_id), str(row.state))
                for row in rows
            )

    def _retryable_analysis(self) -> tuple[str, str] | None:
        """Select one explicitly allowlisted terminal run that has no successor."""

        if not self.retry_analysis_run_ids:
            return None
        successor = aliased(KnowledgeAnalysisRunRecord)
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionDecisionRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        retry_order = case(
            {
                analysis_run_id: ordinal
                for ordinal, analysis_run_id in enumerate(self.retry_analysis_run_ids)
            },
            value=KnowledgeAnalysisRunRecord.analysis_run_id,
            else_=len(self.retry_analysis_run_ids),
        )
        with self.sessions() as session:
            row = session.execute(
                select(
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                    KnowledgeAnalysisRunRecord.created_by_operator_id,
                )
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id
                    == KnowledgeAnalysisRunRecord.source_revision_id,
                )
                .join(
                    LegacyItemExtractionDecisionRecord,
                    ItemRevisionRecord.registration_key == registration_key,
                )
                .join(
                    LegacyItemExtractionBatchWorkUnitRecord,
                    LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                    == LegacyItemExtractionDecisionRecord.acceptance_id,
                )
                .outerjoin(
                    successor,
                    successor.predecessor_analysis_run_id
                    == KnowledgeAnalysisRunRecord.analysis_run_id,
                )
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id.in_(
                        self.extraction_batch_ids
                    ),
                    KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
                    KnowledgeAnalysisRunRecord.analysis_run_id.in_(self.retry_analysis_run_ids),
                    KnowledgeAnalysisRunRecord.state.in_(("FAILED", "REJECTED", "CANCELLED")),
                    successor.analysis_run_id.is_(None),
                )
                .order_by(retry_order, KnowledgeAnalysisRunRecord.analysis_run_id)
                .limit(1)
            ).one_or_none()
            if row is None:
                return None
            return str(row.analysis_run_id), str(row.created_by_operator_id)

    def _candidate(self) -> _LearningCandidate | None:
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionAcceptanceRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        with self.sessions() as session:
            row = session.execute(
                select(
                    LegacyItemExtractionAcceptanceRecord,
                    LegacyItemExtractionDecisionRecord,
                    LegacyItemExtractionBatchRecord.requested_by_operator_id,
                )
                .join(
                    LegacyItemExtractionDecisionRecord,
                    LegacyItemExtractionDecisionRecord.acceptance_id
                    == LegacyItemExtractionAcceptanceRecord.acceptance_id,
                )
                .join(
                    LegacyItemExtractionBatchWorkUnitRecord,
                    LegacyItemExtractionBatchWorkUnitRecord.acceptance_id
                    == LegacyItemExtractionAcceptanceRecord.acceptance_id,
                )
                .join(
                    LegacyItemExtractionBatchRecord,
                    LegacyItemExtractionBatchRecord.extraction_batch_id
                    == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                )
                .outerjoin(
                    ItemRevisionRecord,
                    ItemRevisionRecord.registration_key == registration_key,
                )
                .outerjoin(
                    KnowledgeAnalysisRunRecord,
                    (KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION")
                    & (
                        KnowledgeAnalysisRunRecord.source_revision_id
                        == ItemRevisionRecord.item_revision_id
                    )
                    & (
                        KnowledgeAnalysisRunRecord.canonical_request["source"][
                            "source_class"
                        ].astext
                        == "PAST_EXAM"
                    )
                    & (
                        KnowledgeAnalysisRunRecord.canonical_request["schema_version"].astext
                        == PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION
                    ),
                )
                .where(
                    LegacyItemExtractionBatchRecord.extraction_batch_id.in_(
                        self.extraction_batch_ids
                    ),
                    LegacyItemExtractionBatchWorkUnitRecord.state == "ACCEPTED",
                    LegacyItemExtractionAcceptanceRecord.state.in_(
                        ("ACCEPTED", "ACCEPTED_WITH_CORRECTIONS")
                    ),
                    LegacyItemExtractionDecisionRecord.decision.in_(
                        ("ACCEPT", "CORRECT_AND_ACCEPT")
                    ),
                    KnowledgeAnalysisRunRecord.analysis_run_id.is_(None),
                )
                .order_by(
                    LegacyItemExtractionBatchRecord.created_at,
                    LegacyItemExtractionBatchRecord.extraction_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                    LegacyItemExtractionDecisionRecord.item_number,
                    LegacyItemExtractionDecisionRecord.item_proposal_id,
                )
                .limit(1)
            ).one_or_none()
        if row is None:
            return None
        acceptance, decision, requested_by = row
        return _LearningCandidate(
            acceptance_id=acceptance.acceptance_id,
            acceptance_sha256=acceptance.acceptance_sha256,
            item_proposal_id=decision.item_proposal_id,
            item_number=decision.item_number,
            requested_by=requested_by,
        )

    @staticmethod
    def _promotion_request(
        candidate: _LearningCandidate,
        *,
        content_pack_release_id: str,
    ) -> LegacyItemPromotionRequest:
        values: dict[str, object] = {
            "schema_version": "legacy-item-promotion-request/1.0",
            "acceptance_id": candidate.acceptance_id,
            "acceptance_sha256": candidate.acceptance_sha256,
            "item_proposal_id": candidate.item_proposal_id,
            "item_number": candidate.item_number,
            "content_pack_release_id": content_pack_release_id,
            "primary_taxonomy_ref": None,
            "difficulty_band": None,
            "requested_by": candidate.requested_by,
            "idempotency_key": (
                f"legacy-auto-learning:{candidate.acceptance_id}:{candidate.item_number}"
            ),
        }
        values["request_sha256"] = content_sha256(values)
        return LegacyItemPromotionRequest.model_validate(values)

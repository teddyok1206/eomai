"""Idempotent bridge from accepted legacy extraction to Item and Graph learning."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import LegacyItemPromotionRequest, ReconcileKnowledgeAnalysisCommand
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, literal, select

from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_assessment_models import (
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_learning_service import LegacyItemLearningCoordinator
from eom_catalog_service.models import ItemRevisionRecord

ACTIVE_ANALYSIS_STATES = (
    "REQUESTED",
    "RESOLVED",
    "QUEUED",
    "RUNNING",
    "VALIDATING",
    "NEEDS_REVIEW",
)


@dataclass(frozen=True)
class _LearningCandidate:
    acceptance_id: str
    acceptance_sha256: str
    item_proposal_id: str
    item_number: int
    requested_by: str


class LegacyItemAutomaticLearningService:
    """Advance one accepted proposal or one active Graph-learning run per poll."""

    def __init__(
        self,
        engine: Engine,
        *,
        extraction_batch_id: str,
        content_pack_release_id: str,
        risk_policy_revision_id: str,
        learning: LegacyItemLearningCoordinator,
        analyses: KnowledgeAnalysisApplicationService,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.extraction_batch_id = extraction_batch_id
        self.content_pack_release_id = content_pack_release_id
        self.risk_policy_revision_id = risk_policy_revision_id
        self.learning = learning
        self.analyses = analyses

    def advance_once(self) -> bool:
        """Reconcile first; otherwise promote and schedule one not-yet-learned proposal."""

        active = self._active_analysis()
        if active is not None:
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
            return True
        candidate = self._candidate()
        if candidate is None:
            return False
        command = self._promotion_request(
            candidate,
            content_pack_release_id=self.content_pack_release_id,
        )
        self.learning.promote_and_schedule(
            command,
            risk_policy_revision_id=self.risk_policy_revision_id,
        )
        return True

    def _active_analysis(self) -> tuple[str, str, str] | None:
        registration_key = (
            literal("legacy-item-promotion:")
            + LegacyItemExtractionAcceptanceRecord.acceptance_id
            + literal(":")
            + LegacyItemExtractionDecisionRecord.item_proposal_id
        )
        with self.sessions() as session:
            run = session.scalar(
                select(KnowledgeAnalysisRunRecord)
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
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id
                    == self.extraction_batch_id,
                    KnowledgeAnalysisRunRecord.source_kind == "APPROVED_ITEM_REVISION",
                    KnowledgeAnalysisRunRecord.state.in_(ACTIVE_ANALYSIS_STATES),
                )
                .order_by(
                    KnowledgeAnalysisRunRecord.created_at,
                    KnowledgeAnalysisRunRecord.analysis_run_id,
                )
                .limit(1)
            )
            if run is None:
                return None
            return run.analysis_run_id, run.created_by_operator_id, run.state

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
                    ),
                )
                .where(
                    LegacyItemExtractionBatchRecord.extraction_batch_id == self.extraction_batch_id,
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

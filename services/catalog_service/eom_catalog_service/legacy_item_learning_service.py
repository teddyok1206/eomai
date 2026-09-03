"""Coordinate reviewed legacy Item promotion and existing Graph knowledge analysis."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    CreateKnowledgeAnalysisCommand,
    KnowledgeAnalysisApplicationResult,
    LegacyItemPromotionRequest,
    LegacyLearnedItemPointer,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import Engine, select

from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_item_promotion_service import (
    LegacyItemPromotion,
    LegacyItemPromotionService,
)


class LegacyItemLearningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyItemLearningStart:
    source: LegacyLearnedItemPointer
    analysis: KnowledgeAnalysisApplicationResult
    item_created: bool
    origin_created: bool


class LegacyItemLearningCoordinator:
    """Use the canonical Item boundary, then schedule the ordinary Graph-learning path."""

    def __init__(
        self,
        engine: Engine,
        *,
        promotion: LegacyItemPromotionService | None = None,
        analyses: KnowledgeAnalysisApplicationService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.promotion = promotion
        self.analyses = analyses or KnowledgeAnalysisApplicationService(engine)

    def promote_and_schedule(
        self,
        command: LegacyItemPromotionRequest,
        *,
        risk_policy_revision_id: str,
        preset_key: str = "knowledge-analysis",
    ) -> LegacyItemLearningStart:
        if self.promotion is None:
            raise LegacyItemLearningError(
                "LEGACY_ITEM_LEARNING_PROMOTION_UNAVAILABLE",
                "legacy item promotion dependency is unavailable",
            )
        promoted = self.promotion.promote(command)
        preset_id, preset_revision_id = self._released_preset(preset_key)
        analysis_command = self._analysis_command(
            promoted,
            risk_policy_revision_id=risk_policy_revision_id,
            preset_key=preset_key,
            preset_revision_id=preset_revision_id,
            requested_by=command.requested_by,
        )
        analysis = self.analyses.create_with_pinned_preset(
            analysis_command,
            preset_id=preset_id,
            preset_revision_id=preset_revision_id,
        )
        return LegacyItemLearningStart(
            source=promoted.source,
            analysis=analysis,
            item_created=promoted.item_created,
            origin_created=promoted.origin_created,
        )

    def retry_failed_analysis(
        self,
        *,
        predecessor_analysis_run_id: str,
        requested_by: str,
    ) -> KnowledgeAnalysisApplicationResult:
        """Create one explicit successor while preserving the failed run and its exact pins."""

        with self.sessions() as session:
            predecessor = session.get(KnowledgeAnalysisRunRecord, predecessor_analysis_run_id)
            preset = (
                session.get(ExecutionPresetRecord, predecessor.preset_id)
                if predecessor is not None
                else None
            )
            request = predecessor.canonical_request if predecessor is not None else {}
            source = request.get("source") if isinstance(request, dict) else None
            if (
                predecessor is None
                or predecessor.state not in {"FAILED", "REJECTED", "CANCELLED"}
                or predecessor.item_revision_id is None
                or not isinstance(source, dict)
                or source.get("source_kind") != "APPROVED_ITEM_REVISION"
                or source.get("source_class") != "PAST_EXAM"
                or request.get("general_knowledge_mode") != "DISABLED"
                or preset is None
            ):
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_LEARNING_RETRY_INVALID",
                    "legacy item analysis predecessor is not retryable",
                )
            command = self._retry_command(
                item_revision_id=predecessor.item_revision_id,
                risk_policy_revision_id=predecessor.risk_policy_revision_id,
                predecessor_analysis_run_id=predecessor.analysis_run_id,
                preset_key=preset.preset_key,
                requested_by=requested_by,
            )
            preset_id = predecessor.preset_id
            preset_revision_id = predecessor.preset_revision_id
        return self.analyses.create_with_pinned_preset(
            command,
            preset_id=preset_id,
            preset_revision_id=preset_revision_id,
        )

    def _released_preset(self, preset_key: str) -> tuple[str, str]:
        with self.sessions() as session:
            preset = session.scalar(
                select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
            )
            revision = (
                session.get(ExecutionPresetRevisionRecord, preset.current_revision_id)
                if preset is not None and preset.current_revision_id is not None
                else None
            )
            if (
                preset is None
                or revision is None
                or preset.state != "ACTIVE"
                or revision.state != "RELEASED"
                or revision.preset_id != preset.preset_id
            ):
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_LEARNING_PRESET_UNAVAILABLE",
                    "knowledge-analysis preset is not released",
                )
            return preset.preset_id, revision.preset_revision_id

    @staticmethod
    def _analysis_command(
        promoted: LegacyItemPromotion,
        *,
        risk_policy_revision_id: str,
        preset_key: str,
        preset_revision_id: str,
        requested_by: str,
    ) -> CreateKnowledgeAnalysisCommand:
        identity = content_sha256(
            {
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_class": "PAST_EXAM",
                "item_revision_id": promoted.source.item_revision_id,
                "risk_policy_revision_id": risk_policy_revision_id,
                "preset_key": preset_key,
                "preset_revision_id": preset_revision_id,
            }
        ).removeprefix("sha256:")
        return CreateKnowledgeAnalysisCommand(
            source=ApprovedItemKnowledgeAnalysisSelection(
                source_class="PAST_EXAM",
                item_revision_id=promoted.source.item_revision_id,
            ),
            preset_key=preset_key,
            general_knowledge_mode="DISABLED",
            risk_policy_revision_id=risk_policy_revision_id,
            predecessor_analysis_run_id=None,
            requested_by=requested_by,
            idempotency_key=f"legacy-item-learning:{identity}",
        )

    @staticmethod
    def _retry_command(
        *,
        item_revision_id: str,
        risk_policy_revision_id: str,
        predecessor_analysis_run_id: str,
        preset_key: str,
        requested_by: str,
    ) -> CreateKnowledgeAnalysisCommand:
        return CreateKnowledgeAnalysisCommand(
            source=ApprovedItemKnowledgeAnalysisSelection(
                source_class="PAST_EXAM",
                item_revision_id=item_revision_id,
            ),
            preset_key=preset_key,
            general_knowledge_mode="DISABLED",
            risk_policy_revision_id=risk_policy_revision_id,
            predecessor_analysis_run_id=predecessor_analysis_run_id,
            requested_by=requested_by,
            idempotency_key=f"legacy-item-learning-retry:{predecessor_analysis_run_id}",
        )

"""Coordinate reviewed legacy Item promotion and existing Graph knowledge analysis."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

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
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import (
    LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID,
    ControlPlaneError,
    compute_control_document_hash,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    WorkerCapacityPolicyV2,
    WorkerCapacityPolicyV3,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select

from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.legacy_item_promotion_service import (
    LegacyItemPromotion,
    LegacyItemPromotionService,
)


class LegacyItemLearningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LegacyItemLearningPresetPin(BaseModel):
    """Exact mutable-current and immutable capacity pointers for automatic learning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_key: Literal["knowledge-analysis"] = "knowledge-analysis"
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    capacity_policy_content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capacity_current_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    capacity_current_content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


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
        preset_pin: LegacyItemLearningPresetPin,
    ) -> LegacyItemLearningStart:
        if self.promotion is None:
            raise LegacyItemLearningError(
                "LEGACY_ITEM_LEARNING_PROMOTION_UNAVAILABLE",
                "legacy item promotion dependency is unavailable",
            )
        # Keep shared locks on both mutable logical pointers across promotion and analysis
        # creation.  A publisher cannot move either pointer between validation and use.
        with self.preset_pin_guard(preset_pin):
            promoted = self.promotion.promote(command)
            analysis_command = self._analysis_command(
                promoted,
                risk_policy_revision_id=risk_policy_revision_id,
                preset_key=preset_pin.preset_key,
                preset_revision_id=preset_pin.preset_revision_id,
                requested_by=command.requested_by,
            )
            analysis = self.analyses.create_with_pinned_preset(
                analysis_command,
                preset_id=preset_pin.preset_id,
                preset_revision_id=preset_pin.preset_revision_id,
            )
        return LegacyItemLearningStart(
            source=promoted.source,
            analysis=analysis,
            item_created=promoted.item_created,
            origin_created=promoted.origin_created,
        )

    def promote_and_schedule_current(
        self,
        command: LegacyItemPromotionRequest,
        *,
        risk_policy_revision_id: str,
        preset_key: str = "knowledge-analysis",
    ) -> LegacyItemLearningStart:
        """Manual compatibility boundary; automatic callers must use exact pins."""

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

    @contextmanager
    def preset_pin_guard(self, pin: LegacyItemLearningPresetPin) -> Iterator[None]:
        """Validate exact pointers and prevent current-pointer movement during one step."""

        with self.sessions.begin() as session:
            session.execute(
                select(func.pg_advisory_xact_lock_shared(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID))
            )
            preset = session.scalar(
                select(ExecutionPresetRecord).where(
                    ExecutionPresetRecord.preset_key == pin.preset_key,
                    ExecutionPresetRecord.preset_id == pin.preset_id,
                )
            )
            revision = session.scalar(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_revision_id == pin.preset_revision_id
                )
            )
            capacity = session.scalar(
                select(WorkerCapacityPolicyRevisionRecord).where(
                    WorkerCapacityPolicyRevisionRecord.capacity_policy_revision_id
                    == pin.capacity_policy_revision_id
                )
            )
            capacity_logical = session.scalar(
                select(WorkerCapacityPolicyRecord).where(
                    WorkerCapacityPolicyRecord.capacity_policy_id == pin.capacity_policy_id
                )
            )
            capacity_current = session.scalar(
                select(WorkerCapacityPolicyRevisionRecord).where(
                    WorkerCapacityPolicyRevisionRecord.capacity_policy_revision_id
                    == pin.capacity_current_revision_id
                )
            )
            if (
                preset is None
                or revision is None
                or preset.preset_key != pin.preset_key
                or preset.preset_id != pin.preset_id
                or preset.state != "ACTIVE"
                or preset.current_revision_id != pin.preset_revision_id
                or revision.preset_revision_id != pin.preset_revision_id
                or revision.state != "RELEASED"
                or revision.preset_id != pin.preset_id
                or revision.content_sha256 != pin.preset_content_sha256
                or revision.capacity_policy_revision_id != pin.capacity_policy_revision_id
                or capacity is None
                or capacity.capacity_policy_revision_id != pin.capacity_policy_revision_id
                or capacity.state != "RELEASED"
                or capacity.capacity_policy_id != pin.capacity_policy_id
                or capacity.content_sha256 != pin.capacity_policy_content_sha256
                or capacity_logical is None
                or capacity_logical.policy_key != "fixed-host"
                or capacity_logical.capacity_policy_id != pin.capacity_policy_id
                or capacity_logical.state != "ACTIVE"
                or capacity_logical.current_revision_id != pin.capacity_current_revision_id
                or capacity_current is None
                or capacity_current.capacity_policy_revision_id != pin.capacity_current_revision_id
                or capacity_current.state != "RELEASED"
                or capacity_current.capacity_policy_id != pin.capacity_policy_id
                or capacity_current.content_sha256 != pin.capacity_current_content_sha256
            ):
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT",
                    "automatic learning preset or capacity pointer differs",
                )
            try:
                preset_model = ExecutionPresetRevision.model_validate(revision.canonical_document)
                capacity_model = WorkerCapacityPolicyV2.model_validate(capacity.canonical_document)
                current_capacity_model = WorkerCapacityPolicyV3.model_validate(
                    capacity_current.canonical_document
                )
                preset_document = preset_model.model_dump(mode="json")
                capacity_document = capacity_model.model_dump(mode="json")
                current_capacity_document = current_capacity_model.model_dump(mode="json")
                preset_content_sha256 = compute_control_document_hash(
                    preset_document, "content_sha256"
                )
                capacity_content_sha256 = compute_control_document_hash(
                    capacity_document, "content_sha256"
                )
                current_capacity_content_sha256 = compute_control_document_hash(
                    current_capacity_document, "content_sha256"
                )
            except (ControlPlaneError, TypeError, ValueError) as exc:
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT",
                    "automatic learning canonical preset or capacity content is invalid",
                ) from exc
            if (
                revision.canonical_document != preset_document
                or revision.schema_version != preset_model.schema_version
                or revision.revision_number != preset_model.revision_number
                or revision.display_name != preset_model.display_name
                or revision.description != preset_model.description
                or revision.general_knowledge_policy != preset_model.general_knowledge_policy
                or tuple(revision.compatible_workflow_protocols)
                != preset_model.compatible_workflow_protocols
                or not (
                    preset_content_sha256
                    == preset_model.content_sha256
                    == revision.content_sha256
                    == pin.preset_content_sha256
                )
                or preset_model.state != "RELEASED"
                or preset_model.preset_id != pin.preset_id
                or preset_model.preset_revision_id != pin.preset_revision_id
                or preset_model.capacity_policy_revision_id != pin.capacity_policy_revision_id
                or capacity.canonical_document != capacity_document
                or capacity.schema_version != capacity_model.schema_version
                or capacity.revision_number != capacity_model.revision_number
                or capacity.max_configured_slots != capacity_model.max_configured_slots
                or capacity.max_active_codex != capacity_model.max_active_codex
                or capacity.max_active_per_slot != capacity_model.max_active_per_slot
                or capacity.max_active_gpu != capacity_model.max_active_gpu
                or capacity.max_active_knowledge_analysis
                != capacity_model.max_active_knowledge_analysis
                or not (
                    capacity_content_sha256
                    == capacity_model.content_sha256
                    == capacity.content_sha256
                    == pin.capacity_policy_content_sha256
                )
                or capacity_model.state != "RELEASED"
                or capacity_model.capacity_policy_id != pin.capacity_policy_id
                or capacity_model.capacity_policy_revision_id != pin.capacity_policy_revision_id
                or capacity_current.canonical_document != current_capacity_document
                or capacity_current.schema_version != current_capacity_model.schema_version
                or capacity_current.revision_number != current_capacity_model.revision_number
                or capacity_current.max_configured_slots
                != current_capacity_model.max_configured_slots
                or capacity_current.max_active_codex != current_capacity_model.max_active_codex
                or capacity_current.max_active_per_slot
                != current_capacity_model.max_active_per_slot
                or capacity_current.max_active_gpu != current_capacity_model.max_active_gpu
                or capacity_current.max_active_knowledge_analysis
                != current_capacity_model.max_active_knowledge_analysis
                or not (
                    current_capacity_content_sha256
                    == current_capacity_model.content_sha256
                    == capacity_current.content_sha256
                    == pin.capacity_current_content_sha256
                )
                or current_capacity_model.state != "RELEASED"
                or current_capacity_model.capacity_policy_id != pin.capacity_policy_id
                or current_capacity_model.capacity_policy_revision_id
                != pin.capacity_current_revision_id
            ):
                raise LegacyItemLearningError(
                    "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT",
                    "automatic learning canonical preset or capacity content differs",
                )
            yield

    def require_preset_pin(self, pin: LegacyItemLearningPresetPin) -> None:
        with self.preset_pin_guard(pin):
            return

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

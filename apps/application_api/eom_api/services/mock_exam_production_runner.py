"""Operator-facing, checkpointed entrypoints for mock-exam production phases."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPolicyPointerV1,
    MockExamAssemblyIntentV1,
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecutionV1,
    MockExamRatingPolicyPointerV1,
)
from eom_api_contracts.mock_exam_retirement import MockExamProductionRetirementReceiptV1
from eom_catalog_contracts.mock_exam_production_plan import MockExamProductionPlanV1
from eom_operator_identity import ActorContext
from eom_workflow_runner.mock_exam_production_retirement import (
    MockExamProductionRetirementService,
)

from eom_api.services.mock_exam_production_checkpoint_store import (
    MockExamProductionCheckpointStore,
)
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinator,
)


class MockExamProductionRunner:
    """Advance exactly one typed phase and durably CAS the returned immutable checkpoint."""

    def __init__(
        self,
        *,
        coordinator: MockExamProductionCoordinator,
        checkpoints: MockExamProductionCheckpointStore,
        retirements: MockExamProductionRetirementService | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._checkpoints = checkpoints
        self._retirements = retirements

    def initialize(
        self,
        plan: MockExamProductionPlanV1,
        actor: ActorContext,
        *,
        production_request_id: str,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        checkpoint = self._coordinator.initialize(
            plan,
            production_request_id=production_request_id,
            operator_id=actor.actor_id,
            at=at,
        )
        return self._checkpoints.create(checkpoint)

    def get(self, execution_id: str) -> MockExamProductionExecutionV1:
        return self._checkpoints.load(execution_id)

    def retire_items(
        self,
        execution_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionRetirementReceiptV1:
        """Fence all old work without advancing or rewriting the immutable checkpoint."""

        if self._retirements is None:
            raise RuntimeError("mock-exam production retirement adapter is unavailable")
        checkpoint = self._checkpoints.load(execution_id)
        return self._retirements.retire(checkpoint, actor, at=at)

    def advance_items(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.advance_items(plan, current, actor, at=at)
        return self._save(current, successor)

    def advance_analyses(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
        general_knowledge_mode: Literal[
            "DISABLED", "AUXILIARY_UNATTRIBUTED"
        ] = "AUXILIARY_UNATTRIBUTED",
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.advance_analyses(
            plan,
            current,
            actor,
            policy,
            at=at,
            general_knowledge_mode=general_knowledge_mode,
        )
        return self._save(current, successor)

    def publish_next_graph_batch(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        publication_input: MockExamGraphPublicationInputV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.publish_next_graph_batch(
            plan,
            current,
            actor,
            publication_input,
            at=at,
        )
        return self._save(current, successor)

    def review_analyses(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        review_set: MockExamExplicitAnalysisReviewSetV1,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.review_analyses(
            plan,
            current,
            actor,
            review_set,
            policy,
            at=at,
        )
        return self._save(current, successor)

    def publish_ratings(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        rating_set: MockExamExplicitRatingSetV1,
        policy: MockExamRatingPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.publish_ratings(
            plan,
            current,
            actor,
            rating_set,
            policy,
            at=at,
        )
        return self._save(current, successor)

    def advance_assembly(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        intent: MockExamAssemblyIntentV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.advance_assembly(
            plan,
            current,
            actor,
            intent,
            at=at,
        )
        return self._save(current, successor)

    def advance_hwpx(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        current = self._checkpoints.load(execution_id)
        successor = self._coordinator.advance_hwpx(
            plan,
            current,
            actor,
            at=at,
        )
        return self._save(current, successor)

    def _save(
        self,
        current: MockExamProductionExecutionV1,
        successor: MockExamProductionExecutionV1,
    ) -> MockExamProductionExecutionV1:
        if successor.execution_revision_id == current.execution_revision_id:
            return current
        return self._checkpoints.compare_and_swap(
            current.execution_revision_id,
            successor,
        )

"""Application-owned execution context for exact creative source/page inputs.

This is local composition, not a JSON authority grant. The source callback must
derive the operator and original request from the persisted Workflow/step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from eom_workflow.control_plane import (
    ResolvedExecutionPlanV27,
    ResolvedExecutionPlanV28,
    parse_creative_learning_execution_plan,
)
from eom_workflow.models import ExternalItemLearningWorkerRequest

from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_page_publication import (
    read_external_item_learning_page_artifact,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher


@dataclass(frozen=True, slots=True)
class ExternalItemLearningExecutionContext:
    source_authorizer: Callable[[ExternalItemLearningWorkerRequest], None]
    page_publisher: ControlFileSetPublisher

    def reauthorize_source(self, request: ExternalItemLearningWorkerRequest) -> None:
        try:
            self.source_authorizer(request)
        except ValueError as exc:
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_AUTHORIZATION_FAILED",
                "creative learning source authorization failed",
            ) from exc

    def verify_page_input(self, request: ExternalItemLearningWorkerRequest) -> None:
        read_external_item_learning_page_artifact(
            self.page_publisher, request.work_input.page_artifact
        )


def validate_external_item_learning_execution_plan(
    record: ResolvedExecutionPlanRecord | None,
    *,
    workflow_id: str,
    step_key: str,
    request: ExternalItemLearningWorkerRequest,
) -> ResolvedExecutionPlanV27 | ResolvedExecutionPlanV28:
    """Bind the immutable row, full plan, Workflow and exact work for replay too."""

    try:
        if record is None:
            raise ValueError("missing creative execution plan")
        plan = parse_creative_learning_execution_plan(record.canonical_document)
        if (
            plan.workflow_id != workflow_id
            or step_key != "extract"
            or plan.work_input != request.work_input
            or (
                record.plan_id,
                record.workflow_id,
                record.preset_id,
                record.preset_revision_id,
                record.capacity_policy_revision_id,
                record.graph_snapshot_revision_id,
                record.evidence_bundle_revision_id,
                record.plan_sha256,
                record.resolver_version,
                record.resolved_at,
            )
            != (
                plan.plan_id,
                plan.workflow_id,
                plan.preset_id,
                plan.preset_revision_id,
                plan.capacity_policy_revision_id,
                None,
                None,
                plan.plan_sha256,
                plan.resolver_version,
                plan.resolved_at,
            )
        ):
            raise ValueError("creative execution plan differs from its persisted identity")
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_CREATIVE_PLAN_UNAVAILABLE", "the exact creative execution plan is required"
        ) from exc
    return plan

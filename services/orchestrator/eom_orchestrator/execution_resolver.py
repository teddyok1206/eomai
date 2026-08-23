"""Deterministic released-preset resolution into one immutable execution plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import new_execution_plan_id
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    ResolvedExecutionPlan,
    ResolvedStepExecution,
    WorkerRole,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    compute_control_document_hash,
    record_resolved_execution_plan,
)

RESOLVER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ExecutionStepRequirement:
    """Workflow-owned step identity and role, in deterministic execution-plan order."""

    step_key: str
    role: WorkerRole


def resolve_execution_plan(
    session: Session,
    *,
    preset_key: str,
    dependencies: ResolvedPlanDependencyEvidence,
    steps: tuple[ExecutionStepRequirement, ...],
    resolved_at: datetime | None = None,
) -> ResolvedExecutionPlan:
    """Resolve the currently published preset once for one exact workflow.

    Existing workflow plans are returned byte-for-byte. No current pointer is consulted during a
    replay after the first plan has been persisted.
    """

    if not steps:
        raise ControlPlaneError("CONTROL_PLAN_STEPS_MISSING", "execution plan has no steps")
    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == dependencies.workflow_id
        )
    )
    if existing is not None:
        return ResolvedExecutionPlan.model_validate(existing.canonical_document)

    logical = session.scalar(
        select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
    )
    if logical is None or logical.state != "ACTIVE" or logical.current_revision_id is None:
        raise ControlPlaneError(
            "CONTROL_PRESET_NOT_PUBLISHED", "execution preset has no published revision"
        )
    revision = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
    if revision is None or revision.preset_id != logical.preset_id or revision.state != "RELEASED":
        raise ControlPlaneError(
            "CONTROL_PRESET_POINTER_INVALID", "published execution preset is stale"
        )
    preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
    policies = {policy.role: policy for policy in preset.role_policies}
    if len(policies) != len(preset.role_policies):
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "execution preset has duplicate role policies"
        )

    resolved_steps: list[ResolvedStepExecution] = []
    seen_keys: set[str] = set()
    for required in steps:
        if required.step_key in seen_keys:
            raise ControlPlaneError("CONTROL_PLAN_STEP_DUPLICATE", "execution step is duplicated")
        seen_keys.add(required.step_key)
        policy = policies.get(required.role)
        if policy is None:
            raise ControlPlaneError(
                "CONTROL_PRESET_ROLE_MISSING", "execution preset does not define a required role"
            )
        candidate = policy.model_candidates[0]
        resolved_steps.append(
            ResolvedStepExecution(
                step_key=required.step_key,
                role=required.role,
                model=candidate.model,
                reasoning_effort=candidate.reasoning_effort,
                instruction_bundle=policy.instruction_bundle,
                reference_bundle=policy.reference_bundle,
                worker_pool_key=policy.worker_pool_key,
                timeout_seconds=policy.timeout_seconds,
                sandbox=policy.sandbox,
                network=policy.network,
                general_knowledge_mode=(
                    "DENIED"
                    if preset.general_knowledge_policy == "DENY"
                    else "ALLOWED_WITH_PROVENANCE"
                ),
            )
        )

    actual_resolved_at = resolved_at or datetime.now(UTC)
    if actual_resolved_at.tzinfo is None or actual_resolved_at.utcoffset() is None:
        raise ControlPlaneError("CONTROL_TIMESTAMP_INVALID", "resolution timestamp is not UTC")
    document = {
        "schema_version": "resolved-execution-plan/1.0",
        "plan_id": new_execution_plan_id(),
        "workflow_id": dependencies.workflow_id,
        "preset_id": preset.preset_id,
        "preset_revision_id": preset.preset_revision_id,
        "preset_sha256": preset.content_sha256,
        "workflow_definition_key": dependencies.workflow_definition_key,
        "workflow_definition_version": dependencies.workflow_definition_version,
        "workflow_definition_sha256": dependencies.workflow_definition_sha256,
        "content_pack_release_id": dependencies.content_pack_release_id,
        "content_pack_sha256": dependencies.content_pack_sha256,
        "capacity_policy_revision_id": preset.capacity_policy_revision_id,
        "graph_snapshot_revision_id": dependencies.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": dependencies.evidence_bundle_revision_id,
        "steps": [step.model_dump(mode="json") for step in resolved_steps],
        "resolver_version": RESOLVER_VERSION,
        "resolved_at": actual_resolved_at,
        "plan_sha256": "sha256:" + "0" * 64,
    }
    normalized = ResolvedExecutionPlan.model_validate(document).model_dump(mode="json")
    normalized["plan_sha256"] = compute_control_document_hash(normalized, "plan_sha256")
    model = ResolvedExecutionPlan.model_validate(normalized)
    record = record_resolved_execution_plan(
        session,
        document=model.model_dump(mode="json"),
        dependencies=dependencies,
    )
    return ResolvedExecutionPlan.model_validate(record.canonical_document)

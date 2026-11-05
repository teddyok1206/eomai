"""Resolve the released material purpose once; never replace a running input pin."""

from datetime import UTC, datetime

from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_identifiers import content_sha256, new_execution_plan_id
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    ResolvedExecutionPlanV33,
    ResolvedStepExecution,
)
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.material_learning_request import MaterialLearningWorkerRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_resolver import lock_current_execution_preset
from eom_orchestrator.material_learning_execution import validate_material_learning_execution_plan


def resolve_material_learning_plan(
    session: Session,
    *,
    workflow_id: str,
    workflow_definition_sha256: str,
    workflow_role_schema_version: str,
    work: MaterialLearningWork,
    expected_preset: ExecutionPresetRevision,
    resolved_at: datetime | None = None,
) -> ResolvedExecutionPlanV33:
    if workflow_role_schema_version != "workflow-role/1.37.0":
        raise ControlPlaneError("CONTROL_MATERIAL_PROTOCOL_INVALID", "material protocol differs")
    record = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow_id
        )
    )
    if record is not None:
        plan = validate_material_learning_execution_plan(
            record,
            workflow_id=workflow_id,
            step_key="learn",
            request=MaterialLearningWorkerRequest(work_input=work),
        )
        if plan.workflow_definition_sha256 != workflow_definition_sha256 or (
            plan.preset_id,
            plan.preset_revision_id,
            plan.preset_sha256,
        ) != (
            expected_preset.preset_id,
            expected_preset.preset_revision_id,
            expected_preset.content_sha256,
        ):
            raise ControlPlaneError(
                "CONTROL_PLAN_CONFLICT", "material plan already pins other input"
            )
        return plan
    preset = lock_current_execution_preset(
        session,
        preset_key="material-learning",
        workflow_role_schema_version=workflow_role_schema_version,
    )
    if preset != expected_preset:
        raise ControlPlaneError(
            "CONTROL_PRESET_POINTER_STALE", "material preset changed before pin"
        )
    if len(preset.role_policies) != 1 or preset.general_knowledge_policy != "DENY":
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "one source-only support role required"
        )
    policy = preset.role_policies[0]
    candidate = policy.model_candidates[0]
    step = ResolvedStepExecution(
        step_key="learn",
        role=policy.role,
        model=candidate.model,
        reasoning_effort=candidate.reasoning_effort,
        instruction_bundle=policy.instruction_bundle,
        reference_bundle=policy.reference_bundle,
        worker_pool_key=policy.worker_pool_key,
        timeout_seconds=policy.timeout_seconds,
        sandbox=policy.sandbox,
        network=policy.network,
        general_knowledge_mode="DENIED",
    )
    body = {
        "schema_version": "resolved-execution-plan/33.0",
        "plan_id": new_execution_plan_id(),
        "workflow_id": workflow_id,
        "workload_class": "KNOWLEDGE_ANALYSIS",
        "preset_id": preset.preset_id,
        "preset_revision_id": preset.preset_revision_id,
        "preset_sha256": preset.content_sha256,
        "workflow_definition_key": "material-learning",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": workflow_definition_sha256,
        "work_input": work.model_dump(mode="json"),
        "capacity_policy_revision_id": preset.capacity_policy_revision_id,
        "steps": [step.model_dump(mode="json")],
        "resolver_version": "33.0.0",
        "resolved_at": (resolved_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    document = {**body, "plan_sha256": content_sha256(body)}
    validate_control_contract("resolved-execution-plan-v33", document)
    plan = ResolvedExecutionPlanV33.model_validate(document)
    session.add(
        ResolvedExecutionPlanRecord(
            plan_id=plan.plan_id,
            workflow_id=plan.workflow_id,
            preset_id=plan.preset_id,
            preset_revision_id=plan.preset_revision_id,
            capacity_policy_revision_id=plan.capacity_policy_revision_id,
            graph_snapshot_revision_id=None,
            evidence_bundle_revision_id=None,
            plan_sha256=plan.plan_sha256,
            resolver_version=plan.resolver_version,
            canonical_document=plan.model_dump(mode="json"),
            resolved_at=plan.resolved_at,
        )
    )
    session.flush()
    session.add(
        ResolvedExecutionPlanStepRecord(
            plan_id=plan.plan_id,
            step_key=step.step_key,
            role=step.role,
            model=step.model,
            reasoning_effort=step.reasoning_effort,
            instruction_bundle_revision_id=step.instruction_bundle.bundle_revision_id,
            reference_bundle_revision_id=None,
            worker_pool_key=step.worker_pool_key,
            timeout_seconds=step.timeout_seconds,
            sandbox=step.sandbox,
            network=step.network,
            general_knowledge_mode=step.general_knowledge_mode,
        )
    )
    session.flush()
    return plan

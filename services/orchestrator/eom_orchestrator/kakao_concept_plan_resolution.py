"""Resolve a source-only concept phase once; no model, new queue or dedicated slot."""

from datetime import UTC, datetime

from eom_identifiers import content_sha256, new_execution_plan_id
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedStepExecution
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import CONCEPT_ROLE_PROTOCOL, KakaoConceptWork
from sqlalchemy import select
from sqlalchemy.orm import Session

from .control_models import (
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from .control_service import ControlPlaneError, capacity_worker_role_clause
from .execution_resolver import read_current_execution_preset


def validate_kakao_concept_execution_plan(
    record: ResolvedExecutionPlanRecord | None,
    *,
    workflow_id: str,
    step_key: str,
    work: KakaoConceptWork,
) -> KakaoConceptExecutionPlan:
    try:
        if record is None:
            raise ValueError("concept plan missing")
        plan = KakaoConceptExecutionPlan.model_validate(record.canonical_document)
        if (
            plan.workflow_id != workflow_id
            or step_key != "assist"
            or plan.work_input != work
            or any(
                getattr(record, name) != getattr(plan, name)
                for name in (
                    "plan_id",
                    "workflow_id",
                    "preset_id",
                    "preset_revision_id",
                    "capacity_policy_revision_id",
                    "plan_sha256",
                    "resolver_version",
                    "resolved_at",
                )
            )
            or record.graph_snapshot_revision_id is not None
            or record.evidence_bundle_revision_id is not None
        ):
            raise ValueError("concept plan row differs")
    except ValueError as error:
        raise ControlPlaneError(
            "CONTROL_KAKAO_CONCEPT_PLAN_UNAVAILABLE", "the exact concept execution plan is required"
        ) from error
    return plan


def resolve_kakao_concept_plan(
    session: Session,
    *,
    workflow_id: str,
    workflow_definition_sha256: str,
    workflow_role_schema_version: str,
    work: KakaoConceptWork,
    expected_preset: ExecutionPresetRevision,
    resolved_at: datetime | None = None,
) -> KakaoConceptExecutionPlan:
    if workflow_role_schema_version != CONCEPT_ROLE_PROTOCOL:
        raise ControlPlaneError(
            "CONTROL_KAKAO_CONCEPT_PROTOCOL_INVALID", "concept protocol differs"
        )
    record = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow_id
        )
    )
    if record is not None:
        plan = validate_kakao_concept_execution_plan(
            record, workflow_id=workflow_id, step_key="assist", work=work
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
                "CONTROL_PLAN_CONFLICT", "concept plan already pins other input"
            )
        return plan
    preset = read_current_execution_preset(
        session,
        preset_key="kakao-concepts",
        workflow_role_schema_version=workflow_role_schema_version,
    )
    if preset != expected_preset:
        raise ControlPlaneError("CONTROL_PRESET_POINTER_STALE", "concept preset changed before pin")
    if len(preset.role_policies) != 1 or preset.general_knowledge_policy != "DENY":
        raise ControlPlaneError(
            "CONTROL_PRESET_POLICY_INVALID", "one source-only support role required"
        )
    capacity = session.get(WorkerCapacityPolicyRevisionRecord, preset.capacity_policy_revision_id)
    if capacity is None or capacity.schema_version != "worker-capacity-policy/1.7":
        raise ControlPlaneError(
            "CONTROL_CAPACITY_ROLE_MISMATCH", "concept work requires ordinary shared slots"
        )
    # Public capacity owner validates the released policy/hash/pool and preserves reserved06.
    capacity_worker_role_clause(capacity, pool_key="support", execution_role="support")
    policy = preset.role_policies[0]
    candidate = policy.model_candidates[0]
    step = ResolvedStepExecution(
        step_key="assist",
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
    body = dict(
        schema_version="resolved-execution-plan/42.0",
        plan_id=new_execution_plan_id(),
        workflow_id=workflow_id,
        workload_class="KNOWLEDGE_ANALYSIS",
        preset_id=preset.preset_id,
        preset_revision_id=preset.preset_revision_id,
        preset_sha256=preset.content_sha256,
        workflow_definition_key="kakao-concepts",
        workflow_definition_version="1.0.0",
        workflow_definition_sha256=workflow_definition_sha256,
        work_input=work.model_dump(mode="json"),
        capacity_policy_revision_id=preset.capacity_policy_revision_id,
        steps=[step.model_dump(mode="json")],
        resolver_version="42.0.0",
        resolved_at=(resolved_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    )
    document = body | dict(plan_sha256=content_sha256(body))
    validate_control_contract("resolved-execution-plan-v42", document)
    plan = KakaoConceptExecutionPlan.model_validate(document)
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

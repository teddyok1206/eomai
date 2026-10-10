"""One Pack-free comparison plan in the caller-owned Workflow transaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_identifiers import content_sha256, new_execution_plan_id
from eom_workflow.control_plane import (
    ExecutionPresetRevision,
    InstructionBundleManifest,
    RoleExecutionPolicy,
    UtcDatetime,
)
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL
from eom_workflow.inference_transfer_control import (
    TRANSFER_RUBRIC_MEMBER,
    ResolvedExecutionPlanV21,
    validate_inference_transfer_rubric_instruction,
)
from eom_workflow.inference_transfer_materialization import (
    validate_inference_transfer_workflow_plan,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.schemas import validate_inference_transfer_workflow_request
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetRolePolicyRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    resolve_control_artifact_pointer,
    resolve_released_instruction_bundle,
)
from eom_orchestrator.execution_resolver import lock_current_execution_preset
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.preset_model_selection import preset_model_options, validated_preset

PRESET_KEY = "item-inference-transfer-comparison"


def resolve_inference_transfer_execution_plan(
    session: Session,
    *,
    workflow_id: str,
    workflow_definition_version: str,
    workflow_definition_sha256: str,
    workflow_role_schema_version: str,
    workflow_request: InferenceTransferWorkflowRequest,
    core_prompt_sha256: str,
    prompt_sha256: str,
    resolved_at: datetime,
) -> ResolvedExecutionPlanV21:
    """Pin once or replay exact history; no source-authority or worker-launch grant.

    Runner supplies the actual immutable Workflow request and holds its Workflow
    fence in this same transaction. The existing FK and unique Workflow key are
    additional guards, not permission for this adapter to create a Workflow.
    ``resolved_at`` is the current server observation time; replay preserves the
    original plan time while rechecking the selected candidate's availability.
    """

    try:
        request = validate_inference_transfer_workflow_request(
            workflow_request.model_dump(mode="json")
        )
        observed_at = TypeAdapter(UtcDatetime).validate_python(resolved_at)
        if workflow_definition_version != "1.0.0" or workflow_role_schema_version != (
            TRANSFER_PAIR_PROTOCOL
        ):
            raise ValueError("comparison definition or protocol differs")
    except (ValueError, JsonSchemaValidationError) as exc:
        raise ControlPlaneError(
            "CONTROL_TRANSFER_CONTEXT_INVALID", "comparison Workflow context is invalid"
        ) from exc
    if session.get(ProtocolVersionRecord, workflow_role_schema_version) is None:
        raise ControlPlaneError("CONTROL_PROTOCOL_MISSING", "comparison protocol is not registered")

    existing = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow_id
        )
    )
    if existing is not None:
        plan = _checked_context(
            existing.canonical_document,
            request=request,
            workflow_id=workflow_id,
            workflow_definition_sha256=workflow_definition_sha256,
            core_prompt_sha256=core_prompt_sha256,
            prompt_sha256=prompt_sha256,
        )
        _require_record_closure(session, existing, plan)
        preset = _pinned_preset(session, plan)
        instruction = resolve_released_instruction_bundle(
            session, _single_policy(preset).instruction_bundle
        )
    else:
        preset = lock_current_execution_preset(
            session,
            preset_key=PRESET_KEY,
            workflow_role_schema_version=workflow_role_schema_version,
        )
        # Reparse the row through the same public schema/hash/identity boundary
        # used by model selection; the current-pointer lock is retained.
        row = session.get(ExecutionPresetRevisionRecord, preset.preset_revision_id)
        if row is None:
            raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "preset revision is missing")
        checked_preset = validated_preset(row)
        if (
            not isinstance(checked_preset, ExecutionPresetRevision)
            or checked_preset != preset
            or row.capacity_policy_revision_id != preset.capacity_policy_revision_id
            or tuple(row.compatible_workflow_protocols) != preset.compatible_workflow_protocols
        ):
            raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "preset document differs")
        policy = _single_policy(preset)
        instruction = resolve_released_instruction_bundle(session, policy.instruction_bundle)
        members = {
            component.relative_path: component.artifact for component in instruction.components
        }
        rubric = members.get(TRANSFER_RUBRIC_MEMBER)
        if rubric is None:
            raise ControlPlaneError(
                "CONTROL_TRANSFER_RUBRIC_INVALID", "comparison rubric member is missing"
            )
        body: dict[str, Any] = {
            "schema_version": "resolved-execution-plan/21.0",
            "plan_id": new_execution_plan_id(),
            "workflow_id": workflow_id,
            "preset_id": preset.preset_id,
            "preset_revision_id": preset.preset_revision_id,
            "preset_sha256": preset.content_sha256,
            "workflow_definition_sha256": workflow_definition_sha256,
            "comparison_request_sha256": request.comparison.request_sha256,
            "left_profile": request.comparison.left_profile.model_dump(mode="json"),
            "right_profile": request.comparison.right_profile.model_dump(mode="json"),
            "graph_snapshot": request.left_profile.source_basis.graph_snapshot.model_dump(
                mode="json"
            ),
            "access_policy_revision_id": request.access_policy_revision_id,
            "access_policy_sha256": request.access_policy_sha256,
            "requester_permissions_sha256": request.requester_permissions_sha256,
            "rubric": request.comparison.rubric.model_dump(mode="json"),
            "rubric_artifact": rubric.model_dump(mode="json"),
            "core_prompt_sha256": core_prompt_sha256,
            "prompt_sha256": prompt_sha256,
            "capacity_policy_revision_id": preset.capacity_policy_revision_id,
            "steps": [_policy_step(policy)],
            "resolved_at": observed_at.isoformat().replace("+00:00", "Z"),
        }
        # Defaults are part of canonical V21 bytes, not implicit persisted state.
        body.update(
            workload_class="CODEX",
            workflow_definition_key=PRESET_KEY,
            workflow_definition_version=workflow_definition_version,
            resolver_version="21.0.0",
        )
        body["plan_sha256"] = content_sha256(body)
        plan = _checked_context(
            body,
            request=request,
            workflow_id=workflow_id,
            workflow_definition_sha256=workflow_definition_sha256,
            core_prompt_sha256=core_prompt_sha256,
            prompt_sha256=prompt_sha256,
        )
    _admit_exact_controls(
        session, preset=preset, plan=plan, instruction=instruction, observed_at=observed_at
    )
    if existing is None:
        _record_validated_inference_transfer_plan(session, plan)
    return plan


def _checked_context(
    document: object,
    *,
    request: InferenceTransferWorkflowRequest,
    workflow_id: str,
    workflow_definition_sha256: str,
    core_prompt_sha256: str,
    prompt_sha256: str,
) -> ResolvedExecutionPlanV21:
    try:
        plan = validate_inference_transfer_workflow_plan(
            document,
            workflow_request=request,
            workflow_id=workflow_id,
            step_key="compare_pair",
            core_prompt_sha256=core_prompt_sha256,
            prompt_sha256=prompt_sha256,
        )
        if plan.workflow_definition_sha256 != workflow_definition_sha256:
            raise ValueError("comparison Workflow definition pin differs")
    except (ValueError, JsonSchemaValidationError) as exc:
        raise ControlPlaneError(
            "CONTROL_TRANSFER_CONTEXT_INVALID", "comparison plan and Workflow pins differ"
        ) from exc
    return plan


def _pinned_preset(session: Session, plan: ResolvedExecutionPlanV21) -> ExecutionPresetRevision:
    logical = session.get(ExecutionPresetRecord, plan.preset_id)
    row = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
    if (
        logical is None
        or logical.preset_key != PRESET_KEY
        or logical.state != "ACTIVE"
        or row is None
    ):
        raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "pinned preset is unavailable")
    preset = validated_preset(row)
    if (
        not isinstance(preset, ExecutionPresetRevision)
        or preset.preset_id != plan.preset_id
        or preset.preset_revision_id != plan.preset_revision_id
        or preset.content_sha256 != plan.preset_sha256
        or preset.state != "RELEASED"
        or TRANSFER_PAIR_PROTOCOL not in preset.compatible_workflow_protocols
        or tuple(row.compatible_workflow_protocols) != preset.compatible_workflow_protocols
        or row.capacity_policy_revision_id != preset.capacity_policy_revision_id
    ):
        raise ControlPlaneError("CONTROL_PRESET_POINTER_INVALID", "pinned preset identity differs")
    return preset


def _single_policy(preset: ExecutionPresetRevision) -> RoleExecutionPolicy:
    if (
        len(preset.role_policies) != 1
        or len(preset.role_policies[0].model_candidates) != 1
        or preset.general_knowledge_policy != "DENY"
    ):
        raise ControlPlaneError(
            "CONTROL_PLAN_POLICY_MISMATCH",
            "comparison requires one candidate and denied general knowledge",
        )
    return preset.role_policies[0]


def _policy_step(policy: RoleExecutionPolicy) -> dict[str, Any]:
    candidate = policy.model_candidates[0]
    return {
        "step_key": "compare_pair",
        "role": str(policy.role),
        "model": candidate.model,
        "reasoning_effort": str(candidate.reasoning_effort),
        "instruction_bundle": policy.instruction_bundle.model_dump(mode="json"),
        "reference_bundle": (
            policy.reference_bundle.model_dump(mode="json")
            if policy.reference_bundle is not None
            else None
        ),
        "worker_pool_key": policy.worker_pool_key,
        "timeout_seconds": policy.timeout_seconds,
        "sandbox": policy.sandbox,
        "network": policy.network,
        "general_knowledge_mode": "DENIED",
    }


def _admit_exact_controls(
    session: Session,
    *,
    preset: ExecutionPresetRevision,
    plan: ResolvedExecutionPlanV21,
    instruction: InstructionBundleManifest,
    observed_at: datetime,
) -> None:
    policy = _single_policy(preset)
    if (
        plan.preset_id != preset.preset_id
        or plan.preset_revision_id != preset.preset_revision_id
        or plan.preset_sha256 != preset.content_sha256
        or plan.capacity_policy_revision_id != preset.capacity_policy_revision_id
        or plan.steps[0].model_dump(mode="json") != _policy_step(policy)
    ):
        raise ControlPlaneError(
            "CONTROL_PLAN_POLICY_MISMATCH", "comparison plan differs from preset"
        )
    rows = tuple(
        session.scalars(
            select(ExecutionPresetRolePolicyRecord).where(
                ExecutionPresetRolePolicyRecord.preset_revision_id == preset.preset_revision_id
            )
        )
    )
    expected = {
        "preset_revision_id": preset.preset_revision_id,
        "role": str(policy.role),
        "model_candidates": [
            candidate.model_dump(mode="json") for candidate in policy.model_candidates
        ],
        "instruction_bundle_revision_id": policy.instruction_bundle.bundle_revision_id,
        "reference_bundle_revision_id": (
            policy.reference_bundle.bundle_revision_id
            if policy.reference_bundle is not None
            else None
        ),
        "worker_pool_key": policy.worker_pool_key,
        "timeout_seconds": policy.timeout_seconds,
        "sandbox": policy.sandbox,
        "network": policy.network,
    }
    if len(rows) != 1 or any(getattr(rows[0], key) != value for key, value in expected.items()):
        raise ControlPlaneError("CONTROL_PLAN_POLICY_MISMATCH", "preset role projection differs")
    try:
        validate_inference_transfer_rubric_instruction(plan, instruction)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_TRANSFER_RUBRIC_INVALID", "released comparison rubric differs"
        ) from exc
    for component in instruction.components:
        resolve_control_artifact_pointer(
            session, component.artifact, expected_media_type="text/markdown"
        )
    candidate = policy.model_candidates[0]
    options = preset_model_options(session, preset, observed_at=observed_at)
    if candidate not in options.get(str(policy.role), ()):
        raise ControlPlaneError(
            "CONTROL_PRESET_MODEL_UNAVAILABLE", "comparison candidate has no fresh admitted slot"
        )


def _plan_projection(plan: ResolvedExecutionPlanV21) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "workflow_id": plan.workflow_id,
        "preset_id": plan.preset_id,
        "preset_revision_id": plan.preset_revision_id,
        "capacity_policy_revision_id": plan.capacity_policy_revision_id,
        "graph_snapshot_revision_id": plan.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": None,
        "plan_sha256": plan.plan_sha256,
        "resolver_version": plan.resolver_version,
        "canonical_document": plan.model_dump(mode="json"),
        "resolved_at": plan.resolved_at,
    }


def _step_projection(plan: ResolvedExecutionPlanV21) -> dict[str, Any]:
    step = plan.steps[0]
    return {
        "plan_id": plan.plan_id,
        "step_key": step.step_key,
        "role": str(step.role),
        "model": step.model,
        "reasoning_effort": str(step.reasoning_effort),
        "instruction_bundle_revision_id": step.instruction_bundle.bundle_revision_id,
        "reference_bundle_revision_id": None,
        "worker_pool_key": step.worker_pool_key,
        "timeout_seconds": step.timeout_seconds,
        "sandbox": step.sandbox,
        "network": step.network,
        "general_knowledge_mode": str(step.general_knowledge_mode),
    }


def _require_record_closure(
    session: Session, record: ResolvedExecutionPlanRecord, plan: ResolvedExecutionPlanV21
) -> None:
    if any(getattr(record, key) != value for key, value in _plan_projection(plan).items()):
        raise ControlPlaneError("CONTROL_PLAN_CONFLICT", "stored comparison plan identity differs")
    rows = tuple(
        session.scalars(
            select(ResolvedExecutionPlanStepRecord).where(
                ResolvedExecutionPlanStepRecord.plan_id == plan.plan_id
            )
        )
    )
    if len(rows) != 1 or any(
        getattr(rows[0], key) != value for key, value in _step_projection(plan).items()
    ):
        raise ControlPlaneError(
            "CONTROL_PLAN_CONFLICT", "stored comparison step projection differs"
        )


def _record_validated_inference_transfer_plan(
    session: Session, plan: ResolvedExecutionPlanV21
) -> ResolvedExecutionPlanRecord:
    """Persist only the admitted plan; the caller owns the surrounding transaction."""

    if session.get(ResolvedExecutionPlanRecord, plan.plan_id) is not None:
        raise ControlPlaneError("CONTROL_PLAN_CONFLICT", "comparison plan identity is already used")
    record = ResolvedExecutionPlanRecord(**_plan_projection(plan))
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        # A raced Workflow winner is a conflict, not evidence that this plan
        # succeeded. Leave rollback to the caller; do not query a failed Tx.
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == (
            "uq_execution_plan_workflow"
        ):
            raise ControlPlaneError(
                "CONTROL_PLAN_CONFLICT", "Workflow already has a comparison plan"
            ) from exc
        raise
    session.add(ResolvedExecutionPlanStepRecord(**_step_projection(plan)))
    # Do not catch arbitrary integrity failures and manufacture a successful
    # replay. The existing Workflow fence and unique/FK constraints are retained.
    session.flush()
    return record

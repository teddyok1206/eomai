"""Atomic pair admission through the existing Workflow, V21 and command repositories."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
    prepare_inference_transfer_worker_comparison_v11,
)
from eom_operator_identity import ActorContext
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.inference_transfer_resolution import (
    read_inference_transfer_execution_plan,
    read_inference_transfer_execution_plan_v11,
    resolve_inference_transfer_execution_plan,
    resolve_inference_transfer_execution_plan_v11,
)
from eom_workflow import compile_definition_data
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_PROTOCOL_V11,
    TRANSFER_PAIR_WORKFLOW_KEY,
    TRANSFER_PAIR_WORKFLOW_VERSION,
    TRANSFER_PAIR_WORKFLOW_VERSION_V11,
)
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV21
from eom_workflow.inference_transfer_workflow import (
    InferenceTransferWorkflowRequest,
    InferenceTransferWorkflowRequestV11,
)
from eom_workflow_runner.inference_transfer_admission import InferenceTransferSubmissionContext
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    admitted_workflow_definition,
    create_workflow_instance,
    enqueue_command,
    inference_transfer_business_fingerprint,
    load_persisted_inference_transfer_workflow_request,
)
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_submission import AuthorizedInferenceTransferSubmission


class InferenceTransferStartAdapter:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def start(
        self,
        submission: AuthorizedInferenceTransferSubmission,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        if actor.actor_id != submission.operator_id:
            raise ApiError(
                403, "PERMISSION_DENIED", "Permission denied", "Actual principal differs."
            )
        with transaction(self.sessions) as session:
            # The existing unique key protects persistence. This bounded advisory
            # lock also serializes capture/replay when current permission SHA changes.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "inference-transfer-start:" + idempotency_key},
            )
            existing = session.scalar(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                validate_inference_transfer_start_replay(session, existing, submission)
                return inference_transfer_start_identity(session, existing)
            definition = admitted_workflow_definition(
                session,
                definition_key=TRANSFER_PAIR_WORKFLOW_KEY,
                definition_version=(
                    TRANSFER_PAIR_WORKFLOW_VERSION_V11
                    if isinstance(submission.workflow_request, InferenceTransferWorkflowRequestV11)
                    else TRANSFER_PAIR_WORKFLOW_VERSION
                ),
            )
            if definition is None:
                raise ApiError(
                    503,
                    "INFERENCE_TRANSFER_NOT_READY",
                    "Comparison unavailable",
                    "The purpose-specific Workflow is not admitted.",
                )
            _check_definition(
                definition,
                version=(
                    TRANSFER_PAIR_WORKFLOW_VERSION_V11
                    if isinstance(submission.workflow_request, InferenceTransferWorkflowRequestV11)
                    else TRANSFER_PAIR_WORKFLOW_VERSION
                ),
            )

            def resolve_plan(
                actual: Session,
                workflow: WorkflowInstanceRecord,
                core_prompt_sha256: str,
                prompt_sha256: str,
            ) -> ResolvedExecutionPlanV21:
                return _resolve_initial_plan(
                    actual,
                    workflow=workflow,
                    definition=definition,
                    wrapper=submission.workflow_request,
                    core_prompt_sha256=core_prompt_sha256,
                    prompt_sha256=prompt_sha256,
                )

            return start_inference_transfer_in_session(
                session,
                definition=definition,
                submission=submission,
                actor=actor,
                idempotency_key=idempotency_key,
                resolve_plan=resolve_plan,
            )


def _resolve_initial_plan(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    definition: WorkflowDefinitionRecord,
    wrapper: object,
    core_prompt_sha256: str,
    prompt_sha256: str,
) -> ResolvedExecutionPlanV21:
    if isinstance(wrapper, InferenceTransferWorkflowRequestV11):
        return resolve_inference_transfer_execution_plan_v11(
            session,
            workflow_id=workflow.workflow_id,
            workflow_definition_version=definition.definition_version,
            workflow_definition_sha256=definition.definition_hash,
            workflow_role_schema_version=workflow.role_schema_version,
            workflow_request=wrapper,
            core_prompt_sha256=core_prompt_sha256,
            prompt_sha256=prompt_sha256,
            resolved_at=datetime.now(UTC),
        )
    if not isinstance(wrapper, InferenceTransferWorkflowRequest):
        raise ValueError("typed comparison wrapper required")
    return resolve_inference_transfer_execution_plan(
        session,
        workflow_id=workflow.workflow_id,
        workflow_definition_version=definition.definition_version,
        workflow_definition_sha256=definition.definition_hash,
        workflow_role_schema_version=workflow.role_schema_version,
        workflow_request=wrapper,
        core_prompt_sha256=core_prompt_sha256,
        prompt_sha256=prompt_sha256,
        resolved_at=datetime.now(UTC),
    )


def start_inference_transfer_in_session(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    submission: AuthorizedInferenceTransferSubmission,
    actor: ActorContext,
    idempotency_key: str,
    resolve_plan: Callable[[Session, WorkflowInstanceRecord, str, str], ResolvedExecutionPlanV21],
    runtime_context: dict[str, Any] | None = None,
) -> tuple[str, str, int]:
    """Reuse atomic START materialization; the caller owns locks and transaction."""
    wrapper = submission.workflow_request
    context = dict(runtime_context or {})
    context["inference_transfer_submission"] = {
        "submission_sha256": submission.selection.submission_sha256,
        "snapshot_header_sha256": submission.selection.expected_header_sha256,
    }
    workflow, created = create_workflow_instance(
        session,
        definition=definition,
        request=wrapper,
        idempotency_key=idempotency_key,
        actor_type="human",
        actor_id=actor.actor_id,
        runtime_context=context,
        inference_transfer_context=InferenceTransferSubmissionContext(
            operator_id=actor.actor_id,
            requester_permissions_sha256=wrapper.requester_permissions_sha256,
        ),
    )
    if not created:
        validate_inference_transfer_start_replay(session, workflow, submission)
        return inference_transfer_start_identity(session, workflow)
    prepared = (
        prepare_inference_transfer_worker_comparison_v11(
            wrapper.comparison, left=wrapper.left_profile, right=wrapper.right_profile
        )
        if isinstance(wrapper, InferenceTransferWorkflowRequestV11)
        else prepare_inference_transfer_worker_comparison(
            wrapper.comparison, left=wrapper.left_profile, right=wrapper.right_profile
        )
    )
    try:
        plan = resolve_plan(session, workflow, prepared.core_prompt_sha256, prepared.prompt_sha256)
    except ControlPlaneError as exc:
        # Caller transaction rolls back Workflow, plan and START together.
        raise ApiError(
            409,
            exc.code,
            "Comparison controls unavailable",
            "The exact comparison controls are not released and compatible.",
        ) from exc
    context = dict(workflow.runtime_context)
    context["execution_plan"] = {
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "preset_id": plan.preset_id,
        "preset_revision_id": plan.preset_revision_id,
    }
    workflow.runtime_context = context
    command, _ = enqueue_command(
        session,
        workflow_id=workflow.workflow_id,
        command_type=CommandType.START_WORKFLOW,
        payload={},
        actor_type="human",
        actor_id=actor.actor_id,
        source="application_api",
        idempotency_key=f"start:{workflow.workflow_id}",
    )
    return command.command_id, workflow.workflow_id, workflow.lock_version


def _check_definition(
    definition: WorkflowDefinitionRecord, *, version: str = TRANSFER_PAIR_WORKFLOW_VERSION
) -> None:
    compiled = compile_definition_data(
        definition.canonical_definition, definition.source_path, {"support"}
    )
    if (
        compiled.sha256 != definition.definition_hash
        or compiled.definition.definition_key != TRANSFER_PAIR_WORKFLOW_KEY
        or compiled.definition.definition_version != version
    ):
        raise ApiError(
            503,
            "INFERENCE_TRANSFER_CONTRACT_INVALID",
            "Comparison unavailable",
            "The stored Workflow definition does not match its immutable hash.",
        )


def validate_inference_transfer_start_replay(
    session: Session,
    workflow: WorkflowInstanceRecord,
    submission: AuthorizedInferenceTransferSubmission,
) -> ResolvedExecutionPlanV21:
    definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
    if definition is None:
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The original comparison definition is missing.",
        )
    successor = isinstance(submission.workflow_request, InferenceTransferWorkflowRequestV11)
    version = TRANSFER_PAIR_WORKFLOW_VERSION_V11 if successor else TRANSFER_PAIR_WORKFLOW_VERSION
    _check_definition(definition, version=version)
    original = load_persisted_inference_transfer_workflow_request(workflow.initial_request)
    metadata = workflow.runtime_context.get("inference_transfer_submission")
    expected = {
        "submission_sha256": submission.selection.submission_sha256,
        "snapshot_header_sha256": submission.selection.expected_header_sha256,
    }
    # Source reads happened before this lookup. Preserve initial permission capture,
    # not a new wrapper SHA, while requiring all other immutable input bytes exact.
    if (
        workflow.created_actor_type != "human"
        or workflow.created_actor_id != submission.operator_id
        or workflow.definition_key != TRANSFER_PAIR_WORKFLOW_KEY
        or workflow.definition_version != version
        or workflow.protocol_version != "1.0.1"
        or workflow.role_schema_version
        != (TRANSFER_PAIR_PROTOCOL_V11 if successor else TRANSFER_PAIR_PROTOCOL)
        or workflow.definition_hash != definition.definition_hash
        or workflow.request_hash
        != inference_transfer_business_fingerprint(
            definition, original, actor_type="human", actor_id=submission.operator_id
        )
        or metadata != expected
        or original.model_dump(
            mode="json", exclude={"request_sha256", "requester_permissions_sha256"}
        )
        != submission.workflow_request.model_dump(
            mode="json", exclude={"request_sha256", "requester_permissions_sha256"}
        )
        or workflow.request_payload != workflow.initial_request
    ):
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The existing immutable comparison differs from this exact submission.",
        )
    prepared = (
        prepare_inference_transfer_worker_comparison_v11(
            original.comparison, left=original.left_profile, right=original.right_profile
        )
        if isinstance(original, InferenceTransferWorkflowRequestV11)
        else prepare_inference_transfer_worker_comparison(
            original.comparison, left=original.left_profile, right=original.right_profile
        )
    )
    pin = workflow.runtime_context.get("execution_plan")
    if not isinstance(pin, dict) or not isinstance(pin.get("plan_id"), str):
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The original comparison execution pin is missing.",
        )
    try:
        plan: ResolvedExecutionPlanV21
        if isinstance(original, InferenceTransferWorkflowRequestV11):
            plan = read_inference_transfer_execution_plan_v11(
                session,
                plan_id=pin["plan_id"],
                workflow_id=workflow.workflow_id,
                workflow_definition_sha256=workflow.definition_hash,
                workflow_request=original,
                core_prompt_sha256=prepared.core_prompt_sha256,
                prompt_sha256=prepared.prompt_sha256,
            )
        else:
            plan = read_inference_transfer_execution_plan(
                session,
                plan_id=pin["plan_id"],
                workflow_id=workflow.workflow_id,
                workflow_definition_sha256=workflow.definition_hash,
                workflow_request=original,
                core_prompt_sha256=prepared.core_prompt_sha256,
                prompt_sha256=prepared.prompt_sha256,
            )
    except ControlPlaneError as exc:
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The original comparison execution plan differs.",
        ) from exc
    if pin != {
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "preset_id": plan.preset_id,
        "preset_revision_id": plan.preset_revision_id,
    }:
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The original comparison execution pin differs.",
        )

    return plan


def inference_transfer_start_identity(
    session: Session, workflow: WorkflowInstanceRecord
) -> tuple[str, str, int]:
    command = session.scalar(
        select(WorkflowCommandRecord)
        .where(
            WorkflowCommandRecord.workflow_id == workflow.workflow_id,
            WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
            WorkflowCommandRecord.actor_id == workflow.created_actor_id,
            WorkflowCommandRecord.actor_type == "human",
            WorkflowCommandRecord.source == "application_api",
        )
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .limit(1)
    )
    if command is None:
        raise ApiError(
            409,
            "INFERENCE_TRANSFER_SUBMISSION_CONFLICT",
            "Comparison replay conflict",
            "The existing comparison has no matching original start command.",
        )
    return command.command_id, workflow.workflow_id, workflow.lock_version

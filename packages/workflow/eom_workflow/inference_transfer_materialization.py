"""Small application-owned context for one exact comparison materialization."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from eom_workflow.control_plane import FrozenModel, Sha256, WorkflowId
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    InferenceTransferPairWorkerRequest,
    validate_inference_transfer_execution_plan,
)
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV21
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.models import RoleWorkerInput
from eom_workflow.schemas import validate_inference_transfer_workflow_request, validate_role_input


class InferenceTransferMaterializationContext(FrozenModel):
    """Exact expected values, never source authority or a separately stored entity."""

    workflow_id: WorkflowId
    step_key: Literal["compare_pair"] = "compare_pair"
    workflow_request: InferenceTransferWorkflowRequest
    worker_input: RoleWorkerInput
    core_prompt_sha256: Sha256
    prompt_sha256: Sha256

    @model_validator(mode="after")
    def exact_workflow_and_role_input(self) -> InferenceTransferMaterializationContext:
        request = validate_inference_transfer_workflow_request(
            self.workflow_request.model_dump(mode="json")
        )
        document = self.worker_input.model_dump(mode="json")
        validate_role_input(document, "support", TRANSFER_PAIR_PROTOCOL)
        worker_input = RoleWorkerInput.model_validate(document)
        if (
            worker_input.workflow_id != self.workflow_id
            or worker_input.protocol_version != TRANSFER_PAIR_PROTOCOL
            or worker_input.role != "support"
            or worker_input.upstream_artifacts
            or not isinstance(worker_input.request, InferenceTransferPairWorkerRequest)
            or worker_input.request != request.worker_request()
        ):
            raise ValueError("inference-transfer materialization role input differs")
        return self


def validate_inference_transfer_materialization_plan(
    document: object, *, context: InferenceTransferMaterializationContext
) -> ResolvedExecutionPlanV21:
    """Bind V21 to independently prepared policy, permissions, input and prompt pins."""

    checked = InferenceTransferMaterializationContext.model_validate(
        context.model_dump(mode="json")
    )
    return validate_inference_transfer_workflow_plan(
        document,
        workflow_request=checked.workflow_request,
        workflow_id=checked.workflow_id,
        step_key=checked.step_key,
        core_prompt_sha256=checked.core_prompt_sha256,
        prompt_sha256=checked.prompt_sha256,
    )


def validate_inference_transfer_workflow_plan(
    document: object,
    *,
    workflow_request: InferenceTransferWorkflowRequest,
    workflow_id: str,
    step_key: str,
    core_prompt_sha256: str,
    prompt_sha256: str,
) -> ResolvedExecutionPlanV21:
    """Validate independent Workflow pins before an ephemeral job identity exists."""

    request = validate_inference_transfer_workflow_request(workflow_request.model_dump(mode="json"))
    plan = validate_inference_transfer_execution_plan(
        document,
        request=request.worker_request(),
        workflow_id=workflow_id,
        step_key=step_key,
        core_prompt_sha256=core_prompt_sha256,
        prompt_sha256=prompt_sha256,
    )
    if (
        plan.access_policy_revision_id != request.access_policy_revision_id
        or plan.access_policy_sha256 != request.access_policy_sha256
        or plan.requester_permissions_sha256 != request.requester_permissions_sha256
    ):
        raise ValueError("inference-transfer materialization policy or permissions differ")
    return plan

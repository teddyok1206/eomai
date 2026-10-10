"""Pure application-purpose admission; source authorization is a separate owner port."""

from __future__ import annotations

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_WORKFLOW_KEY,
    TRANSFER_PAIR_WORKFLOW_VERSION,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.models import WorkflowRequest
from eom_workflow.schemas import (
    WorkflowSchemaError,
    validate_inference_transfer_workflow_request,
)
from pydantic import Field, ValidationError

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode


class InferenceTransferSubmissionContext(FrozenModel):
    """Server-composition input, not authentication evidence or a permission grant."""

    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    requester_permissions_sha256: Sha256


def admit_inference_transfer_workflow_request(
    *,
    definition_key: str,
    definition_version: str,
    role_protocol_version: str | None,
    request: WorkflowRequest | InferenceTransferWorkflowRequest,
    actor_type: str,
    actor_id: str,
    submission_context: InferenceTransferSubmissionContext | None,
) -> WorkflowRequest | InferenceTransferWorkflowRequest:
    """Reject cross-purpose input before lookup/create; do not authorize sources here."""

    is_purpose = definition_key == TRANSFER_PAIR_WORKFLOW_KEY
    is_transfer = isinstance(request, InferenceTransferWorkflowRequest)
    if is_purpose != is_transfer or (not is_transfer and submission_context is not None):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "workflow request kind does not match comparison purpose",
        )
    if not is_transfer:
        return request
    if (
        definition_version != TRANSFER_PAIR_WORKFLOW_VERSION
        or role_protocol_version != TRANSFER_PAIR_PROTOCOL
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "comparison workflow definition version or protocol differs",
        )
    if submission_context is None or actor_type != "human":
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "comparison requires an explicit server-owned operator context",
        )
    try:
        checked = validate_inference_transfer_workflow_request(request.model_dump(mode="json"))
        context = InferenceTransferSubmissionContext.model_validate(
            submission_context.model_dump(mode="json")
        )
    except (ValidationError, WorkflowSchemaError) as exc:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "comparison workflow request or server context is invalid",
        ) from exc
    if (
        actor_id != context.operator_id
        or checked.requester_permissions_sha256 != context.requester_permissions_sha256
    ):
        raise WorkflowError(
            WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
            "comparison operator or initial audit snapshot differs",
        )
    return checked

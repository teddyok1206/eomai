"""Principal-injected API-peer comparison reads; no reusable authorization token."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
    parse_workflow_read_request,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

type InferenceTransferWorkflowBindingError = Literal[
    "INFERENCE_TRANSFER_FORBIDDEN",
    "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND",
    "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
    "INFERENCE_TRANSFER_WORKFLOW_CHANGED",
    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
    "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE",
    "INFERENCE_TRANSFER_RESULT_INVALID",
    "INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED",
]
type TransferOperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES = 256 * 1024


def _canonical_binding_hash(value: FrozenModel, field: str) -> None:
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError(f"{field} differs from the canonical private comparison binding")
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > (
        MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES
    ):
        raise ValueError("private comparison binding exceeds its encoded byte budget")


class InferenceTransferWorkflowBindingRequest(FrozenModel):
    """The authenticated API principal supplies actor_id; never a public body/model."""

    schema_version: Literal["inference-transfer-workflow-binding-request/1.0"] = (
        "inference-transfer-workflow-binding-request/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_WORKFLOW_READ"] = "INFERENCE_TRANSFER_WORKFLOW_READ"
    actor_id: TransferOperatorId
    request: InferenceTransferWorkflowReadRequest
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_private_binding(self) -> InferenceTransferWorkflowBindingRequest:
        parse_workflow_read_request(self.request.model_dump(mode="json"))
        _canonical_binding_hash(self, "binding_sha256")
        return self


class InferenceTransferWorkflowBindingReply(FrozenModel):
    schema_version: Literal["inference-transfer-workflow-binding-reply/1.0"] = (
        "inference-transfer-workflow-binding-reply/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_WORKFLOW_READ"] = "INFERENCE_TRANSFER_WORKFLOW_READ"
    actor_id: TransferOperatorId | None
    request_binding_sha256: Sha256 | None
    status: Literal["SUCCESS", "FAILED"]
    result: InferenceTransferWorkflowReadResult | None
    error_code: InferenceTransferWorkflowBindingError | None
    reply_sha256: Sha256

    @model_validator(mode="after")
    def exact_reply_presence(self) -> InferenceTransferWorkflowBindingReply:
        if (self.status == "SUCCESS") != (self.result is not None) or (
            (self.status == "FAILED") != (self.error_code is not None)
        ):
            raise ValueError("comparison binding status/result/error presence differs")
        if (self.actor_id is None) != (self.request_binding_sha256 is None) or (
            self.status == "SUCCESS" and self.actor_id is None
        ):
            raise ValueError("comparison binding actor/hash context must be jointly present")
        if self.result is not None:
            parse_workflow_read_result(self.result.model_dump(mode="json"))
        _canonical_binding_hash(self, "reply_sha256")
        return self


def parse_workflow_binding_request(value: object) -> InferenceTransferWorkflowBindingRequest:
    if not isinstance(value, dict):
        raise ValueError("private comparison read request must be a JSON object")
    validate_contract("item-inference-transfer-workflow-binding", value)
    return InferenceTransferWorkflowBindingRequest.model_validate(value)


def parse_workflow_binding_reply(value: object) -> InferenceTransferWorkflowBindingReply:
    if not isinstance(value, dict):
        raise ValueError("private comparison read reply must be a JSON object")
    validate_contract("item-inference-transfer-workflow-binding", value)
    return InferenceTransferWorkflowBindingReply.model_validate(value)


def validate_workflow_binding_reply(
    request: InferenceTransferWorkflowBindingRequest,
    reply: InferenceTransferWorkflowBindingReply,
) -> None:
    """Bind the exact actual principal/request; a SUCCESS string is not access proof."""
    request = parse_workflow_binding_request(request.model_dump(mode="json"))
    reply = parse_workflow_binding_reply(reply.model_dump(mode="json"))
    if reply.status == "FAILED" and reply.actor_id is None:
        # A malformed frame has no validated identity to echo. It carries no
        # source/result content and can only deny, never establish permission.
        return
    if reply.actor_id != request.actor_id or reply.request_binding_sha256 != request.binding_sha256:
        raise ValueError("private comparison reply actor or exact request binding differs")
    if reply.result is not None:
        validate_workflow_read_result_context(request.request, reply.result)

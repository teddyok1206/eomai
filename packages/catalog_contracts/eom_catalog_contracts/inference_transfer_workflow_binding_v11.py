"""Principal-injected API-peer comparison reads; no reusable authorization token."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
    validate_workflow_read_result_context_v11,
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


class InferenceTransferWorkflowBindingRequestV11(FrozenModel):
    """The authenticated API principal supplies actor_id; never a public body/model."""

    schema_version: Literal["inference-transfer-workflow-binding-request/1.1"] = (
        "inference-transfer-workflow-binding-request/1.1"
    )
    operation: Literal["INFERENCE_TRANSFER_WORKFLOW_READ"] = "INFERENCE_TRANSFER_WORKFLOW_READ"
    actor_id: TransferOperatorId
    request: InferenceTransferWorkflowReadRequestV11
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_private_binding(self) -> InferenceTransferWorkflowBindingRequestV11:
        parse_workflow_read_request_v11(self.request.model_dump(mode="json"))
        _canonical_binding_hash(self, "binding_sha256")
        return self


class InferenceTransferWorkflowBindingReplyV11(FrozenModel):
    schema_version: Literal["inference-transfer-workflow-binding-reply/1.1"] = (
        "inference-transfer-workflow-binding-reply/1.1"
    )
    operation: Literal["INFERENCE_TRANSFER_WORKFLOW_READ"] = "INFERENCE_TRANSFER_WORKFLOW_READ"
    actor_id: TransferOperatorId | None
    request_binding_sha256: Sha256 | None
    status: Literal["SUCCESS", "FAILED"]
    result: InferenceTransferWorkflowReadResultV11 | None
    error_code: InferenceTransferWorkflowBindingError | None
    reply_sha256: Sha256

    @model_validator(mode="after")
    def exact_reply_presence(self) -> InferenceTransferWorkflowBindingReplyV11:
        if (self.status == "SUCCESS") != (self.result is not None) or (
            (self.status == "FAILED") != (self.error_code is not None)
        ):
            raise ValueError("comparison binding status/result/error presence differs")
        if (self.actor_id is None) != (self.request_binding_sha256 is None) or (
            self.status == "SUCCESS" and self.actor_id is None
        ):
            raise ValueError("comparison binding actor/hash context must be jointly present")
        if self.result is not None:
            parse_workflow_read_result_v11(self.result.model_dump(mode="json"))
        _canonical_binding_hash(self, "reply_sha256")
        return self


def parse_workflow_binding_request_v11(value: object) -> InferenceTransferWorkflowBindingRequestV11:
    if not isinstance(value, dict):
        raise ValueError("private comparison read request must be a JSON object")
    validate_contract("item-inference-transfer-workflow-binding-v1.1", value)
    return InferenceTransferWorkflowBindingRequestV11.model_validate(value)


def parse_workflow_binding_reply_v11(value: object) -> InferenceTransferWorkflowBindingReplyV11:
    if not isinstance(value, dict):
        raise ValueError("private comparison read reply must be a JSON object")
    validate_contract("item-inference-transfer-workflow-binding-v1.1", value)
    return InferenceTransferWorkflowBindingReplyV11.model_validate(value)


def validate_workflow_binding_reply_v11(
    request: InferenceTransferWorkflowBindingRequestV11,
    reply: InferenceTransferWorkflowBindingReplyV11,
) -> None:
    """Bind the exact actual principal/request; a SUCCESS string is not access proof."""
    request = parse_workflow_binding_request_v11(request.model_dump(mode="json"))
    reply = parse_workflow_binding_reply_v11(reply.model_dump(mode="json"))
    if reply.status == "FAILED" and reply.actor_id is None:
        # A malformed frame has no validated identity to echo. It carries no
        # source/result content and can only deny, never establish permission.
        return
    if reply.actor_id != request.actor_id or reply.request_binding_sha256 != request.binding_sha256:
        raise ValueError("private comparison reply actor or exact request binding differs")
    if reply.result is not None:
        validate_workflow_read_result_context_v11(request.request, reply.result)

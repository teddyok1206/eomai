"""Current authenticated purpose reads; generic WORKFLOW_READ never grants content access."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
    parse_workflow_read_request,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError


class InferenceTransferWorkflowReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InferenceTransferWorkflowReadPort(Protocol):
    def execute(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult: ...


_FAILURE_STATUS = {
    "INFERENCE_TRANSFER_FORBIDDEN": 403,
    "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND": 404,
    "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID": 422,
    "INFERENCE_TRANSFER_WORKFLOW_CHANGED": 409,
    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH": 409,
    "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE": 503,
    "INFERENCE_TRANSFER_RESULT_INVALID": 503,
    "INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED": 422,
}


class InferenceTransferWorkflowReadApplicationService:
    def __init__(self, reader: InferenceTransferWorkflowReadPort) -> None:
        self.reader = reader

    def execute(
        self, authentication: AccessAuthentication, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult:
        required = {
            PermissionKey.WORKFLOW_READ,
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        }
        if (
            authentication.operator.status != "ACTIVE"
            or authentication.operator.must_change_password
            or authentication.password_change_required
            or not required.issubset(authentication.permissions)
        ):
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Comparison read denied.")
        try:
            checked = parse_workflow_read_request(request.model_dump(mode="json"))
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
                "Invalid comparison read",
                "The exact comparison read does not satisfy its contract.",
            ) from exc
        try:
            raw = self.reader.execute(authentication.operator.operator_id, checked)
        except InferenceTransferWorkflowReadError as exc:
            code = (
                exc.code
                if exc.code in _FAILURE_STATUS
                else "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
            )
            raise ApiError(
                _FAILURE_STATUS[code],
                code,
                "Comparison read unavailable",
                "The authorized owner could not resolve this exact comparison.",
            ) from exc
        try:
            if not isinstance(raw, InferenceTransferWorkflowReadResult):
                raise ValueError("untyped owner reply")
            result = parse_workflow_read_result(raw.model_dump(mode="json"))
            validate_workflow_read_result_context(checked, result)
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                503,
                "INFERENCE_TRANSFER_RESULT_INVALID",
                "Invalid comparison result",
                "The owner result differs from the exact comparison request.",
            ) from exc
        return result

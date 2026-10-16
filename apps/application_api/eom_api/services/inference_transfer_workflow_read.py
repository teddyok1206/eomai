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
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
    validate_workflow_read_result_context_v11,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.operator_read_authorization import authorize_current_operator_read


class InferenceTransferWorkflowReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InferenceTransferWorkflowReadPort(Protocol):
    def execute(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult: ...


class InferenceTransferWorkflowReadPortV11(Protocol):
    def execute_v11(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11: ...


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
        authorize_inference_transfer_read(authentication)
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


def authorize_inference_transfer_read(authentication: AccessAuthentication) -> None:
    required = {
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
    }
    authorize_current_operator_read(authentication, required)


class InferenceTransferWorkflowReadApplicationServiceV11:
    """Explicit result successor; never promote a historical 1.0 reply."""

    def __init__(self, reader: InferenceTransferWorkflowReadPortV11) -> None:
        self.reader = reader

    def execute(
        self, authentication: AccessAuthentication, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11:
        authorize_inference_transfer_read(authentication)
        try:
            checked = parse_workflow_read_request_v11(request.model_dump(mode="json"))
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
                "Invalid comparison read",
                "The exact comparison read does not satisfy its contract.",
            ) from exc
        try:
            raw = self.reader.execute_v11(authentication.operator.operator_id, checked)
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
            if not isinstance(raw, InferenceTransferWorkflowReadResultV11):
                raise ValueError("untyped successor owner reply")
            result = parse_workflow_read_result_v11(raw.model_dump(mode="json"))
            validate_workflow_read_result_context_v11(checked, result)
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                503,
                "INFERENCE_TRANSFER_RESULT_INVALID",
                "Invalid comparison result",
                "The owner result differs from the exact comparison request.",
            ) from exc
        return result

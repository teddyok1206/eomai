"""Authenticated read-only snapshot use case; Catalog retains source authority."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    parse_snapshot_request,
    parse_snapshot_result,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result_context,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_snapshot_port import (
    InferenceTransferSnapshotReadError,
    InferenceTransferSnapshotReadPort,
)

_FAILURE_STATUS = {
    "INFERENCE_TRANSFER_FORBIDDEN": 403,
    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH": 409,
    "INFERENCE_TRANSFER_SNAPSHOT_CHANGED": 409,
    "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED": 409,
    "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID": 409,
    "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID": 422,
    "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED": 422,
    "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE": 503,
}


class InferenceTransferSnapshotApplicationService:
    def __init__(self, reader: InferenceTransferSnapshotReadPort) -> None:
        self.reader = reader

    def execute(
        self,
        authentication: AccessAuthentication,
        request: InferenceTransferSnapshotRequest,
    ) -> InferenceTransferSnapshotResult:
        """Revalidate closed input and bind only the server-authenticated principal."""
        try:
            request = parse_snapshot_request(request.model_dump(mode="json"))
        except (ValueError, JsonSchemaValidationError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
                "Invalid comparison snapshot request",
                "The snapshot request does not satisfy its pinned contract.",
            ) from exc
        prepare = (
            request
            if isinstance(request, InferenceTransferSnapshotPrepareRequest)
            else request.header.prepare
        )
        required = {
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        }
        if "PAST_EXAM" in prepare.source_classes:
            required.add(PermissionKey.CONTENT_INTAKE_READ)
        operator = authentication.operator
        if (
            operator.status != "ACTIVE"
            or operator.must_change_password
            or authentication.password_change_required
            or not required.issubset(authentication.permissions)
            or (
                not isinstance(request, InferenceTransferSnapshotPrepareRequest)
                and request.header.actor_id != operator.operator_id
            )
        ):
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "Permission denied",
                "This snapshot requires the current operator's source read permissions.",
            )
        try:
            raw = self.reader.execute(operator.operator_id, request)
        except InferenceTransferSnapshotReadError as exc:
            code = (
                exc.code
                if exc.code in _FAILURE_STATUS
                else ("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
            )
            raise ApiError(
                _FAILURE_STATUS[code],
                code,
                "Comparison snapshot unavailable",
                "The authorized Catalog snapshot could not be resolved. Its pins were not changed.",
            ) from exc
        try:
            if not isinstance(
                raw,
                (
                    InferenceTransferSnapshotPrepareResult,
                    InferenceTransferSnapshotReadResult,
                    InferenceTransferSnapshotAuthorizeResult,
                ),
            ):
                raise ValueError("Catalog reply is not a typed snapshot result")
            result = parse_snapshot_result(raw.model_dump(mode="json"))
            if isinstance(request, InferenceTransferSnapshotPrepareRequest) and isinstance(
                result, InferenceTransferSnapshotPrepareResult
            ):
                validate_snapshot_prepare_result(request, result)
                if result.header.actor_id != operator.operator_id:
                    raise ValueError("Catalog prepared a different operator's snapshot")
            elif isinstance(request, InferenceTransferSnapshotReadRequest) and isinstance(
                result, InferenceTransferSnapshotReadResult
            ):
                # Full-population membership is independently checked by the
                # Catalog owner; a chunk is not a substitute for its full index.
                validate_snapshot_read_result_context(request, result)
            elif isinstance(request, InferenceTransferSnapshotAuthorizeRequest) and isinstance(
                result, InferenceTransferSnapshotAuthorizeResult
            ):
                validate_snapshot_authorize_result(request, result)
            else:
                raise ValueError("Catalog returned a different snapshot phase")
        except (ValueError, JsonSchemaValidationError) as exc:
            raise ApiError(
                503,
                "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID",
                "Invalid Catalog snapshot reply",
                "The returned snapshot does not match the exact authenticated request.",
            ) from exc
        return result

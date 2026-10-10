"""Authenticated metadata use case and its small Catalog read port."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.inference_transfer_metadata import (
    METADATA_ERRORS,
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
    parse_metadata_request,
    parse_metadata_result,
    validate_metadata_result,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema import ValidationError as SchemaError

from eom_api.errors import ApiError

_FAILURE_STATUS = {
    "INFERENCE_TRANSFER_FORBIDDEN": 403,
    "INFERENCE_TRANSFER_METADATA_NOT_FOUND": 404,
    "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH": 409,
    "INFERENCE_TRANSFER_METADATA_POLICY_INVALID": 409,
    "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID": 422,
    "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED": 422,
    "INFERENCE_TRANSFER_METADATA_UNAVAILABLE": 503,
}


class InferenceTransferMetadataReadError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InferenceTransferMetadataReadPort(Protocol):
    def resolve(
        self, actor_id: str, request: InferenceTransferMetadataResolveRequest
    ) -> InferenceTransferMetadataResolveResult: ...


class InferenceTransferMetadataApplicationService:
    def __init__(self, reader: InferenceTransferMetadataReadPort) -> None:
        self.reader = reader

    def resolve(
        self, authentication: AccessAuthentication, request: InferenceTransferMetadataResolveRequest
    ) -> InferenceTransferMetadataResolveResult:
        try:
            request = parse_metadata_request(request.model_dump(mode="json"))
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID",
                "Invalid metadata request",
                "The exact metadata request contract is invalid.",
            ) from exc
        required = {
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        }
        if "PAST_EXAM" in request.source_classes:
            required.add(PermissionKey.CONTENT_INTAKE_READ)
        actor = authentication.operator
        if (
            actor.status != "ACTIVE"
            or actor.must_change_password
            or authentication.password_change_required
            or not required.issubset(authentication.permissions)
        ):
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "Permission denied",
                "Current source read permissions are required for this metadata.",
            )
        try:
            raw = self.reader.resolve(actor.operator_id, request)
        except InferenceTransferMetadataReadError as exc:
            code = (
                exc.code
                if exc.code in METADATA_ERRORS
                else "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
            )
            raise ApiError(
                _FAILURE_STATUS[code],
                code,
                "Graph metadata unavailable",
                "The exact Graph metadata could not be resolved; its pins were not changed.",
            ) from exc
        try:
            if not isinstance(raw, InferenceTransferMetadataResolveResult):
                raise ValueError("metadata result must be typed")
            result = parse_metadata_result(raw.model_dump(mode="json"))
            validate_metadata_result(request, result)
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                503,
                "INFERENCE_TRANSFER_METADATA_REPLY_INVALID",
                "Invalid metadata reply",
                "The Catalog response differs from the exact authenticated metadata request.",
            ) from exc
        return result

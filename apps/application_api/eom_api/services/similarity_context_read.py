"""Authenticated common reference reads; no model, queue or direct Catalog storage access."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.similarity_context import SimilarityContext, parse_similarity_context
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_workflow_read import authorize_inference_transfer_read
from eom_api.services.similarity_context_client import SimilarityContextClientError

MAX_PUBLIC_SIMILARITY_SELECTOR_BYTES = 4096


class SimilarityContextReadPort(Protocol):
    def read(
        self, actor_id: str, selection: CompletedSimilarityQuerySelection
    ) -> SimilarityContext: ...


_FAILURE_STATUS = {
    "SOURCE_ACCESS_DENIED": 403,
    "SOURCE_REVOKED": 409,
    "SOURCE_POINTER_INVALID": 409,
    "SOURCE_HASH_MISMATCH": 409,
    "INDEX_POINTER_INVALID": 409,
    "INDEX_HASH_MISMATCH": 409,
    "QUERY_RESULT_INVALID": 409,
    "AUTHORITY_UNAVAILABLE": 503,
    "SIMILARITY_CONTEXT_REQUEST_INVALID": 422,
    "SIMILARITY_CONTEXT_BUDGET_EXCEEDED": 422,
    "SIMILARITY_CONTEXT_UNAVAILABLE": 503,
}


def _unavailable(code: str) -> ApiError:
    safe = code if code in _FAILURE_STATUS else "SIMILARITY_CONTEXT_UNAVAILABLE"
    return ApiError(
        _FAILURE_STATUS[safe],
        safe,
        "Similarity context unavailable",
        "The authorized owner could not resolve this exact context; its pins were not changed.",
    )


class SimilarityContextReadApplicationService:
    def __init__(self, reader: SimilarityContextReadPort) -> None:
        self.reader = reader

    def read(
        self, authentication: AccessAuthentication, selection: CompletedSimilarityQuerySelection
    ) -> SimilarityContext:
        authorize_inference_transfer_read(authentication)
        # The currently admitted adapter is approved past-exam variation. This
        # additional source permission is not inferred from a model-supplied role.
        if PermissionKey.CONTENT_INTAKE_READ not in authentication.permissions:
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Source read denied.")
        try:
            selection = CompletedSimilarityQuerySelection.model_validate(selection)
        except (ValueError, SchemaError):
            raise _unavailable("SIMILARITY_CONTEXT_REQUEST_INVALID") from None
        try:
            raw = self.reader.read(authentication.operator.operator_id, selection)
        except SimilarityContextClientError as error:
            raise _unavailable(error.code) from None
        try:
            result = parse_similarity_context(raw)
            if result.request.request_sha256 != selection.context_request_sha256:
                raise ValueError("context request differs from exact selection")
        except (ValueError, SchemaError):
            raise _unavailable("SIMILARITY_CONTEXT_UNAVAILABLE") from None
        if result.status == "FAILED":
            assert result.error_code is not None
            raise _unavailable(result.error_code)
        return result

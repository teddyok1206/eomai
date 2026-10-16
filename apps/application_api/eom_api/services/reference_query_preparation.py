"""HTTP use case for exact native preparation; no response cache or implicit retry."""

from __future__ import annotations

from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
)

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.reference_query_prepare_client import (
    NativeReferenceQueryPrepareClient,
    ReferenceQueryPrepareClientError,
)


class ReferenceQueryPreparationApplicationService:
    def __init__(self, client: NativeReferenceQueryPrepareClient | None) -> None:
        self.client = client

    def prepare(
        self,
        context: RequestContext,
        request: SupportedReferenceQueryPrepareRequest,
        *,
        idempotency_key: str,
    ) -> ReferenceQueryPrepareReply:
        if request.idempotency_key != idempotency_key:
            raise ApiError(
                409,
                "REFERENCE_QUERY_PREPARE_CONFLICT",
                "Preparation key differs",
                "The header must retain the exact original preparation key.",
            )
        if self.client is None:
            raise ApiError(
                503,
                "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
                "Preparation unavailable",
                "The compatible native preparation owner is not activated.",
            )
        try:
            return self.client.prepare(context, request)
        except ReferenceQueryPrepareClientError:
            # A timed-out exchange may already have admitted the original Job.
            # Only explicit same-key re-observation can establish its outcome.
            raise ApiError(
                503,
                "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
                "Preparation unavailable",
                "Retain the original key and pins when checking this request again.",
            ) from None

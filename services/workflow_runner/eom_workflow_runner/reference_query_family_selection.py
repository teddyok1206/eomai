"""Exact request-family routing among explicitly admitted owner compositions."""

from __future__ import annotations

from collections.abc import Callable

from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareRequestV2,
    ReferenceQueryPrepareRequestV3,
    ReferenceQueryPrepareRequestV4,
    SupportedReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
    parse_supported_reference_query_prepare_request,
    validate_supported_reference_query_prepare_reply,
)
from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort


class ReferenceQueryFamilyPreparation:
    """Operation-local factories already bind one genuine transport capture.

    No session cache or authentication is created here. Each selected application
    remains responsible for current source, policy, session and command authority.
    """

    def __init__(
        self,
        primary: Callable[[], ReferenceQueryPreparationPort],
        mixed: Callable[[], ReferenceQueryPreparationPort] | None,
        public: Callable[[], ReferenceQueryPreparationPort] | None = None,
    ) -> None:
        self.primary, self.mixed, self.public = primary, mixed, public

    def prepare(
        self, request: SupportedReferenceQueryPrepareRequest
    ) -> SupportedReferenceQueryPrepareReply:
        request = parse_supported_reference_query_prepare_request(request)
        single = (
            request.requests[0] if isinstance(request, ReferenceQueryPrepareRequestV3) else request
        )
        factory = (
            self.public
            if isinstance(request, ReferenceQueryPrepareRequestV4)
            else (
                self.mixed if isinstance(single, ReferenceQueryPrepareRequestV2) else self.primary
            )
        )
        if factory is None:
            raise ValueError("REFERENCE_QUERY_PREPARE_UNAVAILABLE")
        reply = factory().prepare(request)
        validate_supported_reference_query_prepare_reply(request, reply)
        return reply

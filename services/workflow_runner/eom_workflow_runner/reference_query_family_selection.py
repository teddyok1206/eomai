"""Exact request-family routing between two explicitly admitted owner compositions."""

from __future__ import annotations

from collections.abc import Callable

from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareRequestV2,
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
    ) -> None:
        self.primary, self.mixed = primary, mixed

    def prepare(
        self, request: SupportedReferenceQueryPrepareRequest
    ) -> SupportedReferenceQueryPrepareReply:
        request = parse_supported_reference_query_prepare_request(request)
        factory = (
            self.mixed if isinstance(request, ReferenceQueryPrepareRequestV2) else self.primary
        )
        if factory is None:
            raise ValueError("REFERENCE_QUERY_PREPARE_UNAVAILABLE")
        reply = factory().prepare(request)
        validate_supported_reference_query_prepare_reply(request, reply)
        return reply

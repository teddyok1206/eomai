"""Native application boundary, not an authenticated DTO or a runtime default."""

from typing import Protocol

from eom_catalog_contracts.reference_query_prepare import (
    SupportedReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
)


class ReferenceQueryPreparationPort(Protocol):
    """Trusted composition binds a genuine capture before exposing this operation."""

    def prepare(
        self, request: SupportedReferenceQueryPrepareRequest
    ) -> SupportedReferenceQueryPrepareReply: ...

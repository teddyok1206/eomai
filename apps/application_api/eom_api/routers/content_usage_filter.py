"""Optional public query parameters; Catalog owns membership semantics."""

from typing import Annotated, Literal

from eom_catalog_contracts.content_usage_filter import ContentUsageFilter
from eom_operator_identity import PermissionKey
from fastapi import Depends, Query

from eom_api.dependencies import Auth
from eom_api.errors import ApiError


def content_usage_filter(
    authentication: Auth,
    usage_state: Literal["USED", "UNUSED"] | None = Query(default=None),
    usage_year: int | None = Query(default=None, ge=1900, le=3000),
) -> ContentUsageFilter | None:
    if usage_state is None:
        if usage_year is not None:
            raise ApiError(
                422, "CONTENT_USAGE_FILTER_INVALID", "Invalid year", "Select usage state"
            )
        return None
    if PermissionKey.DELIVERABLE_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Content usage read denied")
    return ContentUsageFilter(state=usage_state, academic_year=usage_year)


UsageFilter = Annotated[ContentUsageFilter | None, Depends(content_usage_filter)]

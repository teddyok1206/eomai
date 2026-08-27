"""Read-only, pinned curriculum selection catalogs for item authoring."""

from __future__ import annotations

from eom_api_contracts import SingleResponse
from eom_catalog_contracts import (
    IntegratedScienceEditorialOutline,
    load_integrated_science_editorial_outline,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import require_permission
from eom_api.routers.common import one

router = APIRouter(tags=["curriculum"])


@router.get(
    "/curriculum/integrated-science-editorial-outline",
    operation_id="integrated_science_editorial_outline_get",
    response_model=SingleResponse[IntegratedScienceEditorialOutline],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def integrated_science_editorial_outline(
    request: Request,
) -> SingleResponse[IntegratedScienceEditorialOutline]:
    return one(request, load_integrated_science_editorial_outline())

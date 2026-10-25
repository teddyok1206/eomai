"""Actual-current-user preparation and exact-key re-observation, never direct execution."""

from __future__ import annotations

from eom_api_contracts import SingleResponse
from eom_api_contracts.reference_queries import SupportedReferenceQueryPrepareInput
from eom_catalog_contracts.reference_query_prepare import (
    MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES,
    SupportedReferenceQueryPrepareReply,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import (
    Auth,
    IdempotencyKey,
    get_request_context,
    get_services,
    require_permission,
)
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/knowledge/reference-queries", tags=["reference-queries"])


@router.post(
    "/preparation",
    operation_id="reference_query_prepare",
    response_model=SingleResponse[SupportedReferenceQueryPrepareReply],
    responses={
        202: {
            "model": SingleResponse[SupportedReferenceQueryPrepareReply],
            "description": "Original preparation admitted or still pending",
        }
    },
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START, fresh=True))],
)
async def prepare(
    request: Request,
    body: SupportedReferenceQueryPrepareInput,
    response: Response,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[SupportedReferenceQueryPrepareReply]:
    del authentication
    if len(await request.body()) > MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES:
        raise ApiError(
            422,
            "REFERENCE_QUERY_PREPARE_REQUEST_INVALID",
            "Preparation request too large",
            "The exact preparation request exceeds its fixed byte budget.",
        )
    result = await run_in_threadpool(
        get_services(request).reference_query_preparation.prepare,
        get_request_context(request),
        body,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 202 if result.status == "PENDING" else 200
    return one(request, result)

"""One existing QUERY-backed DB search; same-key observation never caches a PENDING reply."""

from eom_api_contracts import SingleResponse
from eom_api_contracts.item_db_similarity import ItemDbSimilarityInput, ItemDbSimilarityView
from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, get_request_context, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/item-db/similarity", tags=["item-db"])


@router.post(
    "",
    operation_id="item_db_similarity_search",
    response_model=SingleResponse[ItemDbSimilarityView],
    responses={202: {"model": SingleResponse[ItemDbSimilarityView]}},
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START, fresh=True))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.WORKFLOW_READ.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
            PermissionKey.CONTENT_INTAKE_READ.value,
        ]
    },
)
async def search(
    request: Request,
    body: ItemDbSimilarityInput,
    response: Response,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ItemDbSimilarityView]:
    del authentication
    if len(await request.body()) > MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES:
        raise ApiError(
            422,
            "ITEM_DB_SIMILARITY_REQUEST_INVALID",
            "Search input too large",
            "The exact selected source exceeds its fixed byte bound.",
        )
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity.search,
        get_request_context(request),
        body,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 202 if result.status == "PENDING" else 200
    return one(request, result)

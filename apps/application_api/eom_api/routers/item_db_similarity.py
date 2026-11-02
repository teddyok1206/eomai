"""One existing QUERY-backed DB search; same-key observation never caches a PENDING reply."""

from typing import Annotated

from eom_api_contracts import ListResponse, SingleResponse
from eom_api_contracts.item_db_similarity import (
    ItemDbSimilarityAnchorResult,
    ItemDbSimilarityInput,
    ItemDbSimilarityListInput,
    ItemDbSimilaritySearchView,
    ItemDbSimilarityView,
)
from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, get_request_context, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one

router = APIRouter(prefix="/item-db/similarity", tags=["item-db"])

SearchId = Annotated[str, Path(pattern=r"^dbsearch_[0-9a-f]{32}$")]


@router.post(
    "/searches",
    operation_id="item_db_similarity_list_submit",
    response_model=SingleResponse[ItemDbSimilaritySearchView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START, fresh=True))],
)
async def submit_list(
    request: Request,
    response: Response,
    body: ItemDbSimilarityListInput,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ItemDbSimilaritySearchView]:
    del authentication
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity_searches.submit,
        get_request_context(request),
        body,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "/searches",
    operation_id="item_db_similarity_list_recent",
    response_model=ListResponse[ItemDbSimilaritySearchView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
async def recent_list(
    request: Request,
    response: Response,
    authentication: Auth,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=2048),
) -> ListResponse[ItemDbSimilaritySearchView]:
    del authentication
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity_searches.recent,
        get_request_context(request),
        limit=limit,
        cursor=cursor,
    )
    response.headers["Cache-Control"] = "no-store"
    return many(
        request, result.data, limit=limit, next_cursor=result.next_cursor, has_more=result.has_more
    )


@router.get(
    "/searches/{search_id}",
    operation_id="item_db_similarity_list_read",
    response_model=SingleResponse[ItemDbSimilaritySearchView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
async def read_search(
    request: Request, response: Response, search_id: SearchId, authentication: Auth
) -> SingleResponse[ItemDbSimilaritySearchView]:
    del authentication
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity_searches.get,
        get_request_context(request),
        search_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.post(
    "/searches/{search_id}/check",
    operation_id="item_db_similarity_list_check",
    response_model=SingleResponse[ItemDbSimilaritySearchView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START, fresh=True))],
)
async def check_search(
    request: Request,
    response: Response,
    search_id: SearchId,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ItemDbSimilaritySearchView]:
    del authentication
    if idempotency_key != search_id:
        raise ApiError(
            409,
            "ITEM_DB_SIMILARITY_REQUEST_CONFLICT",
            "Search check differs",
            "The check key must identify the existing owned search.",
        )
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity_searches.check,
        get_request_context(request),
        search_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "/searches/{search_id}/results/{ordinal}",
    operation_id="item_db_similarity_list_result_read",
    response_model=SingleResponse[ItemDbSimilarityAnchorResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
async def read_search_result(
    request: Request,
    response: Response,
    search_id: SearchId,
    ordinal: Annotated[int, Path(ge=0, le=31)],
    authentication: Auth,
) -> SingleResponse[ItemDbSimilarityAnchorResult]:
    del authentication
    result = await run_in_threadpool(
        request.app.state.services.item_db_similarity_searches.read_result,
        get_request_context(request),
        search_id,
        ordinal,
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


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

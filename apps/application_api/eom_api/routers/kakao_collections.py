"""Accept or read a registered-room collection. HTTP never runs a browser."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_collection import KakaoCollectionStatus, KakaoRoomCollectionSelection
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/collections", tags=["kakao-archive"])
COLLECT = require_permission(PermissionKey.KAKAO_ARCHIVE_COLLECT, admin_only=True)
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
ERROR_STATUS = {
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_ROOM_RETIRED": 409,
    "KAKAO_ARCHIVE_COLLECTION_ALREADY_PENDING": 409,
    "KAKAO_ARCHIVE_COLLECTION_CAPABILITY_MISMATCH": 409,
    "KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID": 409,
}


@contextmanager
def _boundary() -> Iterator[None]:
    try:
        yield
    except CatalogApplicationClientError as error:
        code = error.code if error.code in ERROR_STATUS else "KAKAO_ARCHIVE_UNAVAILABLE"
        raise ApiError(
            ERROR_STATUS.get(code, 503),
            code,
            "KakaoTalk collection request failed",
            "The collection request could not be handled.",
        ) from error


@router.post(
    "",
    status_code=202,
    operation_id="kakao_collection_start",
    response_model=SingleResponse[KakaoCollectionStatus],
    dependencies=[Depends(COLLECT)],
)
def start_collection(
    request: Request,
    response: Response,
    body: KakaoRoomCollectionSelection,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SingleResponse[KakaoCollectionStatus]:
    if if_match != etag(body.selection.expected_binding_version):
        raise ApiError(
            412, "API_PRECONDITION_FAILED", "Precondition failed", "The binding ETag must match."
        )
    with _boundary():
        result = request.app.state.services.catalog_application.start_kakao_room_collection(
            body.selection,
            expected_policy_revision_id=body.expected_policy_revision_id,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "/{run_id}",
    operation_id="kakao_collection_status",
    response_model=SingleResponse[KakaoCollectionStatus],
    dependencies=[Depends(READ)],
)
def read_collection(
    request: Request,
    response: Response,
    authentication: Auth,
    run_id: Annotated[str, Path(pattern=r"^kakaorun_[0-9a-f]{32}$")],
    source_binding_id: Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")],
) -> SingleResponse[KakaoCollectionStatus]:
    with _boundary():
        result = request.app.state.services.catalog_application.get_kakao_room_collection(
            source_binding_id,
            run_id,
            actor=request.state.request_context.actor(),
        )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)

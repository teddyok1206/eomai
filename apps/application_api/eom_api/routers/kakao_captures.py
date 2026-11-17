"""Manual received-input metadata/room confirmation; never launches collection."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_capture_intake import ConfirmKakaoManualCapture, KakaoManualCapturePage
from eom_api_contracts.kakao_rooms import KakaoRoomMutation
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Query, Request, Response

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/manual-captures", tags=["kakao-archive"])
COLLECT = require_permission(PermissionKey.KAKAO_ARCHIVE_COLLECT, admin_only=True)
ERROR_STATUS = {
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE": 409,
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE": 409,
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_UNCONFIRMED": 409,
    "KAKAO_ARCHIVE_ROOM_IDENTITY_UNAVAILABLE": 409,
    "KAKAO_ARCHIVE_ROOM_IDENTITY_MISMATCH": 409,
    "KAKAO_ARCHIVE_CHANNEL_IDENTITY_MISMATCH": 409,
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
            "KakaoTalk input request failed",
            "The received input could not be verified.",
        ) from error


@router.get(
    "",
    operation_id="kakao_capture_list",
    response_model=SingleResponse[KakaoManualCapturePage],
    dependencies=[Depends(COLLECT)],
)
def list_captures(
    request: Request,
    response: Response,
    authentication: Auth,
    source_binding_id: Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")],
) -> SingleResponse[KakaoManualCapturePage]:
    with _boundary():
        result = request.app.state.services.catalog_application.list_kakao_manual_captures(
            source_binding_id, actor=request.state.request_context.actor()
        )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.post(
    "/confirm-room",
    operation_id="kakao_capture_confirm_room",
    response_model=SingleResponse[KakaoRoomMutation],
    dependencies=[Depends(COLLECT)],
)
def confirm_capture(
    request: Request,
    response: Response,
    body: ConfirmKakaoManualCapture,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SingleResponse[KakaoRoomMutation]:
    if if_match != etag(body.expected_binding_version):
        raise ApiError(
            412, "API_PRECONDITION_FAILED", "Precondition failed", "The binding ETag must match."
        )
    with _boundary():
        result = request.app.state.services.catalog_application.confirm_kakao_manual_capture(
            body, actor=request.state.request_context.actor(), idempotency_key=idempotency_key
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(result.room.resource_version)
    return one(request, result)

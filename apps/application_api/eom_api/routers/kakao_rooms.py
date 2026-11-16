"""Admitted-room reads and explicit mapping; no public room admission or activation."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_rooms import (
    KakaoRoom,
    KakaoRoomCommand,
    KakaoRoomMutation,
    KakaoRoomPage,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/rooms", tags=["kakao-archive"])
RoomId = Annotated[str, Path(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
CHANGE = require_permission(PermissionKey.KAKAO_ARCHIVE_EDIT)
_ERROR_STATUS = {
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_STUDENT_RETIRED": 409,
    "KAKAO_ARCHIVE_STUDENT_STALE": 409,
    "KAKAO_ARCHIVE_ROOM_RETIRED": 409,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_STORED_ROOM_INVALID": 503,
    "KAKAO_ARCHIVE_STORED_STUDENT_INVALID": 503,
}


@contextmanager
def _boundary() -> Iterator[None]:
    try:
        yield
    except CatalogApplicationClientError as error:
        code = error.code if error.code in _ERROR_STATUS else "KAKAO_ARCHIVE_UNAVAILABLE"
        raise ApiError(
            _ERROR_STATUS.get(code, 503),
            code,
            "KakaoTalk request failed",
            "The private room operation could not be completed.",
        ) from error


def _headers(response: Response, room: KakaoRoom | None = None) -> None:
    response.headers["Cache-Control"] = "no-store"
    if room is not None:
        response.headers["ETag"] = etag(room.resource_version)


@router.get(
    "",
    operation_id="kakao_room_list",
    response_model=SingleResponse[KakaoRoomPage],
    dependencies=[Depends(READ)],
)
def list_rooms(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoRoomPage]:
    with _boundary():
        result = request.app.state.services.catalog_application.list_kakao_rooms(
            source_binding_id,
            actor=request.state.request_context.actor(),
            limit=limit,
            cursor=cursor,
        )
    _headers(response)
    return one(request, result)


@router.get(
    "/{room_id}",
    operation_id="kakao_room_read",
    response_model=SingleResponse[KakaoRoom],
    dependencies=[Depends(READ)],
)
def read_room(
    request: Request,
    response: Response,
    room_id: RoomId,
    source_binding_id: BindingId,
    authentication: Auth,
    mapping_revision_id: str | None = Query(
        default=None, pattern=r"^kakaomappingrev_[0-9a-f]{32}$"
    ),
) -> SingleResponse[KakaoRoom]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_room(
            source_binding_id,
            room_id,
            actor=request.state.request_context.actor(),
            mapping_revision_id=mapping_revision_id,
        )
    _headers(response, result)
    return one(request, result)


@router.post(
    "/{room_id}/mapping",
    operation_id="kakao_room_mapping",
    response_model=SingleResponse[KakaoRoomMutation],
    dependencies=[Depends(CHANGE)],
)
def map_room(
    request: Request,
    response: Response,
    room_id: RoomId,
    source_binding_id: BindingId,
    body: KakaoRoomCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected: ExpectedVersion,
) -> SingleResponse[KakaoRoomMutation]:
    if expected != body.expected_resource_version:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The command version must match its resource ETag.",
        )
    with _boundary():
        result = request.app.state.services.catalog_application.command_kakao_room(
            source_binding_id,
            room_id,
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.room)
    return one(request, result)

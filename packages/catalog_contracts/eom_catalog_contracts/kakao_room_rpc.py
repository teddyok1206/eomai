"""Owner-private room mappings on the existing API-only Catalog transport."""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive import KakaoRoomId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_rooms import (
    KakaoMappingRevisionId,
    KakaoRoom,
    KakaoRoomCommand,
    KakaoRoomMap,
    KakaoRoomMutation,
    KakaoRoomPage,
)
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type KakaoRoomOperation = Literal["COMMAND_KAKAO_ROOM", "READ_KAKAO_ROOM", "LIST_KAKAO_ROOMS"]
type KakaoRoomErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_STORED_STUDENT_INVALID",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_STALE",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_STORED_ROOM_INVALID",
]
KAKAO_ROOM_OPERATIONS = frozenset(get_args(KakaoRoomOperation.__value__))
KAKAO_ROOM_ERROR_CODES = frozenset(get_args(KakaoRoomErrorCode.__value__))


class _ApiScope(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")


class CommandKakaoRoomRequest(_ApiScope):
    operation: Literal["COMMAND_KAKAO_ROOM"] = "COMMAND_KAKAO_ROOM"
    room_id: KakaoRoomId
    idempotency_key: IdempotencyKey
    command: KakaoRoomCommand


class ReadKakaoRoomRequest(_ApiScope):
    operation: Literal["READ_KAKAO_ROOM"] = "READ_KAKAO_ROOM"
    room_id: KakaoRoomId
    mapping_revision_id: KakaoMappingRevisionId | None = None


class ListKakaoRoomsRequest(_ApiScope):
    operation: Literal["LIST_KAKAO_ROOMS"] = "LIST_KAKAO_ROOMS"
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: KakaoRoomId | None = None


type KakaoRoomRequest = Annotated[
    CommandKakaoRoomRequest | ReadKakaoRoomRequest | ListKakaoRoomsRequest,
    Field(discriminator="operation"),
]


class _OkReply(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class CommandKakaoRoomReply(_OkReply):
    operation: Literal["COMMAND_KAKAO_ROOM"] = "COMMAND_KAKAO_ROOM"
    result: KakaoRoomMutation


class ReadKakaoRoomReply(_OkReply):
    operation: Literal["READ_KAKAO_ROOM"] = "READ_KAKAO_ROOM"
    result: KakaoRoom


class ListKakaoRoomsReply(_OkReply):
    operation: Literal["LIST_KAKAO_ROOMS"] = "LIST_KAKAO_ROOMS"
    result: KakaoRoomPage


class KakaoRoomFailure(FrozenModel):
    operation: KakaoRoomOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoRoomErrorCode


type _SuccessReply = Annotated[
    CommandKakaoRoomReply | ReadKakaoRoomReply | ListKakaoRoomsReply,
    Field(discriminator="operation"),
]
type KakaoRoomReply = Annotated[_SuccessReply | KakaoRoomFailure, Field(discriminator="status")]
_REQUEST: TypeAdapter[KakaoRoomRequest] = TypeAdapter(KakaoRoomRequest)
_REPLY: TypeAdapter[KakaoRoomReply] = TypeAdapter(KakaoRoomReply)


def parse_kakao_room_request(value: dict[str, object]) -> KakaoRoomRequest:
    validate_contract("catalog-kakao-room-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_room_reply(value: dict[str, object]) -> KakaoRoomReply:
    validate_contract("catalog-kakao-room-response-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_room_reply(request: KakaoRoomRequest, reply: KakaoRoomReply) -> None:
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if reply.operation != request.operation or reply.request_id != request.request_id:
        raise ValueError(invalid)
    if isinstance(reply, KakaoRoomFailure):
        return
    if isinstance(request, ListKakaoRoomsRequest):
        if not isinstance(reply, ListKakaoRoomsReply):
            raise ValueError(invalid)
        ids = tuple(item.room_id for item in reply.result.items)
        if (
            len(ids) > request.limit
            or any(
                item.source_binding_id != request.source_binding_id for item in reply.result.items
            )
            or any(request.cursor is not None and identity <= request.cursor for identity in ids)
            or (reply.result.next_cursor is not None and len(ids) != request.limit)
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoRoomRequest):
        if (
            not isinstance(reply, ReadKakaoRoomReply)
            or reply.result.room_id != request.room_id
            or reply.result.source_binding_id != request.source_binding_id
            or (
                request.mapping_revision_id is not None
                and reply.result.mapping.mapping_revision_id != request.mapping_revision_id
            )
        ):
            raise ValueError(invalid)
    else:
        if not isinstance(reply, CommandKakaoRoomReply):
            raise ValueError(invalid)
        room, command = reply.result.room, request.command
        mapping = room.mapping
        if (
            room.room_id != request.room_id
            or room.source_binding_id != request.source_binding_id
            or room.resource_version != command.expected_resource_version + 1
            or mapping.previous_revision_id != command.parent_revision_id
            or mapping.reason != command.reason
            or room.state != "ACTIVE"
        ):
            raise ValueError(invalid)
        if isinstance(command, KakaoRoomMap):
            if (
                mapping.state != "MAPPED"
                or mapping.student_id != command.student_id
                or mapping.student_display_revision_id != command.student_display_revision_id
            ):
                raise ValueError(invalid)
        elif mapping.state != "UNMAPPED":
            raise ValueError(invalid)

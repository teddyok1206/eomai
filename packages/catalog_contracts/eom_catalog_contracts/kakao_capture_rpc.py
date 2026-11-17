"""Closed API-peer messages; no local paths, provider keys or model authority."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive import KakaoBindingId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_capture_intake import ConfirmKakaoManualCapture, KakaoManualCapturePage
from .kakao_rooms import KakaoRoomMutation
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type KakaoCaptureOperation = Literal["LIST_KAKAO_MANUAL_CAPTURES", "CONFIRM_KAKAO_MANUAL_CAPTURE"]
type KakaoCaptureErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_UNAVAILABLE",
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE",
    "KAKAO_ARCHIVE_MANUAL_CAPTURE_UNCONFIRMED",
    "KAKAO_ARCHIVE_ROOM_IDENTITY_UNAVAILABLE",
    "KAKAO_ARCHIVE_ROOM_IDENTITY_MISMATCH",
    "KAKAO_ARCHIVE_CHANNEL_IDENTITY_MISMATCH",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_STORED_ROOM_INVALID",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_CAPTURE_OPERATIONS = frozenset(get_args(KakaoCaptureOperation.__value__))
KAKAO_CAPTURE_ERROR_CODES = frozenset(get_args(KakaoCaptureErrorCode.__value__))


class _Identity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class ListKakaoCapturesRequest(_Identity):
    operation: Literal["LIST_KAKAO_MANUAL_CAPTURES"] = "LIST_KAKAO_MANUAL_CAPTURES"
    source_binding_id: KakaoBindingId


class ConfirmKakaoCaptureRequest(_Identity):
    operation: Literal["CONFIRM_KAKAO_MANUAL_CAPTURE"] = "CONFIRM_KAKAO_MANUAL_CAPTURE"
    command: ConfirmKakaoManualCapture
    idempotency_key: IdempotencyKey


type KakaoCaptureRequest = Annotated[
    ListKakaoCapturesRequest | ConfirmKakaoCaptureRequest, Field(discriminator="operation")
]


class _Ok(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class ListKakaoCapturesReply(_Ok):
    operation: Literal["LIST_KAKAO_MANUAL_CAPTURES"] = "LIST_KAKAO_MANUAL_CAPTURES"
    result: KakaoManualCapturePage


class ConfirmKakaoCaptureReply(_Ok):
    operation: Literal["CONFIRM_KAKAO_MANUAL_CAPTURE"] = "CONFIRM_KAKAO_MANUAL_CAPTURE"
    result: KakaoRoomMutation


class KakaoCaptureFailure(FrozenModel):
    operation: KakaoCaptureOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoCaptureErrorCode


type _Success = Annotated[
    ListKakaoCapturesReply | ConfirmKakaoCaptureReply, Field(discriminator="operation")
]
type KakaoCaptureReply = Annotated[_Success | KakaoCaptureFailure, Field(discriminator="status")]
_REQUEST: TypeAdapter[KakaoCaptureRequest] = TypeAdapter(KakaoCaptureRequest)
_REPLY: TypeAdapter[KakaoCaptureReply] = TypeAdapter(KakaoCaptureReply)


def parse_kakao_capture_request(value: dict[str, object]) -> KakaoCaptureRequest:
    validate_contract("catalog-kakao-capture-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_capture_reply(value: dict[str, object]) -> KakaoCaptureReply:
    validate_contract("catalog-kakao-capture-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_capture_reply(request: KakaoCaptureRequest, reply: KakaoCaptureReply) -> None:
    if request.operation != reply.operation or request.request_id != reply.request_id:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, KakaoCaptureFailure):
        return
    expected = (
        request.source_binding_id
        if isinstance(request, ListKakaoCapturesRequest)
        else request.command.source_binding_id
    )
    if isinstance(reply, ListKakaoCapturesReply):
        actual = reply.result.source_binding_id
    else:
        actual = reply.result.room.source_binding_id
    if actual != expected:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")

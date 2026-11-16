"""Private manual-login transport; public callers cannot supply runtime authority."""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_manual import (
    KakaoManualEnd,
    KakaoManualLeaseId,
    KakaoManualMutation,
    KakaoManualRenew,
    KakaoManualSession,
    KakaoManualStart,
)
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type KakaoManualOperation = Literal[
    "START_KAKAO_MANUAL", "COMMAND_KAKAO_MANUAL", "READ_KAKAO_MANUAL"
]
type KakaoManualErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "KAKAO_ARCHIVE_STORED_MANUAL_SESSION_INVALID",
    "KAKAO_ARCHIVE_REMOTE_NOT_READY",
    "KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE",
    "KAKAO_ARCHIVE_REMOTE_PROFILE_UNASSIGNED",
    "KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY",
    "KAKAO_ARCHIVE_REMOTE_OBSERVATION_STALE",
    "KAKAO_ARCHIVE_REMOTE_OBSERVATION_MISMATCH",
    "KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE",
    "KAKAO_ARCHIVE_REMOTE_FENCE_STALE",
    "KAKAO_ARCHIVE_REMOTE_LEASE_EXPIRED",
    "KAKAO_ARCHIVE_REMOTE_STOP_UNCONFIRMED",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_MANUAL_OPERATIONS = frozenset(get_args(KakaoManualOperation.__value__))
KAKAO_MANUAL_ERROR_CODES = frozenset(get_args(KakaoManualErrorCode.__value__))


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class StartKakaoManualRequest(_ApiIdentity):
    operation: Literal["START_KAKAO_MANUAL"] = "START_KAKAO_MANUAL"
    idempotency_key: IdempotencyKey
    command: KakaoManualStart


class CommandKakaoManualRequest(_ApiIdentity):
    operation: Literal["COMMAND_KAKAO_MANUAL"] = "COMMAND_KAKAO_MANUAL"
    lease_id: KakaoManualLeaseId
    idempotency_key: IdempotencyKey
    command: Annotated[KakaoManualRenew | KakaoManualEnd, Field(discriminator="action")]


class ReadKakaoManualRequest(_ApiIdentity):
    operation: Literal["READ_KAKAO_MANUAL"] = "READ_KAKAO_MANUAL"
    lease_id: KakaoManualLeaseId


type KakaoManualRequest = Annotated[
    StartKakaoManualRequest | CommandKakaoManualRequest | ReadKakaoManualRequest,
    Field(discriminator="operation"),
]


class _OkReply(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class StartKakaoManualReply(_OkReply):
    operation: Literal["START_KAKAO_MANUAL"] = "START_KAKAO_MANUAL"
    result: KakaoManualMutation


class CommandKakaoManualReply(_OkReply):
    operation: Literal["COMMAND_KAKAO_MANUAL"] = "COMMAND_KAKAO_MANUAL"
    result: KakaoManualMutation


class ReadKakaoManualReply(_OkReply):
    operation: Literal["READ_KAKAO_MANUAL"] = "READ_KAKAO_MANUAL"
    result: KakaoManualSession


class KakaoManualFailure(FrozenModel):
    operation: KakaoManualOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoManualErrorCode


type _SuccessReply = Annotated[
    StartKakaoManualReply | CommandKakaoManualReply | ReadKakaoManualReply,
    Field(discriminator="operation"),
]
type KakaoManualReply = Annotated[_SuccessReply | KakaoManualFailure, Field(discriminator="status")]
_REQUEST: TypeAdapter[KakaoManualRequest] = TypeAdapter(KakaoManualRequest)
_REPLY: TypeAdapter[KakaoManualReply] = TypeAdapter(KakaoManualReply)


def parse_kakao_manual_request(value: dict[str, object]) -> KakaoManualRequest:
    validate_contract("catalog-kakao-manual-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_manual_reply(value: dict[str, object]) -> KakaoManualReply:
    validate_contract("catalog-kakao-manual-response-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_manual_reply(request: KakaoManualRequest, reply: KakaoManualReply) -> None:
    """A same-key START receipt is PREPARING even if the runtime later becomes ready."""
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if reply.operation != request.operation or reply.request_id != request.request_id:
        raise ValueError(invalid)
    if isinstance(reply, KakaoManualFailure):
        return
    if isinstance(request, StartKakaoManualRequest):
        if not isinstance(reply, StartKakaoManualReply):
            raise ValueError(invalid)
        session = reply.result.session
        if (
            session.source_binding_id != request.command.source_binding_id
            or session.phase != "PREPARING"
            or session.resource_version != 1
            or session.grant_revision != 0
            or session.ready
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoManualRequest):
        if not isinstance(reply, ReadKakaoManualReply) or reply.result.lease_id != request.lease_id:
            raise ValueError(invalid)
    else:
        if not isinstance(reply, CommandKakaoManualReply):
            raise ValueError(invalid)
        session = reply.result.session
        if session.lease_id != request.lease_id:
            raise ValueError(invalid)
        if isinstance(request.command, KakaoManualRenew):
            if (
                session.grant_revision != request.command.expected_grant_revision + 1
                or session.phase != "ACTIVE"
            ):
                raise ValueError(invalid)
        elif (
            session.resource_version != request.command.expected_resource_version + 1
            or session.phase != "STOPPING"
            or session.ready
        ):
            raise ValueError(invalid)

"""Closed API-to-Catalog binding messages; callers never supply roles or permissions."""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive import KakaoBindingId
from .kakao_archive_binding import (
    KakaoBindingCommand,
    KakaoBindingCreate,
    KakaoBindingMutation,
    KakaoBindingPage,
    KakaoBindingRetire,
    KakaoBindingUpdatePolicy,
    KakaoSourceBinding,
)
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type KakaoBindingOperation = Literal[
    "CREATE_KAKAO_BINDING",
    "COMMAND_KAKAO_BINDING",
    "READ_KAKAO_BINDING",
    "LIST_KAKAO_BINDINGS",
]
type KakaoBindingErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_POLICY_REFERENCE_INVALID",
    "KAKAO_ARCHIVE_STORED_POLICY_INVALID",
    "KAKAO_ARCHIVE_STORED_BINDING_INVALID",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_BINDING_OPERATIONS = frozenset(get_args(KakaoBindingOperation.__value__))
KAKAO_BINDING_ERROR_CODES = frozenset(get_args(KakaoBindingErrorCode.__value__))
RequestId = Annotated[
    str, Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
]
IdempotencyKey = Annotated[str, Field(pattern=r"^[!-~]{16,128}$")]


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class CreateKakaoBindingRequest(_ApiIdentity):
    operation: Literal["CREATE_KAKAO_BINDING"] = "CREATE_KAKAO_BINDING"
    idempotency_key: IdempotencyKey
    command: KakaoBindingCreate


class CommandKakaoBindingRequest(_ApiIdentity):
    operation: Literal["COMMAND_KAKAO_BINDING"] = "COMMAND_KAKAO_BINDING"
    source_binding_id: KakaoBindingId
    idempotency_key: IdempotencyKey
    command: KakaoBindingCommand


class ReadKakaoBindingRequest(_ApiIdentity):
    operation: Literal["READ_KAKAO_BINDING"] = "READ_KAKAO_BINDING"
    source_binding_id: KakaoBindingId


class ListKakaoBindingsRequest(_ApiIdentity):
    operation: Literal["LIST_KAKAO_BINDINGS"] = "LIST_KAKAO_BINDINGS"
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: KakaoBindingId | None = None


type KakaoBindingRequest = Annotated[
    CreateKakaoBindingRequest
    | CommandKakaoBindingRequest
    | ReadKakaoBindingRequest
    | ListKakaoBindingsRequest,
    Field(discriminator="operation"),
]


class _OkReply(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class CreateKakaoBindingReply(_OkReply):
    operation: Literal["CREATE_KAKAO_BINDING"] = "CREATE_KAKAO_BINDING"
    result: KakaoBindingMutation


class CommandKakaoBindingReply(_OkReply):
    operation: Literal["COMMAND_KAKAO_BINDING"] = "COMMAND_KAKAO_BINDING"
    result: KakaoBindingMutation


class ReadKakaoBindingReply(_OkReply):
    operation: Literal["READ_KAKAO_BINDING"] = "READ_KAKAO_BINDING"
    result: KakaoSourceBinding


class ListKakaoBindingsReply(_OkReply):
    operation: Literal["LIST_KAKAO_BINDINGS"] = "LIST_KAKAO_BINDINGS"
    result: KakaoBindingPage


class KakaoBindingFailure(FrozenModel):
    operation: KakaoBindingOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoBindingErrorCode


type _SuccessReply = Annotated[
    CreateKakaoBindingReply
    | CommandKakaoBindingReply
    | ReadKakaoBindingReply
    | ListKakaoBindingsReply,
    Field(discriminator="operation"),
]
type KakaoBindingReply = Annotated[
    _SuccessReply | KakaoBindingFailure, Field(discriminator="status")
]
_REQUEST: TypeAdapter[KakaoBindingRequest] = TypeAdapter(KakaoBindingRequest)
_REPLY: TypeAdapter[KakaoBindingReply] = TypeAdapter(KakaoBindingReply)


def parse_kakao_binding_request(value: dict[str, object]) -> KakaoBindingRequest:
    validate_contract("catalog-kakao-binding-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_binding_reply(value: dict[str, object]) -> KakaoBindingReply:
    validate_contract("catalog-kakao-binding-response-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_binding_reply(request: KakaoBindingRequest, reply: KakaoBindingReply) -> None:
    """Reject a valid but unrelated success before public rendering or idempotent replay."""
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if reply.operation != request.operation or reply.request_id != request.request_id:
        raise ValueError(invalid)
    if isinstance(reply, KakaoBindingFailure):
        return
    if isinstance(request, CreateKakaoBindingRequest):
        if not isinstance(reply, CreateKakaoBindingReply):
            raise ValueError(invalid)
        binding = reply.result.binding
        if (
            binding.display_name != request.command.display_name
            or binding.policy_revision.policy != request.command.policy
            or binding.state != "DRAFT"
            or binding.resource_version != 1
            or binding.policy_revision.revision_number != 1
        ):
            raise ValueError(invalid)
    elif isinstance(request, CommandKakaoBindingRequest):
        if not isinstance(reply, CommandKakaoBindingReply):
            raise ValueError(invalid)
        binding = reply.result.binding
        if (
            binding.source_binding_id != request.source_binding_id
            or binding.resource_version != request.command.expected_resource_version + 1
        ):
            raise ValueError(invalid)
        if isinstance(request.command, KakaoBindingRetire) and (
            binding.state != "RETIRED"
            or binding.policy_revision.policy_revision_id
            != request.command.parent_policy_revision_id
        ):
            raise ValueError(invalid)
        if isinstance(request.command, KakaoBindingUpdatePolicy) and (
            binding.state != "DRAFT"
            or binding.policy_revision.previous_revision_id
            != request.command.parent_policy_revision_id
            or binding.policy_revision.policy != request.command.policy
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoBindingRequest):
        if (
            not isinstance(reply, ReadKakaoBindingReply)
            or reply.result.source_binding_id != request.source_binding_id
        ):
            raise ValueError(invalid)
    elif isinstance(reply, ListKakaoBindingsReply):
        identities = [item.source_binding_id for item in reply.result.items]
        if (
            len(identities) > request.limit
            or any(left >= right for left, right in pairwise(identities))
            or (request.cursor is not None and any(i <= request.cursor for i in identities))
            or (
                reply.result.next_cursor is not None
                and (len(identities) != request.limit or reply.result.next_cursor != identities[-1])
            )
        ):
            raise ValueError(invalid)
    else:
        raise ValueError(invalid)

"""Closed student-directory messages on the existing authenticated Catalog transport."""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_students import (
    KakaoStudent,
    KakaoStudentCommand,
    KakaoStudentCreate,
    KakaoStudentId,
    KakaoStudentMutation,
    KakaoStudentPage,
    KakaoStudentRename,
    KakaoStudentRetire,
    KakaoStudentRevisionId,
)
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type KakaoStudentOperation = Literal[
    "CREATE_KAKAO_STUDENT", "COMMAND_KAKAO_STUDENT", "READ_KAKAO_STUDENT", "LIST_KAKAO_STUDENTS"
]
type KakaoStudentErrorCode = Literal[
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
]
KAKAO_STUDENT_OPERATIONS = frozenset(get_args(KakaoStudentOperation.__value__))
KAKAO_STUDENT_ERROR_CODES = frozenset(get_args(KakaoStudentErrorCode.__value__))


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class CreateKakaoStudentRequest(_ApiIdentity):
    operation: Literal["CREATE_KAKAO_STUDENT"] = "CREATE_KAKAO_STUDENT"
    idempotency_key: IdempotencyKey
    command: KakaoStudentCreate


class CommandKakaoStudentRequest(_ApiIdentity):
    operation: Literal["COMMAND_KAKAO_STUDENT"] = "COMMAND_KAKAO_STUDENT"
    student_id: KakaoStudentId
    idempotency_key: IdempotencyKey
    command: KakaoStudentCommand


class ReadKakaoStudentRequest(_ApiIdentity):
    operation: Literal["READ_KAKAO_STUDENT"] = "READ_KAKAO_STUDENT"
    student_id: KakaoStudentId
    display_revision_id: KakaoStudentRevisionId | None = None


class ListKakaoStudentsRequest(_ApiIdentity):
    operation: Literal["LIST_KAKAO_STUDENTS"] = "LIST_KAKAO_STUDENTS"
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: KakaoStudentId | None = None


type KakaoStudentRequest = Annotated[
    CreateKakaoStudentRequest
    | CommandKakaoStudentRequest
    | ReadKakaoStudentRequest
    | ListKakaoStudentsRequest,
    Field(discriminator="operation"),
]


class _OkReply(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class CreateKakaoStudentReply(_OkReply):
    operation: Literal["CREATE_KAKAO_STUDENT"] = "CREATE_KAKAO_STUDENT"
    result: KakaoStudentMutation


class CommandKakaoStudentReply(_OkReply):
    operation: Literal["COMMAND_KAKAO_STUDENT"] = "COMMAND_KAKAO_STUDENT"
    result: KakaoStudentMutation


class ReadKakaoStudentReply(_OkReply):
    operation: Literal["READ_KAKAO_STUDENT"] = "READ_KAKAO_STUDENT"
    result: KakaoStudent


class ListKakaoStudentsReply(_OkReply):
    operation: Literal["LIST_KAKAO_STUDENTS"] = "LIST_KAKAO_STUDENTS"
    result: KakaoStudentPage


class KakaoStudentFailure(FrozenModel):
    operation: KakaoStudentOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoStudentErrorCode


type _SuccessReply = Annotated[
    CreateKakaoStudentReply
    | CommandKakaoStudentReply
    | ReadKakaoStudentReply
    | ListKakaoStudentsReply,
    Field(discriminator="operation"),
]
type KakaoStudentReply = Annotated[
    _SuccessReply | KakaoStudentFailure, Field(discriminator="status")
]
_REQUEST: TypeAdapter[KakaoStudentRequest] = TypeAdapter(KakaoStudentRequest)
_REPLY: TypeAdapter[KakaoStudentReply] = TypeAdapter(KakaoStudentReply)


def parse_kakao_student_request(value: dict[str, object]) -> KakaoStudentRequest:
    validate_contract("catalog-kakao-student-request-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_student_reply(value: dict[str, object]) -> KakaoStudentReply:
    validate_contract("catalog-kakao-student-response-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_student_reply(request: KakaoStudentRequest, reply: KakaoStudentReply) -> None:
    """A valid DTO is not sufficient: prove the exact requested identity/parent/revision."""
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if reply.operation != request.operation or reply.request_id != request.request_id:
        raise ValueError(invalid)
    if isinstance(reply, KakaoStudentFailure):
        return
    if isinstance(request, CreateKakaoStudentRequest):
        if not isinstance(reply, CreateKakaoStudentReply):
            raise ValueError(invalid)
        student = reply.result.student
        if (
            student.display_name != request.command.display_name
            or student.resource_version != 1
            or student.state != "ACTIVE"
        ):
            raise ValueError(invalid)
    elif isinstance(request, CommandKakaoStudentRequest):
        if not isinstance(reply, CommandKakaoStudentReply):
            raise ValueError(invalid)
        student = reply.result.student
        if (
            student.student_id != request.student_id
            or student.resource_version != request.command.expected_resource_version + 1
            or student.previous_revision_id != request.command.parent_revision_id
            or (isinstance(request.command, KakaoStudentRetire) and student.state != "RETIRED")
            or (
                isinstance(request.command, KakaoStudentRename)
                and (
                    student.state != "ACTIVE"
                    or student.display_name != request.command.display_name
                )
            )
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoStudentRequest):
        if (
            not isinstance(reply, ReadKakaoStudentReply)
            or reply.result.student_id != request.student_id
            or (
                request.display_revision_id is not None
                and reply.result.display_revision_id != request.display_revision_id
            )
        ):
            raise ValueError(invalid)
    elif isinstance(reply, ListKakaoStudentsReply):
        ids = tuple(item.student_id for item in reply.result.items)
        if (
            len(ids) > request.limit
            or any(request.cursor is not None and identity <= request.cursor for identity in ids)
            or (reply.result.next_cursor is not None and len(ids) != request.limit)
        ):
            raise ValueError(invalid)
    else:
        raise ValueError(invalid)

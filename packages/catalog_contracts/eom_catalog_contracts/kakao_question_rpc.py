"""Exact question read/review messages on the existing API-only Catalog socket."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_question import (
    BlockId,
    KakaoQuestionConfirm,
    KakaoQuestionExclude,
    QuestionId,
    QuestionRevisionId,
)
from .kakao_question_store import (
    KakaoQuestionChange,
    KakaoQuestionCreate,
    KakaoQuestionMutation,
    KakaoQuestionPage,
    KakaoStoredQuestion,
)
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

type KakaoQuestionOperation = Literal[
    "CREATE_KAKAO_QUESTION",
    "CHANGE_KAKAO_QUESTION",
    "READ_KAKAO_QUESTION",
    "LIST_KAKAO_QUESTIONS",
    "READ_KAKAO_QUESTION_IMAGE",
]
type KakaoQuestionErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_CANDIDATE_NOT_FOUND",
    "KAKAO_ARCHIVE_CANDIDATE_ALREADY_REGISTERED",
    "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID",
    "KAKAO_ARCHIVE_STORED_QUESTION_INVALID",
    "KAKAO_ARCHIVE_STORED_SOURCE_INVALID",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_IMAGE_UNAVAILABLE",
    "KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_QUESTION_OPERATIONS = frozenset(get_args(KakaoQuestionOperation.__value__))
KAKAO_QUESTION_ERROR_CODES = frozenset(get_args(KakaoQuestionErrorCode.__value__))
AttachmentId = Annotated[str, Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")]


class KakaoQuestionDisplayText(FrozenModel):
    kind: Literal["TEXT"] = "TEXT"
    block_id: BlockId
    role: Literal["student", "staff"]
    text: str = Field(min_length=1, max_length=20000)


class KakaoQuestionDisplayImage(FrozenModel):
    kind: Literal["IMAGE"] = "IMAGE"
    block_id: BlockId
    role: Literal["student", "staff"]
    attachment_id: AttachmentId
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    availability: Literal["available", "expired", "denied", "not_found", "pending", "failed"]
    source_quality: Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"]


class KakaoQuestionView(FrozenModel):
    schema_version: Literal["kakao-question-view/1.0"] = "kakao-question-view/1.0"
    question: KakaoStoredQuestion
    ordered_blocks: tuple[
        Annotated[
            KakaoQuestionDisplayText | KakaoQuestionDisplayImage, Field(discriminator="kind")
        ],
        ...,
    ] = Field(min_length=1, max_length=230)
    review_reasons: tuple[str, ...] = Field(max_length=8)
    boundary_uncertain: bool = Field(strict=True)

    @model_validator(mode="after")
    def unique_blocks(self) -> "KakaoQuestionView":
        if len({block.block_id for block in self.ordered_blocks}) != len(
            self.ordered_blocks
        ) or len(set(self.review_reasons)) != len(self.review_reasons):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class KakaoQuestionImageDescriptor(FrozenModel):
    schema_version: Literal["kakao-question-image/1.0"] = "kakao-question-image/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    attachment_id: AttachmentId
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    content_length: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    sha256: Sha256


class _ApiIdentity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class CreateKakaoQuestionRequest(_ApiIdentity):
    operation: Literal["CREATE_KAKAO_QUESTION"] = "CREATE_KAKAO_QUESTION"
    command: KakaoQuestionCreate
    idempotency_key: IdempotencyKey


class ChangeKakaoQuestionRequest(_ApiIdentity):
    operation: Literal["CHANGE_KAKAO_QUESTION"] = "CHANGE_KAKAO_QUESTION"
    command: KakaoQuestionChange
    idempotency_key: IdempotencyKey


class _QuestionIdentity(_ApiIdentity):
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId | None = None
    question_id: QuestionId
    question_revision_id: QuestionRevisionId


class ReadKakaoQuestionRequest(_QuestionIdentity):
    operation: Literal["READ_KAKAO_QUESTION"] = "READ_KAKAO_QUESTION"


class ReadKakaoQuestionImageRequest(_QuestionIdentity):
    operation: Literal["READ_KAKAO_QUESTION_IMAGE"] = "READ_KAKAO_QUESTION_IMAGE"
    attachment_id: AttachmentId


class ListKakaoQuestionsRequest(_ApiIdentity):
    operation: Literal["LIST_KAKAO_QUESTIONS"] = "LIST_KAKAO_QUESTIONS"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId | None = None
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: QuestionId | None = None


type KakaoQuestionRequest = Annotated[
    CreateKakaoQuestionRequest
    | ChangeKakaoQuestionRequest
    | ReadKakaoQuestionRequest
    | ListKakaoQuestionsRequest
    | ReadKakaoQuestionImageRequest,
    Field(discriminator="operation"),
]


class _OkReply(FrozenModel):
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None


class CreateKakaoQuestionReply(_OkReply):
    operation: Literal["CREATE_KAKAO_QUESTION"] = "CREATE_KAKAO_QUESTION"
    result: KakaoQuestionMutation


class ChangeKakaoQuestionReply(_OkReply):
    operation: Literal["CHANGE_KAKAO_QUESTION"] = "CHANGE_KAKAO_QUESTION"
    result: KakaoQuestionMutation


class ReadKakaoQuestionReply(_OkReply):
    operation: Literal["READ_KAKAO_QUESTION"] = "READ_KAKAO_QUESTION"
    result: KakaoQuestionView


class ListKakaoQuestionsReply(_OkReply):
    operation: Literal["LIST_KAKAO_QUESTIONS"] = "LIST_KAKAO_QUESTIONS"
    result: KakaoQuestionPage


class ReadKakaoQuestionImageReply(_OkReply):
    operation: Literal["READ_KAKAO_QUESTION_IMAGE"] = "READ_KAKAO_QUESTION_IMAGE"
    result: KakaoQuestionImageDescriptor


class KakaoQuestionFailure(FrozenModel):
    operation: KakaoQuestionOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoQuestionErrorCode


type _SuccessReply = Annotated[
    CreateKakaoQuestionReply
    | ChangeKakaoQuestionReply
    | ReadKakaoQuestionReply
    | ListKakaoQuestionsReply
    | ReadKakaoQuestionImageReply,
    Field(discriminator="operation"),
]
type KakaoQuestionReply = Annotated[
    _SuccessReply | KakaoQuestionFailure, Field(discriminator="status")
]
_REQUEST: TypeAdapter[KakaoQuestionRequest] = TypeAdapter(KakaoQuestionRequest)
_REPLY: TypeAdapter[KakaoQuestionReply] = TypeAdapter(KakaoQuestionReply)


def parse_kakao_question_request(value: dict[str, object]) -> KakaoQuestionRequest:
    validate_contract("catalog-kakao-question-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_question_reply(value: dict[str, object]) -> KakaoQuestionReply:
    validate_contract("catalog-kakao-question-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_question_reply(request: KakaoQuestionRequest, reply: KakaoQuestionReply) -> None:
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    value: KakaoStoredQuestion | KakaoQuestionImageDescriptor
    if request.operation != reply.operation or request.request_id != reply.request_id:
        raise ValueError(invalid)
    if isinstance(reply, KakaoQuestionFailure):
        return
    if isinstance(request, (CreateKakaoQuestionRequest, ChangeKakaoQuestionRequest)):
        if not isinstance(reply, (CreateKakaoQuestionReply, ChangeKakaoQuestionReply)):
            raise ValueError(invalid)
        value, command = reply.result.question, request.command
        if (value.source_binding_id, value.room_id) != (command.source_binding_id, command.room_id):
            raise ValueError(invalid)
        if isinstance(command, KakaoQuestionCreate):
            if (
                value.resource_version != 1
                or value.previous_revision_id is not None
                or value.review_state != "UNREVIEWED"
            ):
                raise ValueError(invalid)
        elif (
            value.question_id != command.question_id
            or value.resource_version != command.expected_resource_version + 1
            or value.previous_revision_id != command.edit.parent_revision_id
            or (
                isinstance(command.edit, KakaoQuestionConfirm) and value.review_state != "CONFIRMED"
            )
            or (isinstance(command.edit, KakaoQuestionExclude) and value.review_state != "EXCLUDED")
        ):
            raise ValueError(invalid)
    elif isinstance(request, ListKakaoQuestionsRequest):
        if not isinstance(reply, ListKakaoQuestionsReply):
            raise ValueError(invalid)
        items = reply.result.items
        if (
            len(items) > request.limit
            or any(
                item.source_binding_id != request.source_binding_id
                or (request.room_id is not None and item.room_id != request.room_id)
                or (request.cursor is not None and item.question_id <= request.cursor)
                for item in items
            )
            or (reply.result.next_cursor is not None and len(items) != request.limit)
        ):
            raise ValueError(invalid)
    else:
        if isinstance(reply, ReadKakaoQuestionReply):
            value = reply.result.question
        elif isinstance(reply, ReadKakaoQuestionImageReply):
            if (
                not isinstance(request, ReadKakaoQuestionImageRequest)
                or reply.result.attachment_id != request.attachment_id
            ):
                raise ValueError(invalid)
            value = reply.result
        else:
            raise ValueError(invalid)
        if any(
            getattr(value, key) != getattr(request, key)
            for key in ("source_binding_id", "question_id", "question_revision_id")
        ):
            raise ValueError(invalid)
        if request.room_id is not None and value.room_id != request.room_id:
            raise ValueError(invalid)

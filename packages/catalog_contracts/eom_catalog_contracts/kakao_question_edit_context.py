"""Exact text-span metadata for an existing question, not content or edit authority."""

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, TypeAdapter, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId
from .kakao_archive_rpc import RequestId
from .kakao_question import BlockId, QuestionId, QuestionRevisionId
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

READ_KAKAO_QUESTION_EDIT_CONTEXT = "READ_KAKAO_QUESTION_EDIT_CONTEXT"
type EditContextErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_STORED_QUESTION_INVALID",
    "KAKAO_ARCHIVE_STORED_SOURCE_INVALID",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID",
    "KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
EDIT_CONTEXT_ERRORS = frozenset(get_args(EditContextErrorCode.__value__))


class KakaoTextEditRange(FrozenModel):
    block_id: BlockId
    can_split: bool = Field(strict=True)
    start_codepoint: int | None = Field(strict=True, ge=0, le=65535)
    end_codepoint: int | None = Field(strict=True, ge=1, le=65536)

    @model_validator(mode="after")
    def exact_span(self) -> Self:
        if self.can_split:
            if (
                self.start_codepoint is None
                or self.end_codepoint is None
                or self.start_codepoint >= self.end_codepoint
            ):
                raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        elif self.start_codepoint is not None or self.end_codepoint is not None:
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class KakaoQuestionEditContext(FrozenModel):
    schema_version: Literal["kakao-question-edit-context/1.0"] = "kakao-question-edit-context/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    resource_version: int = Field(strict=True, ge=1, le=2147483647)
    text_blocks: tuple[KakaoTextEditRange, ...] = Field(max_length=230)

    @model_validator(mode="after")
    def closed_context(self) -> Self:
        if len({block.block_id for block in self.text_blocks}) != len(self.text_blocks):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        validate_contract("kakao-question-edit-context-v1", self.model_dump(mode="json"))
        return self


class ReadKakaoQuestionEditContext(FrozenModel):
    operation: Literal["READ_KAKAO_QUESTION_EDIT_CONTEXT"] = "READ_KAKAO_QUESTION_EDIT_CONTEXT"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId | None = None
    question_id: QuestionId
    question_revision_id: QuestionRevisionId


class KakaoQuestionEditContextReply(FrozenModel):
    operation: Literal["READ_KAKAO_QUESTION_EDIT_CONTEXT"] = "READ_KAKAO_QUESTION_EDIT_CONTEXT"
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None
    result: KakaoQuestionEditContext


class KakaoQuestionEditContextFailure(FrozenModel):
    operation: Literal["READ_KAKAO_QUESTION_EDIT_CONTEXT"] = "READ_KAKAO_QUESTION_EDIT_CONTEXT"
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    error_code: EditContextErrorCode
    result: None = None


type EditContextReply = Annotated[
    KakaoQuestionEditContextReply | KakaoQuestionEditContextFailure, Field(discriminator="status")
]
_REPLY: TypeAdapter[EditContextReply] = TypeAdapter(EditContextReply)


def parse_edit_context_request(value: dict[str, object]) -> ReadKakaoQuestionEditContext:
    validate_contract("kakao-question-edit-context-v1", value)
    return ReadKakaoQuestionEditContext.model_validate(value)


def parse_edit_context_reply(value: dict[str, object]) -> EditContextReply:
    validate_contract("kakao-question-edit-context-v1", value)
    return _REPLY.validate_python(value)


def check_edit_context_reply(
    request: ReadKakaoQuestionEditContext, reply: EditContextReply
) -> None:
    if request.request_id != reply.request_id or request.operation != reply.operation:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, KakaoQuestionEditContextFailure):
        return
    value = reply.result
    if (value.source_binding_id, value.question_id, value.question_revision_id) != (
        request.source_binding_id,
        request.question_id,
        request.question_revision_id,
    ) or (request.room_id is not None and value.room_id != request.room_id):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")

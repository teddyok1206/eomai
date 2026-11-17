"""Explicit new source selection; never an automatic edit or authority grant."""

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId, RowOrdinal
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_question import QuestionId, QuestionRevisionId
from .kakao_question_rpc import KAKAO_QUESTION_ERROR_CODES, KakaoQuestionErrorCode
from .kakao_question_store import KakaoQuestionMutation
from .kakao_rooms import KakaoMappingRevisionId
from .kakao_source import SourceRevisionId
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

REFRESH_KAKAO_QUESTION_SOURCE = "REFRESH_KAKAO_QUESTION_SOURCE"
type RefreshErrorCode = KakaoQuestionErrorCode | Literal["KAKAO_ARCHIVE_SOURCE_ORDER_UNVERIFIED"]
REFRESH_ERROR_CODES = KAKAO_QUESTION_ERROR_CODES | {"KAKAO_ARCHIVE_SOURCE_ORDER_UNVERIFIED"}


class KakaoQuestionSourceRefresh(FrozenModel):
    schema_version: Literal["kakao-question-source-refresh/1.0"] = (
        "kakao-question-source-refresh/1.0"
    )
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    parent_revision_id: QuestionRevisionId
    expected_resource_version: int = Field(strict=True, ge=1, le=2147483646)
    expected_mapping_revision_id: KakaoMappingRevisionId
    source_revision_id: SourceRevisionId
    candidate_ordinal: RowOrdinal
    replace_display_edits: Literal[True]

    @field_validator("replace_display_edits", mode="before")
    @classmethod
    def explicit_replacement(cls, value: object) -> object:
        if value is not True:
            raise ValueError("KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID")
        return value

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-question-source-refresh-v1", self.model_dump(mode="json"))
        return self


class RefreshKakaoQuestionSourceRequest(FrozenModel):
    operation: Literal["REFRESH_KAKAO_QUESTION_SOURCE"] = "REFRESH_KAKAO_QUESTION_SOURCE"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime
    command: KakaoQuestionSourceRefresh
    idempotency_key: IdempotencyKey


class RefreshKakaoQuestionSourceReply(FrozenModel):
    operation: Literal["REFRESH_KAKAO_QUESTION_SOURCE"] = "REFRESH_KAKAO_QUESTION_SOURCE"
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None
    result: KakaoQuestionMutation


class RefreshKakaoQuestionSourceFailure(FrozenModel):
    operation: Literal["REFRESH_KAKAO_QUESTION_SOURCE"] = "REFRESH_KAKAO_QUESTION_SOURCE"
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    error_code: RefreshErrorCode
    result: None = None


type RefreshReply = Annotated[
    RefreshKakaoQuestionSourceReply | RefreshKakaoQuestionSourceFailure,
    Field(discriminator="status"),
]
_REPLY: TypeAdapter[RefreshReply] = TypeAdapter(RefreshReply)


def parse_refresh_request(value: dict[str, object]) -> RefreshKakaoQuestionSourceRequest:
    validate_contract("kakao-question-source-refresh-v1", value)
    return RefreshKakaoQuestionSourceRequest.model_validate(value)


def parse_refresh_reply(value: dict[str, object]) -> RefreshReply:
    validate_contract("kakao-question-source-refresh-v1", value)
    return _REPLY.validate_python(value)


def check_refresh_reply(request: RefreshKakaoQuestionSourceRequest, reply: RefreshReply) -> None:
    if (request.operation, request.request_id) != (reply.operation, reply.request_id):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, RefreshKakaoQuestionSourceFailure):
        return
    value, command = reply.result.question, request.command
    if (
        value.source_binding_id,
        value.room_id,
        value.question_id,
        value.previous_revision_id,
        value.resource_version,
        value.review_state,
    ) != (
        command.source_binding_id,
        command.room_id,
        command.question_id,
        command.parent_revision_id,
        command.expected_resource_version + 1,
        "UNREVIEWED",
    ) or (
        value.student is not None
        and value.student.room_mapping_revision_id != command.expected_mapping_revision_id
    ):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")

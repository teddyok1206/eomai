"""Additive API-peer composition messages; released question-v1 bytes stay unchanged."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_question_composition import KakaoQuestionComposition, KakaoQuestionMerge
from .kakao_question_composition_result import KakaoQuestionCompositionResult
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

COMPOSE_KAKAO_QUESTIONS = "COMPOSE_KAKAO_QUESTIONS"
type KakaoComposeError = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID",
    "KAKAO_ARCHIVE_QUESTION_EDIT_INVALID",
    "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID",
    "KAKAO_ARCHIVE_STORED_QUESTION_INVALID",
    "KAKAO_ARCHIVE_STORED_SOURCE_INVALID",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_COMPOSE_ERRORS = frozenset(get_args(KakaoComposeError.__value__))


class ComposeKakaoQuestionsRequest(FrozenModel):
    operation: Literal["COMPOSE_KAKAO_QUESTIONS"] = "COMPOSE_KAKAO_QUESTIONS"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime
    command: KakaoQuestionComposition
    idempotency_key: IdempotencyKey


class ComposeKakaoQuestionsReply(FrozenModel):
    operation: Literal["COMPOSE_KAKAO_QUESTIONS"] = "COMPOSE_KAKAO_QUESTIONS"
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None
    result: KakaoQuestionCompositionResult


class KakaoComposeFailure(FrozenModel):
    operation: Literal["COMPOSE_KAKAO_QUESTIONS"] = "COMPOSE_KAKAO_QUESTIONS"
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoComposeError


KakaoComposeReply = Annotated[
    ComposeKakaoQuestionsReply | KakaoComposeFailure, Field(discriminator="status")
]
_REPLY: TypeAdapter[KakaoComposeReply] = TypeAdapter(KakaoComposeReply)


def parse_kakao_compose_request(value: dict[str, object]) -> ComposeKakaoQuestionsRequest:
    validate_contract("catalog-kakao-question-compose-v1", value)
    return ComposeKakaoQuestionsRequest.model_validate(value)


def parse_kakao_compose_reply(value: dict[str, object]) -> KakaoComposeReply:
    validate_contract("catalog-kakao-question-compose-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_compose_reply(
    request: ComposeKakaoQuestionsRequest, reply: KakaoComposeReply
) -> None:
    if reply.operation != request.operation or reply.request_id != request.request_id:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, KakaoComposeFailure):
        return
    result, command = reply.result, request.command
    inputs = command.inputs if isinstance(command, KakaoQuestionMerge) else (command.input,)
    if (
        result.operation != command.operation
        or result.source_binding_id != command.source_binding_id
        or result.room_id != command.room_id
        or result.inputs != inputs
        or len(result.outputs)
        != (1 if isinstance(command, KakaoQuestionMerge) else len(command.partitions))
    ):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")

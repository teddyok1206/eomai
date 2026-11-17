"""Bounded candidates of one accepted source; no collection or editing authority."""

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, TypeAdapter, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId, ReviewReason
from .kakao_archive_rpc import RequestId
from .kakao_question import KakaoQuestionProvenance
from .kakao_rooms import KakaoMappingRevisionId
from .kakao_source import SourceRevisionId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

LIST_KAKAO_QUESTION_CANDIDATES = "LIST_KAKAO_QUESTION_CANDIDATES"
type CandidateErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_STORED_ROOM_INVALID",
    "KAKAO_ARCHIVE_STORED_SOURCE_INVALID",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_SOURCE_ORDER_UNVERIFIED",
    "KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
CANDIDATE_ERROR_CODES = frozenset(get_args(CandidateErrorCode.__value__))


class KakaoCandidateSummary(FrozenModel):
    candidate_ordinal: int = Field(strict=True, ge=1, le=100000)
    student_message_count: int = Field(strict=True, ge=1, le=100000)
    reply_message_count: int = Field(strict=True, ge=0, le=100000)
    photo_count: int = Field(strict=True, ge=0, le=100000)
    first_student_at_utc: UtcDatetime | None
    preview: str = Field(max_length=240)
    boundary_uncertain: bool = Field(strict=True)
    review_reasons: tuple[ReviewReason, ...] = Field(max_length=8)
    saved_question: KakaoQuestionProvenance | None
    recomposed: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact_registration(self) -> Self:
        if (self.recomposed and self.saved_question is None) or len(
            set(self.review_reasons)
        ) != len(self.review_reasons):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class KakaoQuestionCandidatePage(FrozenModel):
    schema_version: Literal["kakao-question-candidate-page/1.0"] = (
        "kakao-question-candidate-page/1.0"
    )
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    source_revision_id: SourceRevisionId | None
    source_resolution_sha256: Sha256 | None
    mapping_revision_id: KakaoMappingRevisionId
    total_candidates: int = Field(strict=True, ge=0, le=100000)
    unknown_sender_rows: int = Field(strict=True, ge=0, le=100000)
    items: tuple[KakaoCandidateSummary, ...] = Field(max_length=100)
    next_after_ordinal: int | None = Field(strict=True, ge=1, le=100000)

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        if (self.source_revision_id is None) != (self.source_resolution_sha256 is None):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        if self.source_revision_id is None and (
            self.total_candidates
            or self.unknown_sender_rows
            or self.items
            or self.next_after_ordinal is not None
        ):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        ordinals = tuple(item.candidate_ordinal for item in self.items)
        if ordinals and (
            ordinals != tuple(range(ordinals[0], ordinals[-1] + 1))
            or ordinals[-1] > self.total_candidates
        ):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        expected_next = ordinals[-1] if ordinals and ordinals[-1] < self.total_candidates else None
        if self.next_after_ordinal != expected_next:
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        validate_contract("kakao-question-candidate-page-v1", self.model_dump(mode="json"))
        return self


class ListKakaoQuestionCandidates(FrozenModel):
    operation: Literal["LIST_KAKAO_QUESTION_CANDIDATES"] = "LIST_KAKAO_QUESTION_CANDIDATES"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    source_revision_id: SourceRevisionId | None = None
    after_ordinal: int = Field(default=0, strict=True, ge=0, le=100000)
    limit: int = Field(default=50, strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def pin_followup(self) -> Self:
        if self.after_ordinal and self.source_revision_id is None:
            raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
        return self


class KakaoCandidateReply(FrozenModel):
    operation: Literal["LIST_KAKAO_QUESTION_CANDIDATES"] = "LIST_KAKAO_QUESTION_CANDIDATES"
    request_id: RequestId
    status: Literal["OK"] = "OK"
    error_code: None = None
    result: KakaoQuestionCandidatePage


class KakaoCandidateFailure(FrozenModel):
    operation: Literal["LIST_KAKAO_QUESTION_CANDIDATES"] = "LIST_KAKAO_QUESTION_CANDIDATES"
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    error_code: CandidateErrorCode
    result: None = None


type CandidateReply = Annotated[
    KakaoCandidateReply | KakaoCandidateFailure, Field(discriminator="status")
]
_REPLY: TypeAdapter[CandidateReply] = TypeAdapter(CandidateReply)


def parse_candidate_request(value: dict[str, object]) -> ListKakaoQuestionCandidates:
    validate_contract("kakao-question-candidate-page-v1", value)
    return ListKakaoQuestionCandidates.model_validate(value)


def parse_candidate_reply(value: dict[str, object]) -> CandidateReply:
    validate_contract("kakao-question-candidate-page-v1", value)
    return _REPLY.validate_python(value)


def check_candidate_reply(request: ListKakaoQuestionCandidates, reply: CandidateReply) -> None:
    if request.request_id != reply.request_id or request.operation != reply.operation:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, KakaoCandidateFailure):
        return
    value = reply.result
    if (value.source_binding_id, value.room_id) != (request.source_binding_id, request.room_id) or (
        request.source_revision_id is not None
        and value.source_revision_id != request.source_revision_id
    ):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if len(value.items) > request.limit or (
        value.items and value.items[0].candidate_ordinal != request.after_ordinal + 1
    ):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")

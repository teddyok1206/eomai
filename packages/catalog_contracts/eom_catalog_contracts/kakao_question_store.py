"""Typed private question commands and small exact-revision read projections."""

from typing import Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId, KakaoRoomId, RowOrdinal
from eom_catalog_contracts.kakao_question import (
    QUESTION_REF,
    KakaoQuestionEditCommand,
    KakaoQuestionStudentPin,
    QuestionId,
    QuestionRevisionId,
)
from eom_catalog_contracts.kakao_source import SourceRevisionId
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_catalog_contracts.validation import validate_contract


class KakaoQuestionCreate(FrozenModel):
    schema_version: Literal["kakao-question-create/1.0"] = "kakao-question-create/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    source_revision_id: SourceRevisionId
    candidate_ordinal: RowOrdinal
    expected_mapping_revision_id: str = Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-question-store-v1", self.model_dump(mode="json"))
        return self


class KakaoQuestionChange(FrozenModel):
    schema_version: Literal["kakao-question-change/1.0"] = "kakao-question-change/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    expected_resource_version: int = Field(strict=True, ge=1, le=2147483646)
    edit: KakaoQuestionEditCommand

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-question-store-v1", self.model_dump(mode="json"))
        return self


class KakaoStoredQuestion(FrozenModel):
    schema_version: Literal["kakao-stored-question/1.0"] = "kakao-stored-question/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    previous_revision_id: QuestionRevisionId | None
    resource_version: int = Field(strict=True, ge=1, le=2147483647)
    manifest: ArtifactMemberPointer
    review_state: Literal["UNREVIEWED", "CONFIRMED", "EXCLUDED"]
    first_student_at_utc: UtcDatetime | None
    student: KakaoQuestionStudentPin | None
    created_at: UtcDatetime

    @model_validator(mode="after")
    def exact_revision(self) -> Self:
        validate_contract("kakao-question-store-v1", self.model_dump(mode="json"))
        if (
            self.manifest.schema_ref != QUESTION_REF
            or self.manifest.media_type != "application/json"
            or (self.resource_version == 1) != (self.previous_revision_id is None)
            or self.previous_revision_id == self.question_revision_id
        ):
            raise ValueError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
        return self


class KakaoQuestionMutation(FrozenModel):
    schema_version: Literal["kakao-question-mutation/1.0"] = "kakao-question-mutation/1.0"
    question: KakaoStoredQuestion
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-question-store-v1", self.model_dump(mode="json"))
        return self


class KakaoQuestionPage(FrozenModel):
    schema_version: Literal["kakao-question-page/1.0"] = "kakao-question-page/1.0"
    items: tuple[KakaoStoredQuestion, ...] = Field(max_length=100)
    next_cursor: QuestionId | None

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        validate_contract("kakao-question-store-v1", self.model_dump(mode="json"))
        ids = tuple(item.question_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_ARCHIVE_QUESTION_PAGE_INVALID")
        return self

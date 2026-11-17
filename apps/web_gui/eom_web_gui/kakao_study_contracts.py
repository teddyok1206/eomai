"""Bounded editable study projections; Catalog remains the rule and source owner."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .contracts import UtcDatetime, WebModel
from .kakao_archive_contracts import Label, ResourceVersion
from .kakao_delivery_contracts import (
    KakaoArtifactPointer,
    PacketId,
    PacketRevisionId,
    Sha256,
    StudentExport,
    StudentId,
)
from .kakao_question_contracts import BindingId, RevisionId

StudyId = Annotated[str, Field(pattern=r"^kakaostudy_[0-9a-f]{32}$")]
StudyRevisionId = Annotated[str, Field(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")]


class StudyBlockEdit(WebModel):
    block_index: int = Field(strict=True, ge=0, le=5)
    title: Label | None = None
    relevance: str | None = Field(default=None, min_length=1, max_length=1000)
    explanation: str | None = Field(default=None, min_length=1, max_length=8000)
    capture_indices: tuple[Annotated[int, Field(strict=True, ge=0, le=3)], ...] | None = Field(
        default=None, max_length=4
    )


class StudyNote(WebModel):
    title: Label
    text: str = Field(min_length=1, max_length=8000)


class StudyQuestionEdit(WebModel):
    question_revision_id: RevisionId
    concept_task_id: str | None = Field(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")
    blocks: tuple[StudyBlockEdit, ...] = Field(max_length=6)
    notes: tuple[StudyNote, ...] = Field(max_length=8)


class _StudySelection(WebModel):
    source_binding_id: BindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: StudentId
    title: Label
    questions: tuple[StudyQuestionEdit, ...] = Field(min_length=1, max_length=200)


class StudyCreate(_StudySelection):
    schema_version: Literal["kakao-study-create/1.0"]


class StudyRevise(_StudySelection):
    schema_version: Literal["kakao-study-revise/1.0"]
    study_id: StudyId
    parent_revision_id: StudyRevisionId
    expected_resource_version: int = Field(strict=True, ge=1, le=2147483646)


class StoredStudy(WebModel):
    schema_version: Literal["kakao-stored-study/1.0"]
    study_id: StudyId
    study_revision_id: StudyRevisionId
    previous_revision_id: StudyRevisionId | None
    resource_version: ResourceVersion
    source_binding_id: BindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: StudentId
    title: Label
    created_at: UtcDatetime
    question_count: int = Field(strict=True, ge=1, le=200)
    manifest: KakaoArtifactPointer

    @model_validator(mode="after")
    def source_format(self) -> Self:
        if (
            self.manifest.schema_ref,
            self.manifest.member_path,
            self.manifest.media_type,
        ) != ("eom://schemas/kakao-archive/study-store-v1/1.0", "study.json", "application/json"):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        if (self.resource_version == 1) != (self.previous_revision_id is None):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class StudyMutation(WebModel):
    schema_version: Literal["kakao-study-mutation/1.0"]
    study: StoredStudy
    replayed: bool = Field(strict=True)


class StudyView(WebModel):
    schema_version: Literal["kakao-study-view/1.0"]
    study: StoredStudy
    questions: tuple[StudyQuestionEdit, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_questions(self) -> Self:
        if len(self.questions) != self.study.question_count or len(
            {q.question_revision_id for q in self.questions}
        ) != len(self.questions):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class StudyPage(WebModel):
    schema_version: Literal["kakao-study-page/1.0"]
    items: tuple[StoredStudy, ...] = Field(max_length=100)
    next_cursor: StudyId | None


class StudyExportPin(WebModel):
    study_id: StudyId
    study_revision_id: StudyRevisionId
    manifest_sha256: Sha256


class StudyExportCreate(WebModel):
    schema_version: Literal["kakao-study-export-create/1.0"]
    source_binding_id: BindingId
    study: StudyExportPin


class StudyExport(WebModel):
    schema_version: Literal["kakao-study-export/1.0"]
    study: StudyExportPin
    export: StudentExport

    @model_validator(mode="after")
    def study_format(self) -> Self:
        if self.export.schema_version != "kakao-export/2.0":
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class StudyExportMutation(WebModel):
    schema_version: Literal["kakao-study-export-mutation/1.0"]
    result: StudyExport
    replayed: bool = Field(strict=True)

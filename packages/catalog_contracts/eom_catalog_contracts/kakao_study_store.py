"""Saved private study selections; original questions, concepts and images remain pointers."""

from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ConfigDict, Field, field_validator, model_validator

from .kakao_archive import KakaoBindingId, validate_kakao_display_name
from .kakao_concept_knowledge import KakaoConceptResultPin
from .kakao_concept_tasks import ConceptTaskId
from .kakao_packet_store import PACKET_REF, PacketId, PacketRevisionId
from .kakao_question import OperatorId, QuestionRevisionId
from .kakao_students import KakaoStudentId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

StudyId = Annotated[str, Field(pattern=r"^kakaostudy_[0-9a-f]{32}$")]
StudyRevisionId = Annotated[str, Field(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")]
STUDY_REF = "eom://schemas/kakao-archive/study-store-v1/1.0"
MAX_STUDY_BYTES = 4 * 1024 * 1024


def _validate_study(value: dict[str, object]) -> None:
    try:
        validate_contract("kakao-study-store-v1", value)
    except JsonSchemaError:
        # JSON Schema errors carry the full instance, including private notes.
        raise ValueError("KAKAO_STUDY_CONTRACT_INVALID") from None


class _StudyValue(FrozenModel):
    model_config = ConfigDict(hide_input_in_errors=True, revalidate_instances="always")


class KakaoStudyBlockEdit(_StudyValue):
    block_index: int = Field(strict=True, ge=0, le=5)
    title: str | None = Field(default=None, min_length=1, max_length=128)
    relevance: str | None = Field(default=None, min_length=1, max_length=1000)
    explanation: str | None = Field(default=None, min_length=1, max_length=8000)
    capture_indices: tuple[Annotated[int, Field(strict=True, ge=0, le=3)], ...] | None = Field(
        default=None, max_length=4
    )

    @model_validator(mode="after")
    def unique_captures(self) -> Self:
        if self.title is not None:
            validate_kakao_display_name(self.title)
        if self.capture_indices is not None and len(set(self.capture_indices)) != len(
            self.capture_indices
        ):
            raise ValueError("KAKAO_STUDY_CAPTURE_DUPLICATED")
        return self


class KakaoStudyNote(_StudyValue):
    title: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)

    _title = field_validator("title")(validate_kakao_display_name)


class KakaoStudyQuestionEdit(_StudyValue):
    question_revision_id: QuestionRevisionId
    concept_task_id: ConceptTaskId | None
    blocks: tuple[KakaoStudyBlockEdit, ...] = Field(max_length=6)
    notes: tuple[KakaoStudyNote, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def selected_blocks(self) -> Self:
        if len({b.block_index for b in self.blocks}) != len(self.blocks) or (
            self.concept_task_id is None and self.blocks
        ):
            raise ValueError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
        return self


class _Selection(_StudyValue):
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: KakaoStudentId
    title: str = Field(min_length=1, max_length=128)
    questions: tuple[KakaoStudyQuestionEdit, ...] = Field(min_length=1, max_length=200)

    _title = field_validator("title")(validate_kakao_display_name)

    @model_validator(mode="after")
    def closed_request(self) -> Self:
        if len({q.question_revision_id for q in self.questions}) != len(self.questions):
            raise ValueError("KAKAO_STUDY_QUESTION_DUPLICATED")
        if len(canonical_json_bytes(self)) > MAX_STUDY_BYTES:
            raise ValueError("KAKAO_STUDY_TOO_LARGE")
        _validate_study(self.model_dump(mode="json"))
        return self


class KakaoStudyCreate(_Selection):
    schema_version: Literal["kakao-study-create/1.0"] = "kakao-study-create/1.0"


class KakaoStudyRevise(_Selection):
    schema_version: Literal["kakao-study-revise/1.0"] = "kakao-study-revise/1.0"
    study_id: StudyId
    parent_revision_id: StudyRevisionId
    expected_resource_version: int = Field(strict=True, ge=1, le=2147483646)


KakaoStudyCommand = KakaoStudyCreate | KakaoStudyRevise


class KakaoStudyQuestion(_StudyValue):
    edit: KakaoStudyQuestionEdit
    result: KakaoConceptResultPin | None

    @model_validator(mode="after")
    def source_result(self) -> Self:
        if (self.edit.concept_task_id is None) != (self.result is None):
            raise ValueError("KAKAO_STUDY_CONCEPT_RESULT_REQUIRED")
        return self


class _Revision(_StudyValue):
    study_id: StudyId
    study_revision_id: StudyRevisionId
    previous_revision_id: StudyRevisionId | None
    resource_version: int = Field(strict=True, ge=1, le=2147483647)
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: KakaoStudentId
    title: str = Field(min_length=1, max_length=128)
    created_at: UtcDatetime

    _title = field_validator("title")(validate_kakao_display_name)

    @model_validator(mode="after")
    def lineage(self) -> Self:
        if (self.resource_version == 1) != (self.previous_revision_id is None) or (
            self.previous_revision_id == self.study_revision_id
        ):
            raise ValueError("KAKAO_STUDY_LINEAGE_INVALID")
        _validate_study(self.model_dump(mode="json"))
        return self


class KakaoStudyManifest(_Revision):
    schema_version: Literal["kakao-study-manifest/1.0"] = "kakao-study-manifest/1.0"
    packet_manifest: ArtifactMemberPointer
    subset_sha256: Sha256
    questions: tuple[KakaoStudyQuestion, ...] = Field(min_length=1, max_length=200)
    created_by: OperatorId

    @model_validator(mode="after")
    def question_set(self) -> Self:
        if (
            len({q.edit.question_revision_id for q in self.questions}) != len(self.questions)
            or self.packet_manifest.schema_ref != PACKET_REF
            or self.packet_manifest.media_type != "application/json"
            or self.packet_manifest.member_path != "packet.json"
            or len(canonical_json_bytes(self)) > MAX_STUDY_BYTES
        ):
            raise ValueError("KAKAO_STUDY_MANIFEST_INVALID")
        return self


class KakaoStoredStudy(_Revision):
    schema_version: Literal["kakao-stored-study/1.0"] = "kakao-stored-study/1.0"
    question_count: int = Field(strict=True, ge=1, le=200)
    manifest: ArtifactMemberPointer

    @model_validator(mode="after")
    def manifest_pointer(self) -> Self:
        if (self.manifest.schema_ref, self.manifest.media_type, self.manifest.member_path) != (
            STUDY_REF,
            "application/json",
            "study.json",
        ):
            raise ValueError("KAKAO_STUDY_POINTER_INVALID")
        return self


class KakaoStudyMutation(_StudyValue):
    schema_version: Literal["kakao-study-mutation/1.0"] = "kakao-study-mutation/1.0"
    study: KakaoStoredStudy
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        _validate_study(self.model_dump(mode="json"))
        return self


class KakaoStudyPage(_StudyValue):
    schema_version: Literal["kakao-study-page/1.0"] = "kakao-study-page/1.0"
    items: tuple[KakaoStoredStudy, ...] = Field(max_length=100)
    next_cursor: StudyId | None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        ids = tuple(item.study_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_STUDY_PAGE_INVALID")
        _validate_study(self.model_dump(mode="json"))
        return self

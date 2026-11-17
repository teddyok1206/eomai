"""Small browser projections; source/revision integrity stays in Catalog."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import UtcDatetime, WebModel
from .kakao_archive_contracts import Label, ResourceVersion

QuestionId = Annotated[str, Field(pattern=r"^kakaoquestion_[0-9a-f]{32}$")]
RevisionId = Annotated[str, Field(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")]
RoomId = Annotated[str, Field(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
BindingId = Annotated[str, Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
AttachmentId = Annotated[str, Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")]
Reason = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1000,
        pattern=r"\S",
    ),
]


class QuestionStudent(WebModel):
    student_id: str = Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")
    student_display_revision_id: str = Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")
    room_mapping_revision_id: str = Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")
    display_name: Label


class QuestionManifestPointer(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    # Catalog owns pointer resolution; Web must not guess the publisher's filename.
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: Literal["eom://schemas/kakao-archive/question-manifest-v1/1.0"]
    media_type: Literal["application/json"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class StoredQuestion(WebModel):
    schema_version: Literal["kakao-stored-question/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    question_id: QuestionId
    question_revision_id: RevisionId
    previous_revision_id: RevisionId | None
    resource_version: ResourceVersion
    manifest: QuestionManifestPointer
    review_state: Literal["UNREVIEWED", "CONFIRMED", "EXCLUDED"]
    first_student_at_utc: UtcDatetime | None
    student: QuestionStudent | None
    created_at: UtcDatetime


class QuestionPage(WebModel):
    schema_version: Literal["kakao-question-page/1.0"]
    items: tuple[StoredQuestion, ...] = Field(max_length=100)
    next_cursor: QuestionId | None


class CandidateQuestionReference(WebModel):
    question_id: QuestionId
    question_revision_id: RevisionId


class CandidateSummary(WebModel):
    candidate_ordinal: int = Field(strict=True, ge=1, le=100000)
    student_message_count: int = Field(strict=True, ge=1, le=100000)
    reply_message_count: int = Field(strict=True, ge=0, le=100000)
    photo_count: int = Field(strict=True, ge=0, le=100000)
    first_student_at_utc: UtcDatetime | None
    preview: str = Field(max_length=240)
    boundary_uncertain: bool = Field(strict=True)
    review_reasons: tuple[str, ...] = Field(max_length=8)
    saved_question: CandidateQuestionReference | None
    recomposed: bool = Field(strict=True)


class QuestionCandidatePage(WebModel):
    schema_version: Literal["kakao-question-candidate-page/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    source_revision_id: str | None = Field(pattern=r"^kakaosourcerev_[0-9a-f]{32}$")
    source_resolution_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    mapping_revision_id: str = Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")
    total_candidates: int = Field(strict=True, ge=0, le=100000)
    unknown_sender_rows: int = Field(strict=True, ge=0, le=100000)
    items: tuple[CandidateSummary, ...] = Field(max_length=100)
    next_after_ordinal: int | None = Field(strict=True, ge=1, le=100000)


class QuestionCreate(WebModel):
    schema_version: Literal["kakao-question-create/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    source_revision_id: str = Field(pattern=r"^kakaosourcerev_[0-9a-f]{32}$")
    candidate_ordinal: int = Field(strict=True, ge=1, le=100000)
    expected_mapping_revision_id: str = Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")


class QuestionConfirm(WebModel):
    schema_version: Literal["kakao-question-edit/1.0"]
    action: Literal["CONFIRM"]
    parent_revision_id: RevisionId
    reason: Reason
    boundary_confirmed: bool = Field(strict=True)


class QuestionExclude(WebModel):
    schema_version: Literal["kakao-question-edit/1.0"]
    action: Literal["EXCLUDE"]
    parent_revision_id: RevisionId
    reason: Reason


QuestionReview = Annotated[QuestionConfirm | QuestionExclude, Field(discriminator="action")]


class QuestionMutation(WebModel):
    schema_version: Literal["kakao-question-mutation/1.0"]
    question: StoredQuestion
    replayed: bool = Field(strict=True)


class DisplayText(WebModel):
    kind: Literal["TEXT"]
    block_id: str = Field(min_length=1, max_length=128)
    role: Literal["student", "staff"]
    text: str = Field(min_length=1, max_length=20000)


class DisplayImage(WebModel):
    kind: Literal["IMAGE"]
    block_id: str = Field(min_length=1, max_length=128)
    role: Literal["student", "staff"]
    attachment_id: AttachmentId
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    availability: Literal["available", "expired", "denied", "not_found", "pending", "failed"]
    source_quality: Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"]


class QuestionView(WebModel):
    schema_version: Literal["kakao-question-view/1.0"]
    question: StoredQuestion
    ordered_blocks: tuple[
        Annotated[DisplayText | DisplayImage, Field(discriminator="kind")], ...
    ] = Field(min_length=1, max_length=230)
    review_reasons: tuple[str, ...] = Field(max_length=8)
    boundary_uncertain: bool = Field(strict=True)


class TextEditRange(WebModel):
    block_id: str = Field(min_length=1, max_length=128)
    can_split: bool = Field(strict=True)
    start_codepoint: int | None = Field(strict=True, ge=0, le=65535)
    end_codepoint: int | None = Field(strict=True, ge=1, le=65536)

    @model_validator(mode="after")
    def exact_span(self) -> "TextEditRange":
        if self.can_split:
            if (
                self.start_codepoint is None
                or self.end_codepoint is None
                or self.start_codepoint >= self.end_codepoint
            ):
                raise ValueError("invalid source range")
        elif self.start_codepoint is not None or self.end_codepoint is not None:
            raise ValueError("invalid unavailable range")
        return self


class QuestionEditContext(WebModel):
    schema_version: Literal["kakao-question-edit-context/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    question_id: QuestionId
    question_revision_id: RevisionId
    resource_version: ResourceVersion
    text_blocks: tuple[TextEditRange, ...] = Field(max_length=230)

    @model_validator(mode="after")
    def unique_blocks(self) -> "QuestionEditContext":
        if len({block.block_id for block in self.text_blocks}) != len(self.text_blocks):
            raise ValueError("duplicate text block")
        return self


class CompositionInput(WebModel):
    question_id: QuestionId
    question_revision_id: RevisionId
    resource_version: int = Field(strict=True, ge=1, le=2147483646)


class WholeBlockSelection(WebModel):
    kind: Literal["BLOCK"]
    block_id: str = Field(min_length=1, max_length=128)


class TextSpanSelection(WebModel):
    kind: Literal["TEXT_SPAN"]
    block_id: str = Field(min_length=1, max_length=128)
    start_codepoint: int = Field(strict=True, ge=0, le=65535)
    end_codepoint: int = Field(strict=True, ge=1, le=65536)

    @model_validator(mode="after")
    def nonempty(self) -> "TextSpanSelection":
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("invalid text span")
        return self


CompositionPartition = Annotated[
    tuple[Annotated[WholeBlockSelection | TextSpanSelection, Field(discriminator="kind")], ...],
    Field(min_length=1, max_length=230),
]


class QuestionSplit(WebModel):
    schema_version: Literal["kakao-question-compose/1.0"]
    operation: Literal["SPLIT"]
    source_binding_id: BindingId
    room_id: RoomId
    input: CompositionInput
    partitions: tuple[CompositionPartition, ...] = Field(min_length=2, max_length=100)


class QuestionMerge(WebModel):
    schema_version: Literal["kakao-question-compose/1.0"]
    operation: Literal["MERGE"]
    source_binding_id: BindingId
    room_id: RoomId
    inputs: tuple[CompositionInput, ...] = Field(min_length=2, max_length=100)


QuestionComposition = Annotated[QuestionSplit | QuestionMerge, Field(discriminator="operation")]


class QuestionCompositionResult(WebModel):
    schema_version: Literal["kakao-question-composition-result/1.0"]
    composition_id: str = Field(pattern=r"^kakaocomposition_[0-9a-f]{32}$")
    operation: Literal["SPLIT", "MERGE"]
    source_binding_id: BindingId
    room_id: RoomId
    inputs: tuple[CompositionInput, ...] = Field(min_length=1, max_length=100)
    outputs: tuple[StoredQuestion, ...] = Field(min_length=1, max_length=100)
    replayed: bool = Field(strict=True)

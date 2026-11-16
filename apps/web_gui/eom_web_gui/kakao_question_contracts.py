"""Small browser projections; source/revision integrity stays in Catalog."""

from typing import Annotated, Literal

from pydantic import Field

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

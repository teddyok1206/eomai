"""Role-preserving study PDF values; input provenance is authorized by the core owner."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from .render import (
    BindingId,
    ExportId,
    FrozenModel,
    LocalMember,
    PacketRevisionId,
    QuestionRevisionId,
    RenderBlockReference,
    RenderExecution,
    RenderImage,
    RenderText,
    Sha256,
    StudentId,
    subset_sha256,
    validate_render_content,
    validate_render_result_shape,
)
from .study_validation import validate_study_contract

StudyRevisionId = Annotated[str, Field(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")]
MessageOccurrenceId = Annotated[str, Field(pattern=r"^kakaomessage_[0-9a-f]{32}$")]


class StudySourceText(FrozenModel):
    source_occurrence_id: MessageOccurrenceId
    value: RenderText


class StudySourceImage(FrozenModel):
    source_occurrence_id: MessageOccurrenceId
    value: RenderImage


class StudySourceContent(FrozenModel):
    text_blocks: tuple[StudySourceText, ...] = Field(max_length=200)
    images: tuple[StudySourceImage, ...] = Field(max_length=30)
    ordered_blocks: tuple[RenderBlockReference, ...] = Field(min_length=1, max_length=230)

    @model_validator(mode="after")
    def closure(self) -> Self:
        validate_render_content(
            tuple(block.value for block in self.text_blocks),
            tuple(image.value for image in self.images),
            self.ordered_blocks,
        )
        return self


class StudyMessageMetadata(FrozenModel):
    source_occurrence_id: MessageOccurrenceId
    role: Literal["student", "staff"]
    kind: Literal["text", "attachment", "deleted", "system", "unknown"]
    raw_date: str = Field(min_length=1, max_length=64)
    source_timezone: Literal["Asia/Seoul", "unknown"]
    sent_at_utc: AwareDatetime | None

    @model_validator(mode="after")
    def time_evidence(self) -> Self:
        if self.source_timezone == "unknown":
            if self.sent_at_utc is not None:
                raise ValueError("KAKAO_STUDY_RENDER_TIME_UNVERIFIED")
        else:
            if self.sent_at_utc is None or self.sent_at_utc.utcoffset() != timedelta(0):
                raise ValueError("KAKAO_STUDY_RENDER_TIME_INVALID")
            try:
                local = datetime.strptime(self.raw_date, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("KAKAO_STUDY_RENDER_RAW_DATE_INVALID") from None
            if local.replace(tzinfo=ZoneInfo("Asia/Seoul")).astimezone(UTC) != self.sent_at_utc:
                raise ValueError("KAKAO_STUDY_RENDER_TIME_MISMATCH")
        return self


class StudyCitation(FrozenModel):
    """Display citation, not retrieval permission; core pins the real evidence revision."""

    evidence_id: str = Field(min_length=1, max_length=128)
    source_title: str = Field(min_length=1, max_length=256)
    page_label: str = Field(min_length=1, max_length=128)
    source_sha256: Sha256


class StudySupplement(FrozenModel):
    supplement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=128)
    origin: Literal["USER_NOTE", "SOURCE_EXCERPT", "MODEL_DRAFT"]
    text_blocks: tuple[RenderText, ...] = Field(max_length=200)
    images: tuple[RenderImage, ...] = Field(max_length=30)
    ordered_blocks: tuple[RenderBlockReference, ...] = Field(min_length=1, max_length=230)
    citations: tuple[StudyCitation, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def content_and_citations(self) -> Self:
        validate_render_content(self.text_blocks, self.images, self.ordered_blocks)
        if self.origin == "SOURCE_EXCERPT" and not self.citations:
            raise ValueError("KAKAO_STUDY_RENDER_CITATION_REQUIRED")
        keys = {(value.evidence_id, value.page_label) for value in self.citations}
        if len(keys) != len(self.citations):
            raise ValueError("KAKAO_STUDY_RENDER_CITATION_DUPLICATED")
        return self


class StudyQuestion(FrozenModel):
    question_revision_id: QuestionRevisionId
    header_date: date | None
    student: StudySourceContent
    staff: StudySourceContent | None
    messages: tuple[StudyMessageMetadata, ...] = Field(min_length=1, max_length=230)
    supplements: tuple[StudySupplement, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def selected_occurrences(self) -> Self:
        roles: dict[str, str] = {}
        blocks = 0
        block_keys: set[tuple[str, str]] = set()
        for role, content in (("student", self.student), ("staff", self.staff)):
            if content is None:
                continue
            blocks += len(content.ordered_blocks)
            block_keys.update(("TEXT", use.value.span_id) for use in content.text_blocks)
            block_keys.update(
                ("IMAGE", use.value.attachment_occurrence_id) for use in content.images
            )
            occurrences = (
                *(use.source_occurrence_id for use in content.text_blocks),
                *(use.source_occurrence_id for use in content.images),
            )
            for occurrence in occurrences:
                if roles.setdefault(occurrence, role) != role:
                    raise ValueError("KAKAO_STUDY_RENDER_ROLE_MISMATCH")
        metadata = {value.source_occurrence_id: value for value in self.messages}
        if (
            blocks > 230
            or len(block_keys) != blocks
            or len(metadata) != len(self.messages)
            or set(metadata) != roles.keys()
            or any(metadata[key].role != role for key, role in roles.items())
        ):
            raise ValueError("KAKAO_STUDY_RENDER_MESSAGE_SET_MISMATCH")
        student_times = [value.sent_at_utc for value in self.messages if value.role == "student"]
        known = [value for value in student_times if value is not None]
        expected_date = (
            min(known).astimezone(ZoneInfo("Asia/Seoul")).date()
            if len(known) == len(student_times)
            else None
        )
        if self.header_date != expected_date:
            raise ValueError("KAKAO_STUDY_RENDER_HEADER_DATE_MISMATCH")
        if len({value.supplement_id for value in self.supplements}) != len(self.supplements):
            raise ValueError("KAKAO_STUDY_RENDER_SUPPLEMENT_DUPLICATED")
        return self


class StudyRenderManifest(FrozenModel):
    schema_version: Literal["kakao-study-render-manifest/1.0"]
    source_binding_id: BindingId
    packet_revision_id: PacketRevisionId
    study_revision_id: StudyRevisionId | None
    student_id: StudentId
    student_display_name: str = Field(min_length=1, max_length=128)
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    questions: tuple[StudyQuestion, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def pinned_subset(self) -> Self:
        revisions = tuple(value.question_revision_id for value in self.questions)
        if len(set(revisions)) != len(revisions) or subset_sha256(revisions) != self.subset_sha256:
            raise ValueError("KAKAO_STUDY_RENDER_SUBSET_INVALID")
        if self.study_revision_id is None and any(value.supplements for value in self.questions):
            raise ValueError("KAKAO_STUDY_RENDER_STUDY_REVISION_REQUIRED")
        if self.mode == "FINAL" and any(
            question.header_date is None
            or any(value.sent_at_utc is None for value in question.messages)
            for question in self.questions
        ):
            raise ValueError("KAKAO_STUDY_RENDER_DATE_UNVERIFIED")
        total = 0
        for question in self.questions:
            for content in (question.student, question.staff):
                if content is not None:
                    total += sum(len(block.value.text) for block in content.text_blocks)
            total += sum(
                len(block.text) for value in question.supplements for block in value.text_blocks
            )
        if total > 4_000_000:
            raise ValueError("KAKAO_STUDY_RENDER_TEXT_BUDGET_EXCEEDED")
        validate_study_contract("manifest", self.model_dump(mode="json"))
        return self


class StudyRenderCommand(FrozenModel):
    execution: RenderExecution
    schema_version: Literal["kakao-study-render/1.0"]
    export_id: ExportId
    source_binding_id: BindingId
    packet_revision_id: PacketRevisionId
    study_revision_id: StudyRevisionId | None
    student_id: StudentId
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    renderer_release_sha256: Sha256
    layout_policy: Literal["student-study-a4/1.0"]
    manifest: LocalMember
    font: LocalMember

    @model_validator(mode="after")
    def local_input_types(self) -> Self:
        if self.manifest.media_type != "application/json" or self.font.media_type not in {
            "font/otf",
            "font/ttf",
        }:
            raise ValueError("KAKAO_STUDY_RENDER_MEMBER_TYPE_INVALID")
        validate_study_contract("command", self.model_dump(mode="json"))
        return self


class StudyRenderResult(FrozenModel):
    execution: RenderExecution
    schema_version: Literal["kakao-study-render-result/1.0"]
    export_id: ExportId
    command_sha256: Sha256
    manifest_sha256: Sha256
    status: Literal["COMPLETED", "NEEDS_LAYOUT_REVIEW", "INVALID_INPUT"]
    page_count: int = Field(ge=0, le=200, strict=True)
    outputs: tuple[LocalMember, ...] = Field(max_length=202)
    error_code: str | None = Field(max_length=80)
    question_revision_id: QuestionRevisionId | None

    @model_validator(mode="after")
    def terminal_shape(self) -> Self:
        validate_render_result_shape(
            self.status, self.page_count, self.outputs, self.error_code, self.question_revision_id
        )
        validate_study_contract("result", self.model_dump(mode="json"))
        return self


def study_input_members(
    command: StudyRenderCommand, manifest: StudyRenderManifest
) -> tuple[LocalMember, ...]:
    for field in (
        "source_binding_id",
        "packet_revision_id",
        "study_revision_id",
        "student_id",
        "subset_sha256",
        "mode",
    ):
        if getattr(command, field) != getattr(manifest, field):
            raise ValueError("KAKAO_STUDY_RENDER_MANIFEST_IDENTITY_MISMATCH")
    members = {command.manifest.relative_path: command.manifest}

    def add(member: LocalMember) -> None:
        if members.setdefault(member.relative_path, member) != member:
            raise ValueError("KAKAO_STUDY_RENDER_MEMBER_COLLISION")

    add(command.font)
    for question in manifest.questions:
        for content in (question.student, question.staff):
            if content is not None:
                for image in content.images:
                    if image.value.member is not None:
                        add(image.value.member)
        for supplement in question.supplements:
            for illustration in supplement.images:
                if illustration.member is not None:
                    add(illustration.member)
    if sum(member.size_bytes for member in members.values()) > 256 * 1024 * 1024:
        raise ValueError("KAKAO_STUDY_RENDER_INPUT_BYTES_EXCEEDED")
    return tuple(members.values())

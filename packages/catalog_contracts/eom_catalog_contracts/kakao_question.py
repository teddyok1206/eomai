"""Immutable private question selections and packets; source text stays in its Artifact."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import (
    AssociationLevel,
    KakaoBindingId,
    KakaoNormalizationRevisionId,
    KakaoRoomId,
    KakaoSnapshotRevisionId,
    ReviewReason,
    RowOrdinal,
    validate_kakao_display_name,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime, _safe_text
from eom_catalog_contracts.validation import validate_contract

QuestionId = Annotated[str, Field(pattern=r"^kakaoquestion_[0-9a-f]{32}$")]
QuestionRevisionId = Annotated[str, Field(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")]
StudentId = Annotated[str, Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
OperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
BlockId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]
NORMALIZATION_REF = "eom://schemas/kakao-archive/message-normalization-v1/1.0"
QUESTION_REF = "eom://schemas/kakao-archive/question-manifest-v1/1.0"
FinalBlocker = Literal[
    "NOT_REVIEWED",
    "EXCLUDED",
    "STUDENT_UNMAPPED",
    "TIMEZONE_UNVERIFIED",
    "BOUNDARY_UNCONFIRMED",
    "STALE_SOURCE",
    "MISSING_ATTACHMENT",
    "ATTACHMENT_UNRESOLVED",
    "IMAGE_QUALITY_UNCONFIRMED",
    "PHOTO_MARKER_UNVERIFIED",
    "SOURCE_DELETION",
]


def question_period_utc(start_date: date, end_date_inclusive: date) -> tuple[datetime, datetime]:
    """KST inclusive calendar dates become UTC [start, next midnight)."""
    if end_date_inclusive < start_date or end_date_inclusive == date.max:
        raise ValueError("KAKAO_ARCHIVE_PERIOD_INVALID")
    zone = ZoneInfo("Asia/Seoul")
    try:
        start = datetime.combine(start_date, time.min, zone).astimezone(UTC)
        end = datetime.combine(end_date_inclusive + timedelta(days=1), time.min, zone).astimezone(
            UTC
        )
    except (OverflowError, ValueError):
        raise ValueError("KAKAO_ARCHIVE_PERIOD_INVALID") from None
    return start, end


def _meaningful(value: str) -> str:
    _safe_text(value)
    if not value.strip():
        raise ValueError("KAKAO_ARCHIVE_EMPTY_TEXT")
    return value


class KakaoQuestionStudentPin(FrozenModel):
    student_id: StudentId
    student_display_revision_id: str = Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")
    room_mapping_revision_id: str = Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=128)

    _name = field_validator("display_name")(validate_kakao_display_name)


class KakaoNormalizationRef(FrozenModel):
    normalization_revision_id: KakaoNormalizationRevisionId
    snapshot_revision_id: KakaoSnapshotRevisionId
    pointer: ArtifactMemberPointer

    @model_validator(mode="after")
    def normalization_member(self) -> Self:
        if (
            self.pointer.schema_ref != NORMALIZATION_REF
            or self.pointer.media_type != "application/json"
        ):
            raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_POINTER_INVALID")
        return self


class KakaoDisplayOverride(FrozenModel):
    text: str = Field(min_length=1, max_length=20000)
    reason: Reason

    _text = field_validator("text", "reason")(_meaningful)


class KakaoImageCrop(FrozenModel):
    """Exact millionths of the EXIF-oriented, explicitly rotated image; no float ambiguity."""

    left_ppm: int = Field(strict=True, ge=0, le=1000000)
    top_ppm: int = Field(strict=True, ge=0, le=1000000)
    right_ppm: int = Field(strict=True, ge=0, le=1000000)
    bottom_ppm: int = Field(strict=True, ge=0, le=1000000)

    @model_validator(mode="after")
    def positive_area(self) -> Self:
        if self.left_ppm >= self.right_ppm or self.top_ppm >= self.bottom_ppm:
            raise ValueError("KAKAO_ARCHIVE_IMAGE_CROP_INVALID")
        return self


class KakaoImageTransform(FrozenModel):
    transform_revision_id: str = Field(pattern=r"^kakaotransformrev_[0-9a-f]{32}$")
    operation_order: Literal["EXIF_THEN_ROTATE_THEN_CROP"] = "EXIF_THEN_ROTATE_THEN_CROP"
    rotate_clockwise: Literal[0, 90, 180, 270]
    crop: KakaoImageCrop | None
    reason: Reason

    _reason = field_validator("reason")(_meaningful)

    @field_validator("rotate_clockwise", mode="before")
    @classmethod
    def integer_rotation(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("KAKAO_ARCHIVE_IMAGE_ROTATION_INVALID")
        return value


class KakaoImageQualityAcceptance(FrozenModel):
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    source_sha256: Sha256
    accepted_by: OperatorId
    accepted_at: UtcDatetime
    reason: Reason

    _reason = field_validator("reason")(_meaningful)


class _SourceBlock(FrozenModel):
    block_id: BlockId
    source_occurrence_id: str = Field(pattern=r"^kakaomessage_[0-9a-f]{32}$")
    normalization_revision_id: KakaoNormalizationRevisionId
    row_ordinal: RowOrdinal
    role: Literal["student", "staff"]
    sent_at_utc: UtcDatetime | None


class KakaoQuestionText(_SourceBlock):
    kind: Literal["TEXT"] = "TEXT"
    source_text_sha256: Sha256
    start_codepoint: int = Field(strict=True, ge=0, le=65536)
    end_codepoint: int = Field(strict=True, ge=1, le=65536)
    display_override: KakaoDisplayOverride | None = None

    @model_validator(mode="after")
    def nonempty_span(self) -> Self:
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
        return self


class KakaoQuestionImage(_SourceBlock):
    kind: Literal["IMAGE"] = "IMAGE"
    attachment_id: str = Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    availability: Literal["available", "expired", "denied", "not_found", "pending", "failed"]
    association: AssociationLevel
    source_pointer: ArtifactMemberPointer | None
    source_quality: Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"] = "UNKNOWN"
    quality_acceptance: KakaoImageQualityAcceptance | None = None
    transform: KakaoImageTransform | None = None

    @model_validator(mode="after")
    def exact_image(self) -> Self:
        if (self.availability == "available") != (self.source_pointer is not None):
            raise ValueError("KAKAO_ARCHIVE_IMAGE_POINTER_INVALID")
        if self.source_pointer is None:
            if self.source_quality != "UNKNOWN" or self.quality_acceptance or self.transform:
                raise ValueError("KAKAO_ARCHIVE_IMAGE_UNAVAILABLE")
        elif self.source_pointer.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("KAKAO_ARCHIVE_IMAGE_MEDIA_INVALID")
        if self.quality_acceptance is not None and (
            self.source_quality != "BEST_AVAILABLE"
            or self.quality_acceptance.attachment_revision_id != self.attachment_revision_id
            or self.source_pointer is None
            or self.quality_acceptance.source_sha256 != self.source_pointer.sha256
        ):
            raise ValueError("KAKAO_ARCHIVE_IMAGE_QUALITY_PIN_INVALID")
        return self


KakaoQuestionBlock = Annotated[KakaoQuestionText | KakaoQuestionImage, Field(discriminator="kind")]


class KakaoQuestionReviewDecision(FrozenModel):
    actor_id: OperatorId
    decided_at: UtcDatetime
    reason: Reason
    boundary_confirmed: bool = Field(strict=True)

    _reason = field_validator("reason")(_meaningful)


class KakaoQuestionProvenance(FrozenModel):
    question_id: QuestionId
    question_revision_id: QuestionRevisionId


class KakaoSelectionExclusion(FrozenModel):
    block_id: BlockId
    reason: Reason

    _reason = field_validator("reason")(_meaningful)


class KakaoQuestionManifest(FrozenModel):
    schema_version: Literal["kakao-question-manifest/1.0"] = "kakao-question-manifest/1.0"
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    previous_revision_id: QuestionRevisionId | None
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    student: KakaoQuestionStudentPin | None
    sources: tuple[KakaoNormalizationRef, ...] = Field(min_length=1, max_length=100)
    ordered_blocks: tuple[KakaoQuestionBlock, ...] = Field(min_length=1, max_length=230)
    first_student_at_utc: UtcDatetime | None
    review_state: Literal["UNREVIEWED", "CONFIRMED", "EXCLUDED"] = "UNREVIEWED"
    review_decision: KakaoQuestionReviewDecision | None = None
    review_reasons: tuple[ReviewReason, ...] = Field(max_length=8)
    boundary_uncertain: bool = Field(strict=True)
    source_stale: bool = Field(default=False, strict=True)
    provenance: tuple[KakaoQuestionProvenance, ...] = Field(default=(), max_length=100)
    selection_exclusions: tuple[KakaoSelectionExclusion, ...] = Field(default=(), max_length=230)
    rule_revision: Literal["turn_v1"] = "turn_v1"
    created_by: OperatorId
    created_at: UtcDatetime

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if self.previous_revision_id == self.question_revision_id:
            raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
        if (self.review_state == "UNREVIEWED") != (self.review_decision is None):
            raise ValueError("KAKAO_ARCHIVE_REVIEW_DECISION_INVALID")
        if self.review_decision and (
            self.review_decision.decided_at != self.created_at
            or self.review_decision.actor_id != self.created_by
        ):
            raise ValueError("KAKAO_ARCHIVE_REVIEW_DECISION_INVALID")
        source_ids = {source.normalization_revision_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_DUPLICATED")
        ids = [block.block_id for block in self.ordered_blocks]
        if len(set(ids)) != len(ids):
            raise ValueError("KAKAO_ARCHIVE_BLOCK_DUPLICATED")
        images = [
            block.attachment_id
            for block in self.ordered_blocks
            if isinstance(block, KakaoQuestionImage)
        ]
        if len(set(images)) != len(images):
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_DUPLICATED")
        if any(block.normalization_revision_id not in source_ids for block in self.ordered_blocks):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
        student_times = [
            block.sent_at_utc for block in self.ordered_blocks if block.role == "student"
        ]
        if not student_times:
            raise ValueError("KAKAO_ARCHIVE_STUDENT_SELECTION_EMPTY")
        expected_time = (
            min(value for value in student_times if value is not None)
            if all(value is not None for value in student_times)
            else None
        )
        if self.first_student_at_utc != expected_time:
            raise ValueError("KAKAO_ARCHIVE_QUESTION_TIME_INVALID")
        provenance_ids = [(item.question_id, item.question_revision_id) for item in self.provenance]
        if len(set(provenance_ids)) != len(provenance_ids):
            raise ValueError("KAKAO_ARCHIVE_PROVENANCE_DUPLICATED")
        excluded = [entry.block_id for entry in self.selection_exclusions]
        if len(set(excluded)) != len(excluded) or set(excluded).intersection(ids):
            raise ValueError("KAKAO_ARCHIVE_EXCLUSIONS_INVALID")
        validate_contract("kakao-question-manifest-v1", self.model_dump(mode="json"))
        return self


class KakaoQuestionConfirm(FrozenModel):
    schema_version: Literal["kakao-question-edit/1.0"] = "kakao-question-edit/1.0"
    action: Literal["CONFIRM"] = "CONFIRM"
    parent_revision_id: QuestionRevisionId
    reason: Reason
    boundary_confirmed: bool = Field(strict=True)

    _reason = field_validator("reason")(_meaningful)


class KakaoQuestionExclude(FrozenModel):
    schema_version: Literal["kakao-question-edit/1.0"] = "kakao-question-edit/1.0"
    action: Literal["EXCLUDE"] = "EXCLUDE"
    parent_revision_id: QuestionRevisionId
    reason: Reason

    _reason = field_validator("reason")(_meaningful)


class KakaoQuestionEdit(FrozenModel):
    schema_version: Literal["kakao-question-edit/1.0"] = "kakao-question-edit/1.0"
    action: Literal["EDIT"] = "EDIT"
    parent_revision_id: QuestionRevisionId
    student: KakaoQuestionStudentPin | None
    ordered_blocks: tuple[KakaoQuestionBlock, ...] = Field(min_length=1, max_length=230)
    selection_exclusions: tuple[KakaoSelectionExclusion, ...] = Field(max_length=230)


KakaoQuestionEditCommand = Annotated[
    KakaoQuestionConfirm | KakaoQuestionExclude | KakaoQuestionEdit, Field(discriminator="action")
]


class KakaoPacketQuestion(FrozenModel):
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    room_id: KakaoRoomId
    student: KakaoQuestionStudentPin
    manifest: ArtifactMemberPointer
    first_student_at_utc: UtcDatetime | None
    final_blockers: tuple[FinalBlocker, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def question_pointer(self) -> Self:
        if (
            self.manifest.schema_ref != QUESTION_REF
            or self.manifest.media_type != "application/json"
        ):
            raise ValueError("KAKAO_ARCHIVE_QUESTION_POINTER_INVALID")
        return self


class KakaoQuestionPacket(FrozenModel):
    schema_version: Literal["kakao-question-packet/1.0"] = "kakao-question-packet/1.0"
    packet_id: str = Field(pattern=r"^kakaopacket_[0-9a-f]{32}$")
    packet_revision_id: str = Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")
    previous_revision_id: str | None = Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")
    source_binding_id: KakaoBindingId
    mode: Literal["DRAFT", "FINAL"]
    include_replies: bool = Field(strict=True)
    display_start_date: date
    display_end_date_inclusive: date
    range_start_utc: UtcDatetime
    range_end_utc_exclusive: UtcDatetime
    question_selection_policy: Literal["first-student-message/1.0"] = "first-student-message/1.0"
    collection_coverage: Literal["UNKNOWN", "PARTIAL", "COMPLETE"] = "UNKNOWN"
    questions: tuple[KakaoPacketQuestion, ...] = Field(min_length=1, max_length=200)
    created_by: OperatorId
    created_at: UtcDatetime

    @model_validator(mode="after")
    def immutable_members(self) -> Self:
        if self.previous_revision_id == self.packet_revision_id:
            raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
        if (self.range_start_utc, self.range_end_utc_exclusive) != question_period_utc(
            self.display_start_date, self.display_end_date_inclusive
        ):
            raise ValueError("KAKAO_ARCHIVE_PERIOD_INVALID")
        ids = [question.question_id for question in self.questions]
        revisions = [question.question_revision_id for question in self.questions]
        if len(set(ids)) != len(ids) or len(set(revisions)) != len(revisions):
            raise ValueError("KAKAO_ARCHIVE_PACKET_QUESTION_DUPLICATED")
        displays: dict[str, tuple[str, str]] = {}
        for question in self.questions:
            display = (question.student.student_display_revision_id, question.student.display_name)
            if displays.setdefault(question.student.student_id, display) != display:
                raise ValueError("KAKAO_ARCHIVE_STUDENT_DISPLAY_CONFLICT")
            if self.mode == "FINAL" and question.final_blockers:
                raise ValueError("KAKAO_ARCHIVE_FINAL_BLOCKED")
            if question.first_student_at_utc is not None and not (
                self.range_start_utc <= question.first_student_at_utc < self.range_end_utc_exclusive
            ):
                raise ValueError("KAKAO_ARCHIVE_QUESTION_OUTSIDE_PERIOD")
        validate_contract("kakao-question-packet-v1", self.model_dump(mode="json"))
        return self


class KakaoPacketStudentSubset(FrozenModel):
    packet_revision_id: str = Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")
    student_id: StudentId
    student_display_revision_id: str = Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=128)
    questions: tuple[KakaoPacketQuestion, ...] = Field(min_length=1, max_length=200)
    subset_sha256: Sha256

    _name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def exact_student_subset(self) -> Self:
        expected = (self.student_id, self.student_display_revision_id, self.display_name)
        ids = {entry.question_id for entry in self.questions}
        revisions = tuple(entry.question_revision_id for entry in self.questions)
        if len(ids) != len(self.questions) or len(set(revisions)) != len(revisions):
            raise ValueError("KAKAO_ARCHIVE_PACKET_QUESTION_DUPLICATED")
        if any(
            (
                entry.student.student_id,
                entry.student.student_display_revision_id,
                entry.student.display_name,
            )
            != expected
            for entry in self.questions
        ):
            raise ValueError("KAKAO_ARCHIVE_STUDENT_SUBSET_MISMATCH")
        if self.subset_sha256 != sha256_bytes(canonical_json_bytes(revisions)):
            raise ValueError("KAKAO_ARCHIVE_STUDENT_SUBSET_HASH_MISMATCH")
        return self

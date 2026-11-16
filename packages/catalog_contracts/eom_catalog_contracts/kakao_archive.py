"""Private source observations and unreviewed question candidates, never Item content.

Normalization is a bounded Artifact payload, not a DB row or an execution grant.
Snapshot row ordinals preserve repeated messages; an owner resolves identities and ACLs.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime, _safe_text
from eom_catalog_contracts.validation import validate_contract

KakaoBindingId = Annotated[str, Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
KakaoRoomId = Annotated[str, Field(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
KakaoSnapshotRevisionId = Annotated[str, Field(pattern=r"^kakaosnapshotrev_[0-9a-f]{32}$")]
KakaoNormalizationRevisionId = Annotated[
    str, Field(pattern=r"^kakaonormalizationrev_[0-9a-f]{32}$")
]
RowOrdinal = Annotated[int, Field(strict=True, ge=1, le=100000)]
MessageRole = Literal["student", "staff", "system", "unknown"]
MessageKind = Literal["text", "attachment", "deleted", "system", "unknown"]
SourceTimezone = Literal["Asia/Seoul", "unknown"]
SourceOrder = Literal["ascending", "descending", "unknown"]
AssociationLevel = Literal[
    "SOURCE_VERIFIED", "SEQUENCE_INFERRED", "SNAPSHOT_ONLY", "MANUAL_CONFIRMED", "UNRESOLVED"
]
ReviewReason = Literal[
    "UNKNOWN_SENDER",
    "TIMEZONE_UNVERIFIED",
    "SOURCE_SCOPE_UNVERIFIED",
    "ATTACHMENT_UNAVAILABLE",
    "ATTACHMENT_ASSOCIATION_UNRESOLVED",
    "PHOTO_MARKER_UNVERIFIED",
    "SOURCE_DELETION",
]
BoundedText = Annotated[str, Field(max_length=65536)]


def validate_kakao_display_name(value: str) -> str:
    """Display metadata is nonblank, control-free, and never normalized into identity."""
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("KAKAO_ARCHIVE_DISPLAY_NAME_INVALID")
    return value


class KakaoAttachmentObservation(FrozenModel):
    attachment_id: str = Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    album_ordinal: int = Field(strict=True, ge=1, le=1000)
    availability: Literal["available", "expired", "denied", "not_found", "pending", "failed"]
    association: AssociationLevel


class KakaoMessageObservation(FrozenModel):
    """Evidence supplied by the capture owner for one exact snapshot row."""

    row_ordinal: RowOrdinal
    role: MessageRole = "unknown"
    role_evidence_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=256)
    kind: MessageKind = "unknown"
    attachments: tuple[KakaoAttachmentObservation, ...] = Field(default=(), max_length=1000)

    @field_validator("role_evidence_id", "source_message_id")
    @classmethod
    def safe_evidence(cls, value: str | None) -> str | None:
        return _safe_text(value) if value is not None else None

    @model_validator(mode="after")
    def explicit_evidence(self) -> Self:
        if (self.role == "unknown") != (self.role_evidence_id is None):
            raise ValueError("KAKAO_ARCHIVE_ROLE_EVIDENCE_INVALID")
        if len({a.attachment_id for a in self.attachments}) != len(self.attachments):
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_DUPLICATED")
        ordinals = tuple(a.album_ordinal for a in self.attachments)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("KAKAO_ARCHIVE_ALBUM_ORDER_INVALID")
        return self


class KakaoNormalizedMessage(KakaoMessageObservation):
    raw_date: str = Field(max_length=64)
    raw_sender: str = Field(max_length=512)
    text: BoundedText
    extra_values: tuple[BoundedText, ...] = Field(max_length=32)
    sent_at_utc: UtcDatetime | None

    _safe = field_validator("raw_date", "raw_sender", "text")(_safe_text)


class KakaoMessageNormalization(FrozenModel):
    schema_version: Literal["kakao-message-normalization/1.0"] = "kakao-message-normalization/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    snapshot_revision_id: KakaoSnapshotRevisionId
    normalization_revision_id: KakaoNormalizationRevisionId
    source_sha256: Sha256
    source_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    observed_at_utc: UtcDatetime
    parser_revision: Literal["kakao-csv/1.0"] = "kakao-csv/1.0"
    source_timezone: SourceTimezone
    source_order: SourceOrder
    context_start_verified: bool = Field(strict=True)
    context_end_verified: bool = Field(strict=True)
    columns: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = Field(max_length=35)
    messages: tuple[KakaoNormalizedMessage, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def exact_rows(self) -> Self:
        validate_contract("kakao-message-normalization-v1", self.model_dump(mode="json"))
        if len(set(self.columns)) != len(self.columns) or not {"DATE", "USER", "MESSAGE"}.issubset(
            self.columns
        ):
            raise ValueError("KAKAO_ARCHIVE_CSV_COLUMNS_INVALID")
        if tuple(m.row_ordinal for m in self.messages) != tuple(range(1, len(self.messages) + 1)):
            raise ValueError("KAKAO_ARCHIVE_ROW_ORDER_INVALID")
        source_ids: set[str] = set()
        attachment_ids: set[str] = set()
        for message in self.messages:
            if len(message.extra_values) != len(self.columns) - 3:
                raise ValueError("KAKAO_ARCHIVE_EXTRA_COLUMNS_INVALID")
            for value in message.extra_values:
                _safe_text(value)
            if (message.sent_at_utc is None) != (self.source_timezone == "unknown"):
                raise ValueError("KAKAO_ARCHIVE_TIMEZONE_INVALID")
            if message.source_message_id is not None:
                if message.source_message_id in source_ids:
                    raise ValueError("KAKAO_ARCHIVE_SOURCE_MESSAGE_DUPLICATED")
                source_ids.add(message.source_message_id)
            for attachment in message.attachments:
                if attachment.attachment_id in attachment_ids:
                    raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_DUPLICATED")
                attachment_ids.add(attachment.attachment_id)
        return self


class KakaoQuestionCandidate(FrozenModel):
    candidate_ordinal: RowOrdinal
    student_rows: tuple[RowOrdinal, ...] = Field(min_length=1, max_length=100000)
    reply_rows: tuple[RowOrdinal, ...] = Field(max_length=100000)
    attachments: tuple[KakaoAttachmentObservation, ...] = Field(max_length=1000)
    first_student_at_utc: UtcDatetime | None
    boundary_uncertain: bool = Field(strict=True)
    review_reasons: tuple[ReviewReason, ...] = Field(max_length=8)
    reviewed: Literal[False] = False


class KakaoQuestionCandidates(FrozenModel):
    schema_version: Literal["kakao-question-candidates/1.0"] = "kakao-question-candidates/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    normalization_revision_id: KakaoNormalizationRevisionId
    rule_revision: Literal["turn_v1"] = "turn_v1"
    candidates: tuple[KakaoQuestionCandidate, ...] = Field(max_length=100000)
    unresolved_rows: tuple[RowOrdinal, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def unique_members(self) -> Self:
        validate_contract("kakao-question-candidates-v1", self.model_dump(mode="json"))
        rows: set[int] = set()
        for ordinal, candidate in enumerate(self.candidates, 1):
            members = (*candidate.student_rows, *candidate.reply_rows)
            if candidate.candidate_ordinal != ordinal or rows.intersection(members):
                raise ValueError("KAKAO_ARCHIVE_CANDIDATE_ROWS_INVALID")
            if len(set(members)) != len(members):
                raise ValueError("KAKAO_ARCHIVE_CANDIDATE_ROWS_INVALID")
            rows.update(members)
        if rows.intersection(self.unresolved_rows):
            raise ValueError("KAKAO_ARCHIVE_UNRESOLVED_ROWS_INVALID")
        return self

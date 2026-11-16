"""Small packet commands and exact immutable revision descriptors."""

from datetime import date
from typing import Annotated, Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId, validate_kakao_display_name
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance, question_period_utc
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

PacketId = Annotated[str, Field(pattern=r"^kakaopacket_[0-9a-f]{32}$")]
PacketRevisionId = Annotated[str, Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")]
PACKET_REF = "eom://schemas/kakao-archive/question-packet-v1/1.0"


class _Selection(FrozenModel):
    source_binding_id: KakaoBindingId
    title: str = Field(min_length=1, max_length=128)
    questions: tuple[KakaoQuestionProvenance, ...] = Field(min_length=1, max_length=200)
    display_start_date: date
    display_end_date_inclusive: date
    mode: Literal["DRAFT", "FINAL"]
    include_replies: bool = Field(strict=True)

    _title = field_validator("title")(validate_kakao_display_name)

    @model_validator(mode="after")
    def selection(self) -> Self:
        question_period_utc(self.display_start_date, self.display_end_date_inclusive)
        if len({pin.question_id for pin in self.questions}) != len(self.questions):
            raise ValueError("KAKAO_ARCHIVE_PACKET_QUESTION_DUPLICATED")
        validate_contract("kakao-packet-store-v1", self.model_dump(mode="json"))
        return self


class KakaoPacketCreate(_Selection):
    schema_version: Literal["kakao-packet-create/1.0"] = "kakao-packet-create/1.0"


class KakaoPacketRevise(_Selection):
    schema_version: Literal["kakao-packet-revise/1.0"] = "kakao-packet-revise/1.0"
    packet_id: PacketId
    parent_revision_id: PacketRevisionId
    expected_resource_version: int = Field(strict=True, ge=1, le=2147483646)


KakaoPacketCommand = KakaoPacketCreate | KakaoPacketRevise


class KakaoStoredPacket(FrozenModel):
    schema_version: Literal["kakao-stored-packet/1.0"] = "kakao-stored-packet/1.0"
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    previous_revision_id: PacketRevisionId | None
    resource_version: int = Field(strict=True, ge=1, le=2147483647)
    title: str = Field(min_length=1, max_length=128)
    manifest: ArtifactMemberPointer
    display_start_date: date
    display_end_date_inclusive: date
    mode: Literal["DRAFT", "FINAL"]
    include_replies: bool = Field(strict=True)
    question_count: int = Field(strict=True, ge=1, le=200)
    student_count: int = Field(strict=True, ge=1, le=200)
    created_at: UtcDatetime

    _title = field_validator("title")(validate_kakao_display_name)

    @model_validator(mode="after")
    def exact_revision(self) -> Self:
        validate_contract("kakao-packet-store-v1", self.model_dump(mode="json"))
        question_period_utc(self.display_start_date, self.display_end_date_inclusive)
        if (
            self.manifest.schema_ref != PACKET_REF
            or self.manifest.media_type != "application/json"
            or (self.resource_version == 1) != (self.previous_revision_id is None)
            or self.previous_revision_id == self.packet_revision_id
            or self.student_count > self.question_count
        ):
            raise ValueError("KAKAO_ARCHIVE_STORED_PACKET_INVALID")
        return self


class KakaoPacketMutation(FrozenModel):
    schema_version: Literal["kakao-packet-mutation/1.0"] = "kakao-packet-mutation/1.0"
    packet: KakaoStoredPacket
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-packet-store-v1", self.model_dump(mode="json"))
        return self


class KakaoPacketPage(FrozenModel):
    schema_version: Literal["kakao-packet-page/1.0"] = "kakao-packet-page/1.0"
    items: tuple[KakaoStoredPacket, ...] = Field(max_length=100)
    next_cursor: PacketId | None

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        validate_contract("kakao-packet-store-v1", self.model_dump(mode="json"))
        ids = tuple(item.packet_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_ARCHIVE_PACKET_PAGE_INVALID")
        return self

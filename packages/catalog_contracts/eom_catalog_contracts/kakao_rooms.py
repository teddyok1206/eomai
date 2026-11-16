"""Private admitted room identity and exact immutable room-to-student mapping."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import (
    KakaoBindingId,
    KakaoRoomId,
    validate_kakao_display_name,
)
from eom_catalog_contracts.kakao_archive_binding import KakaoResourceVersion
from eom_catalog_contracts.kakao_students import KakaoStudentId, KakaoStudentRevisionId
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime, _safe_text
from eom_catalog_contracts.validation import validate_contract

ROOM_OBSERVATION_REF = "eom://schemas/kakao-archive/room-directory-v1/1.0"
KakaoMappingRevisionId = Annotated[str, Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")]
IdentityLevel = Literal["SOURCE_VERIFIED", "MANUAL_CONFIRMED"]
MappingState = Literal["MAPPED", "UNMAPPED"]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]


def _reason(value: str) -> str:
    _safe_text(value)
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("KAKAO_ARCHIVE_MAPPING_REASON_INVALID")
    return value


def room_mapping_sha256(
    *, student_id: str | None, student_display_revision_id: str | None, reason: str
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "student_id": student_id,
                "student_display_revision_id": student_display_revision_id,
                "reason": reason,
            }
        )
    )


class KakaoRoomObservation(FrozenModel):
    """Internal evidence value; constructing it does not grant source admission authority."""

    schema_version: Literal["kakao-room-observation/1.0"] = "kakao-room-observation/1.0"
    source_binding_id: KakaoBindingId
    proposed_room_id: KakaoRoomId | None
    identity_level: IdentityLevel
    source_identity_sha256: Sha256
    display_name: str = Field(min_length=1, max_length=128)
    observed_at: UtcDatetime
    source_evidence: ArtifactMemberPointer

    _name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoRoomMap(FrozenModel):
    schema_version: Literal["kakao-room-mapping-command/1.0"] = "kakao-room-mapping-command/1.0"
    action: Literal["MAP_STUDENT"] = "MAP_STUDENT"
    parent_revision_id: KakaoMappingRevisionId
    expected_resource_version: KakaoResourceVersion
    student_id: KakaoStudentId
    student_display_revision_id: KakaoStudentRevisionId
    reason: Reason

    _reason = field_validator("reason")(_reason)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoRoomUnmap(FrozenModel):
    schema_version: Literal["kakao-room-mapping-command/1.0"] = "kakao-room-mapping-command/1.0"
    action: Literal["UNMAP_STUDENT"] = "UNMAP_STUDENT"
    parent_revision_id: KakaoMappingRevisionId
    expected_resource_version: KakaoResourceVersion
    reason: Reason

    _reason = field_validator("reason")(_reason)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self


KakaoRoomCommand = Annotated[KakaoRoomMap | KakaoRoomUnmap, Field(discriminator="action")]


class KakaoRoomMapping(FrozenModel):
    schema_version: Literal["kakao-room-mapping/1.0"] = "kakao-room-mapping/1.0"
    mapping_revision_id: KakaoMappingRevisionId
    previous_revision_id: KakaoMappingRevisionId | None
    resource_version: KakaoResourceVersion
    state: MappingState
    student_id: KakaoStudentId | None
    student_display_revision_id: KakaoStudentRevisionId | None
    student_display_name: str | None = Field(min_length=1, max_length=128)
    reason: Reason
    sha256: Sha256
    created_at: UtcDatetime

    _reason = field_validator("reason")(_reason)

    @model_validator(mode="after")
    def exact_mapping(self) -> Self:
        values = (self.student_id, self.student_display_revision_id, self.student_display_name)
        if (self.state == "MAPPED" and any(value is None for value in values)) or (
            self.state == "UNMAPPED" and any(value is not None for value in values)
        ):
            raise ValueError("KAKAO_ARCHIVE_MAPPING_STUDENT_INVALID")
        if self.student_display_name is not None:
            validate_kakao_display_name(self.student_display_name)
        if (self.resource_version == 1) != (
            self.previous_revision_id is None
        ) or self.previous_revision_id == self.mapping_revision_id:
            raise ValueError("KAKAO_ARCHIVE_MAPPING_LINEAGE_INVALID")
        if self.sha256 != room_mapping_sha256(
            student_id=self.student_id,
            student_display_revision_id=self.student_display_revision_id,
            reason=self.reason,
        ):
            raise ValueError("KAKAO_ARCHIVE_MAPPING_HASH_MISMATCH")
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoRoom(FrozenModel):
    schema_version: Literal["kakao-room/1.0"] = "kakao-room/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    display_name: str = Field(min_length=1, max_length=128)
    state: Literal["ACTIVE", "RETIRED"]
    identity_level: IdentityLevel
    resource_version: KakaoResourceVersion
    created_at: UtcDatetime
    last_observed_at: UtcDatetime
    mapping: KakaoRoomMapping

    _name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def exact_revision(self) -> Self:
        if (
            self.resource_version != self.mapping.resource_version
            or self.mapping.created_at < self.created_at
        ):
            raise ValueError("KAKAO_ARCHIVE_ROOM_REVISION_INVALID")
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self


class KakaoRoomMutation(FrozenModel):
    room: KakaoRoom
    replayed: bool = Field(strict=True)


class KakaoRoomPage(FrozenModel):
    items: tuple[KakaoRoom, ...] = Field(max_length=100)
    next_cursor: KakaoRoomId | None

    @model_validator(mode="after")
    def ordered_page(self) -> Self:
        ids = tuple(item.room_id for item in self.items)
        if ids != tuple(sorted(set(ids))) or (
            self.next_cursor is not None and (not ids or self.next_cursor != ids[-1])
        ):
            raise ValueError("KAKAO_ARCHIVE_ROOM_PAGE_INVALID")
        if len({item.source_binding_id for item in self.items}) > 1:
            raise ValueError("KAKAO_ARCHIVE_ROOM_PAGE_INVALID")
        validate_contract("kakao-room-directory-v1", self.model_dump(mode="json"))
        return self

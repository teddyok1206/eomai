"""Browser room DTOs; Catalog owns admission, mapping integrity and permissions."""

from typing import Annotated, Literal

from pydantic import Field

from eom_web_gui.contracts import UtcDatetime, WebModel
from eom_web_gui.kakao_archive_contracts import Label, ResourceVersion
from eom_web_gui.kakao_student_contracts import StudentId, StudentRevisionId

RoomId = Annotated[str, Field(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
MappingRevisionId = Annotated[str, Field(pattern=r"^kakaomappingrev_[0-9a-f]{32}$")]
Reason = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1000,
        pattern=r"^[^\x00-\x1f\x7f]*[^\s\x00-\x1f\x7f][^\x00-\x1f\x7f]*$",
    ),
]


class RoomMap(WebModel):
    schema_version: Literal["kakao-room-mapping-command/1.0"]
    action: Literal["MAP_STUDENT"]
    parent_revision_id: MappingRevisionId
    expected_resource_version: ResourceVersion
    student_id: StudentId
    student_display_revision_id: StudentRevisionId
    reason: Reason


class RoomUnmap(WebModel):
    schema_version: Literal["kakao-room-mapping-command/1.0"]
    action: Literal["UNMAP_STUDENT"]
    parent_revision_id: MappingRevisionId
    expected_resource_version: ResourceVersion
    reason: Reason


RoomCommand = Annotated[RoomMap | RoomUnmap, Field(discriminator="action")]


class RoomMapping(WebModel):
    schema_version: Literal["kakao-room-mapping/1.0"]
    mapping_revision_id: MappingRevisionId
    previous_revision_id: MappingRevisionId | None
    resource_version: ResourceVersion
    state: Literal["MAPPED", "UNMAPPED"]
    student_id: StudentId | None
    student_display_revision_id: StudentRevisionId | None
    student_display_name: Label | None
    reason: Reason
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: UtcDatetime


class Room(WebModel):
    schema_version: Literal["kakao-room/1.0"]
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    room_id: RoomId
    display_name: Label
    state: Literal["ACTIVE", "RETIRED"]
    identity_level: Literal["SOURCE_VERIFIED", "MANUAL_CONFIRMED"]
    resource_version: ResourceVersion
    created_at: UtcDatetime
    last_observed_at: UtcDatetime
    mapping: RoomMapping


class RoomPage(WebModel):
    items: tuple[Room, ...] = Field(max_length=100)
    next_cursor: RoomId | None


class RoomMutation(WebModel):
    room: Room
    replayed: bool = Field(strict=True)

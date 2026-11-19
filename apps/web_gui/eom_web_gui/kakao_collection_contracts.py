"""Studio DTOs for an existing registered room, never browser routing authority."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .contracts import UtcDatetime, WebModel
from .kakao_archive_contracts import ResourceVersion

BindingId = Annotated[str, Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
RoomId = Annotated[str, Field(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
RunId = Annotated[str, Field(pattern=r"^kakaorun_[0-9a-f]{32}$")]


class RoomCollectionSelection(WebModel):
    schema_version: Literal["kakao-capability-confirmation/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    expected_binding_version: ResourceVersion


class RoomCollectionStart(WebModel):
    selection: RoomCollectionSelection
    expected_policy_revision_id: str = Field(pattern=r"^kakaopolicyrev_[0-9a-f]{32}$")


class RoomCollectionStatus(WebModel):
    schema_version: Literal["kakao-collection-status/1.0"]
    run_id: RunId
    source_binding_id: BindingId
    state: Literal[
        "QUEUED",
        "INVENTORY",
        "COLLECTING",
        "RECONCILING",
        "PAUSING",
        "PAUSED",
        "AUTH_REQUIRED",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "CANCELLED",
    ]
    resource_version: ResourceVersion
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("invalid collection time")
        return self


class RoomCollectionStatusView(WebModel):
    schema_version: Literal["kakao-collection-status-view/1.0"]
    collection: RoomCollectionStatus
    failure_reason: Literal["KAKAO_LOGIN_REQUIRED"] | None

    @model_validator(mode="after")
    def valid_reason(self) -> Self:
        if self.failure_reason is not None and self.collection.state != "FAILED":
            raise ValueError("failure reason without a failed collection")
        return self

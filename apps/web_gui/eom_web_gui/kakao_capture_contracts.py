"""BFF input/output validation; no collector paths or provider keys."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .contracts import UtcDatetime, WebModel
from .kakao_archive_contracts import Label, ResourceVersion
from .kakao_manual_contracts import LeaseId

CaptureId = Annotated[str, Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")]
Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class PhotoCheckSelection(WebModel):
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    manual_lease_id: LeaseId
    csv_capture_id: CaptureId
    photo_capture_id: CaptureId


class PhotoCheckResult(WebModel):
    selection: PhotoCheckSelection
    row_ordinal: int | None = Field(strict=True, ge=1, le=100000)


class CaptureItem(WebModel):
    manual_lease_id: LeaseId
    capture_id: CaptureId
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    size_bytes: int | None = Field(strict=True, ge=1, le=33554432)
    state: Literal[
        "ROOM_IDENTITY_OBSERVED",
        "NOT_RECEIVED",
        "TRANSFER_FAILED",
        "NO_OBSERVATION",
        "ROOM_IDENTITY_UNAVAILABLE",
        "INPUT_UNAVAILABLE",
    ]
    preview_sha256: Hash | None

    @model_validator(mode="after")
    def checked_state(self) -> Self:
        if (self.state == "ROOM_IDENTITY_OBSERVED") != (self.preview_sha256 is not None):
            raise ValueError("invalid capture preview")
        if self.completed_at is not None and (
            self.started_at is None or self.completed_at < self.started_at
        ):
            raise ValueError("invalid capture time")
        if self.state == "ROOM_IDENTITY_OBSERVED" and (
            self.completed_at is None or self.size_bytes is None
        ):
            raise ValueError("invalid capture preview")
        return self


class CapturePage(WebModel):
    schema_version: Literal["kakao-manual-capture-page/1.0"]
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    binding_resource_version: ResourceVersion
    scope: Literal["RECENT_EIGHT_MANUAL_SESSIONS"]
    items: tuple[CaptureItem, ...] = Field(max_length=50)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def unique_inputs(self) -> Self:
        if len({(v.manual_lease_id, v.capture_id) for v in self.items}) != len(self.items):
            raise ValueError("duplicate capture")
        return self


class CaptureConfirm(WebModel):
    schema_version: Literal["kakao-manual-capture-confirm/1.0"]
    source_binding_id: str = Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")
    manual_lease_id: LeaseId
    capture_id: CaptureId
    expected_preview_sha256: Hash
    expected_binding_version: ResourceVersion
    display_name: Label
    channel_and_room_confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def explicit_confirmation(self) -> Self:
        if not self.channel_and_room_confirmed:
            raise ValueError("confirmation required")
        return self

"""Bounded public metadata and explicit room confirmation, never source/browser authority."""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import Field, field_validator, model_validator

from .kakao_archive import KakaoBindingId, validate_kakao_display_name
from .kakao_archive_binding import KakaoResourceVersion
from .kakao_manual import KakaoManualLeaseId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

CaptureState = Literal[
    "ROOM_IDENTITY_OBSERVED",
    "NOT_RECEIVED",
    "TRANSFER_FAILED",
    "NO_OBSERVATION",
    "ROOM_IDENTITY_UNAVAILABLE",
    "INPUT_UNAVAILABLE",
]


def manual_capture_preview_sha256(
    *,
    owner: str,
    binding: str,
    lease: str,
    capture: str,
    receipt_sha256: str,
    observation_sha256: str,
    room_identity_sha256: str,
) -> str:
    """Pin the displayed input, not an authorization token or a new persisted entity."""
    return sha256_bytes(
        canonical_json_bytes(
            dict(
                owner=owner,
                binding=binding,
                lease=lease,
                capture=capture,
                receipt_sha256=receipt_sha256,
                observation_sha256=observation_sha256,
                room_identity_sha256=room_identity_sha256,
            )
        )
    )


class KakaoManualCaptureItem(FrozenModel):
    manual_lease_id: KakaoManualLeaseId
    capture_id: str = Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    size_bytes: int | None = Field(strict=True, ge=1, le=33554432)
    state: CaptureState
    preview_sha256: Sha256 | None

    @model_validator(mode="after")
    def evidence_state(self) -> Self:
        if (self.state == "ROOM_IDENTITY_OBSERVED") != (self.preview_sha256 is not None):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_PREVIEW_INVALID")
        if self.completed_at is not None and (
            self.started_at is None or self.completed_at < self.started_at
        ):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_PREVIEW_INVALID")
        if self.state == "ROOM_IDENTITY_OBSERVED" and (
            self.completed_at is None or self.size_bytes is None
        ):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_PREVIEW_INVALID")
        return self


class KakaoManualCapturePage(FrozenModel):
    schema_version: Literal["kakao-manual-capture-page/1.0"] = "kakao-manual-capture-page/1.0"
    source_binding_id: KakaoBindingId
    binding_resource_version: KakaoResourceVersion
    scope: Literal["RECENT_EIGHT_MANUAL_SESSIONS"] = "RECENT_EIGHT_MANUAL_SESSIONS"
    items: tuple[KakaoManualCaptureItem, ...] = Field(max_length=50)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def closed_page(self) -> Self:
        if len({(v.manual_lease_id, v.capture_id) for v in self.items}) != len(self.items):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_PREVIEW_DUPLICATED")
        validate_contract("kakao-manual-capture-intake-v1", self.model_dump(mode="json"))
        return self


class ConfirmKakaoManualCapture(FrozenModel):
    schema_version: Literal["kakao-manual-capture-confirm/1.0"] = "kakao-manual-capture-confirm/1.0"
    source_binding_id: KakaoBindingId
    manual_lease_id: KakaoManualLeaseId
    capture_id: str = Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")
    expected_preview_sha256: Sha256
    expected_binding_version: KakaoResourceVersion
    display_name: str = Field(min_length=1, max_length=128)
    channel_and_room_confirmed: bool = Field(strict=True)

    _name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def explicit_confirmation(self) -> Self:
        if not self.channel_and_room_confirmed:
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_CONFIRMATION_REQUIRED")
        validate_contract("kakao-manual-capture-intake-v1", self.model_dump(mode="json"))
        return self

"""An operator's exact room confirmation and private evidence, not AUTO permission."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import Field, field_validator, model_validator

from .kakao_archive import KakaoBindingId, validate_kakao_display_name
from .kakao_archive_binding import KakaoResourceVersion
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

MANUAL_ROOM_EVIDENCE_REF = "eom://schemas/kakao-archive/manual-room-intake-v1/1.0"
CSV_POPUP_PROOF_SCHEMA = "eom://schemas/kakao-archive/csv-popup-room-proof-v1/1.0"
CSV_POPUP_ROOM_EVIDENCE_REF = CSV_POPUP_PROOF_SCHEMA + "#/$defs/evidence"
MANUAL_ROOM_EVIDENCE_REFS = (MANUAL_ROOM_EVIDENCE_REF, CSV_POPUP_ROOM_EVIDENCE_REF)
ProviderKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


def manual_channel_identity_sha256(channel_key: str) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            dict(
                provider="KAKAO_CHANNEL_ADMIN",
                origin="https://business.kakao.com",
                channel_key=channel_key,
            )
        )
    )


def observed_manual_room_keys(document_path: str, download_path: str) -> tuple[str, str] | None:
    """Parse only observed path shapes, not a navigation target or capability claim.

    Room identity is obtained from the actual SDK photo download, not a guessed
    document URL suffix, source name, list position or image filename.
    """
    document = document_path.removeprefix("/").split("/")
    download = download_path.removeprefix("/").split("/")
    if (
        not document_path.startswith("/")
        or not download_path.startswith("/")
        or len(document) < 5
        or document[0] != "space"
        or document[2] != "channel"
        or document[4] != "chats"
        or len(download) != 8
        or download[0:2] != ["api", "profiles"]
        or download[3] != "chats"
        or download[-1] != "image"
        or document[3] != download[2]
        or any(
            re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
            for value in (
                document[1],
                document[3],
                download[2],
                download[4],
                download[5],
                download[6],
            )
        )
    ):
        return None
    return download[2], download[4]


def manual_room_identity_sha256(channel_key: str, room_key: str) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            dict(provider="KAKAO_CHANNEL_ADMIN", channel_key=channel_key, room_key=room_key)
        )
    )


class ConfirmKakaoManualRoom(FrozenModel):
    schema_version: Literal["kakao-manual-room-confirmation/1.0"] = (
        "kakao-manual-room-confirmation/1.0"
    )
    source_binding_id: KakaoBindingId
    manual_lease_id: str = Field(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")
    capture_id: str = Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")
    expected_channel_key: ProviderKey
    expected_room_key: ProviderKey
    display_name: str = Field(min_length=1, max_length=128)
    expected_binding_version: KakaoResourceVersion

    _name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def closed_request(self) -> Self:
        validate_contract("kakao-manual-room-intake-v1", self.model_dump(mode="json"))
        return self


class _ManualRoomEvidenceFields(FrozenModel):
    owner_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    confirmation: ConfirmKakaoManualRoom
    request_sha256: Sha256
    profile_id: str = Field(pattern=r"^kakaoprofile_[0-9a-f]{32}$")
    browser_run_id: str = Field(pattern=r"^kakaobrowserrun_[0-9a-f]{32}$")
    fence_epoch: int = Field(strict=True, ge=1, le=2147483647)
    page_instance_id: str = Field(pattern=r"^kakaopage_[0-9a-f]{32}$")
    capture_started_at: UtcDatetime
    observed_at: UtcDatetime
    capture_completed_at: UtcDatetime
    payload_sha256: Sha256
    payload_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    receipt_sha256: Sha256
    observation_sha256: Sha256
    source_identity_sha256: Sha256

    @model_validator(mode="after")
    def exact_confirmation(self) -> Self:
        if (
            self.request_sha256
            != sha256_bytes(canonical_json_bytes(self.confirmation.model_dump(mode="json")))
            or self.source_identity_sha256
            != manual_room_identity_sha256(
                self.confirmation.expected_channel_key, self.confirmation.expected_room_key
            )
            or not self.capture_started_at <= self.observed_at <= self.capture_completed_at
        ):
            raise ValueError("KAKAO_ARCHIVE_MANUAL_ROOM_EVIDENCE_INVALID")
        return self


class KakaoManualRoomEvidence(_ManualRoomEvidenceFields):
    schema_version: Literal["kakao-manual-room-evidence/1.0"] = "kakao-manual-room-evidence/1.0"
    identity_method: Literal["MANUALLY_CONFIRMED_CHANNEL_AND_DOWNLOAD_ROOM_PATH"] = (
        "MANUALLY_CONFIRMED_CHANNEL_AND_DOWNLOAD_ROOM_PATH"
    )

    @model_validator(mode="after")
    def closed_evidence(self) -> Self:
        validate_contract("kakao-manual-room-intake-v1", self.model_dump(mode="json"))
        return self


class KakaoCsvPopupRoomEvidence(_ManualRoomEvidenceFields):
    schema_version: Literal["kakao-csv-popup-room-evidence/1.0"] = (
        "kakao-csv-popup-room-evidence/1.0"
    )
    identity_method: Literal["MANUALLY_CONFIRMED_CSV_AND_CORROBORATED_POPUP"] = (
        "MANUALLY_CONFIRMED_CSV_AND_CORROBORATED_POPUP"
    )

    @model_validator(mode="after")
    def closed_evidence(self) -> Self:
        validate_contract("kakao-csv-popup-room-proof-v1", self.model_dump(mode="json"))
        return self


ManualRoomEvidence = KakaoManualRoomEvidence | KakaoCsvPopupRoomEvidence


def manual_room_evidence_type(
    schema_ref: str,
) -> type[KakaoManualRoomEvidence] | type[KakaoCsvPopupRoomEvidence]:
    if schema_ref == MANUAL_ROOM_EVIDENCE_REF:
        return KakaoManualRoomEvidence
    if schema_ref == CSV_POPUP_ROOM_EVIDENCE_REF:
        return KakaoCsvPopupRoomEvidence
    raise ValueError("KAKAO_ARCHIVE_MANUAL_ROOM_EVIDENCE_INVALID")

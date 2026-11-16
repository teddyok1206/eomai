"""Small capture receipt; CSV bytes and normalized conversation stay in Artifacts."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId, KakaoRoomId, KakaoSnapshotRevisionId
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

SNAPSHOT_REF = "eom://schemas/kakao-archive/room-snapshot/1.0"
# The CSV is a media format, not a JSON document. Its receipt is JSON-Schema validated.
CSV_FORMAT_REF = "eom://formats/kakao-archive/channel-csv/1.0"


class KakaoRoomSnapshot(FrozenModel):
    schema_version: Literal["kakao-room-snapshot/1.0"] = "kakao-room-snapshot/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    snapshot_revision_id: KakaoSnapshotRevisionId
    source_sha256: Sha256
    source_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    observed_at_utc: UtcDatetime
    csv_scope: Literal["full_accessible_history", "loaded_window", "explicit_range", "unknown"]

    @model_validator(mode="after")
    def validate_snapshot_schema(self) -> Self:
        validate_contract("kakao-room-snapshot-v1", self.model_dump(mode="json"))
        return self

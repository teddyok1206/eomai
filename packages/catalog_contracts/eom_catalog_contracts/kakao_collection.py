"""Accepted collection intents and metadata reads; not browser execution authority."""

from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import Field, StrictBool, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId
from .kakao_archive_binding import KakaoPolicyRevisionId, KakaoResourceVersion
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

KakaoRunId = Annotated[str, Field(pattern=r"^kakaorun_[0-9a-f]{32}$")]
KakaoTaskId = Annotated[str, Field(pattern=r"^kakaotask_[0-9a-f]{32}$")]
KakaoCapabilityRevisionId = Annotated[str, Field(pattern=r"^kakaocapabilityrev_[0-9a-f]{32}$")]
CollectionState = Literal[
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


class KakaoRoomCollectionCreate(FrozenModel):
    schema_version: Literal["kakao-room-collection-create/1.0"] = "kakao-room-collection-create/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    capability_revision_id: KakaoCapabilityRevisionId
    expected_binding_version: KakaoResourceVersion
    expected_policy_revision_id: KakaoPolicyRevisionId

    @model_validator(mode="after")
    def closed_request(self) -> Self:
        validate_contract("kakao-collection-intent-v1", self.model_dump(mode="json"))
        return self


class AcceptedKakaoRoomCollection(FrozenModel):
    schema_version: Literal["kakao-room-collection-accepted/1.0"] = (
        "kakao-room-collection-accepted/1.0"
    )
    request: KakaoRoomCollectionCreate
    run_id: KakaoRunId
    task_id: KakaoTaskId
    request_sha256: Sha256
    policy_sha256: Sha256
    adapter_release_sha256: Sha256
    created_at: UtcDatetime
    replayed: StrictBool

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        if self.request_sha256 != sha256_bytes(
            canonical_json_bytes(self.request.model_dump(mode="json"))
        ):
            raise ValueError("KAKAO_ARCHIVE_COLLECTION_REQUEST_MISMATCH")
        validate_contract("kakao-collection-intent-v1", self.model_dump(mode="json"))
        return self


class KakaoCollectionStatus(FrozenModel):
    schema_version: Literal["kakao-collection-status/1.0"] = "kakao-collection-status/1.0"
    run_id: KakaoRunId
    source_binding_id: KakaoBindingId
    state: CollectionState
    resource_version: KakaoResourceVersion
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def valid_status(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("KAKAO_ARCHIVE_COLLECTION_TIME_INVALID")
        validate_contract("kakao-collection-intent-v1", self.model_dump(mode="json"))
        return self

"""Private accepted execution identity; not a worker/public authorization token."""

from typing import Literal

from pydantic import Field, model_validator

from .kakao_archive import (
    KakaoBindingId,
    KakaoNormalizationRevisionId,
    KakaoRoomId,
    KakaoSnapshotRevisionId,
)
from .kakao_collection import KakaoRunId, KakaoTaskId
from .kakao_manual import KakaoBrowserRunId, KakaoProfileId
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract


class KakaoCollectionAttempt(FrozenModel):
    schema_version: Literal["kakao-collection-attempt/1.0"] = "kakao-collection-attempt/1.0"
    run_id: KakaoRunId
    task_id: KakaoTaskId
    attempt_id: str = Field(pattern=r"^kakaoattempt_[0-9a-f]{32}$")
    command_id: str = Field(pattern=r"^kakaocommand_[0-9a-f]{32}$")
    attempt_number: int = Field(default=1, strict=True, ge=1, le=1)
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    profile_id: KakaoProfileId
    browser_run_id: KakaoBrowserRunId
    fence: int = Field(strict=True, ge=1, le=2147483647)
    snapshot_revision_id: KakaoSnapshotRevisionId
    normalization_revision_id: KakaoNormalizationRevisionId
    created_at: UtcDatetime
    state: Literal["RESERVED", "COMMAND_READY", "RESULT_ACCEPTED"]

    @model_validator(mode="after")
    def closed_identity(self) -> "KakaoCollectionAttempt":
        validate_contract("kakao-collection-attempt-v1", self.model_dump(mode="json"))
        return self

"""Small owner-private binding bootstrap contracts; no channel verification authority."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import (
    KakaoBindingId,
    SourceTimezone,
    validate_kakao_display_name,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

KakaoPolicyRevisionId = Annotated[str, Field(pattern=r"^kakaopolicyrev_[0-9a-f]{32}$")]
KakaoResourceVersion = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class KakaoCollectionPolicy(FrozenModel):
    """Future schedule intent only; this value does not enable collection."""

    interval_minutes: int = Field(default=1440, strict=True, ge=60, le=10080)
    include_images: Literal[True] = True
    source_timezone: SourceTimezone = "unknown"
    question_rule_version: Literal["turn_v1"] = "turn_v1"

    @field_validator("include_images", mode="before")
    @classmethod
    def explicit_images(cls, value: object) -> object:
        if value is not True:
            raise ValueError("KAKAO_ARCHIVE_IMAGE_POLICY_INVALID")
        return value


def collection_policy_sha256(policy: KakaoCollectionPolicy) -> str:
    data = json.dumps(
        policy.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class KakaoCollectionPolicyRevision(FrozenModel):
    source_binding_id: KakaoBindingId
    policy_revision_id: KakaoPolicyRevisionId
    previous_revision_id: KakaoPolicyRevisionId | None
    revision_number: KakaoResourceVersion
    sha256: Sha256
    policy: KakaoCollectionPolicy
    created_at: UtcDatetime

    @model_validator(mode="after")
    def immutable_policy(self) -> Self:
        if self.sha256 != collection_policy_sha256(self.policy):
            raise ValueError("KAKAO_ARCHIVE_POLICY_HASH_MISMATCH")
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("KAKAO_ARCHIVE_POLICY_LINEAGE_INVALID")
        if self.previous_revision_id == self.policy_revision_id:
            raise ValueError("KAKAO_ARCHIVE_POLICY_LINEAGE_INVALID")
        return self


class KakaoBindingCreate(FrozenModel):
    schema_version: Literal["kakao-binding-create/1.0"] = "kakao-binding-create/1.0"
    action: Literal["CREATE"] = "CREATE"
    display_name: str = Field(min_length=1, max_length=128)
    policy: KakaoCollectionPolicy

    _display_name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-source-binding-create-v1", self.model_dump(mode="json"))
        return self


class KakaoBindingUpdatePolicy(FrozenModel):
    schema_version: Literal["kakao-binding-command/1.0"] = "kakao-binding-command/1.0"
    action: Literal["UPDATE_COLLECTION_POLICY"] = "UPDATE_COLLECTION_POLICY"
    parent_policy_revision_id: KakaoPolicyRevisionId
    expected_resource_version: KakaoResourceVersion
    policy: KakaoCollectionPolicy

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-source-binding-command-v1", self.model_dump(mode="json"))
        return self


class KakaoBindingRetire(FrozenModel):
    schema_version: Literal["kakao-binding-command/1.0"] = "kakao-binding-command/1.0"
    action: Literal["RETIRE"] = "RETIRE"
    parent_policy_revision_id: KakaoPolicyRevisionId
    expected_resource_version: KakaoResourceVersion

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-source-binding-command-v1", self.model_dump(mode="json"))
        return self


KakaoBindingCommand = Annotated[
    KakaoBindingUpdatePolicy | KakaoBindingRetire, Field(discriminator="action")
]


class KakaoSourceBinding(FrozenModel):
    schema_version: Literal["kakao-source-binding/1.0"] = "kakao-source-binding/1.0"
    source_binding_id: KakaoBindingId
    display_name: str = Field(min_length=1, max_length=128)
    state: Literal["DRAFT", "RETIRED"]
    resource_version: KakaoResourceVersion
    policy_revision: KakaoCollectionPolicyRevision
    schedule_enabled: Literal[False] = False
    capability_state: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    created_at: UtcDatetime
    updated_at: UtcDatetime

    _display_name = field_validator("display_name")(validate_kakao_display_name)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        if self.policy_revision.source_binding_id != self.source_binding_id:
            raise ValueError("KAKAO_ARCHIVE_POLICY_BINDING_MISMATCH")
        if self.updated_at < self.created_at or self.policy_revision.created_at > self.updated_at:
            raise ValueError("KAKAO_ARCHIVE_TIME_INVALID")
        if self.policy_revision.revision_number > self.resource_version:
            raise ValueError("KAKAO_ARCHIVE_POLICY_LINEAGE_INVALID")
        validate_contract("kakao-source-binding-v1", self.model_dump(mode="json"))
        return self


class KakaoBindingPage(FrozenModel):
    items: tuple[KakaoSourceBinding, ...] = Field(max_length=100)
    next_cursor: KakaoBindingId | None


class KakaoBindingMutation(FrozenModel):
    binding: KakaoSourceBinding
    replayed: bool = Field(strict=True)

"""Content Pack API DTOs."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel, ArtifactPointer, OpaqueId, UtcDatetime


class ContentPackReleaseView(ApiModel):
    content_pack_release_id: OpaqueId
    content_pack_id: OpaqueId
    pack_key: str
    version: str
    schema_version: str
    state: str
    bundle: ArtifactPointer
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    released_at: UtcDatetime | None = None


class ContentPackActivationView(ApiModel):
    activation_id: OpaqueId
    environment: str
    pack_key: str
    content_pack_release_id: OpaqueId
    active: bool
    activated_by: str
    activated_at: UtcDatetime
    resource_version: int = Field(ge=1)


class ActivateContentPackRequest(ApiModel):
    environment: Literal["development", "test"]
    reason: str = Field(min_length=1, max_length=1000)

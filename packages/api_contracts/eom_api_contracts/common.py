"""Common immutable Application API response contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
RequestId = Annotated[
    str, Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
]
OpaqueId = Annotated[str, Field(min_length=1, max_length=128)]
Sha256 = Annotated[str, Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponseMeta(ApiModel):
    request_id: RequestId
    api_version: Literal["1"] = "1"


class PageMeta(ApiModel):
    next_cursor: str | None = None
    has_more: bool = False
    limit: int = Field(ge=1, le=200)


class SingleResponse[DataT](ApiModel):
    data: DataT
    meta: ResponseMeta


class ListResponse[DataT](ApiModel):
    data: tuple[DataT, ...]
    page: PageMeta
    meta: ResponseMeta


class ArtifactPointer(ApiModel):
    artifact_id: OpaqueId
    artifact_revision_id: OpaqueId
    sha256: Sha256
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=127)
    logical_uri: str = Field(pattern=r"^nas://artifacts/[^/]+/[^/]+$")


class EmptyResult(ApiModel):
    revoked_sessions: int = Field(default=0, ge=0)


class EmptyRequest(ApiModel):
    pass


class CommandResult(ApiModel):
    command_id: OpaqueId
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: OpaqueId
    status: Literal["ACCEPTED", "COMPLETED"]
    resource_version: int = Field(ge=1)
    status_url: str = Field(pattern=r"^/api/v1/")

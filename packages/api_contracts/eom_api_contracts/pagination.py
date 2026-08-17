"""Strict cursor pagination query contracts."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel


class CursorQuery(ApiModel):
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=1024)
    sort: Literal["created_at", "-created_at"] = "-created_at"

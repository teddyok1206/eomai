"""Explicit larger bound only for the mixed-document delivery broker."""

from typing import Literal

from pydantic import Field

from eom_hwpx_contracts.models import HwpxManagerDownloadResponse, StrictModel


class CuratedManagerDownloadRequest(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    operation: Literal["download-curated"] = "download-curated"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")


class CuratedManagerDownloadResponse(HwpxManagerDownloadResponse):
    schema_version: Literal["2.0"] = "2.0"  # type: ignore[assignment]
    content_length: int | None = Field(default=None, ge=1, le=256 * 1024 * 1024)

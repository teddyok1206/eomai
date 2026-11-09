"""Small build status for a saved DB assembly, independent of an Item ID."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel, UtcDatetime
from eom_api_contracts.hwpx import HwpxBuildState, HwpxValidationState


class CreateCuratedHwpxBuildRequest(ApiModel):
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class _CuratedHwpxBuildFields(ApiModel):
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    state: HwpxBuildState
    validation_state: HwpxValidationState
    section_count: int | None = Field(default=None, ge=1, le=10000)
    output_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    output_size_bytes: int | None = Field(default=None, ge=1, le=256 * 1024**2)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    download_available: bool


class CuratedHwpxBuildView(_CuratedHwpxBuildFields):
    schema_version: Literal["curated-hwpx-build-view/1.0"] = "curated-hwpx-build-view/1.0"
    placement_count: int = Field(ge=1, le=200)


class CuratedHwpxBuildViewV2(_CuratedHwpxBuildFields):
    schema_version: Literal["curated-hwpx-build-view/2.0"] = "curated-hwpx-build-view/2.0"
    placement_count: int = Field(ge=1, le=100000)


type CuratedHwpxView = CuratedHwpxBuildView | CuratedHwpxBuildViewV2

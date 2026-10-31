"""Local-only editable assembly inputs; no NAS paths, identity grants or raw payloads."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel


class CuratedHwpxSegment(StrictModel):
    position: int = Field(strict=True, ge=1, le=200)
    local_file: str = Field(pattern=r"^inputs/[0-9]{3}\.(hwpx|hwp)$")
    source_format: Literal["HWP", "HWPX"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(strict=True, ge=1, le=50 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_workspace_name(self) -> Self:
        if self.local_file != f"inputs/{self.position:03d}.{self.source_format.lower()}":
            raise ValueError("segment filename differs from position and detected format")
        return self


class CuratedHwpxRenderRequest(StrictModel):
    schema_version: Literal["curated-hwpx-render-request/1.0"]
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    profile: Literal["NATIVE_EDITABLE_PRESERVATION_V1"]
    segments: tuple[CuratedHwpxSegment, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def bounded_ordered_inputs(self) -> Self:
        if tuple(row.position for row in self.segments) != tuple(range(1, len(self.segments) + 1)):
            raise ValueError("segments must be contiguous and ordered")
        if sum(row.size_bytes for row in self.segments) > 256 * 1024 * 1024:
            raise ValueError("curated compressed input byte budget exceeded")
        return self


type CuratedHwpxFailure = Literal[
    "HWPX_CURATED_INPUT_INVALID",
    "HWPX_CURATED_INPUT_CHANGED",
    "HWPX_CURATED_FORMAT_UNSUPPORTED",
    "HWPX_CURATED_PRESERVATION_FAILED",
]


class CuratedHwpxRenderResult(StrictModel):
    schema_version: Literal["curated-hwpx-render-result/1.0"]
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    profile: Literal["NATIVE_EDITABLE_PRESERVATION_V1"]
    status: Literal["SUCCEEDED", "FAILED"]
    source_sha256: tuple[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")], ...] = Field(
        max_length=200
    )
    section_source_positions: tuple[Annotated[int, Field(strict=True, ge=1, le=200)], ...] = Field(
        max_length=10000
    )
    binary_count: int = Field(strict=True, ge=0, le=10000)
    output_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_size_bytes: int | None = Field(strict=True, ge=1, le=256 * 1024 * 1024)
    failure_code: CuratedHwpxFailure | None

    @model_validator(mode="after")
    def exact_terminal_evidence(self) -> Self:
        if self.status == "FAILED":
            if (
                self.failure_code is None
                or self.output_sha256 is not None
                or self.output_size_bytes is not None
                or self.source_sha256
                or self.section_source_positions
                or self.binary_count
            ):
                raise ValueError("failed curated result cannot advertise a deliverable")
        else:
            if (
                self.failure_code is not None
                or self.output_sha256 is None
                or self.output_size_bytes is None
                or not self.source_sha256
                or not self.section_source_positions
            ):
                raise ValueError("successful curated result requires preservation evidence")
            positions = self.section_source_positions
            if tuple(sorted(positions)) != positions or set(positions) != set(
                range(1, len(self.source_sha256) + 1)
            ):
                raise ValueError("curated result does not cover all sources in order")
        return self

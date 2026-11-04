"""Local-only editable assembly inputs; no NAS paths, identity grants or raw payloads."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel
from eom_hwpx_contracts.validation import parse_json_object, validate_contract


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
        _validate_segments(self.segments)
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


def _validate_segments(segments: tuple[CuratedHwpxSegment, ...]) -> None:
    if tuple(row.position for row in segments) != tuple(range(1, len(segments) + 1)):
        raise ValueError("segments must be contiguous and ordered")
    if sum(row.size_bytes for row in segments) > 256 * 1024 * 1024:
        raise ValueError("curated compressed input byte budget exceeded")


class CuratedHwpConverterSnapshot(StrictModel):
    """Installed optional tool identity, not an arbitrary executable path."""

    profile: Literal["HWP2HWPX_NATIVE_V1"]
    source_commit: Literal["62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d"]
    bundle_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CuratedHwpxRenderRequestV2(StrictModel):
    schema_version: Literal["curated-hwpx-render-request/2.0"]
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    profile: Literal["NATIVE_EDITABLE_PRESERVATION_V2"]
    segments: tuple[CuratedHwpxSegment, ...] = Field(min_length=1, max_length=200)
    converter: CuratedHwpConverterSnapshot | None

    @model_validator(mode="after")
    def bounded_ordered_inputs(self) -> Self:
        _validate_segments(self.segments)
        if any(row.source_format == "HWP" for row in self.segments) != (self.converter is not None):
            raise ValueError("converter identity is required exactly for native HWP inputs")
        return self


type CuratedHwpxWarning = Literal[
    "FIRST_DOCUMENT_PRINT_SETTINGS", "STYLE_NAMES_RELOCATED", "HWP_CONVERTED_NATIVE"
]


class CuratedHwpxRenderResultV2(CuratedHwpxRenderResult):
    schema_version: Literal["curated-hwpx-render-result/2.0"]  # type: ignore[assignment]
    profile: Literal["NATIVE_EDITABLE_PRESERVATION_V2"]  # type: ignore[assignment]
    segment_sha256: tuple[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")], ...] = Field(
        max_length=200
    )
    warnings: tuple[CuratedHwpxWarning, ...] = Field(max_length=4)
    converter_bundle_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_conversion_lineage(self) -> Self:
        if len(self.segment_sha256) != len(self.source_sha256):
            raise ValueError("curated source/segment lineage count differs")
        if len(self.warnings) != len(set(self.warnings)):
            raise ValueError("curated result repeats a warning")
        if self.status == "FAILED":
            if self.segment_sha256 or self.warnings or self.converter_bundle_sha256 is not None:
                raise ValueError("failed curated result cannot advertise converted segments")
        elif ("HWP_CONVERTED_NATIVE" in self.warnings) != (
            self.converter_bundle_sha256 is not None
        ):
            raise ValueError("native conversion requires its exact installed bundle identity")
        return self


def parse_curated_render_request(
    payload: bytes,
) -> CuratedHwpxRenderRequest | CuratedHwpxRenderRequestV2:
    """Select an explicitly released profile without reinterpreting historical V1."""
    return parse_curated_render_value(parse_json_object(payload))


def parse_curated_render_value(
    value: dict[str, object],
) -> CuratedHwpxRenderRequest | CuratedHwpxRenderRequestV2:
    """Validate an already decoded object without parsing the same bytes twice."""
    if value.get("schema_version") == "curated-hwpx-render-request/2.0":
        validate_contract("curated-render-request-v2", value)
        return CuratedHwpxRenderRequestV2.model_validate(value)
    validate_contract("curated-render-request", value)
    return CuratedHwpxRenderRequest.model_validate(value)

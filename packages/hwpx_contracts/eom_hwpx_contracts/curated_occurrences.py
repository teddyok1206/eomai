"""Occurrence-preserving successor of the existing editable mixed delivery.

Old V1 input/V3 render bytes and bounds remain unchanged. The new profile
separates repeated Item targets from unique positions, retaining byte budgets.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.curated_build import (
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
    Sha256,
)
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.curated_mixed import (
    CuratedCanonicalSegment,
    CuratedEditorialSegment,
    CuratedMixedRenderRequest,
    CuratedMixedRenderResult,
    CuratedNativeSegment,
)
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot, StrictModel
from eom_hwpx_contracts.native_item import NativeItemRenderRequest
from eom_hwpx_contracts.validation import validate_contract

MAX_OCCURRENCES = 100000
CURATED_OCCURRENCE_PROFILE = "CURATED_EDITABLE_OCCURRENCES_V2"
PlacementId = Annotated[str, Field(pattern=r"^placement_[0-9a-f]{32}$")]


class CuratedNativeOccurrenceInput(CuratedNativeDocumentInput):
    position: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)
    placement_id: PlacementId


class CuratedRegisteredOccurrenceInput(CuratedRegisteredItemInput):
    position: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)
    placement_id: PlacementId


type CuratedOccurrenceInput = Annotated[
    CuratedNativeOccurrenceInput | CuratedRegisteredOccurrenceInput,
    Field(discriminator="kind"),
]


class CuratedHwpxBuildInputV2(StrictModel):
    schema_version: Literal["curated-hwpx-build-input/2.0"] = "curated-hwpx-build-input/2.0"
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    profile: Literal["CURATED_EDITABLE_OCCURRENCES_V2"] = "CURATED_EDITABLE_OCCURRENCES_V2"
    renderer_version: Literal["2.0.0"] = "2.0.0"
    handoff: ContentTeamHandoffSnapshot | None
    converter: CuratedHwpConverterSnapshot | None
    placements: tuple[CuratedOccurrenceInput, ...] = Field(min_length=1, max_length=MAX_OCCURRENCES)

    @model_validator(mode="after")
    def exact_occurrences_and_tools(self) -> Self:
        if any(row.position != number for number, row in enumerate(self.placements, 1)) or len(
            {row.placement_id for row in self.placements}
        ) != len(self.placements):
            raise ValueError("output occurrences must be unique and contiguous")
        native = tuple(
            row for row in self.placements if isinstance(row, CuratedNativeDocumentInput)
        )
        if (
            any(row.source_format == "HWP" for row in native) != (self.converter is not None)
            or (len(native) != len(self.placements)) != (self.handoff is not None)
            or sum(row.size_bytes for row in native) > 256 * 1024 * 1024
        ):
            raise ValueError("occurrence tools or declared input budget differ")
        return self


class CuratedNativeOccurrenceSegment(CuratedNativeSegment):
    position: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)
    local_file: str = Field(pattern=r"^inputs/[0-9]{3,6}\.(hwpx|hwp)$")


class CuratedCanonicalOccurrenceSegment(CuratedCanonicalSegment):
    position: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)
    blueprint_file: str = Field(pattern=r"^input/items/[0-9]{3,6}/native-item\.json$")


class CuratedEditorialOccurrenceSegment(CuratedEditorialSegment):
    position: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)
    json_file: str = Field(pattern=r"^input/items/[0-9]{3,6}/item-content\.json$")
    markdown_file: str = Field(pattern=r"^input/items/[0-9]{3,6}/content-team-item\.md$")


type CuratedOccurrenceSegment = Annotated[
    CuratedNativeOccurrenceSegment
    | CuratedCanonicalOccurrenceSegment
    | CuratedEditorialOccurrenceSegment,
    Field(discriminator="kind"),
]


class CuratedOccurrenceRenderRequest(StrictModel):
    schema_version: Literal["curated-hwpx-render-request/4.0"] = "curated-hwpx-render-request/4.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    input_plan_sha256: Sha256
    profile: Literal["CURATED_EDITABLE_OCCURRENCES_V2"] = "CURATED_EDITABLE_OCCURRENCES_V2"
    segments: tuple[CuratedOccurrenceSegment, ...] = Field(min_length=1, max_length=MAX_OCCURRENCES)
    handoff: ContentTeamHandoffSnapshot | None
    converter: CuratedHwpConverterSnapshot | None

    @model_validator(mode="after")
    def ordered_bounded_occurrences(self) -> Self:
        if any(row.position != number for number, row in enumerate(self.segments, 1)):
            raise ValueError("output segments must be contiguous")
        native = tuple(row for row in self.segments if isinstance(row, CuratedNativeSegment))
        if any(row.source_format == "HWP" for row in native) != (self.converter is not None) or (
            len(native) != len(self.segments)
        ) != (self.handoff is not None):
            raise ValueError("output converter/handoff differs")
        size = sum(row.size_bytes for row in native)
        images: dict[str, int] = {}
        for row in self.segments:
            if isinstance(row, CuratedCanonicalSegment):
                size += row.blueprint_size_bytes
            elif isinstance(row, CuratedEditorialSegment):
                size += row.json_size_bytes + row.markdown_size_bytes
                for image in row.images:
                    previous = images.setdefault(image.local_file, image.size_bytes)
                    if previous != image.size_bytes:
                        raise ValueError("shared image size differs")
        if size + sum(images.values()) > 256 * 1024 * 1024:
            raise ValueError("output declared input byte budget exceeded")
        return self


class CuratedOccurrenceRenderResult(CuratedMixedRenderResult):
    schema_version: Literal["curated-hwpx-render-result/4.0"] = "curated-hwpx-render-result/4.0"  # type: ignore[assignment]
    profile: Literal["CURATED_EDITABLE_OCCURRENCES_V2"] = "CURATED_EDITABLE_OCCURRENCES_V2"  # type: ignore[assignment]
    source_sha256: tuple[Sha256, ...] = Field(max_length=MAX_OCCURRENCES)
    segment_sha256: tuple[Sha256, ...] = Field(max_length=MAX_OCCURRENCES)
    section_source_positions: tuple[
        Annotated[int, Field(strict=True, ge=1, le=MAX_OCCURRENCES)], ...
    ] = Field(max_length=10000)
    failure_position: int | None = Field(default=None, strict=True, ge=1, le=MAX_OCCURRENCES)


class NativeItemRenderRequestV2(NativeItemRenderRequest):
    schema_version: Literal["native-item-render-request/2.0"] = "native-item-render-request/2.0"  # type: ignore[assignment]
    profile: Literal["CANONICAL_ITEM_NATIVE_V2"] = "CANONICAL_ITEM_NATIVE_V2"  # type: ignore[assignment]
    item_number: int = Field(strict=True, ge=1, le=MAX_OCCURRENCES)


type CuratedBuildInput = CuratedHwpxBuildInput | CuratedHwpxBuildInputV2
type CuratedRenderRequest = CuratedMixedRenderRequest | CuratedOccurrenceRenderRequest
type CuratedRenderResult = CuratedMixedRenderResult | CuratedOccurrenceRenderResult


def parse_curated_build_input(value: dict[str, object]) -> CuratedBuildInput:
    if value.get("schema_version") == "curated-hwpx-build-input/2.0":
        validate_contract("curated-build-input-v2", value)
        return CuratedHwpxBuildInputV2.model_validate(value)
    validate_contract("curated-build-input", value)
    return CuratedHwpxBuildInput.model_validate(value)


def parse_mixed_render_request(value: dict[str, object]) -> CuratedRenderRequest:
    if value.get("schema_version") == "curated-hwpx-render-request/4.0":
        validate_contract("curated-render-request-v4", value)
        return CuratedOccurrenceRenderRequest.model_validate(value)
    validate_contract("curated-render-request-v3", value)
    return CuratedMixedRenderRequest.model_validate(value)


def parse_mixed_render_result(value: dict[str, object]) -> CuratedRenderResult:
    if value.get("schema_version") == "curated-hwpx-render-result/4.0":
        validate_contract("curated-render-result-v4", value)
        return CuratedOccurrenceRenderResult.model_validate(value)
    validate_contract("curated-render-result-v3", value)
    return CuratedMixedRenderResult.model_validate(value)


def parse_native_item_render(value: dict[str, object]) -> NativeItemRenderRequest:
    if value.get("schema_version") == "native-item-render-request/2.0":
        validate_contract("native-item-render-request-v2", value)
        return NativeItemRenderRequestV2.model_validate(value)
    validate_contract("native-item-render-request", value)
    return NativeItemRenderRequest.model_validate(value)

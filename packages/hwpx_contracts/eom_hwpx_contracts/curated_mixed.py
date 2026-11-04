"""One file-only mixed render request; persisted source identities stay in the build plan."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.curated_document import (
    CuratedHwpConverterSnapshot,
    CuratedHwpxRenderResultV2,
    CuratedHwpxSegment,
)
from eom_hwpx_contracts.models import (
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    StrictModel,
)

type _Sha = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class CuratedNativeSegment(CuratedHwpxSegment):
    kind: Literal["NATIVE_DOCUMENT"] = "NATIVE_DOCUMENT"


class CuratedCanonicalSegment(StrictModel):
    kind: Literal["CANONICAL_ITEM"] = "CANONICAL_ITEM"
    position: int = Field(strict=True, ge=1, le=200)
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_sha256: _Sha
    effective_content_sha256: _Sha
    blueprint_file: str = Field(pattern=r"^input/items/[0-9]{3}/native-item\.json$")
    blueprint_sha256: _Sha
    blueprint_size_bytes: int = Field(strict=True, ge=1, le=2 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_position(self) -> Self:
        if self.blueprint_file != f"input/items/{self.position:03d}/native-item.json":
            raise ValueError("canonical segment path differs from its position")
        return self


class CuratedEditorialImage(StrictModel):
    """Binding identity is unchanged; only local_file names the shared staged bytes.

    binding.file_name is the historical single-item value, never a filesystem
    request in this profile. This avoids copying a common PNG for every placement.
    """

    binding: ContentTeamImageSource
    local_file: str = Field(pattern=r"^images/[0-9a-f]{64}\.png$")
    size_bytes: int = Field(strict=True, ge=24, le=2 * 1024 * 1024)

    @model_validator(mode="after")
    def content_addressed_file(self) -> Self:
        if self.local_file != f"images/{self.binding.sha256[7:]}.png":
            raise ValueError("editorial image file differs from its content hash")
        return self


class CuratedEditorialSegment(StrictModel):
    kind: Literal["CONTENT_TEAM_ITEM"] = "CONTENT_TEAM_ITEM"
    position: int = Field(strict=True, ge=1, le=200)
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_schema_ref: Literal["eom.assessment.item-content/2.0", "eom.assessment.item-content/3.0"]
    json_file: str = Field(pattern=r"^input/items/[0-9]{3}/item-content\.json$")
    source_sha256: _Sha
    json_size_bytes: int = Field(strict=True, ge=1, le=2 * 1024 * 1024)
    markdown_file: str = Field(pattern=r"^input/items/[0-9]{3}/content-team-item\.md$")
    markdown_sha256: _Sha
    markdown_size_bytes: int = Field(strict=True, ge=1, le=1024 * 1024)
    images: tuple[CuratedEditorialImage, ...] = Field(max_length=2)

    @model_validator(mode="after")
    def exact_item_inputs(self) -> Self:
        prefix = f"input/items/{self.position:03d}"
        if (
            self.json_file != f"{prefix}/item-content.json"
            or self.markdown_file != f"{prefix}/content-team-item.md"
        ):
            raise ValueError("editorial segment files differ from its position")
        ordinals = tuple(image.binding.visual_ordinal for image in self.images)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("editorial segment image uses must be unique and ordered")
        return self


type CuratedMixedSegment = Annotated[
    CuratedNativeSegment | CuratedCanonicalSegment | CuratedEditorialSegment,
    Field(discriminator="kind"),
]


class CuratedMixedRenderRequest(StrictModel):
    schema_version: Literal["curated-hwpx-render-request/3.0"] = "curated-hwpx-render-request/3.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: _Sha
    input_plan_sha256: _Sha
    profile: Literal["CURATED_EDITABLE_MIXED_V1"] = "CURATED_EDITABLE_MIXED_V1"
    segments: tuple[CuratedMixedSegment, ...] = Field(min_length=1, max_length=200)
    handoff: ContentTeamHandoffSnapshot | None
    converter: CuratedHwpConverterSnapshot | None

    @model_validator(mode="after")
    def ordered_inputs_and_shared_resources(self) -> Self:
        if tuple(row.position for row in self.segments) != tuple(range(1, len(self.segments) + 1)):
            raise ValueError("mixed segments must be contiguous and ordered")
        native = tuple(row for row in self.segments if isinstance(row, CuratedNativeSegment))
        canonical = tuple(row for row in self.segments if not isinstance(row, CuratedNativeSegment))
        if (
            any(row.source_format == "HWP" for row in native) != (self.converter is not None)
            or bool(canonical) != (self.handoff is not None)
            or len({row.item_revision_id for row in canonical}) != len(canonical)
        ):
            raise ValueError("mixed converter/handoff or Item identities differ")
        size = sum(row.size_bytes for row in native)
        images: dict[str, int] = {}
        for row in canonical:
            if isinstance(row, CuratedCanonicalSegment):
                size += row.blueprint_size_bytes
            else:
                size += row.json_size_bytes + row.markdown_size_bytes
                for image in row.images:
                    if image.local_file in images and images[image.local_file] != image.size_bytes:
                        raise ValueError("shared image size differs between uses")
                    images[image.local_file] = image.size_bytes
        if size + sum(images.values()) > 256 * 1024 * 1024:
            raise ValueError("mixed declared input byte budget exceeded")
        return self


class CuratedMixedRenderResult(CuratedHwpxRenderResultV2):
    schema_version: Literal["curated-hwpx-render-result/3.0"] = "curated-hwpx-render-result/3.0"  # type: ignore[assignment]
    profile: Literal["CURATED_EDITABLE_MIXED_V1"] = "CURATED_EDITABLE_MIXED_V1"  # type: ignore[assignment]
    input_plan_sha256: _Sha
    native_equation_count: int = Field(strict=True, ge=0, le=1_000_000)
    native_table_count: int = Field(strict=True, ge=0, le=1_000_000)
    failure_position: int | None = Field(default=None, strict=True, ge=1, le=200)

    @model_validator(mode="after")
    def no_partial_success_counts(self) -> Self:
        if self.status == "FAILED" and (self.native_equation_count or self.native_table_count):
            raise ValueError("failed mixed render cannot advertise verified output counts")
        if self.status == "SUCCEEDED" and self.failure_position is not None:
            raise ValueError("successful mixed render cannot name a failed placement")
        return self

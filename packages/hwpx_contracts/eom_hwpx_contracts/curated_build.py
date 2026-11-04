"""Metadata-only snapshots for durable editable assembly delivery.

No source body, binary content, storage path or caller-granted authority is
persisted here. The local Builder request is a separate materialization.
"""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot, StrictModel

type Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

_GENERIC_SCHEMAS = frozenset(
    {
        "eom.assessment.item-content/1.0",
        "eom://schemas/item-registry/assessment-item-content-v1",
    }
)
_EDITORIAL_SCHEMAS = frozenset(
    {
        "eom.assessment.item-content/2.0",
        "eom.assessment.item-content/3.0",
        "eom://schemas/item-registry/assessment-item-content-v2",
        "eom://schemas/item-registry/assessment-item-content-v3",
    }
)


class CuratedArtifactMember(StrictModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: Sha256

    @field_validator("member_path")
    @classmethod
    def safe_member(cls, value: str) -> str:
        if (
            "\\" in value
            or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("unsafe curated Artifact member")
        return value


class CuratedNativeDocumentInput(StrictModel):
    kind: Literal["NATIVE_DOCUMENT"] = "NATIVE_DOCUMENT"
    position: int = Field(strict=True, ge=1, le=200)
    source_format: Literal["HWP", "HWPX"]
    document: CuratedArtifactMember
    size_bytes: int = Field(strict=True, ge=1, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_format(self) -> Self:
        media = {"HWP": "application/vnd.hancom.hwp", "HWPX": "application/vnd.hancom.hwpx"}
        if (
            self.document.media_type != media[self.source_format]
            or self.document.schema_ref != "eom://schemas/content-intake/source-file/1.0"
        ):
            raise ValueError("curated native document format differs from its pointer")
        return self


class CuratedRegisteredItemInput(StrictModel):
    kind: Literal["REGISTERED_ITEM"] = "REGISTERED_ITEM"
    position: int = Field(strict=True, ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    source_content: CuratedArtifactMember
    display_content: CuratedArtifactMember
    recovery_manifest: CuratedArtifactMember | None
    editorial_markdown: CuratedArtifactMember | None

    @model_validator(mode="after")
    def exact_content_family(self) -> Self:
        source, display = self.source_content, self.display_content
        if (
            source.schema_ref not in _GENERIC_SCHEMAS | _EDITORIAL_SCHEMAS
            or source.media_type != "application/json"
            or display.media_type != "application/json"
            or (self.recovery_manifest is None) != (source == display)
            or (self.editorial_markdown is None) != (source.schema_ref in _GENERIC_SCHEMAS)
        ):
            raise ValueError("curated Item content family or rendering pointer is inconsistent")
        if source != display and (
            source.schema_ref not in _GENERIC_SCHEMAS
            or display.schema_ref not in _GENERIC_SCHEMAS
            or self.recovery_manifest is None
            or self.recovery_manifest.media_type != "application/json"
            or self.recovery_manifest.member_path != "visual-presentation.json"
            or self.recovery_manifest.schema_ref
            not in {
                "eom://schemas/external-item/creative-visual-presentation/1.0",
                "eom://schemas/external-item/creative-visual-presentation/1.1",
            }
            or self.recovery_manifest.artifact_id != display.artifact_id
            or self.recovery_manifest.artifact_revision_id != display.artifact_revision_id
        ):
            raise ValueError("curated display content lacks its exact admitted visual proof")
        if self.editorial_markdown is not None and (
            self.editorial_markdown.artifact_id != source.artifact_id
            or self.editorial_markdown.artifact_revision_id != source.artifact_revision_id
            or self.editorial_markdown.member_path != "content-team-item.md"
            or self.editorial_markdown.media_type != "text/markdown"
        ):
            raise ValueError("curated editorial Markdown differs from its source Artifact")
        return self


type CuratedBuildPlacement = Annotated[
    CuratedNativeDocumentInput | CuratedRegisteredItemInput,
    Field(discriminator="kind"),
]


class CuratedHwpxBuildInput(StrictModel):
    schema_version: Literal["curated-hwpx-build-input/1.0"] = "curated-hwpx-build-input/1.0"
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    profile: Literal["CURATED_EDITABLE_MIXED_V1"] = "CURATED_EDITABLE_MIXED_V1"
    renderer_version: Literal["1.0.0"] = "1.0.0"
    handoff: ContentTeamHandoffSnapshot | None
    converter: CuratedHwpConverterSnapshot | None
    placements: tuple[CuratedBuildPlacement, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_order_and_tools(self) -> Self:
        if tuple(row.position for row in self.placements) != tuple(
            range(1, len(self.placements) + 1)
        ):
            raise ValueError("curated build inputs must preserve contiguous assembly order")
        native = tuple(
            row for row in self.placements if isinstance(row, CuratedNativeDocumentInput)
        )
        items = tuple(row for row in self.placements if isinstance(row, CuratedRegisteredItemInput))
        if (
            any(row.source_format == "HWP" for row in native) != (self.converter is not None)
            or bool(items) != (self.handoff is not None)
            or len({row.item_revision_id for row in items}) != len(items)
            or sum(row.size_bytes for row in native) > 256 * 1024 * 1024
        ):
            raise ValueError("curated build tools, unique Items or input budget differ")
        return self

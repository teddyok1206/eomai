"""Immutable resolved selection for an editable, mixed-source document assembly.

The manifest pins inputs only. It never asserts that HWP conversion, package
normalization, HWPX building, or human layout review succeeded.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

CURATED_DOCUMENT_ASSEMBLY_MANIFEST_SCHEMA = "curated-document-assembly-manifest-v1"
CURATED_DOCUMENT_ASSEMBLY_MANIFEST_SCHEMA_REF = (
    "eom://schemas/assessment-assembly/curated-document-assembly-manifest/1.0"
)

_SOURCE_MEDIA = {
    "HWP": "application/vnd.hancom.hwp",
    "HWPX": "application/vnd.hancom.hwpx",
}


class CuratedExternalDocumentPlacement(FrozenModel):
    placement_kind: Literal["EXTERNAL_SOURCE_DOCUMENT"] = "EXTERNAL_SOURCE_DOCUMENT"
    position: int = Field(strict=True, ge=1, le=200)
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    observation_sha256: Sha256
    edition: Literal[2, 3]
    source_format: Literal["HWP", "HWPX"]
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    document_artifact: OriginArtifactMemberPointer
    document_size_bytes: int = Field(strict=True, ge=1, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_detected_source_format(self) -> Self:
        if (
            self.document_artifact.schema_ref != "eom://schemas/content-intake/source-file/1.0"
            or self.document_artifact.media_type != _SOURCE_MEDIA[self.source_format]
        ):
            raise ValueError("curated source format differs from its Intake Artifact")
        return self


class CuratedRegisteredItemPlacement(FrozenModel):
    placement_kind: Literal["REGISTERED_ITEM_REVISION"] = "REGISTERED_ITEM_REVISION"
    position: int = Field(strict=True, ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256


class CuratedPastExamItemPlacement(CuratedRegisteredItemPlacement):
    placement_kind: Literal["PAST_EXAM_ITEM_REVISION"] = "PAST_EXAM_ITEM_REVISION"  # type: ignore[assignment]


type CuratedResolvedPlacement = Annotated[
    CuratedExternalDocumentPlacement
    | CuratedRegisteredItemPlacement
    | CuratedPastExamItemPlacement,
    Field(discriminator="placement_kind"),
]


class CuratedDocumentAssemblyManifestV1(FrozenModel):
    """One ordered pinned input set, distinct from an HWPX output receipt."""

    schema_version: Literal["curated-document-assembly-manifest/1.0"] = (
        "curated-document-assembly-manifest/1.0"
    )
    assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    selection_sha256: Sha256
    placements: tuple[CuratedResolvedPlacement, ...] = Field(min_length=1, max_length=200)
    created_by: ActorId
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def ordered_unique_exact_manifest(self) -> Self:
        if tuple(row.position for row in self.placements) != tuple(
            range(1, len(self.placements) + 1)
        ):
            raise ValueError("curated placements must be contiguous and ordered")
        keys = tuple(
            ("EXTERNAL", row.source_id)
            if isinstance(row, CuratedExternalDocumentPlacement)
            else ("ITEM", row.item_revision_id)
            for row in self.placements
        )
        if len(keys) != len(set(keys)):
            raise ValueError("curated placements repeat a source or Item revision")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("curated assembly manifest hash differs")
        return self

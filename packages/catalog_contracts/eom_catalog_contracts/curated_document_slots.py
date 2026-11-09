"""Occurrence identities for editable curated assemblies; no file materialization.

V1/V2 drafts remain immutable compatibility contracts. V3 separates the position
from its target so repeats, empty positions and cross-section moves are explicit.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.curated_document_assembly import (
    CuratedDocumentAssemblyManifestV1,
    CuratedExternalDocumentPlacement,
)
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

PlacementId = Annotated[str, Field(pattern=r"^placement_[0-9a-f]{32}$")]
AssemblyId = Annotated[str, Field(pattern=r"^assembly_[0-9a-f]{32}$")]
AssemblyRevisionId = Annotated[str, Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")]
SlotPosition = Annotated[int, Field(strict=True, ge=1, le=100000)]
DisplayNumber = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[^\x00-\x1f\x7f]+$")]


class EmptySlotTarget(FrozenModel):
    placement_kind: Literal["EMPTY"]


class ExternalSlotTarget(FrozenModel):
    placement_kind: Literal["EXTERNAL_SOURCE_DOCUMENT"]
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: Sha256
    edition: Literal[2, 3]
    source_format: Literal["HWP", "HWPX"]


class RegisteredSlotTarget(FrozenModel):
    placement_kind: Literal["REGISTERED_ITEM_REVISION", "PAST_EXAM_ITEM_REVISION"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256


class ResolvedExternalSlotTarget(ExternalSlotTarget):
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    document_artifact: OriginArtifactMemberPointer
    document_size_bytes: int = Field(strict=True, ge=1, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def source_media(self) -> Self:
        if (
            self.document_artifact.schema_ref != "eom://schemas/content-intake/source-file/1.0"
            or self.document_artifact.media_type
            != f"application/vnd.hancom.{self.source_format.lower()}"
        ):
            raise ValueError("curated source format differs from its Intake Artifact")
        return self


type SlotTarget = Annotated[
    EmptySlotTarget | ExternalSlotTarget | RegisteredSlotTarget,
    Field(discriminator="placement_kind"),
]
type ResolvedSlotTarget = Annotated[
    EmptySlotTarget | ResolvedExternalSlotTarget | RegisteredSlotTarget,
    Field(discriminator="placement_kind"),
]


class SlotCopyOrigin(FrozenModel):
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha256
    placement_id: PlacementId


class _SlotOccurrence(FrozenModel):
    placement_id: PlacementId
    position: SlotPosition
    points_milli: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None
    display_number: DisplayNumber | None
    note: str = Field(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")
    copied_from: SlotCopyOrigin | None


class CuratedSlot(_SlotOccurrence):
    target: SlotTarget


class ResolvedCuratedSlot(_SlotOccurrence):
    target: ResolvedSlotTarget

    def selection(self) -> CuratedSlot:
        target: SlotTarget = self.target
        if isinstance(target, ResolvedExternalSlotTarget):
            target = ExternalSlotTarget.model_validate(
                target.model_dump(include=set(ExternalSlotTarget.model_fields))
            )
        return CuratedSlot(**self.model_dump(exclude={"target"}), target=target)


def validate_slot_order(slots: tuple[CuratedSlot, ...] | tuple[ResolvedCuratedSlot, ...]) -> None:
    """O(n) occurrence validation; target identity deliberately is not unique."""

    identities: set[str] = set()
    for expected, slot in enumerate(slots, 1):
        if slot.position != expected:
            raise ValueError("slot positions must be contiguous and ordered")
        if slot.placement_id in identities:
            raise ValueError("slot occurrence identity must be unique")
        identities.add(slot.placement_id)


class CuratedDocumentAssemblyDraftV3(FrozenModel):
    schema_version: Literal["curated-document-assembly-draft/3.0"]
    title: str = Field(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")
    placements: tuple[CuratedSlot, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def ordered_occurrences(self) -> Self:
        validate_slot_order(self.placements)
        if self.title != self.title.strip():
            raise ValueError("assembly title must not have outer whitespace")
        return self


class CuratedDocumentAssemblyManifestV2(FrozenModel):
    schema_version: Literal["curated-document-assembly-manifest/2.0"]
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    revision_number: int = Field(strict=True, ge=1)
    previous_revision_id: AssemblyRevisionId | None
    selection_sha256: Sha256
    placements: tuple[ResolvedCuratedSlot, ...] = Field(max_length=100000)
    created_by: ActorId
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def immutable_occurrences(self) -> Self:
        validate_slot_order(self.placements)
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("assembly predecessor must be null only for revision one")
        if self.previous_revision_id == self.assembly_revision_id:
            raise ValueError("assembly revision cannot precede itself")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("curated assembly manifest hash differs")
        return self


def logical_slot_target_key(target: SlotTarget | ResolvedSlotTarget) -> tuple[str, str] | None:
    """Identity only: cross-source equivalence requires the Catalog lineage owner."""

    if isinstance(target, RegisteredSlotTarget):
        return ("ITEM", target.item_id)
    if isinstance(target, ExternalSlotTarget):
        return ("SOURCE", target.source_id)
    return None


type CuratedDeliveryManifest = CuratedDocumentAssemblyManifestV1 | CuratedDocumentAssemblyManifestV2
type CuratedDeliveryTarget = ResolvedExternalSlotTarget | RegisteredSlotTarget


def iter_curated_delivery_positions(
    manifest: CuratedDeliveryManifest,
) -> Iterator[tuple[int, str | None, CuratedDeliveryTarget]]:
    """Small internal read projection, preserving released manifest bytes and each use.

    A historical private placement has no occurrence identity. Do not invent one
    or apply the old unique-target rule to the content-owned successor.
    """
    if isinstance(manifest, CuratedDocumentAssemblyManifestV2):
        for slot in manifest.placements:
            if isinstance(slot.target, EmptySlotTarget):
                raise ValueError("empty content positions cannot be rendered")
            yield slot.position, slot.placement_id, slot.target
    else:
        for row in manifest.placements:
            target_type = (
                ResolvedExternalSlotTarget
                if isinstance(row, CuratedExternalDocumentPlacement)
                else RegisteredSlotTarget
            )
            yield (
                row.position,
                None,
                target_type.model_validate(row.model_dump(include=set(target_type.model_fields))),
            )

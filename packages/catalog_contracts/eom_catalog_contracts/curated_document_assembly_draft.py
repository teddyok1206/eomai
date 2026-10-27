"""Presentation-neutral ordered selection for a future mixed-source Assembly."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel

PinnedSha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ExternalSourcePlacement(FrozenModel):
    placement_kind: Literal["EXTERNAL_SOURCE_DOCUMENT"]
    position: int = Field(ge=1, le=200)
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: PinnedSha256
    edition: Literal[2, 3]
    source_format: Literal["HWP", "HWPX"]


class RegisteredItemPlacement(FrozenModel):
    placement_kind: Literal["REGISTERED_ITEM_REVISION"]
    position: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: PinnedSha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: PinnedSha256


class PastExamItemPlacement(RegisteredItemPlacement):
    placement_kind: Literal["PAST_EXAM_ITEM_REVISION"]  # type: ignore[assignment]


type CuratedPlacement = Annotated[
    ExternalSourcePlacement | RegisteredItemPlacement | PastExamItemPlacement,
    Field(discriminator="placement_kind"),
]


class CuratedDocumentAssemblyDraftV1(FrozenModel):
    """An ordered, non-authoritative selection requiring server-side reauthorization."""

    schema_version: Literal["curated-document-assembly-draft/1.0"]
    placements: tuple[CuratedPlacement, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_unique_placements(self) -> Self:
        if tuple(row.position for row in self.placements) != tuple(
            range(1, len(self.placements) + 1)
        ):
            raise ValueError("assembly positions must be contiguous and ordered")
        keys = tuple(
            ("EXTERNAL", row.source_id)
            if isinstance(row, ExternalSourcePlacement)
            else ("ITEM", row.item_revision_id)
            for row in self.placements
        )
        if len(keys) != len(set(keys)):
            raise ValueError("assembly placements must be unique")
        return self

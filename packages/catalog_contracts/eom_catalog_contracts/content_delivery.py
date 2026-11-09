"""Prepare one exact content scope for the existing curated HWPX application."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.content_planning import (
    ContentLabel,
    DeliverableRevisionId,
    EditionId,
    SectionId,
)
from eom_catalog_contracts.curated_document_slots import AssemblyId, AssemblyRevisionId
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime


class PrepareContentDelivery(FrozenModel):
    command_kind: Literal["PREPARE_DELIVERY"] = "PREPARE_DELIVERY"
    edition_id: EditionId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    section_ids: tuple[SectionId, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_selection(self) -> Self:
        if len(set(self.section_ids)) != len(self.section_ids):
            raise ValueError("output scope repeats a section")
        return self


class ContentDeliveryPrepared(FrozenModel):
    schema_version: Literal["content-delivery-prepared/1.0"] = "content-delivery-prepared/1.0"
    edition_id: EditionId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    scope_sha256: Sha256
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha256
    placement_count: int = Field(strict=True, ge=1, le=100000)
    created_at: UtcDatetime
    replayed: bool


class ReadContentDeliveries(FrozenModel):
    query_kind: Literal["DELIVERIES"]
    edition_id: EditionId
    before_id: AssemblyRevisionId | None
    limit: int = Field(strict=True, ge=1, le=100)


class ContentDeliveryEntry(FrozenModel):
    prepared: ContentDeliveryPrepared
    section_labels: tuple[ContentLabel, ...] = Field(min_length=1, max_length=3)
    section_count: int = Field(strict=True, ge=1, le=10000)
    matches_current_revision: bool


class ContentDeliveryList(FrozenModel):
    result_kind: Literal["DELIVERIES"] = "DELIVERIES"
    edition_id: EditionId
    rows: tuple[ContentDeliveryEntry, ...] = Field(max_length=100)
    next_id: AssemblyRevisionId | None

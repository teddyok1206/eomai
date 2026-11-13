"""Final-array edit commands; the Catalog applies a section set in one transaction."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.content_planning import (
    CONTENT_MAX_SECTIONS,
    AcademicYear,
    ContentLabel,
    ContentSectionStructure,
    DeliverableRevisionId,
    SectionId,
    validate_section_tree,
)
from eom_catalog_contracts.curated_document_slots import (
    AssemblyRevisionId,
    CuratedSlot,
    validate_slot_order,
)
from eom_catalog_contracts.models import FrozenModel, Sha256


class SectionSlotChange(FrozenModel):
    section_id: SectionId
    before_assembly_revision_id: AssemblyRevisionId
    before_manifest_sha256: Sha256
    placements: tuple[CuratedSlot, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def ordered_occurrences(self) -> Self:
        validate_slot_order(self.placements)
        return self


class SaveContentSections(FrozenModel):
    change_kind: Literal["SAVE_SECTIONS"]
    expected_revision_id: DeliverableRevisionId
    expected_sha256: Sha256
    changes: tuple[SectionSlotChange, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_changes(self) -> Self:
        if len({change.section_id for change in self.changes}) != len(self.changes):
            raise ValueError("a section must have exactly one final array")
        ids = [slot.placement_id for change in self.changes for slot in change.placements]
        if len(ids) != len(set(ids)):
            raise ValueError("a placement cannot occur in two final section arrays")
        return self


class SaveContentStructure(FrozenModel):
    change_kind: Literal["SAVE_STRUCTURE"]
    expected_revision_id: DeliverableRevisionId
    expected_sha256: Sha256
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    sections: tuple[ContentSectionStructure, ...] = Field(max_length=CONTENT_MAX_SECTIONS)
    confirmed_removed_sections: tuple[SectionId, ...] = Field(max_length=CONTENT_MAX_SECTIONS)

    @model_validator(mode="after")
    def structure(self) -> Self:
        validate_section_tree(self.sections)
        if len(set(self.confirmed_removed_sections)) != len(self.confirmed_removed_sections):
            raise ValueError("confirmed removed sections must be unique")
        if set(self.confirmed_removed_sections) & {section.section_id for section in self.sections}:
            raise ValueError("a retained section cannot be confirmed as removed")
        if self.edition_label != self.edition_label.strip():
            raise ValueError("edition label must not have outer whitespace")
        return self

"""Graph-pinned item-bank read models."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel


class ItemBankCurriculumUnitView(ApiModel):
    curriculum_unit_id: str = Field(pattern=r"^currunit_[0-9a-f]{32}$")
    unit_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    unit_code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=200)
    unit_level: Literal["MAJOR", "MIDDLE", "MINOR", "ACHIEVEMENT_STANDARD"]
    parent_unit_id: str | None = Field(default=None, pattern=r"^currunit_[0-9a-f]{32}$")


class ItemBankEntryView(ApiModel):
    """One immutable Item placement in a pinned published Graph snapshot."""

    schema_version: Literal["item-bank-entry-view/1.0"] = "item-bank-entry-view/1.0"
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_state: Literal["APPROVED", "SUPERSEDED"]
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    curriculum_units: tuple[ItemBankCurriculumUnitView, ...] = Field(min_length=1, max_length=8)
    placement_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_graph_item(self) -> Self:
        unit_keys = tuple(unit.unit_key for unit in self.curriculum_units)
        unit_ids = tuple(unit.curriculum_unit_id for unit in self.curriculum_units)
        if unit_keys != tuple(sorted(set(unit_keys))) or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("item-bank curriculum units must be sorted and unique")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self

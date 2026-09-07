"""Mock-exam assembly API DTOs."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime


class MockExamScoreBucketView(ApiModel):
    points_milli: int = Field(ge=1)
    count: int = Field(ge=1)


class MockExamCoverageRequirementView(ApiModel):
    requirement_id: str
    selection_count: int = Field(ge=1)
    distinct_units: bool
    allowed_unit_keys: tuple[str, ...] = Field(min_length=1)


class MockExamAssemblyPolicyView(ApiModel):
    schema_version: Literal["mock-exam-assembly-policy/1.0"]
    policy_key: str
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    subject_key: str
    item_count: int = Field(ge=1)
    total_points_milli: int = Field(ge=1)
    score_distribution: tuple[MockExamScoreBucketView, ...]
    required_slot_count: int = Field(ge=0)
    balance_slot_count: int = Field(ge=0)
    inquiry_min_count: int = Field(ge=0)
    inquiry_max_count: int = Field(ge=0)
    coverage_requirements: tuple[MockExamCoverageRequirementView, ...]
    eligible_item_revision_states: tuple[Literal["APPROVED", "SUPERSEDED"], ...]
    outline_key: str
    outline_revision: str
    outline_sha256: Sha256
    guidance_revision: int = Field(ge=1)
    guidance_reviewed_document_sha256: Sha256
    guidance_original_sha256: Sha256


class MockExamAssemblySelectionInput(ApiModel):
    position: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    curriculum_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=16)
    points_milli: int = Field(ge=1)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = None
    is_inquiry: bool
    material_type: str = Field(min_length=1, max_length=64)


class CreateMockExamAssemblyRequest(ApiModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    placements: tuple[MockExamAssemblySelectionInput, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_unique_placements(self) -> Self:
        positions = tuple(row.position for row in self.placements)
        if positions != tuple(range(1, len(self.placements) + 1)):
            raise ValueError("assembly positions must be contiguous and ordered")
        revision_ids = tuple(row.item_revision_id for row in self.placements)
        if len(revision_ids) != len(set(revision_ids)):
            raise ValueError("assembly Item revisions must be unique")
        return self


class MockExamAssemblyPlacementView(MockExamAssemblySelectionInput):
    placement_id: str = Field(pattern=r"^placement_[0-9a-f]{32}$")
    display_number: str
    major_unit_key: str
    item_type_key: str
    difficulty_band: str | None = None
    review_annotation_sha256: Sha256


class MockExamAssemblyValidationView(ApiModel):
    item_count: int = Field(ge=1)
    total_points_milli: int = Field(ge=1)
    score_distribution: dict[str, int]
    required_slot_count: int = Field(ge=0)
    balance_slot_count: int = Field(ge=0)
    inquiry_count: int = Field(ge=0)
    coverage_requirement_ids: tuple[str, ...]
    major_unit_counts: dict[str, int]


class MockExamAssemblyView(ApiModel):
    schema_version: Literal["mock-exam-assembly-manifest/1.0"]
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_form_id: str = Field(pattern=r"^form_[0-9a-f]{32}$")
    assessment_form_revision_id: str = Field(pattern=r"^formrev_[0-9a-f]{32}$")
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    outline_key: str
    outline_revision: str
    outline_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    placements: tuple[MockExamAssemblyPlacementView, ...]
    validation: MockExamAssemblyValidationView
    revision_state: Literal["RELEASED"]
    manifest_sha256: Sha256
    created_at: UtcDatetime
    created_by: str

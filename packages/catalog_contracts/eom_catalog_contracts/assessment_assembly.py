"""Policy-driven immutable mock-exam assembly contracts."""

from __future__ import annotations

import json
from collections import Counter
from importlib.resources import files
from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

INTEGRATED_SCIENCE_ASSEMBLY_POLICY_RESOURCE = "integrated-science-mock-exam-assembly-v1.json"
INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256 = (
    "sha256:312627f1dd8ba71edd7735c9e63ebf41e7d2080550a817c19299d8159b510d04"
)
INTEGRATED_SCIENCE_LAYOUT_POLICY_RESOURCE = "integrated-science-mock-exam-layout-v1.json"
INTEGRATED_SCIENCE_LAYOUT_POLICY_SHA256 = (
    "sha256:a085e1857e3bdd1a7326e7fe407e80a91ee401355cab516f29df4cb780b26a19"
)
INTEGRATED_SCIENCE_RATING_POLICY_RESOURCE = "integrated-science-item-rating-v1.json"
INTEGRATED_SCIENCE_RATING_POLICY_SHA256 = (
    "sha256:d45cba594eee29fb78d2d4550ba780f39955c97a5ac5b8e396f7bc6028490c92"
)

MockExamMaterialProfile = Literal["TEXT", "DATA", "TABLE", "IMAGE", "MIXED", "INQUIRY"]
MockExamPreferredDifficulty = Literal["LOW", "MEDIUM", "HIGH"]
MockExamReviewRating = Literal["A", "B", "C"]


class MockExamScoreBucket(FrozenModel):
    points_milli: int = Field(ge=1, le=1_000_000)
    count: int = Field(ge=1, le=200)


class MockExamCoverageRequirement(FrozenModel):
    requirement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    selection_count: int = Field(ge=1, le=20)
    distinct_units: bool
    allowed_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def deterministic_units(self) -> MockExamCoverageRequirement:
        if self.allowed_unit_keys != tuple(sorted(set(self.allowed_unit_keys))):
            raise ValueError("coverage unit keys must be sorted and unique")
        if self.distinct_units and self.selection_count > len(self.allowed_unit_keys):
            raise ValueError("distinct coverage requires enough allowed units")
        return self


class MockExamGuidancePointer(FrozenModel):
    guidance_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    revision: int = Field(ge=1)
    reviewed_document_sha256: Sha256
    original_sha256: Sha256


class MockExamAssemblyPolicyV1(FrozenModel):
    schema_version: Literal["mock-exam-assembly-policy/1.0"]
    policy_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: Literal["RELEASED"]
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_count: int = Field(ge=1, le=200)
    total_points_milli: int = Field(ge=1, le=1_000_000)
    score_distribution: tuple[MockExamScoreBucket, ...] = Field(min_length=1, max_length=20)
    required_slot_count: int = Field(ge=0, le=200)
    balance_slot_count: int = Field(ge=0, le=200)
    inquiry_min_count: int = Field(ge=0, le=200)
    inquiry_max_count: int = Field(ge=0, le=200)
    coverage_requirements: tuple[MockExamCoverageRequirement, ...] = Field(
        min_length=1, max_length=100
    )
    eligible_item_revision_states: tuple[Literal["APPROVED", "SUPERSEDED"], ...]
    outline_key: str = Field(min_length=1, max_length=128)
    outline_revision: str = Field(min_length=1, max_length=32)
    outline_sha256: Sha256
    guidance_pointer: MockExamGuidancePointer

    @model_validator(mode="after")
    def coherent_policy(self) -> MockExamAssemblyPolicyV1:
        score_keys = tuple(item.points_milli for item in self.score_distribution)
        if score_keys != tuple(sorted(set(score_keys))):
            raise ValueError("score buckets must be sorted and unique")
        if sum(item.count for item in self.score_distribution) != self.item_count:
            raise ValueError("score bucket counts must sum to item count")
        if sum(item.points_milli * item.count for item in self.score_distribution) != (
            self.total_points_milli
        ):
            raise ValueError("score buckets must sum to total points")
        if self.required_slot_count + self.balance_slot_count != self.item_count:
            raise ValueError("required and balance slots must sum to item count")
        if not 0 <= self.inquiry_min_count <= self.inquiry_max_count <= self.item_count:
            raise ValueError("inquiry bounds are incoherent")
        requirement_ids = tuple(item.requirement_id for item in self.coverage_requirements)
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("coverage requirements must be sorted and unique")
        if sum(item.selection_count for item in self.coverage_requirements) != (
            self.required_slot_count
        ):
            raise ValueError("coverage selections must sum to required slots")
        if self.eligible_item_revision_states != tuple(
            sorted(set(self.eligible_item_revision_states))
        ):
            raise ValueError("eligible revision states must be sorted and unique")
        return self


class MockExamLayoutSlotV1(FrozenModel):
    slot_id: str = Field(pattern=r"^slot-[0-9]{2,3}$")
    position: int = Field(ge=1, le=200)
    points_milli: int = Field(ge=1, le=1_000_000)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"
    )
    balance_large_unit_key: str | None = Field(default=None, pattern=r"^eom\.is\.large\.[1-6]$")
    inquiry_required: bool
    preferred_difficulty: MockExamPreferredDifficulty
    preferred_material_profiles: tuple[MockExamMaterialProfile, ...] = Field(
        min_length=1, max_length=6
    )

    @model_validator(mode="after")
    def coherent_slot(self) -> MockExamLayoutSlotV1:
        required = self.coverage_role == "REQUIRED"
        if required != (self.coverage_requirement_id is not None):
            raise ValueError("required layout slots must bind one coverage requirement")
        if required == (self.balance_large_unit_key is not None):
            raise ValueError("only balance layout slots bind one large unit")
        if self.preferred_material_profiles != tuple(
            dict.fromkeys(self.preferred_material_profiles)
        ):
            raise ValueError("preferred material profiles must be unique and ordered")
        return self


class MockExamLayoutPolicyV1(FrozenModel):
    schema_version: Literal["mock-exam-layout-policy/1.0"]
    layout_policy_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    layout_policy_revision_id: str = Field(pattern=r"^layoutpolicyrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: Literal["RELEASED"]
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    assembly_policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    assembly_policy_sha256: Sha256
    guidance_revision: int = Field(ge=1)
    guidance_reviewed_document_sha256: Sha256
    slots: tuple[MockExamLayoutSlotV1, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def coherent_layout(self) -> MockExamLayoutPolicyV1:
        positions = tuple(slot.position for slot in self.slots)
        if positions != tuple(range(1, len(self.slots) + 1)):
            raise ValueError("layout slots must be contiguous and ordered")
        slot_ids = tuple(slot.slot_id for slot in self.slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("layout slot IDs must be unique")
        return self


class MockExamRatingPolicyV1(FrozenModel):
    schema_version: Literal["mock-exam-rating-policy/1.0"]
    rating_policy_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: Literal["RELEASED"]
    review_decision: Literal["APPROVE"]
    rating_field: Literal["final_rating"]
    eligible_ratings: tuple[MockExamReviewRating, ...] = Field(min_length=1, max_length=3)
    guidance_revision: int = Field(ge=1)
    guidance_original_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_ratings(self) -> MockExamRatingPolicyV1:
        if self.eligible_ratings != tuple(sorted(set(self.eligible_ratings))):
            raise ValueError("eligible review ratings must be sorted and unique")
        return self


class MockExamContentPointerV1(FrozenModel):
    item_component_id: str = Field(pattern=r"^itemcomponent_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["assessment-item-content.json"]
    schema_ref: Literal["eom.assessment.item-content/2.0"]
    media_type: Literal["application/json"]
    sha256: Sha256
    editorial_markdown_member: Literal["content-team-item.md"]
    editorial_markdown_sha256: Sha256


class MockExamReviewPointerV1(FrozenModel):
    item_review_record_id: str = Field(pattern=r"^itemreview_[0-9a-f]{32}$")
    review_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    review_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    review_sha256: Sha256
    decision: Literal["APPROVE"]
    final_rating: MockExamReviewRating


class MockExamPlanningCandidateV1(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    item_current_revision: bool
    graph_item_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    graph_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    graph_occurrence_placement_node_id: str | None = Field(
        default=None, pattern=r"^knode_[0-9a-f]{32}$"
    )
    curriculum_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=16)
    large_unit_key: str = Field(pattern=r"^eom\.is\.large\.[1-6]$")
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    is_inquiry: bool
    material_profile: MockExamMaterialProfile
    source_score_display: Literal["2", "2.5", "3"]
    content: MockExamContentPointerV1
    review: MockExamReviewPointerV1
    usage_count: int = Field(ge=0)
    latest_usage_at: UtcDatetime | None
    usage_fingerprint_sha256: Sha256

    @model_validator(mode="after")
    def coherent_candidate(self) -> MockExamPlanningCandidateV1:
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("planning candidate curriculum unit keys must be sorted and unique")
        if (self.graph_source_class == "PAST_EXAM") != (
            self.graph_occurrence_placement_node_id is not None
        ):
            raise ValueError("past-exam planning candidates require an occurrence placement")
        return self


class MockExamUsageSnapshotV1(FrozenModel):
    schema_version: Literal["mock-exam-usage-snapshot/1.0"]
    usage_snapshot_id: str = Field(pattern=r"^usagesnapshot_[0-9a-f]{32}$")
    captured_at: UtcDatetime
    candidate_revision_count: int = Field(ge=0, le=5_000)
    usage_record_count: int = Field(ge=0)
    usage_records_sha256: Sha256
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def self_hash_matches(self) -> MockExamUsageSnapshotV1:
        value = self.model_dump(mode="json", exclude={"usage_snapshot_id", "snapshot_sha256"})
        expected = content_sha256(value)
        if self.snapshot_sha256 != expected or self.usage_snapshot_id != (
            "usagesnapshot_" + expected.removeprefix("sha256:")[:32]
        ):
            raise ValueError("usage snapshot identity does not match canonical content")
        return self


class MockExamPlannedPlacementV1(FrozenModel):
    slot_id: str = Field(pattern=r"^slot-[0-9]{2,3}$")
    position: int = Field(ge=1, le=200)
    display_number: str = Field(min_length=1, max_length=32)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_item_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    graph_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    graph_occurrence_placement_node_id: str | None = Field(
        default=None, pattern=r"^knode_[0-9a-f]{32}$"
    )
    curriculum_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=16)
    large_unit_key: str = Field(pattern=r"^eom\.is\.large\.[1-6]$")
    points_milli: int = Field(ge=1, le=1_000_000)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"
    )
    coverage_unit_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    is_inquiry: bool
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    material_profile: MockExamMaterialProfile
    source_score_display: Literal["2", "2.5", "3"]
    content: MockExamContentPointerV1
    review: MockExamReviewPointerV1
    usage_count: int = Field(ge=0)
    latest_usage_at: UtcDatetime | None
    usage_fingerprint_sha256: Sha256
    selection_reason_sha256: Sha256

    @model_validator(mode="after")
    def coherent_placement(self) -> MockExamPlannedPlacementV1:
        if self.display_number != str(self.position):
            raise ValueError("planned display number must match its position")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("planned curriculum unit keys must be sorted and unique")
        if (self.coverage_role == "REQUIRED") != (self.coverage_requirement_id is not None):
            raise ValueError("only required planned slots bind a coverage requirement")
        if (self.coverage_role == "REQUIRED") != (self.coverage_unit_key is not None):
            raise ValueError("only required planned slots bind a selected coverage unit")
        if self.coverage_unit_key is not None and (
            self.coverage_unit_key not in self.curriculum_unit_keys
        ):
            raise ValueError("selected coverage unit is outside the Item curriculum pointers")
        if (self.graph_source_class == "PAST_EXAM") != (
            self.graph_occurrence_placement_node_id is not None
        ):
            raise ValueError("past-exam planned Items require their occurrence placement")
        return self


class MockExamAssemblyShortageV1(FrozenModel):
    slot_id: str = Field(pattern=r"^slot-[0-9]{2,3}$")
    position: int = Field(ge=1, le=200)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"
    )
    balance_large_unit_key: str | None = Field(default=None, pattern=r"^eom\.is\.large\.[1-6]$")
    inquiry_required: bool
    available_candidate_count: int = Field(ge=0, le=5_000)
    reason: Literal[
        "NO_STRUCTURAL_CANDIDATES",
        "NO_RATED_CANDIDATES",
        "SLOT_CANDIDATE_MISSING",
        "CONSTRAINT_SEARCH_EXHAUSTED",
    ]


class MockExamAssemblyPlanV1(FrozenModel):
    schema_version: Literal["mock-exam-assembly-plan/1.0"]
    status: Literal["READY", "SHORTAGE"]
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    layout_policy_revision_id: str = Field(pattern=r"^layoutpolicyrev_[0-9a-f]{32}$")
    layout_policy_sha256: Sha256
    rating_policy_revision_id: str = Field(pattern=r"^ratingpolicyrev_[0-9a-f]{32}$")
    rating_policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    usage_snapshot: MockExamUsageSnapshotV1
    resolved_candidate_count: int = Field(ge=0, le=5_000)
    rated_candidate_count: int = Field(ge=0, le=5_000)
    placements: tuple[MockExamPlannedPlacementV1, ...] = Field(max_length=200)
    shortages: tuple[MockExamAssemblyShortageV1, ...] = Field(max_length=200)
    validation: MockExamAssemblyValidationV1 | None
    search_visited_nodes: int = Field(ge=0, le=100_000)
    planned_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def coherent_plan(self) -> MockExamAssemblyPlanV1:
        ready = self.status == "READY"
        if ready != bool(self.placements) or ready == bool(self.shortages):
            raise ValueError("assembly plan status and output are incoherent")
        if ready != (self.validation is not None):
            raise ValueError("only a ready assembly plan has validation")
        positions = tuple(row.position for row in self.placements)
        if positions and positions != tuple(range(1, len(positions) + 1)):
            raise ValueError("planned placements must be contiguous and ordered")
        if len({row.item_revision_id for row in self.placements}) != len(self.placements):
            raise ValueError("planned Item revisions must be unique")
        if self.rated_candidate_count > self.resolved_candidate_count:
            raise ValueError("rated candidate count exceeds resolved candidates")
        value = self.model_dump(mode="json", exclude={"plan_sha256"})
        if content_sha256(value) != self.plan_sha256:
            raise ValueError("assembly plan hash does not match canonical content")
        return self


class MockExamAssemblySelection(FrozenModel):
    position: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    curriculum_unit_keys: tuple[str, ...] = Field(min_length=1, max_length=16)
    points_milli: int = Field(ge=1, le=1_000_000)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"
    )
    is_inquiry: bool
    material_type: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def coherent_selection(self) -> MockExamAssemblySelection:
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("curriculum unit keys must be sorted and unique")
        if (self.coverage_role == "REQUIRED") != (self.coverage_requirement_id is not None):
            raise ValueError("only required slots bind a coverage requirement")
        return self


class CreateMockExamAssembly(FrozenModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    placements: tuple[MockExamAssemblySelection, ...] = Field(min_length=1, max_length=200)
    actor_id: ActorId

    @model_validator(mode="after")
    def deterministic_placements(self) -> CreateMockExamAssembly:
        positions = tuple(item.position for item in self.placements)
        if positions != tuple(range(1, len(self.placements) + 1)):
            raise ValueError("assembly positions must be contiguous and ordered")
        item_revision_ids = tuple(item.item_revision_id for item in self.placements)
        if len(item_revision_ids) != len(set(item_revision_ids)):
            raise ValueError("assembly item revisions must be unique")
        return self


class MockExamAssemblyPlacementV1(MockExamAssemblySelection):
    placement_id: str = Field(pattern=r"^placement_[0-9a-f]{32}$")
    display_number: str = Field(min_length=1, max_length=32)
    major_unit_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, max_length=64)
    review_annotation_sha256: Sha256


class MockExamAssemblyValidationV1(FrozenModel):
    item_count: int = Field(ge=1, le=200)
    total_points_milli: int = Field(ge=1, le=1_000_000)
    score_distribution: dict[str, int]
    required_slot_count: int = Field(ge=0, le=200)
    balance_slot_count: int = Field(ge=0, le=200)
    inquiry_count: int = Field(ge=0, le=200)
    coverage_requirement_ids: tuple[str, ...]
    major_unit_counts: dict[str, int]

    @model_validator(mode="after")
    def coherent_counts(self) -> MockExamAssemblyValidationV1:
        if self.coverage_requirement_ids != tuple(sorted(set(self.coverage_requirement_ids))):
            raise ValueError("coverage requirement IDs must be sorted and unique")
        if (
            sum(self.score_distribution.values()) != self.item_count
            or sum(self.major_unit_counts.values()) != self.item_count
            or self.required_slot_count + self.balance_slot_count != self.item_count
            or any(not key.isdigit() or count < 0 for key, count in self.score_distribution.items())
            or any(not key or count < 0 for key, count in self.major_unit_counts.items())
        ):
            raise ValueError("assembly validation counts are incoherent")
        return self


class MockExamAssemblyManifestV1(FrozenModel):
    schema_version: Literal["mock-exam-assembly-manifest/1.0"]
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_form_id: str = Field(pattern=r"^form_[0-9a-f]{32}$")
    assessment_form_revision_id: str = Field(pattern=r"^formrev_[0-9a-f]{32}$")
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    outline_key: str = Field(min_length=1, max_length=128)
    outline_revision: str = Field(min_length=1, max_length=32)
    outline_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    placements: tuple[MockExamAssemblyPlacementV1, ...] = Field(min_length=1, max_length=200)
    validation: MockExamAssemblyValidationV1
    revision_state: Literal["RELEASED"]
    manifest_sha256: Sha256
    created_at: UtcDatetime
    created_by: ActorId

    @model_validator(mode="after")
    def self_hash_matches(self) -> MockExamAssemblyManifestV1:
        value = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if content_sha256(value) != self.manifest_sha256:
            raise ValueError("assembly manifest hash does not match canonical content")
        if (
            tuple(row.position for row in self.placements)
            != tuple(range(1, len(self.placements) + 1))
            or len({row.item_revision_id for row in self.placements}) != len(self.placements)
            or self.validation.item_count != len(self.placements)
            or self.validation.total_points_milli
            != sum(row.points_milli for row in self.placements)
        ):
            raise ValueError("assembly manifest placement projection is incoherent")
        return self


class CreatePlannedMockExamAssembly(FrozenModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256
    expected_plan_sha256: Sha256
    planned_at: UtcDatetime
    actor_id: ActorId


class PreviewMockExamAssemblyPlan(FrozenModel):
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: Sha256


class MockExamAssemblyManifestV2(FrozenModel):
    schema_version: Literal["mock-exam-assembly-manifest/2.0"]
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    assessment_form_id: str = Field(pattern=r"^form_[0-9a-f]{32}$")
    assessment_form_revision_id: str = Field(pattern=r"^formrev_[0-9a-f]{32}$")
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    display_label: str = Field(min_length=1, max_length=128)
    plan: MockExamAssemblyPlanV1
    revision_state: Literal["RELEASED"]
    manifest_sha256: Sha256
    created_at: UtcDatetime
    created_by: ActorId

    @model_validator(mode="after")
    def self_hash_matches(self) -> MockExamAssemblyManifestV2:
        if self.plan.status != "READY" or self.plan.validation is None:
            raise ValueError("released assembly manifest requires one ready plan")
        value = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if content_sha256(value) != self.manifest_sha256:
            raise ValueError("assembly manifest hash does not match canonical content")
        return self


MockExamAssemblyManifestContract = MockExamAssemblyManifestV1 | MockExamAssemblyManifestV2


def load_integrated_science_mock_exam_policy() -> MockExamAssemblyPolicyV1:
    raw = (
        files("eom_catalog_contracts")
        .joinpath(
            "resources",
            "assessment-assembly",
            INTEGRATED_SCIENCE_ASSEMBLY_POLICY_RESOURCE,
        )
        .read_bytes()
    )
    if content_sha256(json.loads(raw)) != INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256:
        raise ValueError("packaged assembly policy hash mismatch")
    value = json.loads(raw)
    validate_contract("mock-exam-assembly-policy", value)
    return MockExamAssemblyPolicyV1.model_validate(value)


def load_integrated_science_mock_exam_layout_policy() -> MockExamLayoutPolicyV1:
    raw = (
        files("eom_catalog_contracts")
        .joinpath(
            "resources",
            "assessment-assembly",
            INTEGRATED_SCIENCE_LAYOUT_POLICY_RESOURCE,
        )
        .read_bytes()
    )
    value = json.loads(raw)
    if content_sha256(value) != INTEGRATED_SCIENCE_LAYOUT_POLICY_SHA256:
        raise ValueError("packaged mock-exam layout policy hash mismatch")
    validate_contract("mock-exam-layout-policy", value)
    return MockExamLayoutPolicyV1.model_validate(value)


def load_integrated_science_mock_exam_rating_policy() -> MockExamRatingPolicyV1:
    raw = (
        files("eom_catalog_contracts")
        .joinpath(
            "resources",
            "assessment-assembly",
            INTEGRATED_SCIENCE_RATING_POLICY_RESOURCE,
        )
        .read_bytes()
    )
    value = json.loads(raw)
    if content_sha256(value) != INTEGRATED_SCIENCE_RATING_POLICY_SHA256:
        raise ValueError("packaged mock-exam rating policy hash mismatch")
    validate_contract("mock-exam-rating-policy", value)
    return MockExamRatingPolicyV1.model_validate(value)


def validate_mock_exam_placements(
    placements: tuple[MockExamAssemblyPlacementV1, ...],
    policy: MockExamAssemblyPolicyV1,
) -> MockExamAssemblyValidationV1:
    if len(placements) != policy.item_count:
        raise ValueError("ASSEMBLY_ITEM_COUNT_INVALID")
    if tuple(item.position for item in placements) != tuple(range(1, policy.item_count + 1)):
        raise ValueError("ASSEMBLY_POSITION_SEQUENCE_INVALID")
    revision_ids = tuple(item.item_revision_id for item in placements)
    if len(revision_ids) != len(set(revision_ids)):
        raise ValueError("ASSEMBLY_ITEM_REVISION_DUPLICATE")
    total_points = sum(item.points_milli for item in placements)
    if total_points != policy.total_points_milli:
        raise ValueError("ASSEMBLY_TOTAL_POINTS_INVALID")
    score_counts = Counter(item.points_milli for item in placements)
    expected_scores = {item.points_milli: item.count for item in policy.score_distribution}
    if score_counts != expected_scores:
        raise ValueError("ASSEMBLY_SCORE_DISTRIBUTION_INVALID")
    required = tuple(item for item in placements if item.coverage_role == "REQUIRED")
    balance = tuple(item for item in placements if item.coverage_role == "BALANCE")
    if len(required) != policy.required_slot_count or len(balance) != policy.balance_slot_count:
        raise ValueError("ASSEMBLY_COVERAGE_ROLE_COUNTS_INVALID")
    requirement_by_id = {item.requirement_id: item for item in policy.coverage_requirements}
    grouped: dict[str, list[MockExamAssemblyPlacementV1]] = {}
    for placement in required:
        assert placement.coverage_requirement_id is not None
        grouped.setdefault(placement.coverage_requirement_id, []).append(placement)
    if set(grouped) != set(requirement_by_id):
        raise ValueError("ASSEMBLY_COVERAGE_REQUIREMENTS_INCOMPLETE")
    for requirement_id, requirement in requirement_by_id.items():
        selected = grouped[requirement_id]
        if len(selected) != requirement.selection_count:
            raise ValueError("ASSEMBLY_COVERAGE_SELECTION_COUNT_INVALID")
        matched_units: list[str] = []
        allowed = set(requirement.allowed_unit_keys)
        for placement in selected:
            matches = allowed.intersection(placement.curriculum_unit_keys)
            if not matches:
                raise ValueError("ASSEMBLY_COVERAGE_UNIT_INVALID")
            matched_units.extend(sorted(matches))
        if requirement.distinct_units and len(set(matched_units)) < requirement.selection_count:
            raise ValueError("ASSEMBLY_COVERAGE_UNITS_NOT_DISTINCT")
    inquiry_count = sum(item.is_inquiry for item in placements)
    if not policy.inquiry_min_count <= inquiry_count <= policy.inquiry_max_count:
        raise ValueError("ASSEMBLY_INQUIRY_COUNT_INVALID")
    major_counts = Counter(item.major_unit_key for item in placements)
    return MockExamAssemblyValidationV1(
        item_count=len(placements),
        total_points_milli=total_points,
        score_distribution={str(key): score_counts[key] for key in sorted(score_counts)},
        required_slot_count=len(required),
        balance_slot_count=len(balance),
        inquiry_count=inquiry_count,
        coverage_requirement_ids=tuple(sorted(grouped)),
        major_unit_counts={key: major_counts[key] for key in sorted(major_counts)},
    )


def validate_mock_exam_planned_placements(
    placements: tuple[MockExamPlannedPlacementV1, ...],
    policy: MockExamAssemblyPolicyV1,
) -> MockExamAssemblyValidationV1:
    """Apply the authoritative assembly invariants to server-derived placements."""

    projected = tuple(
        MockExamAssemblyPlacementV1(
            placement_id="placement_" + row.selection_reason_sha256.removeprefix("sha256:")[:32],
            position=row.position,
            display_number=row.display_number,
            item_id=row.item_id,
            item_revision_id=row.item_revision_id,
            item_manifest_sha256=row.item_manifest_sha256,
            graph_placement_node_id=row.graph_item_node_id,
            curriculum_unit_keys=(
                (row.coverage_unit_key,)
                if row.coverage_unit_key is not None
                else row.curriculum_unit_keys
            ),
            major_unit_key=row.large_unit_key,
            points_milli=row.points_milli,
            coverage_role=row.coverage_role,
            coverage_requirement_id=row.coverage_requirement_id,
            is_inquiry=row.is_inquiry,
            item_type_key=row.item_type_key,
            difficulty_band=row.difficulty_band,
            material_type=row.material_profile,
            review_annotation_sha256=row.selection_reason_sha256,
        )
        for row in placements
    )
    return validate_mock_exam_placements(projected, policy)

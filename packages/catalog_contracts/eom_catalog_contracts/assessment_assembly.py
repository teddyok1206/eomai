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

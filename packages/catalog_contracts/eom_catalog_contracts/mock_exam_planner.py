"""Deterministic fixed-slot mock-exam constraint planning."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Literal, Never

from eom_identifiers import content_sha256

from eom_catalog_contracts.assessment_assembly import (
    MockExamAssemblyCohortV1,
    MockExamAssemblyPlanV1,
    MockExamAssemblyPolicyV1,
    MockExamAssemblyShortageV1,
    MockExamCoverageRequirement,
    MockExamLayoutPolicyV1,
    MockExamLayoutSlotV1,
    MockExamPlannedPlacementV1,
    MockExamPlanningCandidateV1,
    MockExamRatingPolicyV1,
    MockExamUsageSnapshotV1,
    validate_mock_exam_planned_placements,
)

MAX_PLANNER_VISITED_NODES = 100_000

MockExamShortageReason = Literal[
    "NO_STRUCTURAL_CANDIDATES",
    "NO_RATED_CANDIDATES",
    "SLOT_CANDIDATE_MISSING",
    "CONSTRAINT_SEARCH_EXHAUSTED",
]

_DIFFICULTY_LEVELS = {
    "low": 0,
    "easy": 0,
    "하": 0,
    "medium": 1,
    "mid": 1,
    "중": 1,
    "medium-high": 2,
    "medium_high": 2,
    "hard": 2,
    "high": 2,
    "중상": 2,
    "상": 2,
}
_PREFERRED_DIFFICULTY_LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_RATING_RANK = {"A": 0, "B": 1, "C": 2}


class MockExamPlanningError(ValueError):
    """Stable domain error raised only for incoherent pinned planning inputs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_mock_exam_assembly_plan(
    *,
    policy: MockExamAssemblyPolicyV1,
    layout_policy: MockExamLayoutPolicyV1,
    rating_policy: MockExamRatingPolicyV1,
    graph_snapshot_revision_id: str,
    graph_snapshot_sha256: str,
    usage_snapshot: MockExamUsageSnapshotV1,
    resolved_candidate_count: int,
    candidates: tuple[MockExamPlanningCandidateV1, ...],
    planned_at: datetime,
    cohort: MockExamAssemblyCohortV1 | None = None,
) -> MockExamAssemblyPlanV1:
    """Select a complete immutable plan or return an empty, diagnosed shortage.

    Slot lookup is indexed once.  DFS visits the most constrained slot first while the final
    immutable projection retains the content-team layout order.  No partial plan is returned.
    """

    _validate_policy_pair(policy, layout_policy, rating_policy)
    if usage_snapshot.captured_at != planned_at:
        _fail("ASSEMBLY_USAGE_SNAPSHOT_TIME_INVALID", "planning time differs from usage snapshot")
    if usage_snapshot.candidate_revision_count != len(candidates):
        _fail(
            "ASSEMBLY_USAGE_SNAPSHOT_CANDIDATES_INVALID",
            "usage snapshot does not cover every rated candidate",
        )
    if not 0 <= len(candidates) <= resolved_candidate_count <= 5_000:
        _fail("ASSEMBLY_CANDIDATE_COUNT_INVALID", "candidate counts are incoherent")
    candidate_revision_ids = tuple(row.item_revision_id for row in candidates)
    if len(candidate_revision_ids) != len(set(candidate_revision_ids)):
        _fail("ASSEMBLY_CANDIDATE_DUPLICATE", "candidate Item revisions must be unique")
    cohort_by_position: dict[int, str] | None = None
    candidate_by_revision: dict[str, MockExamPlanningCandidateV1] | None = None
    if cohort is not None:
        cohort_by_position = {member.position: member.item_revision_id for member in cohort.members}
        candidate_by_revision = {row.item_revision_id: row for row in candidates}
        cohort_revision_ids = set(cohort_by_position.values())
        if (
            resolved_candidate_count != len(cohort.members)
            or set(candidate_by_revision) != cohort_revision_ids
        ):
            _fail(
                "ASSEMBLY_COHORT_CANDIDATES_INVALID",
                "the pinned Graph/rating candidate set differs from the exact cohort",
            )
        # ``cohort`` is an immutable revision set, not a mutable Item-head query. A later Item
        # revision must not invalidate the revision already admitted to this pinned Graph plan.
        if any(row.graph_source_class != "APPROVED_ITEM" for row in candidates):
            _fail(
                "ASSEMBLY_COHORT_SOURCE_INVALID",
                "an exact production cohort may contain only approved Item revisions",
            )

    requirement_by_id = {row.requirement_id: row for row in policy.coverage_requirements}
    options_by_slot: dict[str, tuple[MockExamPlanningCandidateV1, ...]] = {}
    for slot in layout_policy.slots:
        options: tuple[MockExamPlanningCandidateV1, ...]
        if cohort_by_position is not None and candidate_by_revision is not None:
            candidate = candidate_by_revision[cohort_by_position[slot.position]]
            options = (
                (candidate,) if _candidate_matches_slot(candidate, slot, requirement_by_id) else ()
            )
        else:
            options = tuple(
                sorted(
                    (
                        candidate
                        for candidate in candidates
                        if _candidate_matches_slot(candidate, slot, requirement_by_id)
                    ),
                    key=lambda candidate: _candidate_rank(candidate, slot),
                )
            )
        options_by_slot[slot.slot_id] = options

    if resolved_candidate_count == 0:
        return _shortage_plan(
            policy=policy,
            layout_policy=layout_policy,
            rating_policy=rating_policy,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            graph_snapshot_sha256=graph_snapshot_sha256,
            usage_snapshot=usage_snapshot,
            resolved_candidate_count=0,
            rated_candidate_count=0,
            planned_at=planned_at,
            options_by_slot=options_by_slot,
            reason="NO_STRUCTURAL_CANDIDATES",
            visited_nodes=0,
            cohort=cohort,
        )
    if not candidates:
        return _shortage_plan(
            policy=policy,
            layout_policy=layout_policy,
            rating_policy=rating_policy,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            graph_snapshot_sha256=graph_snapshot_sha256,
            usage_snapshot=usage_snapshot,
            resolved_candidate_count=resolved_candidate_count,
            rated_candidate_count=0,
            planned_at=planned_at,
            options_by_slot=options_by_slot,
            reason="NO_RATED_CANDIDATES",
            visited_nodes=0,
            cohort=cohort,
        )
    if any(not options_by_slot[slot.slot_id] for slot in layout_policy.slots):
        return _shortage_plan(
            policy=policy,
            layout_policy=layout_policy,
            rating_policy=rating_policy,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            graph_snapshot_sha256=graph_snapshot_sha256,
            usage_snapshot=usage_snapshot,
            resolved_candidate_count=resolved_candidate_count,
            rated_candidate_count=len(candidates),
            planned_at=planned_at,
            options_by_slot=options_by_slot,
            reason="SLOT_CANDIDATE_MISSING",
            visited_nodes=0,
            cohort=cohort,
        )

    search_slots = tuple(
        sorted(
            layout_policy.slots,
            key=lambda slot: (
                len(options_by_slot[slot.slot_id]),
                not slot.inquiry_required,
                slot.position,
            ),
        )
    )
    selected_by_slot: dict[str, tuple[MockExamPlanningCandidateV1, str | None]] = {}
    selected_revisions: set[str] = set()
    selected_items: set[str] = set()
    selected_units_by_requirement: dict[str, set[str]] = {}
    visited_nodes = 0

    def search(index: int, inquiry_count: int) -> bool:
        nonlocal visited_nodes
        if visited_nodes >= MAX_PLANNER_VISITED_NODES:
            return False
        if index == len(search_slots):
            return policy.inquiry_min_count <= inquiry_count <= policy.inquiry_max_count
        slot = search_slots[index]
        remaining_required_inquiry = sum(
            future.inquiry_required for future in search_slots[index + 1 :]
        )
        for candidate in options_by_slot[slot.slot_id]:
            visited_nodes += 1
            if visited_nodes > MAX_PLANNER_VISITED_NODES:
                return False
            if (
                candidate.item_revision_id in selected_revisions
                or candidate.item_id in selected_items
            ):
                continue
            next_inquiry_count = inquiry_count + int(candidate.is_inquiry)
            if next_inquiry_count > policy.inquiry_max_count:
                continue
            if next_inquiry_count + remaining_required_inquiry < policy.inquiry_min_count:
                continue
            unit_options = _coverage_unit_options(
                candidate,
                slot,
                requirement_by_id,
                selected_units_by_requirement,
            )
            if not unit_options:
                continue
            for selected_unit_key in unit_options:
                selected_by_slot[slot.slot_id] = (candidate, selected_unit_key)
                selected_revisions.add(candidate.item_revision_id)
                selected_items.add(candidate.item_id)
                if slot.coverage_requirement_id is not None and selected_unit_key is not None:
                    selected_units_by_requirement.setdefault(
                        slot.coverage_requirement_id, set()
                    ).add(selected_unit_key)
                if search(index + 1, next_inquiry_count):
                    return True
                if slot.coverage_requirement_id is not None and selected_unit_key is not None:
                    used = selected_units_by_requirement[slot.coverage_requirement_id]
                    used.remove(selected_unit_key)
                    if not used:
                        del selected_units_by_requirement[slot.coverage_requirement_id]
                selected_items.remove(candidate.item_id)
                selected_revisions.remove(candidate.item_revision_id)
                del selected_by_slot[slot.slot_id]
        return False

    if not search(0, 0):
        return _shortage_plan(
            policy=policy,
            layout_policy=layout_policy,
            rating_policy=rating_policy,
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            graph_snapshot_sha256=graph_snapshot_sha256,
            usage_snapshot=usage_snapshot,
            resolved_candidate_count=resolved_candidate_count,
            rated_candidate_count=len(candidates),
            planned_at=planned_at,
            options_by_slot=options_by_slot,
            reason="CONSTRAINT_SEARCH_EXHAUSTED",
            visited_nodes=min(visited_nodes, MAX_PLANNER_VISITED_NODES),
            cohort=cohort,
        )

    placements = tuple(
        _placement(slot, *selected_by_slot[slot.slot_id]) for slot in layout_policy.slots
    )
    validation = validate_mock_exam_planned_placements(placements, policy)
    return _finish_plan(
        {
            **_plan_header(
                policy,
                layout_policy,
                rating_policy,
                graph_snapshot_revision_id,
                graph_snapshot_sha256,
                usage_snapshot,
                planned_at,
                cohort,
            ),
            "status": "READY",
            "resolved_candidate_count": resolved_candidate_count,
            "rated_candidate_count": len(candidates),
            "placements": [row.model_dump(mode="json") for row in placements],
            "shortages": [],
            "validation": validation.model_dump(mode="json"),
            "search_visited_nodes": visited_nodes,
        }
    )


def _validate_policy_pair(
    policy: MockExamAssemblyPolicyV1,
    layout: MockExamLayoutPolicyV1,
    rating: MockExamRatingPolicyV1,
) -> None:
    if (
        layout.assembly_policy_revision_id != policy.policy_revision_id
        or layout.assembly_policy_sha256 != content_sha256(policy.model_dump(mode="json"))
        or layout.subject_key != policy.subject_key
        or len(layout.slots) != policy.item_count
        or Counter(slot.points_milli for slot in layout.slots)
        != Counter({row.points_milli: row.count for row in policy.score_distribution})
        or sum(slot.points_milli for slot in layout.slots) != policy.total_points_milli
        or sum(slot.coverage_role == "REQUIRED" for slot in layout.slots)
        != policy.required_slot_count
        or sum(slot.coverage_role == "BALANCE" for slot in layout.slots)
        != policy.balance_slot_count
    ):
        _fail("ASSEMBLY_LAYOUT_POLICY_INVALID", "layout and assembly policies differ")
    requirement_counts = Counter(
        slot.coverage_requirement_id
        for slot in layout.slots
        if slot.coverage_requirement_id is not None
    )
    if requirement_counts != Counter(
        {row.requirement_id: row.selection_count for row in policy.coverage_requirements}
    ):
        _fail("ASSEMBLY_LAYOUT_COVERAGE_INVALID", "layout coverage differs from policy")
    required_inquiries = sum(slot.inquiry_required for slot in layout.slots)
    if not policy.inquiry_min_count <= required_inquiries <= policy.inquiry_max_count:
        _fail("ASSEMBLY_LAYOUT_INQUIRY_INVALID", "layout inquiry count differs from policy")
    if rating.eligible_ratings != ("A", "B", "C"):
        _fail("ASSEMBLY_RATING_POLICY_INVALID", "rating policy is not the reviewed A/B/C rule")


def _candidate_matches_slot(
    candidate: MockExamPlanningCandidateV1,
    slot: MockExamLayoutSlotV1,
    requirement_by_id: dict[str, MockExamCoverageRequirement],
) -> bool:
    if slot.inquiry_required and not candidate.is_inquiry:
        return False
    if slot.coverage_requirement_id is None:
        return candidate.large_unit_key == slot.balance_large_unit_key
    requirement = requirement_by_id[slot.coverage_requirement_id]
    allowed = set(requirement.allowed_unit_keys)
    return bool(allowed.intersection(candidate.curriculum_unit_keys))


def _coverage_unit_options(
    candidate: MockExamPlanningCandidateV1,
    slot: MockExamLayoutSlotV1,
    requirement_by_id: dict[str, MockExamCoverageRequirement],
    selected_units_by_requirement: dict[str, set[str]],
) -> tuple[str | None, ...]:
    requirement_id = slot.coverage_requirement_id
    if requirement_id is None:
        return (None,)
    requirement = requirement_by_id[requirement_id]
    options = tuple(
        sorted(set(requirement.allowed_unit_keys).intersection(candidate.curriculum_unit_keys))
    )
    if not requirement.distinct_units:
        return options
    used = selected_units_by_requirement.get(requirement_id, set())
    return tuple(value for value in options if value not in used)


def _candidate_rank(
    candidate: MockExamPlanningCandidateV1, slot: MockExamLayoutSlotV1
) -> tuple[object, ...]:
    observed = (
        _DIFFICULTY_LEVELS.get(candidate.difficulty_band.strip().casefold())
        if candidate.difficulty_band is not None
        else None
    )
    preferred = _PREFERRED_DIFFICULTY_LEVEL[slot.preferred_difficulty]
    difficulty_distance = abs(observed - preferred) if observed is not None else 4
    try:
        material_rank = slot.preferred_material_profiles.index(candidate.material_profile)
    except ValueError:
        material_rank = len(slot.preferred_material_profiles)
    return (
        difficulty_distance,
        material_rank,
        int(candidate.is_inquiry and not slot.inquiry_required),
        _RATING_RANK[candidate.review.final_rating],
        candidate.usage_count,
        int(not candidate.item_current_revision),
        candidate.latest_usage_at.isoformat() if candidate.latest_usage_at is not None else "",
        candidate.item_revision_id,
    )


def _placement(
    slot: MockExamLayoutSlotV1,
    candidate: MockExamPlanningCandidateV1,
    selected_unit_key: str | None,
) -> MockExamPlannedPlacementV1:
    reason = {
        "slot": slot.model_dump(mode="json"),
        "item_revision_id": candidate.item_revision_id,
        "item_manifest_sha256": candidate.item_manifest_sha256,
        "graph_item_node_id": candidate.graph_item_node_id,
        "content_sha256": candidate.content.sha256,
        "review_record_id": candidate.review.item_review_record_id,
        "review_sha256": candidate.review.review_sha256,
        "usage_fingerprint_sha256": candidate.usage_fingerprint_sha256,
        "coverage_unit_key": selected_unit_key,
    }
    return MockExamPlannedPlacementV1(
        slot_id=slot.slot_id,
        position=slot.position,
        display_number=str(slot.position),
        item_id=candidate.item_id,
        item_revision_id=candidate.item_revision_id,
        item_manifest_sha256=candidate.item_manifest_sha256,
        graph_item_node_id=candidate.graph_item_node_id,
        graph_analysis_run_id=candidate.graph_analysis_run_id,
        graph_source_class=candidate.graph_source_class,
        graph_occurrence_placement_node_id=candidate.graph_occurrence_placement_node_id,
        curriculum_unit_keys=candidate.curriculum_unit_keys,
        large_unit_key=candidate.large_unit_key,
        points_milli=slot.points_milli,
        coverage_role=slot.coverage_role,
        coverage_requirement_id=slot.coverage_requirement_id,
        coverage_unit_key=selected_unit_key,
        is_inquiry=candidate.is_inquiry,
        item_type_key=candidate.item_type_key,
        difficulty_band=candidate.difficulty_band,
        material_profile=candidate.material_profile,
        source_score_display=candidate.source_score_display,
        content=candidate.content,
        review=candidate.review,
        usage_count=candidate.usage_count,
        latest_usage_at=candidate.latest_usage_at,
        usage_fingerprint_sha256=candidate.usage_fingerprint_sha256,
        selection_reason_sha256=content_sha256(reason),
    )


def _shortage_plan(
    *,
    policy: MockExamAssemblyPolicyV1,
    layout_policy: MockExamLayoutPolicyV1,
    rating_policy: MockExamRatingPolicyV1,
    graph_snapshot_revision_id: str,
    graph_snapshot_sha256: str,
    usage_snapshot: MockExamUsageSnapshotV1,
    resolved_candidate_count: int,
    rated_candidate_count: int,
    planned_at: datetime,
    options_by_slot: dict[str, tuple[MockExamPlanningCandidateV1, ...]],
    reason: MockExamShortageReason,
    visited_nodes: int,
    cohort: MockExamAssemblyCohortV1 | None,
) -> MockExamAssemblyPlanV1:
    shortages = tuple(
        MockExamAssemblyShortageV1(
            slot_id=slot.slot_id,
            position=slot.position,
            coverage_role=slot.coverage_role,
            coverage_requirement_id=slot.coverage_requirement_id,
            balance_large_unit_key=slot.balance_large_unit_key,
            inquiry_required=slot.inquiry_required,
            available_candidate_count=len(options_by_slot[slot.slot_id]),
            reason=reason,
        )
        for slot in layout_policy.slots
        if not options_by_slot[slot.slot_id] or reason != "SLOT_CANDIDATE_MISSING"
    )
    return _finish_plan(
        {
            **_plan_header(
                policy,
                layout_policy,
                rating_policy,
                graph_snapshot_revision_id,
                graph_snapshot_sha256,
                usage_snapshot,
                planned_at,
                cohort,
            ),
            "status": "SHORTAGE",
            "resolved_candidate_count": resolved_candidate_count,
            "rated_candidate_count": rated_candidate_count,
            "placements": [],
            "shortages": [row.model_dump(mode="json") for row in shortages],
            "validation": None,
            "search_visited_nodes": visited_nodes,
        }
    )


def _plan_header(
    policy: MockExamAssemblyPolicyV1,
    layout: MockExamLayoutPolicyV1,
    rating: MockExamRatingPolicyV1,
    graph_snapshot_revision_id: str,
    graph_snapshot_sha256: str,
    usage_snapshot: MockExamUsageSnapshotV1,
    planned_at: datetime,
    cohort: MockExamAssemblyCohortV1 | None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "mock-exam-assembly-plan/1.0",
        "policy_revision_id": policy.policy_revision_id,
        "policy_sha256": content_sha256(policy.model_dump(mode="json")),
        "layout_policy_revision_id": layout.layout_policy_revision_id,
        "layout_policy_sha256": content_sha256(layout.model_dump(mode="json")),
        "rating_policy_revision_id": rating.rating_policy_revision_id,
        "rating_policy_sha256": content_sha256(rating.model_dump(mode="json")),
        "graph_snapshot_revision_id": graph_snapshot_revision_id,
        "graph_snapshot_sha256": graph_snapshot_sha256,
        "usage_snapshot": usage_snapshot.model_dump(mode="json"),
        "planned_at": planned_at.isoformat().replace("+00:00", "Z"),
    }
    if cohort is not None:
        value["cohort"] = cohort.model_dump(mode="json")
    return value


def _finish_plan(value: dict[str, object]) -> MockExamAssemblyPlanV1:
    value["plan_sha256"] = content_sha256(value)
    return MockExamAssemblyPlanV1.model_validate(value)


def _fail(code: str, message: str) -> Never:
    raise MockExamPlanningError(code, message)

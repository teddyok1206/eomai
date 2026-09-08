from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256,
    INTEGRATED_SCIENCE_LAYOUT_POLICY_SHA256,
    INTEGRATED_SCIENCE_RATING_POLICY_SHA256,
    MockExamAssemblyManifestV2,
    MockExamAssemblyPlacementV1,
    MockExamAssemblyPlanV1,
    MockExamContentPointerV1,
    MockExamPlanningCandidateV1,
    MockExamReviewPointerV1,
    MockExamUsageSnapshotV1,
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
    validate_contract,
    validate_mock_exam_placements,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _identifier(prefix: str, number: int) -> str:
    return prefix + f"{number:032x}"


def _usage_snapshot(
    *, captured_at: datetime, candidate_revision_count: int
) -> MockExamUsageSnapshotV1:
    value = {
        "schema_version": "mock-exam-usage-snapshot/1.0",
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "candidate_revision_count": candidate_revision_count,
        "usage_record_count": 0,
        "usage_records_sha256": content_sha256([]),
    }
    snapshot_sha256 = content_sha256(value)
    return MockExamUsageSnapshotV1.model_validate(
        {
            **value,
            "usage_snapshot_id": ("usagesnapshot_" + snapshot_sha256.removeprefix("sha256:")[:32]),
            "snapshot_sha256": snapshot_sha256,
        }
    )


def _planning_candidates() -> tuple[MockExamPlanningCandidateV1, ...]:
    layout = load_integrated_science_mock_exam_layout_policy()
    policy = load_integrated_science_mock_exam_policy()
    requirement_by_id = {row.requirement_id: row for row in policy.coverage_requirements}
    requirement_offsets: Counter[str] = Counter()
    values: list[MockExamPlanningCandidateV1] = []
    for index, slot in enumerate(layout.slots, start=1):
        if slot.coverage_requirement_id is not None:
            requirement = requirement_by_id[slot.coverage_requirement_id]
            offset = requirement_offsets[requirement.requirement_id]
            unit_key = requirement.allowed_unit_keys[offset]
            requirement_offsets[requirement.requirement_id] += 1
            large_unit_key = f"eom.is.large.{unit_key.split('.')[3].split('-')[0]}"
        else:
            assert slot.balance_large_unit_key is not None
            large_unit_key = slot.balance_large_unit_key
            unit_key = large_unit_key.replace(".large.", ".middle.") + "-1"
        usage_fingerprint = content_sha256(
            {"item_revision_id": _identifier("itemrev_", index), "records": []}
        )
        values.append(
            MockExamPlanningCandidateV1(
                item_id=_identifier("item_", index),
                item_revision_id=_identifier("itemrev_", index),
                item_manifest_sha256="sha256:" + f"{index:064x}",
                item_current_revision=True,
                graph_item_node_id=_identifier("knode_", index),
                graph_analysis_run_id=_identifier("analysisrun_", index),
                graph_source_class="APPROVED_ITEM",
                graph_occurrence_placement_node_id=None,
                curriculum_unit_keys=(unit_key,),
                large_unit_key=large_unit_key,
                item_type_key="multiple-choice",
                difficulty_band=slot.preferred_difficulty,
                is_inquiry=slot.inquiry_required,
                material_profile=slot.preferred_material_profiles[0],
                source_score_display="2",
                content=MockExamContentPointerV1(
                    item_component_id=_identifier("itemcomponent_", index),
                    artifact_id=_identifier("artifact_", index),
                    artifact_revision_id=_identifier("rev_", index),
                    member_path="assessment-item-content.json",
                    schema_ref="eom.assessment.item-content/2.0",
                    media_type="application/json",
                    sha256="sha256:" + f"{index + 100:064x}",
                    editorial_markdown_member="content-team-item.md",
                    editorial_markdown_sha256="sha256:" + f"{index + 200:064x}",
                ),
                review=MockExamReviewPointerV1(
                    item_review_record_id=_identifier("itemreview_", index),
                    review_artifact_id=_identifier("artifact_", index + 100),
                    review_artifact_revision_id=_identifier("rev_", index + 100),
                    review_sha256="sha256:" + f"{index + 300:064x}",
                    decision="APPROVE",
                    final_rating="A",
                ),
                usage_count=0,
                latest_usage_at=None,
                usage_fingerprint_sha256=usage_fingerprint,
            )
        )
    return tuple(values)


def _placements() -> tuple[MockExamAssemblyPlacementV1, ...]:
    policy = load_integrated_science_mock_exam_policy()
    selected: list[tuple[str, str | None]] = []
    for requirement in policy.coverage_requirements:
        for unit_key in requirement.allowed_unit_keys[: requirement.selection_count]:
            selected.append((unit_key, requirement.requirement_id))
    selected.extend(
        (
            ("eom.is.middle.1-1", None),
            ("eom.is.middle.2-1", None),
            ("eom.is.middle.3-2", None),
            ("eom.is.middle.6-5", None),
        )
    )
    points = (1500,) * 8 + (2000,) * 9 + (2500,) * 8
    values = []
    for index, ((unit_key, requirement_id), points_milli) in enumerate(
        zip(selected, points, strict=True), start=1
    ):
        annotation = content_sha256({"position": index, "unit_key": unit_key})
        values.append(
            MockExamAssemblyPlacementV1(
                placement_id=f"placement_{index:032x}",
                position=index,
                display_number=str(index),
                item_id=f"item_{index:032x}",
                item_revision_id=f"itemrev_{index:032x}",
                item_manifest_sha256="sha256:" + f"{index:064x}",
                graph_placement_node_id="knode_" + f"{index:032x}",
                curriculum_unit_keys=(unit_key,),
                major_unit_key="eom.is.volume.i" if index <= 13 else "eom.is.volume.ii",
                points_milli=points_milli,
                coverage_role="REQUIRED" if requirement_id is not None else "BALANCE",
                coverage_requirement_id=requirement_id,
                is_inquiry=index <= 4,
                item_type_key="multiple-choice",
                difficulty_band="MEDIUM",
                material_type="text",
                review_annotation_sha256=annotation,
            )
        )
    return tuple(values)


def test_released_policy_is_schema_valid_and_content_addressed() -> None:
    policy = load_integrated_science_mock_exam_policy()
    assert content_sha256(policy.model_dump(mode="json")) == (
        INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256
    )
    assert policy.item_count == 25
    assert policy.total_points_milli == 50_000
    assert Counter({row.points_milli: row.count for row in policy.score_distribution}) == Counter(
        {1500: 8, 2000: 9, 2500: 8}
    )
    for name in (
        "mock-exam-assembly-policy-v1.schema.json",
        "mock-exam-assembly-manifest-v1.schema.json",
        "mock-exam-layout-policy-v1.schema.json",
        "mock-exam-rating-policy-v1.schema.json",
        "mock-exam-assembly-plan-v1.schema.json",
        "mock-exam-assembly-manifest-v2.schema.json",
    ):
        canonical = ROOT / "schemas" / "assessment-assembly" / name
        packaged = (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
            / name
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


def test_content_team_layout_and_rating_policies_are_pinned() -> None:
    layout = load_integrated_science_mock_exam_layout_policy()
    rating = load_integrated_science_mock_exam_rating_policy()
    assert content_sha256(layout.model_dump(mode="json")) == (
        INTEGRATED_SCIENCE_LAYOUT_POLICY_SHA256
    )
    assert content_sha256(rating.model_dump(mode="json")) == (
        INTEGRATED_SCIENCE_RATING_POLICY_SHA256
    )
    assert tuple(row.points_milli for row in layout.slots) == (
        1500,
        1500,
        2000,
        1500,
        1500,
        2000,
        1500,
        2000,
        2000,
        2000,
        2500,
        2000,
        2500,
        2500,
        1500,
        2500,
        2500,
        2000,
        1500,
        2000,
        2500,
        1500,
        2000,
        2500,
        2500,
    )
    assert tuple(row.position for row in layout.slots if row.inquiry_required) == (
        3,
        6,
        16,
        21,
    )
    assert rating.eligible_ratings == ("A", "B", "C")


def test_server_planner_returns_one_deterministic_complete_plan() -> None:
    policy = load_integrated_science_mock_exam_policy()
    layout = load_integrated_science_mock_exam_layout_policy()
    rating = load_integrated_science_mock_exam_rating_policy()
    candidates = _planning_candidates()
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    usage = _usage_snapshot(captured_at=planned_at, candidate_revision_count=len(candidates))

    def build_plan() -> MockExamAssemblyPlanV1:
        return build_mock_exam_assembly_plan(
            policy=policy,
            layout_policy=layout,
            rating_policy=rating,
            graph_snapshot_revision_id=_identifier("graphrev_", 1),
            graph_snapshot_sha256="sha256:" + "1" * 64,
            usage_snapshot=usage,
            resolved_candidate_count=len(candidates),
            candidates=candidates,
            planned_at=planned_at,
        )

    first = build_plan()
    second = build_plan()
    assert first == second
    assert first.status == "READY"
    assert first.validation is not None
    assert first.validation.item_count == 25
    assert first.validation.total_points_milli == 50_000
    assert len({row.item_id for row in first.placements}) == 25
    assert tuple(row.position for row in first.placements) == tuple(range(1, 26))
    assert tuple(row.position for row in first.placements if row.is_inquiry) == (
        3,
        6,
        16,
        21,
    )
    manifest_value = {
        "schema_version": "mock-exam-assembly-manifest/2.0",
        "assessment_assembly_revision_id": _identifier("assemblyrev_", 1),
        "assessment_assembly_id": _identifier("assembly_", 2),
        "assessment_form_id": _identifier("form_", 3),
        "assessment_form_revision_id": _identifier("formrev_", 4),
        "deliverable_id": _identifier("deliverable_", 5),
        "deliverable_revision_id": _identifier("delivrev_", 6),
        "form_key": "main",
        "display_label": "본시험지",
        "plan": first.model_dump(mode="json"),
        "revision_state": "RELEASED",
        "created_at": planned_at.isoformat().replace("+00:00", "Z"),
        "created_by": _identifier("operator_", 7),
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    manifest = MockExamAssemblyManifestV2.model_validate(manifest_value)
    validate_contract("mock-exam-assembly-manifest-v2", manifest.model_dump(mode="json"))


def test_server_planner_reports_rating_shortage_without_partial_output() -> None:
    policy = load_integrated_science_mock_exam_policy()
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=_identifier("graphrev_", 1),
        graph_snapshot_sha256="sha256:" + "1" * 64,
        usage_snapshot=_usage_snapshot(captured_at=planned_at, candidate_revision_count=0),
        resolved_candidate_count=25,
        candidates=(),
        planned_at=planned_at,
    )
    assert plan.status == "SHORTAGE"
    assert plan.placements == ()
    assert plan.validation is None
    assert {row.reason for row in plan.shortages} == {"NO_RATED_CANDIDATES"}


def test_team_guidance_policy_accepts_exact_25_item_distribution() -> None:
    result = validate_mock_exam_placements(
        _placements(), load_integrated_science_mock_exam_policy()
    )
    assert result.item_count == 25
    assert result.total_points_milli == 50_000
    assert result.score_distribution == {"1500": 8, "2000": 9, "2500": 8}
    assert result.required_slot_count == 21
    assert result.balance_slot_count == 4
    assert result.inquiry_count == 4
    assert len(result.coverage_requirement_ids) == 19


def test_team_guidance_policy_rejects_score_and_distinct_unit_drift() -> None:
    policy = load_integrated_science_mock_exam_policy()
    placements = list(_placements())
    placements[0] = placements[0].model_copy(update={"points_milli": 2000})
    with pytest.raises(ValueError, match="TOTAL_POINTS"):
        validate_mock_exam_placements(tuple(placements), policy)

    placements = list(_placements())
    placements[1] = placements[1].model_copy(
        update={"curriculum_unit_keys": placements[0].curriculum_unit_keys}
    )
    with pytest.raises(ValueError, match="UNITS_NOT_DISTINCT"):
        validate_mock_exam_placements(tuple(placements), policy)

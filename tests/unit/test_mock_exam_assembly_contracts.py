from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256,
    INTEGRATED_SCIENCE_LAYOUT_POLICY_SHA256,
    INTEGRATED_SCIENCE_RATING_POLICY_SHA256,
    CreatePlannedMockExamAssembly,
    MockExamAssemblyCohortV1,
    MockExamAssemblyManifestV2,
    MockExamAssemblyPlacementV1,
    MockExamAssemblyPlanV1,
    MockExamContentPointerV1,
    MockExamPlanningCandidateV1,
    MockExamPlanningError,
    MockExamReviewPointerV1,
    MockExamUsageSnapshotV1,
    PreviewMockExamAssemblyPlan,
    build_mock_exam_assembly_cohort,
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
    validate_contract,
    validate_mock_exam_placements,
)
from eom_catalog_service.mock_exam_assembly_service import (
    MockExamAssemblyError,
    MockExamAssemblyService,
)
from eom_catalog_service.mock_exam_candidate_repository import MockExamPlanningInputs
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine

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


def _cohort(
    candidates: tuple[MockExamPlanningCandidateV1, ...],
) -> MockExamAssemblyCohortV1:
    return build_mock_exam_assembly_cohort(
        tuple(candidate.item_revision_id for candidate in candidates)
    )


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
        "mock-exam-assembly-cohort-v1.schema.json",
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


def test_exact_cohort_is_self_hashed_schema_valid_and_embedded_in_plan() -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    unsigned = cohort.model_dump(mode="json", exclude={"cohort_id", "cohort_sha256"})
    assert cohort.cohort_sha256 == content_sha256(unsigned)
    assert cohort.cohort_id == (
        "assemblycohort_" + cohort.cohort_sha256.removeprefix("sha256:")[:32]
    )
    validate_contract("mock-exam-assembly-cohort", cohort.model_dump(mode="json"))
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    plan = build_mock_exam_assembly_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=_identifier("graphrev_", 1),
        graph_snapshot_sha256="sha256:" + "1" * 64,
        usage_snapshot=_usage_snapshot(
            captured_at=planned_at, candidate_revision_count=len(candidates)
        ),
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=planned_at,
        cohort=cohort,
    )
    assert plan.status == "READY"
    assert plan.cohort == cohort
    assert tuple(row.item_revision_id for row in plan.placements) == tuple(
        member.item_revision_id for member in cohort.members
    )
    validate_contract("mock-exam-assembly-plan", plan.model_dump(mode="json"))


@pytest.mark.parametrize("failure", ["duplicate", "hash", "count"])
def test_exact_cohort_rejects_invalid_identity_or_members(failure: str) -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    value = cohort.model_dump(mode="json")
    if failure == "duplicate":
        value["members"][1]["item_revision_id"] = value["members"][0]["item_revision_id"]
        unsigned = {
            key: raw for key, raw in value.items() if key not in {"cohort_id", "cohort_sha256"}
        }
        value["cohort_sha256"] = content_sha256(unsigned)
        value["cohort_id"] = "assemblycohort_" + value["cohort_sha256"].removeprefix("sha256:")[:32]
    elif failure == "hash":
        value["cohort_sha256"] = "sha256:" + "f" * 64
    else:
        value["members"] = value["members"][:-1]
    with pytest.raises(ValueError):
        MockExamAssemblyCohortV1.model_validate(value)


@pytest.mark.parametrize("failure", ["missing", "external"])
def test_exact_cohort_rejects_non_exact_graph_rating_candidates(failure: str) -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    if failure == "missing":
        supplied = candidates[:-1]
        resolved_count = 25
    elif failure == "external":
        supplied = (
            *candidates,
            candidates[-1].model_copy(
                update={
                    "item_id": _identifier("item_", 100),
                    "item_revision_id": _identifier("itemrev_", 100),
                }
            ),
        )
        resolved_count = 26
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    with pytest.raises(MockExamPlanningError) as raised:
        build_mock_exam_assembly_plan(
            policy=load_integrated_science_mock_exam_policy(),
            layout_policy=load_integrated_science_mock_exam_layout_policy(),
            rating_policy=load_integrated_science_mock_exam_rating_policy(),
            graph_snapshot_revision_id=_identifier("graphrev_", 1),
            graph_snapshot_sha256="sha256:" + "1" * 64,
            usage_snapshot=_usage_snapshot(
                captured_at=planned_at, candidate_revision_count=len(supplied)
            ),
            resolved_candidate_count=resolved_count,
            candidates=supplied,
            planned_at=planned_at,
            cohort=cohort,
        )
    assert raised.value.code == "ASSEMBLY_COHORT_CANDIDATES_INVALID"


def test_exact_cohort_accepts_pinned_revision_after_item_head_advances() -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    supplied = (
        candidates[0].model_copy(update={"item_current_revision": False}),
        *candidates[1:],
    )
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    plan = build_mock_exam_assembly_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=_identifier("graphrev_", 1),
        graph_snapshot_sha256="sha256:" + "1" * 64,
        usage_snapshot=_usage_snapshot(
            captured_at=planned_at,
            candidate_revision_count=len(supplied),
        ),
        resolved_candidate_count=len(supplied),
        candidates=supplied,
        planned_at=planned_at,
        cohort=cohort,
    )
    assert plan.status == "READY"
    assert plan.placements[0].item_revision_id == candidates[0].item_revision_id


def test_exact_cohort_position_binding_prevents_ambiguous_candidate_swap() -> None:
    candidates = _planning_candidates()
    pinned_order = (
        candidates[1].item_revision_id,
        candidates[0].item_revision_id,
        *(candidate.item_revision_id for candidate in candidates[2:]),
    )
    cohort = build_mock_exam_assembly_cohort(pinned_order)
    planned_at = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    plan = build_mock_exam_assembly_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=_identifier("graphrev_", 1),
        graph_snapshot_sha256="sha256:" + "1" * 64,
        usage_snapshot=_usage_snapshot(
            captured_at=planned_at, candidate_revision_count=len(candidates)
        ),
        resolved_candidate_count=len(candidates),
        candidates=tuple(reversed(candidates)),
        planned_at=planned_at,
        cohort=cohort,
    )
    assert plan.status == "READY"
    assert tuple(row.item_revision_id for row in plan.placements) == pinned_order


def test_create_planned_revalidates_exact_cohort_even_on_idempotent_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    planned_at = datetime.now(UTC)
    usage = _usage_snapshot(captured_at=planned_at, candidate_revision_count=len(candidates))
    graph_revision_id = _identifier("graphrev_", 1)
    graph_sha256 = "sha256:" + "1" * 64
    policy = load_integrated_science_mock_exam_policy()
    policy_sha256 = content_sha256(policy.model_dump(mode="json"))
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        usage_snapshot=usage,
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=planned_at,
        cohort=cohort,
    )
    command = CreatePlannedMockExamAssembly(
        deliverable_id=_identifier("deliverable_", 1),
        deliverable_revision_id=_identifier("delivrev_", 2),
        form_key="main",
        display_label="본시험지",
        policy_revision_id=policy.policy_revision_id,
        policy_sha256=policy_sha256,
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        cohort=cohort,
        expected_plan_sha256=plan.plan_sha256,
        planned_at=planned_at,
        actor_id=_identifier("operator_", 3),
    )
    manifest_value: dict[str, Any] = {
        "schema_version": "mock-exam-assembly-manifest/2.0",
        "assessment_assembly_revision_id": _identifier("assemblyrev_", 4),
        "assessment_assembly_id": _identifier("assembly_", 5),
        "assessment_form_id": _identifier("form_", 6),
        "assessment_form_revision_id": _identifier("formrev_", 7),
        "deliverable_id": command.deliverable_id,
        "deliverable_revision_id": command.deliverable_revision_id,
        "form_key": command.form_key,
        "display_label": command.display_label,
        "plan": plan.model_dump(mode="json"),
        "revision_state": "RELEASED",
        "created_at": planned_at.isoformat().replace("+00:00", "Z"),
        "created_by": command.actor_id,
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    existing = MockExamAssemblyManifestV2.model_validate(manifest_value)

    class RecordingCandidates:
        def __init__(self) -> None:
            self.cohorts: list[MockExamAssemblyCohortV1 | None] = []

        def resolve(self, _session: Any, **kwargs: Any) -> MockExamPlanningInputs:
            self.cohorts.append(kwargs.get("cohort"))
            return MockExamPlanningInputs(
                resolved_candidate_count=len(candidates),
                candidates=candidates,
                usage_snapshot=usage,
            )

    repository = RecordingCandidates()
    service = MockExamAssemblyService(
        create_engine("sqlite+pysqlite:///:memory:"),
        candidates=repository,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        service,
        "_resolve_deliverable",
        lambda _session, _command: (
            SimpleNamespace(deliverable_id=command.deliverable_id),
            SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(service, "_planned_replay", lambda _session, _command: existing)
    monkeypatch.setattr(
        service,
        "_resolve_snapshot",
        lambda _session, _command: SimpleNamespace(
            graph_snapshot_revision_id=graph_revision_id,
            snapshot_sha256=graph_sha256,
        ),
    )

    assert service.create_planned(command) == existing
    assert repository.cohorts == [cohort]


def test_exact_cohort_create_remains_resumable_after_generic_preview_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    planned_at = datetime.now(UTC) - timedelta(hours=1)
    usage = _usage_snapshot(captured_at=planned_at, candidate_revision_count=len(candidates))
    graph_revision_id = _identifier("graphrev_", 1)
    graph_sha256 = "sha256:" + "1" * 64
    policy = load_integrated_science_mock_exam_policy()
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        usage_snapshot=usage,
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=planned_at,
        cohort=cohort,
    )
    command = CreatePlannedMockExamAssembly(
        deliverable_id=_identifier("deliverable_", 11),
        deliverable_revision_id=_identifier("delivrev_", 12),
        form_key="resumed-main",
        display_label="재개 본시험지",
        policy_revision_id=policy.policy_revision_id,
        policy_sha256=content_sha256(policy.model_dump(mode="json")),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        cohort=cohort,
        expected_plan_sha256=plan.plan_sha256,
        planned_at=planned_at,
        actor_id=_identifier("operator_", 13),
    )

    class ExactCandidates:
        def resolve(self, _session: Any, **kwargs: Any) -> MockExamPlanningInputs:
            assert kwargs["cohort"] == cohort
            assert kwargs["planned_at"] == planned_at
            return MockExamPlanningInputs(
                resolved_candidate_count=len(candidates),
                candidates=candidates,
                usage_snapshot=usage,
            )

    service = MockExamAssemblyService(
        create_engine("sqlite+pysqlite:///:memory:"),
        candidates=ExactCandidates(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        service,
        "_resolve_deliverable",
        lambda _session, _command: (
            SimpleNamespace(deliverable_id=command.deliverable_id),
            SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(service, "_planned_replay", lambda _session, _command: None)
    monkeypatch.setattr(
        service,
        "_resolve_snapshot",
        lambda _session, _command: SimpleNamespace(
            graph_snapshot_revision_id=graph_revision_id,
            snapshot_sha256=graph_sha256,
        ),
    )
    monkeypatch.setattr(service, "_persist_planned", lambda *_args: None)

    manifest = service.create_planned(command)
    assert manifest.plan.plan_sha256 == plan.plan_sha256
    assert manifest.plan.cohort == cohort

    generic_command = command.model_copy(
        update={"cohort": None, "form_key": "expired-generic"}
    )
    with pytest.raises(MockExamAssemblyError, match="bounded creation window"):
        service.create_planned(generic_command)


def test_preview_resolves_only_the_exact_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    policy = load_integrated_science_mock_exam_policy()
    graph_revision_id = _identifier("graphrev_", 1)
    graph_sha256 = "sha256:" + "1" * 64
    query = PreviewMockExamAssemblyPlan(
        policy_revision_id=policy.policy_revision_id,
        policy_sha256=content_sha256(policy.model_dump(mode="json")),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        cohort=cohort,
    )

    class RecordingCandidates:
        def __init__(self) -> None:
            self.cohorts: list[MockExamAssemblyCohortV1 | None] = []

        def resolve(self, _session: Any, **kwargs: Any) -> MockExamPlanningInputs:
            self.cohorts.append(kwargs.get("cohort"))
            planned_at = kwargs["planned_at"]
            return MockExamPlanningInputs(
                resolved_candidate_count=len(candidates),
                candidates=candidates,
                usage_snapshot=_usage_snapshot(
                    captured_at=planned_at,
                    candidate_revision_count=len(candidates),
                ),
            )

    repository = RecordingCandidates()
    service = MockExamAssemblyService(
        create_engine("sqlite+pysqlite:///:memory:"),
        candidates=repository,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        service,
        "_resolve_snapshot",
        lambda _session, _command: SimpleNamespace(
            graph_snapshot_revision_id=graph_revision_id,
            snapshot_sha256=graph_sha256,
        ),
    )

    result = service.preview(query)
    assert result.status == "READY"
    assert result.cohort == cohort
    assert repository.cohorts == [cohort]


def test_exact_cohort_keeps_its_published_graph_after_corpus_head_advances() -> None:
    candidates = _planning_candidates()
    cohort = _cohort(candidates)
    policy = load_integrated_science_mock_exam_policy()
    pinned_revision_id = _identifier("graphrev_", 1)
    pinned_sha256 = "sha256:" + "1" * 64
    query = PreviewMockExamAssemblyPlan(
        policy_revision_id=policy.policy_revision_id,
        policy_sha256=content_sha256(policy.model_dump(mode="json")),
        graph_snapshot_revision_id=pinned_revision_id,
        graph_snapshot_sha256=pinned_sha256,
        cohort=cohort,
    )
    corpus = SimpleNamespace(
        graph_id=_identifier("graph_", 1),
        current_graph_snapshot_revision_id=_identifier("graphrev_", 2),
    )
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id=pinned_revision_id,
        graph_id=corpus.graph_id,
        state="PUBLISHED",
        ontology_version="education-knowledge-graph/1.1",
        snapshot_sha256=pinned_sha256,
    )

    class SnapshotSession:
        def scalar(self, _statement: Any) -> Any:
            return corpus

        def get(self, _model: Any, revision_id: str) -> Any:
            assert revision_id == pinned_revision_id
            return snapshot

    service = MockExamAssemblyService(create_engine("sqlite+pysqlite:///:memory:"))
    resolved = service._resolve_snapshot(SnapshotSession(), query)  # type: ignore[arg-type]
    assert resolved is snapshot

    legacy_query = query.model_copy(update={"cohort": None})
    with pytest.raises(MockExamAssemblyError, match="eligible published"):
        service._resolve_snapshot(SnapshotSession(), legacy_query)  # type: ignore[arg-type]


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

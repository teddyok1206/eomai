from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_ASSEMBLY_POLICY_SHA256,
    MockExamAssemblyPlacementV1,
    load_integrated_science_mock_exam_policy,
    validate_mock_exam_placements,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


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
    ):
        canonical = ROOT / "schemas" / "assessment-assembly" / name
        packaged = (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
            / name
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


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

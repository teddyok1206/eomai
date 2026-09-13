from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    MockExamProductionPlanV4,
    build_integrated_science_mock_exam_production_plan_v4,
    content_team_material_requirement_for_mock_exam_profile,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    validate_contract,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _plan() -> MockExamProductionPlanV4:
    return build_integrated_science_mock_exam_production_plan_v4(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


@pytest.mark.parametrize(
    ("profile", "panel_count", "image_mode"),
    (
        ("TEXT", None, "skip"),
        ("DATA", None, "skip"),
        ("TABLE", 1, "skip"),
        ("IMAGE", 1, "required"),
        ("MIXED", 2, "required"),
        ("INQUIRY", None, "skip"),
    ),
)
def test_slot_profile_maps_to_exact_material_requirement(
    profile: str,
    panel_count: int | None,
    image_mode: str,
) -> None:
    requirement = content_team_material_requirement_for_mock_exam_profile(profile)  # type: ignore[arg-type]

    assert requirement.form == profile
    assert requirement.panel_count == panel_count
    assert requirement.image_mode == image_mode


def test_v4_plan_is_self_hashed_and_uses_material_briefs() -> None:
    plan = _plan()

    assert plan.schema_version == "mock-exam-production-plan/4.0"
    assert plan.one_item_generation_block.content_pack_version == "1.16.0"
    assert plan.one_item_generation_block.image_mode == "from_material_requirement"
    assert len(plan.workflow_calls) == 25
    for call in plan.workflow_calls:
        brief = call.item_brief
        assert brief.schema_version == "4.0"
        assert brief.material_requirement.form == brief.task_type
        assert brief.material_requirement.image_mode in {"skip", "required"}

    validate_contract("mock-exam-production-plan-v4", plan.model_dump(mode="json"))


def test_v4_plan_rejects_material_drift_without_repairing_it() -> None:
    value = _plan().model_dump(mode="json")
    value["workflow_calls"][0]["item_brief"]["material_requirement"] = {
        "schema_version": "content-team-material-requirement/1.0",
        "form": "TABLE",
        "panel_count": 1,
    }

    with pytest.raises(ValidationError, match="material requirement differs"):
        MockExamProductionPlanV4.model_validate(value)


def test_v4_schemas_are_draft_2020_12_and_packaged_verbatim() -> None:
    pairs = (
        (
            ROOT / "schemas/assessment-assembly/mock-exam-production-plan-v4.schema.json",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-production-plan-v4.schema.json",
        ),
        (
            ROOT / "schemas/api/v1/mock-exam-production-execution-v4.schema.json",
            ROOT / "packages/api_contracts/eom_api_contracts/schemas/"
            "mock-exam-production-execution-v4.schema.json",
        ),
    )
    for canonical, packaged in pairs:
        payload = canonical.read_bytes()
        assert payload == packaged.read_bytes()
        schema = json.loads(payload)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)

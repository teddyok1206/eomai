from __future__ import annotations

from pathlib import Path

import pytest
from eom_web_gui.contracts import (
    CreateEducationalQualityPlanSubmission,
    EducationalQualityObservationSubmission,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "apps/web_gui/eom_web_gui/static/index.html").read_text(encoding="utf-8")
JAVASCRIPT = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")


def test_quality_plan_submission_pins_revision_hash_and_ordered_sample() -> None:
    value = CreateEducationalQualityPlanSubmission(
        operation="CREATE_PLAN",
        assembly_revision_id="assemblyrev_" + "1" * 32,
        assembly_manifest_sha256="sha256:" + "2" * 64,
        secondary_positions=(1, 3, 5),
        idempotency_key="studio:quality:create:test",
    )
    assert value.secondary_positions == (1, 3, 5)
    with pytest.raises(ValidationError):
        CreateEducationalQualityPlanSubmission(
            operation="CREATE_PLAN",
            assembly_revision_id="assemblyrev_" + "1" * 32,
            assembly_manifest_sha256="sha256:" + "2" * 64,
            secondary_positions=(3, 1, 3),
            idempotency_key="studio:quality:create:test",
        )


def test_quality_observation_requires_explicit_visual_applicability() -> None:
    payload = {
        "position": 1,
        "item_revision_id": "itemrev_" + "3" * 32,
        "preview_checked": True,
        "hwpx_checked": True,
        "evidence_checked": True,
        "science_score": 5,
        "critical_error": False,
        "unique_answer": "PASS",
        "evidence_score": 5,
        "authoring_value_score": 5,
        "visual_score": None,
        "visual_not_applicable_reason": "시각 자료가 없는 문항",
        "explanation_quality_score": 5,
        "disposition": "NO_EDIT",
        "edit_minutes": 2,
        "short_reason": "채택 가능",
    }
    assert EducationalQualityObservationSubmission.model_validate(payload).visual_score is None
    with pytest.raises(ValidationError):
        EducationalQualityObservationSubmission.model_validate(
            payload | {"visual_not_applicable_reason": None}
        )


def test_quality_workbench_exposes_human_rubric_and_derived_scorecard() -> None:
    for identifier in (
        "quality-review",
        "quality-assembly-select",
        "quality-reviewer-role",
        "quality-observation-form",
        "quality-scorecard",
        "quality-scorecard-adoptable",
        "quality-scorecard-edit-time",
    ):
        assert f'id="{identifier}"' in HTML or f'data-view="{identifier}"' in HTML
    assert "renderEducationalQualityScorecard" in JAVASCRIPT
    assert "science_score_milli" in JAVASCRIPT
    assert "visual_score_milli" in JAVASCRIPT
    assert "item_manifest_sha256" not in HTML


def test_quality_workbench_uses_permission_and_indexed_item_lookup() -> None:
    assert 'permissions.includes("workflow:approve")' in JAVASCRIPT
    assert "const items = new Map(plan.items.map" in JAVASCRIPT
    render_start = JAVASCRIPT.index("function renderEducationalQualityItemList()")
    render_end = JAVASCRIPT.index("function renderEducationalQualityPlan()")
    assert ".items.find(" not in JAVASCRIPT[render_start:render_end]


def test_quality_position_input_fails_closed_on_mixed_text() -> None:
    parser_start = JAVASCRIPT.index("function parseEducationalQualityPositions(value)")
    parser_end = JAVASCRIPT.index("async function createEducationalQualityPlan")
    parser = JAVASCRIPT[parser_start:parser_end]
    assert "return null" in parser
    assert ".filter(Number.isInteger)" not in parser

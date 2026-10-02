from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api_contracts.educational_quality import (
    CreateEducationalQualityPlanCommand,
    EducationalQualityObservationInput,
    EducationalQualityReviewWorkbenchView,
    EducationalQualityScoreMetricsView,
)
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict[str, object]:
    value = json.loads((ROOT / "schemas/api/v1" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    Draft202012Validator.check_schema(value)
    return value


def _observation() -> dict[str, object]:
    return {
        "position": 1,
        "item_revision_id": "itemrev_" + "1" * 32,
        "preview_checked": True,
        "hwpx_checked": True,
        "evidence_checked": True,
        "science_score": 5,
        "critical_error": False,
        "unique_answer": "PASS",
        "evidence_score": 4,
        "authoring_value_score": 5,
        "visual_score": None,
        "visual_not_applicable_reason": "시각 자료가 없는 문항",
        "explanation_quality_score": 5,
        "disposition": "NO_EDIT",
        "edit_minutes": 3,
        "short_reason": "과학적으로 정확하고 정답이 유일함",
    }


def test_command_schema_and_pydantic_accept_the_same_observation() -> None:
    payload = {
        "operation": "UPSERT_OBSERVATION",
        "session_id": "qualitysession_" + "2" * 32,
        "expected_lock_version": 1,
        "observation": _observation(),
    }
    Draft202012Validator(_schema("educational-quality-review-command-v1.schema.json")).validate(
        payload
    )
    EducationalQualityObservationInput.model_validate(payload["observation"])


def test_visual_score_and_not_applicable_reason_are_exclusive() -> None:
    payload = _observation() | {
        "visual_score": 4,
        "visual_not_applicable_reason": "그림이 있음",
    }
    with pytest.raises(PydanticValidationError):
        EducationalQualityObservationInput.model_validate(payload)
    command = {
        "operation": "UPSERT_OBSERVATION",
        "session_id": "qualitysession_" + "2" * 32,
        "expected_lock_version": 1,
        "observation": payload,
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("educational-quality-review-command-v1.schema.json")).validate(
            command
        )


def test_secondary_positions_are_sorted_and_unique_in_semantic_layer() -> None:
    with pytest.raises(PydanticValidationError):
        CreateEducationalQualityPlanCommand.model_validate(
            {
                "operation": "CREATE_PLAN",
                "assembly_revision_id": "assemblyrev_" + "3" * 32,
                "assembly_manifest_sha256": "sha256:" + "4" * 64,
                "secondary_positions": [3, 1, 3],
            }
        )


def test_workbench_schema_matches_pydantic_minimal_view() -> None:
    payload = {
        "schema_version": "educational-quality-review-workbench/1.0",
        "candidate_assemblies": [],
        "plans": [],
        "selected_plan": None,
    }
    Draft202012Validator(
        _schema("educational-quality-review-workbench-v1.schema.json"),
        format_checker=FormatChecker(),
    ).validate(payload)
    EducationalQualityReviewWorkbenchView.model_validate(payload)


def test_canonical_and_packaged_quality_schemas_are_byte_identical() -> None:
    for name in (
        "educational-quality-review-command-v1.schema.json",
        "educational-quality-review-workbench-v1.schema.json",
    ):
        assert (ROOT / "schemas/api/v1" / name).read_bytes() == (
            ROOT / "packages/api_contracts/eom_api_contracts/schemas" / name
        ).read_bytes()


def test_score_metrics_reject_incoherent_disposition_totals() -> None:
    with pytest.raises(PydanticValidationError, match="score metrics"):
        EducationalQualityScoreMetricsView(
            item_count=2,
            no_edit_count=1,
            minor_edit_count=0,
            major_edit_count=0,
            discard_count=0,
            adoptable_count=1,
            critical_error_count=0,
            unique_answer_pass_count=2,
            unique_answer_ambiguous_count=0,
            unique_answer_fail_count=0,
            total_edit_minutes=4,
            mean_edit_minutes_milli=2000,
            science_score_milli=5000,
            evidence_score_milli=5000,
            authoring_value_score_milli=5000,
            explanation_quality_score_milli=5000,
            visual_scored_item_count=0,
            visual_score_milli=None,
        )

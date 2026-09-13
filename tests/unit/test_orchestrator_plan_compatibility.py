from __future__ import annotations

import pytest
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.orchestrator import _plan_step_evidence_access


def test_solution_plan_v9_without_evidence_access_remains_admitted() -> None:
    assert (
        _plan_step_evidence_access(
            {"schema_version": "resolved-execution-plan/9.0"},
            {"step_key": "analyze", "role": "support"},
        )
        is None
    )


@pytest.mark.parametrize("value", [None, "", "UNREVIEWED"])
def test_evidence_plan_v3_requires_a_valid_access_mode(value: object) -> None:
    step: dict[str, object] = {"step_key": "author", "role": "authoring"}
    if value is not None:
        step["evidence_access"] = value

    with pytest.raises(ControlPlaneError, match="evidence access is invalid") as error:
        _plan_step_evidence_access(
            {"schema_version": "resolved-execution-plan/3.0"},
            step,
        )

    assert error.value.code == "CONTROL_PLAN_EVIDENCE_ACCESS_INVALID"


@pytest.mark.parametrize("value", ["NONE", "EVIDENCE_CONTEXT"])
def test_evidence_plan_v3_returns_its_exact_access_mode(value: str) -> None:
    assert (
        _plan_step_evidence_access(
            {"schema_version": "resolved-execution-plan/3.0"},
            {"step_key": "author", "role": "authoring", "evidence_access": value},
        )
        == value
    )


def test_legacy_plan_rejects_an_out_of_family_evidence_field() -> None:
    with pytest.raises(ControlPlaneError, match="outside its contract family") as error:
        _plan_step_evidence_access(
            {"schema_version": "resolved-execution-plan/9.0"},
            {
                "step_key": "analyze",
                "role": "support",
                "evidence_access": "EVIDENCE_CONTEXT",
            },
        )

    assert error.value.code == "CONTROL_PLAN_EVIDENCE_ACCESS_INVALID"

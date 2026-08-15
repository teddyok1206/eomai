from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from eom_workflow import WorkflowDefinitionError, compile_definition, compile_definition_data
from eom_workflow.compiler import evaluate_decision
from eom_workflow.models import DecisionStep

DEFINITION_PATH = Path("config/workflows/generic-item-development.v1.yaml")
ROLES = {"authoring", "image", "review", "item_management", "support"}


def _raw_definition() -> dict[str, object]:
    raw: object = yaml.safe_load(DEFINITION_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_generic_definition_compiles_with_stable_hash() -> None:
    first = compile_definition(DEFINITION_PATH, ROLES)
    second = compile_definition(DEFINITION_PATH, ROLES)
    assert first.definition.definition_key == "generic-item-development"
    assert first.definition.definition_version == "1.0.0"
    assert first.sha256 == second.sha256
    assert first.sha256.startswith("sha256:")


def test_duplicate_step_is_rejected() -> None:
    raw = _raw_definition()
    steps = raw["steps"]
    assert isinstance(steps, list)
    steps.append(copy.deepcopy(steps[0]))
    with pytest.raises(WorkflowDefinitionError, match="unique"):
        compile_definition_data(raw, "test.yaml", ROLES)


def test_missing_transition_is_rejected() -> None:
    raw = _raw_definition()
    steps = raw["steps"]
    assert isinstance(steps, list) and isinstance(steps[0], dict)
    steps[0]["on_success"] = "missing_step"
    with pytest.raises(WorkflowDefinitionError, match="missing transition"):
        compile_definition_data(raw, "test.yaml", ROLES)


def test_unsafe_operator_and_expression_field_are_rejected() -> None:
    raw = _raw_definition()
    steps = raw["steps"]
    assert isinstance(steps, list) and isinstance(steps[1], dict)
    steps[1]["operator"] = "eval"
    steps[1]["expression"] = "__import__('os')"
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(raw, "test.yaml", ROLES)


def test_unreachable_step_is_rejected() -> None:
    raw = _raw_definition()
    steps = raw["steps"]
    assert isinstance(steps, list)
    steps.append(
        {
            "key": "unreachable",
            "type": "terminal",
            "terminal_status": "COMPLETED",
        }
    )
    with pytest.raises(WorkflowDefinitionError, match="unreachable"):
        compile_definition_data(raw, "test.yaml", ROLES)


def test_unavailable_worker_role_is_rejected() -> None:
    with pytest.raises(WorkflowDefinitionError, match="unavailable"):
        compile_definition(DEFINITION_PATH, ROLES - {"image"})


def test_result_schema_must_match_worker_role() -> None:
    raw = _raw_definition()
    steps = raw["steps"]
    assert isinstance(steps, list) and isinstance(steps[0], dict)
    steps[0]["result_schema"] = "review-result@1.0"
    with pytest.raises(WorkflowDefinitionError, match="does not match"):
        compile_definition_data(raw, "test.yaml", ROLES)


@pytest.mark.parametrize(("image_mode", "target"), [("skip", "review"), ("required", "image")])
def test_image_decision_is_deterministic(image_mode: str, target: str) -> None:
    compiled = compile_definition(DEFINITION_PATH, ROLES)
    decision = compiled.steps_by_key["image_decision"]
    assert isinstance(decision, DecisionStep)
    assert evaluate_decision(decision, {"image_mode": image_mode}) == target

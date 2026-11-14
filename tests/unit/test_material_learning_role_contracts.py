"""Purpose-isolated worker messages and exact plan; no model or source permission."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_learning import MaterialPageCoverage
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ResolvedExecutionPlanV33
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.material_learning_prompt import MATERIAL_LEARNING_GUIDANCE
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from eom_workflow.models import MaterialLearningRoleResult
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    load_role_input_schema,
    load_role_result_schema,
    result_schema_protocol,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_role_schemas import _input
from tests.unit.test_material_learning_contracts import (
    discovery,
    extraction_result,
    extraction_work,
    work,
)

ROOT = Path(__file__).resolve().parents[2]


def worker_input():
    value = _input()
    value.update(
        protocol_version="workflow-role/1.37.0",
        request={"request_name": "MATERIAL_LEARNING_REQUEST", "work_input": work()},
    )
    return value


def material_plan():
    value = _plan()
    value.update(
        schema_version="resolved-execution-plan/33.0",
        workflow_definition_key="material-learning",
        workflow_definition_version="1.0.0",
        resolver_version="33.0.0",
        work_input=work(),
    )
    value["steps"][0]["step_key"] = "learn"
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def test_material_workflow_request_has_no_archive_or_legacy_optional_fields():
    request = MaterialLearningWorkflowRequest(work_input=work())
    assert set(request.model_dump()) == {"request_name", "execution_preset_key", "work_input"}
    assert request.worker_request().request_name == "MATERIAL_LEARNING_REQUEST"
    assert not any(name.startswith("external") for name in request.model_dump())


def test_input_schema_model_and_material_source_are_closed():
    value = worker_input()
    Draft202012Validator(load_role_input_schema("support", "workflow-role/1.37.0")).validate(value)
    parsed = validate_role_input(value, "support", "workflow-role/1.37.0")
    assert parsed.request.work_input.input_sha256 == work()["input_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(protocol_version="workflow-role/1.36.0"),
        lambda value: value.update(role="authoring"),
        lambda value: value["request"].update(request_name="EXTERNAL_ITEM_LEARNING_REQUEST"),
        lambda value: value["request"].update(external_number="10310"),
    ],
)
def test_other_purpose_cannot_reuse_material_worker_envelope(change):
    value = worker_input()
    change(value)
    with pytest.raises((ValueError, ValidationError)):
        validate_role_input(value, "support", "workflow-role/1.37.0")


@pytest.mark.parametrize("kind", ["discovery", "extraction"])
def test_both_result_tasks_use_the_same_source_isolated_role_protocol(kind):
    message = worker_input()
    value = {
        key: message[key]
        for key in (
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "role",
            "artifact",
        )
    }
    value.update(
        status="ok",
        completed_at="2026-11-05T19:00:00Z",
        output={"learning_result": discovery() if kind == "discovery" else extraction_result()},
    )
    Draft202012Validator(load_role_result_schema("material-learning-result@1.0")).validate(value)
    parsed = validate_role_result(value, "support", "material-learning-result@1.0")
    assert isinstance(parsed, MaterialLearningRoleResult)
    assert parsed.output.learning_result.schema_version.startswith("material-learning-")


def test_exact_resolved_plan_keeps_knowledge_workload_and_no_network():
    value = material_plan()
    validate_control_contract("resolved-execution-plan-v33", value)
    parsed = ResolvedExecutionPlanV33.model_validate(value)
    assert parsed.workload_class == "KNOWLEDGE_ANALYSIS"
    assert parsed.steps[0].step_key == "learn"
    assert parsed.steps[0].network == "disabled"
    value = deepcopy(value)
    value["steps"][0]["network"] = "enabled"
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV33.model_validate(value)


@pytest.mark.parametrize("kind", ["discovery", "extraction"])
def test_codex_projection_is_valid_and_bound_to_only_the_requested_task(kind):
    validate_codex_structured_output_schema(
        load_codex_result_schema("material-learning-result@1.0")
    )
    value = worker_input()
    if kind == "extraction":
        value["request"]["work_input"] = extraction_work()
    parsed = validate_role_input(value, "support", "workflow-role/1.37.0")
    projected = constrained_result_schema("material-learning-result@1.0", parsed)
    validate_codex_structured_output_schema(projected)
    selected = "MaterialDiscoveryResult" if kind == "discovery" else "MaterialExtractionResult"
    other = "MaterialExtractionResult" if kind == "discovery" else "MaterialDiscoveryResult"
    assert selected in projected["$defs"]
    assert other not in projected["$defs"]
    assert (
        projected["$defs"][selected]["properties"]["input_sha256"]["const"]
        == parsed.request.work_input.input_sha256
    )


def test_definition_uses_one_existing_support_step_and_frozen_role_protocol():
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v1.yaml", {"support"})
    assert compiled.definition.definition_key == "material-learning"
    assert result_schema_protocol("material-learning-result@1.0") == "workflow-role/1.37.0"


def test_worker_guidance_reads_variable_layout_without_changing_source_identity():
    """Prompt regression only; not proof of live model layout accuracy."""
    for requirement in (
        "not a fixed book template or OCR reading order",
        "all columns, sidebars, shared passages",
        "chapter/book end or in SOLUTIONS",
        "Missing labels stay null",
        "unobserved section stays unknown",
        "Do not force five options",
        "native tables/equations",
    ):
        assert requirement in MATERIAL_LEARNING_GUIDANCE
    layer = (
        ROOT / "config/control-plane/material-learning-v1/instructions/material-learning.md"
    ).read_text()
    for pattern in ("Two-column", "ANSWER_KEY", "worked example", "section_path", "printed_label"):
        assert pattern in layer


def test_discovery_guidance_explains_existing_page_coverage_constraints():
    """Instruction regression, not a guarantee of live model output correctness."""
    for requirement in (
        "Each page's roles must be unique",
        "use NON_CONTENT only as its sole role",
        "the entire page has no instructional content",
        "Never add NON_CONTENT to a question page",
        "header, footer or copyright notice",
    ):
        assert requirement in MATERIAL_LEARNING_GUIDANCE


@pytest.mark.parametrize(
    "roles",
    [
        ["QUESTION", "QUESTION"],
        ["QUESTION", "NON_CONTENT"],
        ["NON_CONTENT", "NON_CONTENT"],
    ],
)
def test_guidance_does_not_relax_duplicate_or_mixed_non_content_coverage(roles):
    with pytest.raises(ValidationError, match="MATERIAL_LEARNING_PAGE_COVERAGE_INVALID"):
        MaterialPageCoverage(source_role="MAIN", physical_page=1, roles=roles, note="")


@pytest.mark.parametrize("roles", [["QUESTION"], ["QUESTION", "SOLUTION"], ["NON_CONTENT"]])
def test_existing_distinct_content_roles_or_single_non_content_remain_valid(roles):
    parsed = MaterialPageCoverage(source_role="MAIN", physical_page=1, roles=roles, note="")
    assert parsed.roles == tuple(roles)


@pytest.mark.parametrize(
    "category,name",
    [
        ("roles", "material-learning-input-v1"),
        ("roles", "material-learning-result-v1"),
        ("control-plane", "resolved-execution-plan-v33"),
    ],
)
def test_new_role_and_control_resource_mirrors(category, name):
    assert (ROOT / "schemas/workflow" / category / (name + ".schema.json")).read_bytes() == (
        ROOT / "packages/workflow/eom_workflow/resources" / category / (name + ".schema.json")
    ).read_bytes()

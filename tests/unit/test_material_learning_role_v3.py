"""The exact-score execution family neither rounds points nor reinterprets old runs."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_workflow.control_plane import ResolvedExecutionPlanV41
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.material_learning_request import (
    MaterialLearningWorkerRequestV3,
    MaterialLearningWorkflowRequestV3,
    material_learning_contract,
    parse_material_learning_worker_request,
    parse_material_learning_workflow_request,
)
from eom_workflow.models import MaterialLearningRoleResultV3
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_role_input_schema,
    role_schema_bundle_hash,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result_for_request,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_material_learning_role_contracts import material_plan
from tests.unit.test_material_learning_role_v2 import request_input

PROTOCOL = "workflow-role/1.40.0"
RESULT = "material-learning-result@3.0"


def test_execution_schemas_and_installed_mirrors_match_the_pinned_generator():
    from scripts.contracts.generate_material_exact_score_execution_schemas import schemas

    root = Path(__file__).resolve().parents[2]
    for relative, document in schemas().items():
        canonical = root / "schemas/workflow" / relative
        installed = root / "packages/workflow/eom_workflow/resources" / relative
        assert json.loads(canonical.read_bytes()) == document
        assert canonical.read_bytes() == installed.read_bytes()


def request_v3(kind="native", points="1.5", *, disposition="IMAGE"):
    message, result = request_input(kind, disposition=disposition)
    message["protocol_version"] = result["protocol_version"] = PROTOCOL
    message["request"]["native_printed_score"] = (
        dict(state="PRINTED", points=points) if kind == "native" else None
    )
    learning = result["output"]["learning_result"]
    if kind != "discovery":
        learning["schema_version"] = "material-learning-extraction-result/2.0"
        if learning["proposal"] is not None:
            learning["proposal"]["content"]["schema_version"] = "creative-source-item-draft/2.0"
        if kind == "native" and learning["proposal"] is not None:
            learning["proposal"]["content"]["score"] = dict(state="PRINTED", points=points)
    return message, result


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_v3_result_admission_and_factories_preserve_exact_source_selection(kind):
    message, result = request_v3(kind)
    snapshot = deepcopy(message)
    Draft202012Validator(load_role_input_schema("support", PROTOCOL)).validate(message)
    parsed = validate_role_input(message, "support", PROTOCOL)
    accepted = validate_role_result_for_request(result, "support", RESULT, parsed)
    assert isinstance(parsed.request, MaterialLearningWorkerRequestV3)
    assert isinstance(accepted, MaterialLearningRoleResultV3)
    assert message == snapshot
    request = parse_material_learning_worker_request(message["request"])
    assert type(request) is MaterialLearningWorkerRequestV3
    workflow = MaterialLearningWorkflowRequestV3(**message["request"])
    assert workflow.worker_request() == request
    assert parse_material_learning_workflow_request(workflow.model_dump(mode="json")) == workflow
    assert material_learning_contract(request).definition_version == "3.0.0"
    assert (
        material_learning_contract(workflow).plan_schema_version == "resolved-execution-plan/41.0"
    )


@pytest.mark.parametrize("points", ["1.5", "2.5", 2])
def test_generation_is_closed_and_pins_the_observed_score(points):
    message, result = request_v3(points=points)
    parsed = validate_role_input(message, "support", PROTOCOL)
    schema = constrained_result_schema(RESULT, parsed)
    validate_codex_structured_output_schema(schema)
    Draft202012Validator(schema).validate(result)
    bad = deepcopy(result)
    bad["output"]["learning_result"]["proposal"]["content"]["score"] = dict(
        state="PRINTED", points=15
    )
    assert not Draft202012Validator(schema).is_valid(bad)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result_for_request(bad, "support", RESULT, parsed)


@pytest.mark.parametrize(
    "kind,score",
    [
        ("native", None),
        ("extraction", {"state": "PRINTED", "points": "1.5"}),
        ("discovery", {"state": "PRINTED", "points": 2}),
    ],
)
def test_native_score_cannot_be_detached_from_its_source_question_scope(kind, score):
    message, _ = request_v3(kind)
    message["request"]["native_printed_score"] = score
    with pytest.raises((ValidationError, WorkflowSchemaError)):
        validate_role_input(message, "support", PROTOCOL)


def test_unreadable_native_content_remains_an_explicit_observation_not_an_invalid_worker_result():
    message, result = request_v3(disposition="UNRESOLVED")
    parsed = validate_role_input(message, "support", PROTOCOL)
    observed = validate_role_result_for_request(result, "support", RESULT, parsed)
    assert observed.output.learning_result.status == "NEEDS_DECISION"
    assert observed.output.learning_result.proposal is None
    assert observed.output.learning_result.conflicts


def test_historical_schema_bundles_are_unchanged_and_reject_new_envelopes():
    assert (
        role_schema_bundle_hash("workflow-role/1.37.0")
        == "sha256:f2f95cbdfd6a8b6d2f7ab3d842fa417a11c7629a36442b37834402a1a4134dd2"
    )
    assert (
        role_schema_bundle_hash("workflow-role/1.39.0")
        == "sha256:4852867c6dd802c0699df9f4954006bc800ea7079e5198234c79556c656ed44b"
    )
    message, result = request_v3()
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(message, "support", "workflow-role/1.39.0")
    old, _ = request_input("native")
    with pytest.raises(WorkflowSchemaError):
        validate_role_result_for_request(
            result, "support", RESULT, validate_role_input(old, "support", "workflow-role/1.39.0")
        )


def test_plan_pins_score_to_request_and_rejects_unhashed_value_changes():
    message, _ = request_v3()
    value = material_plan()
    value.update(
        schema_version="resolved-execution-plan/41.0",
        resolver_version="41.0.0",
        workflow_definition_version="3.0.0",
        work_input=message["request"]["work_input"],
        native_visual_scope=message["request"]["native_visual_scope"],
        native_printed_score=message["request"]["native_printed_score"],
    )
    value["plan_sha256"] = content_sha256(
        {key: child for key, child in value.items() if key != "plan_sha256"}
    )
    validate_control_contract("resolved-execution-plan-v41", value)
    parsed = ResolvedExecutionPlanV41.model_validate(value)
    assert parsed.native_printed_score.points == "1.5"
    value["native_printed_score"]["points"] = "2.5"
    with pytest.raises(ValidationError, match="plan hash differs"):
        ResolvedExecutionPlanV41.model_validate(value)

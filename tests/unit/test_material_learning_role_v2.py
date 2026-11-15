"""Future material envelopes add native-use closure without changing released inner work/results."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from eom_catalog_contracts.material_learning import MaterialExtractionWork
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.admission import workflow_admission
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ResolvedExecutionPlanV40
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.material_learning_prompt import (
    MATERIAL_LEARNING_GUIDANCE,
    material_learning_guidance,
)
from eom_workflow.material_learning_request import (
    MaterialLearningWorkerRequest,
    MaterialLearningWorkerRequestV2,
    MaterialLearningWorkflowRequest,
    MaterialLearningWorkflowRequestV2,
    parse_material_learning_worker_request,
    parse_material_learning_workflow_request,
)
from eom_workflow.models import MaterialLearningRoleResultV2
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_role_input_schema,
    result_schema_protocol,
    role_schema_bundle_hash,
    validate_codex_structured_output_schema,
    validate_material_learning_role_result,
    validate_role_input,
    validate_role_result,
    validate_role_result_for_request,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import (
    discovery,
    extraction_result,
    extraction_work,
    rehash,
    work,
)
from tests.unit.test_material_learning_role_contracts import material_plan, worker_input
from tests.unit.test_material_native_files import native_work
from tests.unit.test_material_native_visual_coverage import case

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "workflow-role/1.39.0"
RESULT = "material-learning-result@2.0"


def request_input(kind="discovery", *, disposition="NATIVE_TABLE", empty=False):
    message = worker_input()
    message["protocol_version"] = PROTOCOL
    scope = coverage = None
    learning = discovery() if kind == "discovery" else extraction_result()
    input_work = work() if kind == "discovery" else extraction_work()
    if kind == "native":
        scope, observed, coverage = case(disposition)
        input_work = native_work()
        input_work["question"]["printed_label"] = str(scope.item_number)
        input_work["solutions"][0]["printed_label"] = f"{scope.item_number}."
        input_work["sources"][0]["office_catalog"]["sha256"] = scope.source_catalog_sha256
        rehash(input_work)
        learning = observed.model_dump(mode="json")
        learning["input_sha256"] = input_work["input_sha256"]
        for region in learning["regions"]:
            if region["role"] == "EDITORIAL_SOLUTION":
                region["physical_page"] = 2
        if empty:
            scope = scope.model_copy(update={"allowed_picture_use_ids": ()})
            coverage["dispositions"] = []
        coverage.update(
            input_sha256=input_work["input_sha256"],
            scope_sha256=content_sha256(scope.model_dump(mode="json")),
        )
    message["request"] = dict(
        request_name="MATERIAL_LEARNING_REQUEST",
        work_input=input_work,
        native_visual_scope=scope.model_dump(mode="json") if scope is not None else None,
    )
    result = {
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
    result.update(
        status="ok",
        completed_at="2026-11-15T02:00:00Z",
        output=dict(learning_result=learning, native_visual_coverage=coverage),
    )
    return message, result


def parse_input(message):
    return validate_role_input(message, "support", PROTOCOL)


def validate_pair(message, result):
    return validate_role_result_for_request(result, "support", RESULT, parse_input(message))


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_future_wrapper_preserves_inner_work_and_nested_result(kind):
    message, result = request_input(kind)
    original_work = canonical_json_bytes(message["request"]["work_input"])
    original_result = canonical_json_bytes(result["output"]["learning_result"])
    parsed = parse_input(message)
    observed = validate_pair(message, result)
    assert isinstance(parsed.request, MaterialLearningWorkerRequestV2)
    assert isinstance(observed, MaterialLearningRoleResultV2)
    assert canonical_json_bytes(parsed.request.work_input.model_dump(mode="json")) == original_work
    assert (
        canonical_json_bytes(observed.output.learning_result.model_dump(mode="json"))
        == original_result
    )
    assert parsed.artifact.file_name == "result.json"
    assert parsed.upstream_artifacts == ()


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_exact_schema_and_typed_request_factories_choose_v2_by_explicit_field(kind):
    message, _ = request_input(kind)
    Draft202012Validator(load_role_input_schema("support", PROTOCOL)).validate(message)
    request = parse_material_learning_worker_request(message["request"])
    assert isinstance(request, MaterialLearningWorkerRequestV2)
    workflow = MaterialLearningWorkflowRequestV2(**message["request"])
    assert workflow.worker_request() == request
    assert parse_material_learning_workflow_request(workflow.model_dump(mode="json")) == workflow
    assert workflow.execution_preset_key == "material-learning"


def test_historical_factories_remain_exact_v1_and_reject_future_fields():
    original = MaterialLearningWorkerRequest(work_input=work())
    assert parse_material_learning_worker_request(original.model_dump(mode="json")) == original
    workflow = MaterialLearningWorkflowRequest(work_input=work())
    assert parse_material_learning_workflow_request(workflow.model_dump(mode="json")) == workflow
    with pytest.raises(ValidationError):
        MaterialLearningWorkerRequest(work_input=work(), native_visual_scope=None)
    with pytest.raises(ValidationError):
        MaterialLearningWorkerRequestV2(work_input=work())


@pytest.mark.parametrize("side", ["input", "result"])
def test_required_nullable_fields_cannot_be_omitted(side):
    message, result = request_input()
    if side == "input":
        message["request"].pop("native_visual_scope")
        with pytest.raises(ValueError):
            parse_input(message)
    else:
        result["output"].pop("native_visual_coverage")
        with pytest.raises(ValueError):
            validate_role_result(result, "support", RESULT)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(protocol_version="workflow-role/1.37.0"),
        lambda value: value.update(protocol_version="workflow-role/1.38.0"),
        lambda value: value.update(role="authoring"),
        lambda value: value.update(upstream_artifacts=[{"untrusted": True}]),
        lambda value: value["request"].update(permit_native=True),
    ],
)
def test_v2_does_not_accept_other_role_protocol_or_model_supplied_authority(change):
    message, _ = request_input("native")
    change(message)
    with pytest.raises(ValueError):
        parse_input(message)


@pytest.mark.parametrize("change", ["number", "catalog", "pdf", "discovery"])
def test_scope_must_match_actual_work_shape_not_only_hint_text(change):
    message, _ = request_input("native")
    if change == "number":
        message["request"]["native_visual_scope"]["item_number"] = 10
    elif change == "catalog":
        message["request"]["native_visual_scope"]["source_catalog_sha256"] = "sha256:" + "f" * 64
    elif change == "pdf":
        message["request"]["work_input"] = extraction_work()
    else:
        message["request"]["work_input"] = work()
    with pytest.raises(ValueError):
        parse_input(message)


@pytest.mark.parametrize(
    "kind", ["IMAGE", "NATIVE_EQUATION", "NATIVE_TABLE", "NON_CONTENT", "UNRESOLVED"]
)
def test_native_receiver_accepts_closed_actual_representation_kinds(kind):
    message, result = request_input("native", disposition=kind)
    validate_pair(message, result)
    projection = constrained_result_schema(RESULT, parse_input(message))
    Draft202012Validator(projection).validate(result)
    validate_codex_structured_output_schema(projection)


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_codex_schema_and_receiver_use_same_exact_context(kind):
    message, result = request_input(kind)
    parsed = parse_input(message)
    schema = constrained_result_schema(RESULT, parsed)
    validate_codex_structured_output_schema(load_codex_result_schema(RESULT))
    validate_codex_structured_output_schema(schema)
    Draft202012Validator(schema).validate(result)
    assert set(schema["properties"]["output"]["properties"]) == {
        "learning_result",
        "native_visual_coverage",
    }
    bad = deepcopy(result)
    bad["job_id"] = "job_" + "f" * 32
    with pytest.raises(SchemaError):
        Draft202012Validator(schema).validate(bad)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result_for_request(bad, "support", RESULT, parsed)


@pytest.mark.parametrize("empty", [False, True])
def test_native_projection_pins_actual_scope_hash_input_use_enum_and_count(empty):
    message, result = request_input("native", empty=empty)
    parsed = parse_input(message)
    schema = constrained_result_schema(RESULT, parsed)
    props = schema["$defs"]["MaterialNativeVisualCoverage"]["properties"]
    scope = parsed.request.native_visual_scope
    assert props["input_sha256"]["const"] == parsed.request.work_input.input_sha256
    assert props["scope_sha256"]["const"] == content_sha256(scope.model_dump(mode="json"))
    count = len(scope.allowed_picture_use_ids)
    assert props["dispositions"]["minItems"] == props["dispositions"]["maxItems"] == count
    if not empty:
        assert schema["$defs"]["MaterialNativeVisualCoverage_pictureUseId"]["enum"] == list(
            scope.allowed_picture_use_ids
        )
    validate_pair(message, result)


@pytest.mark.parametrize("change", ["null", "missing", "duplicate", "foreign", "scope", "block"])
def test_native_receiver_rejects_incomplete_or_unrelated_coverage_before_commit(change):
    message, result = request_input("native")
    coverage = result["output"]["native_visual_coverage"]
    if change == "null":
        result["output"]["native_visual_coverage"] = None
    elif change == "missing":
        coverage["dispositions"] = []
    elif change == "duplicate":
        coverage["dispositions"] *= 2
    elif change == "foreign":
        coverage["dispositions"][0]["picture_use_id"] = "officeobj_" + "f" * 32
    elif change == "scope":
        coverage["scope_sha256"] = "sha256:" + "f" * 64
    else:
        coverage["dispositions"][0]["block_id"] = "block_missing"
    with pytest.raises(ValueError):
        validate_pair(message, result)


def test_non_native_result_cannot_smuggle_native_coverage_and_generic_reader_stays_historical():
    message, result = request_input("native")
    message["request"]["native_visual_scope"] = None
    generic = validate_role_result(result, "support", RESULT)
    with pytest.raises(ValueError, match="UNEXPECTED"):
        validate_material_learning_role_result(parse_input(message).request, generic)
    with pytest.raises(ValueError):
        validate_pair(message, result)


def test_future_plan_pins_full_scope_and_same_single_logical_material_preset():
    message, _ = request_input("native")
    value = material_plan()
    value.update(
        schema_version="resolved-execution-plan/40.0",
        resolver_version="40.0.0",
        workflow_definition_version="2.0.0",
        work_input=message["request"]["work_input"],
        native_visual_scope=message["request"]["native_visual_scope"],
    )
    rehash(value, "plan_sha256")
    validate_control_contract("resolved-execution-plan-v40", value)
    plan = ResolvedExecutionPlanV40.model_validate(value)
    assert plan.work_input == MaterialExtractionWork.model_validate(value["work_input"])
    assert plan.steps[0].network == "disabled"
    assert plan.steps[0].reference_bundle is None
    changed = deepcopy(value)
    changed["native_visual_scope"]["question_document"]["artifact_revision_id"] = "rev_" + "f" * 32
    with pytest.raises(ValidationError, match="plan hash"):
        ResolvedExecutionPlanV40.model_validate(changed)
    changed = deepcopy(value)
    changed["steps"][0]["network"] = "enabled"
    rehash(changed, "plan_sha256")
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV40.model_validate(changed)


def test_discovery_plan_and_result_require_explicit_null_scope_not_omission():
    value = material_plan()
    value.update(
        schema_version="resolved-execution-plan/40.0",
        resolver_version="40.0.0",
        workflow_definition_version="2.0.0",
        native_visual_scope=None,
    )
    rehash(value, "plan_sha256")
    validate_control_contract("resolved-execution-plan-v40", value)
    ResolvedExecutionPlanV40.model_validate(value)
    value.pop("native_visual_scope")
    rehash(value, "plan_sha256")
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV40.model_validate(value)


def test_new_definition_has_same_one_agent_topology_and_one_material_model_card_key():
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v2.yaml", {"support"})
    assert compiled.definition.definition_key == "material-learning"
    assert compiled.definition.definition_version == "2.0.0"
    assert tuple(compiled.steps_by_key) == ("learn", "complete")
    assert result_schema_protocol(RESULT) == PROTOCOL
    assert workflow_admission("material-learning", "2.0.0").role_protocol_version == PROTOCOL


def test_native_prompt_is_selected_only_for_explicit_new_native_input():
    for request in (
        MaterialLearningWorkerRequest(work_input=work()),
        MaterialLearningWorkerRequestV2(work_input=work(), native_visual_scope=None),
        parse_input(request_input("extraction")[0]).request,
    ):
        assert material_learning_guidance(request) is MATERIAL_LEARNING_GUIDANCE
    text = material_learning_guidance(parse_input(request_input("native")[0]).request)
    assert text.startswith(MATERIAL_LEARNING_GUIDANCE)
    for requirement in (
        "EVERY allowed_picture_use_id exactly once",
        "NATIVE_EQUATION or NATIVE_TABLE",
        "do not call them NON_CONTENT",
        "Do not force all uses into images",
        "do not calculate hashes or invent block hashes",
    ):
        assert requirement in text


@pytest.mark.parametrize(
    "category,name,digest",
    [
        (
            "roles",
            "material-learning-input-v1",
            "28a6ef7636d7cc31a90e19682d315f39841df8991a362acf5f560bb9ea574f06",
        ),
        (
            "roles",
            "material-learning-result-v1",
            "b84b323aee3e40b6b69e081296242dba82c3adf673d3ded1caf5645737ca5810",
        ),
        (
            "control-plane",
            "resolved-execution-plan-v33",
            "4d877271f144c8318201b1a4c589de75b0376aec179338d2555f9892dc827279",
        ),
    ],
)
def test_historical_released_schema_bytes_are_unchanged(category, name, digest):
    assert (
        sha256(
            (ROOT / "schemas/workflow" / category / (name + ".schema.json")).read_bytes()
        ).hexdigest()
        == digest
    )
    assert role_schema_bundle_hash("workflow-role/1.37.0") == (
        "sha256:f2f95cbdfd6a8b6d2f7ab3d842fa417a11c7629a36442b37834402a1a4134dd2"
    )


@pytest.mark.parametrize(
    "category,name",
    [
        ("roles", "material-learning-input-v2"),
        ("roles", "material-learning-result-v2"),
        ("control-plane", "resolved-execution-plan-v40"),
    ],
)
def test_new_canonical_schema_and_installed_mirror_are_identical(category, name):
    assert (ROOT / "schemas/workflow" / category / (name + ".schema.json")).read_bytes() == (
        ROOT / "packages/workflow/eom_workflow/resources" / category / (name + ".schema.json")
    ).read_bytes()

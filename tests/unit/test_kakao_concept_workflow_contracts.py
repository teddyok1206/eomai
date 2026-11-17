"""Shared Workflow purpose/pointer isolation, not live slot or application acceptance."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest
from eom_identifiers import content_sha256
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_contracts.concepts import concept_input_members
from eom_workflow.compiler import compile_definition
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import (
    WORK_SCHEMA_SHA256,
    KakaoConceptWork,
    KakaoConceptWorkflowRequest,
    load_kakao_concept_work_schema,
    validate_kakao_concept_request_bytes,
)
from eom_workflow.kakao_concept_result import KakaoConceptRoleResult
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    load_role_input_schema,
    load_role_result_schema,
    result_schema_protocol,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result_for_request,
)
from jsonschema import Draft202012Validator

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_kakao_concept_contracts import (
    ROOT,
    compose_request,
    composed,
    plan,
    plan_request,
    result,
)
from tests.unit.test_material_learning_role_contracts import worker_input as material_input


def work_value(request=None):
    request = plan_request() if request is None else request
    raw = canonical_bytes(request.model_dump(mode="json"))
    members = concept_input_members(request)
    return dict(
        schema_version="kakao-concept-work/1.0",
        task_id=request.task_id,
        phase=request.phase,
        source_binding_id="kakaobinding_" + "1" * 32,
        question_revision_id=request.question.question_revision_id,
        question_manifest=dict(
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "2" * 32,
            member_path="question/question.json",
            sha256=request.question.question_manifest_sha256,
            schema_ref="eom://schemas/kakao-archive/question-manifest-v1/1.0",
            media_type="application/json",
        ),
        request_member=dict(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "3" * 32,
            member_path="concept/request.json",
            sha256=sha256(raw),
            schema_ref="eom://schemas/kakao-archive/concept-assistance/1.0",
            media_type="application/json",
        ),
        request_bytes=len(raw),
        files=[
            dict(
                relative_path=member.relative_path,
                source=dict(
                    artifact_id=f"artifact_{i:032x}",
                    artifact_revision_id=f"rev_{i:032x}",
                    member_path="original.png",
                    sha256=member.sha256,
                    schema_ref="eom://schemas/educational-document/page-image/1.0",
                    media_type=member.media_type,
                ),
                size_bytes=member.size_bytes,
                width_pixels=800,
                height_pixels=1000,
            )
            for i, member in enumerate(members, 10)
        ],
    )


def message(request=None):
    value = material_input()
    value.update(
        protocol_version="workflow-role/1.41.0",
        request=dict(request_name="KAKAO_CONCEPT_REQUEST", work_input=work_value(request)),
    )
    return value


def plan_value():
    value = _plan()
    value.update(
        schema_version="resolved-execution-plan/42.0",
        workflow_definition_key="kakao-concepts",
        workflow_definition_version="1.0.0",
        resolver_version="42.0.0",
        work_input=work_value(),
    )
    value["steps"][0]["step_key"] = "assist"
    return rehash(value)


def rehash(value):
    value["plan_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "plan_sha256"}
    )
    return value


def test_new_work_schema_is_pinned_mirrored_closed_and_pointer_only():
    canonical = ROOT / "schemas/workflow/control-plane/kakao-concept-work-v1.schema.json"
    mirror = ROOT / "packages/workflow/eom_workflow/resources/control-plane" / canonical.name
    assert canonical.read_bytes() == mirror.read_bytes()
    assert sha256(canonical.read_bytes()) == WORK_SCHEMA_SHA256
    Draft202012Validator.check_schema(load_kakao_concept_work_schema())
    work = KakaoConceptWork.model_validate(work_value())
    assert set(type(work).model_fields) == {
        "schema_version",
        "task_id",
        "phase",
        "source_binding_id",
        "question_revision_id",
        "question_manifest",
        "request_member",
        "request_bytes",
        "files",
    }
    assert "student" not in type(work).model_fields and "operator_id" not in type(work).model_fields
    assert len(canonical_bytes(work.model_dump(mode="json"))) < 16000
    assert KakaoConceptWorkflowRequest(work_input=work).worker_request().work_input == work


@pytest.mark.parametrize("compose", [False, True])
def test_request_pointer_binds_exact_canonical_private_input_and_member_set(compose):
    request = compose_request() if compose else plan_request()
    raw = canonical_bytes(request.model_dump(mode="json"))
    work = KakaoConceptWork.model_validate(work_value(request))
    assert validate_kakao_concept_request_bytes(work, raw) == request


@pytest.mark.parametrize(
    "field,new",
    [
        ("phase", "COMPOSE"),
        ("task_id", "kakaoconcepttask_" + "a" * 32),
        ("question_revision_id", "kakaoquestionrev_" + "a" * 32),
    ],
)
def test_wrong_phase_task_or_question_is_not_reinterpreted_as_latest(field, new):
    request = plan_request()
    work = KakaoConceptWork.model_validate(work_value(request) | {field: new})
    with pytest.raises(ValueError, match="REQUEST_MISMATCH"):
        validate_kakao_concept_request_bytes(work, canonical_bytes(request.model_dump(mode="json")))


@pytest.mark.parametrize("change", ["missing", "extra", "hash", "size", "media"])
def test_worker_cannot_receive_an_unreferenced_or_changed_source_file(change):
    request = plan_request()
    value = work_value(request)
    if change == "missing":
        value["files"] = []
    elif change == "extra":
        value["files"].append(dict(value["files"][0], relative_path="other/private.png"))
    elif change == "hash":
        value["files"][0]["source"]["sha256"] = sha256(b"wrong")
    elif change == "size":
        value["files"][0]["size_bytes"] += 1
    else:
        value["files"][0]["source"]["media_type"] = "image/jpeg"
    work = KakaoConceptWork.model_validate(value)
    with pytest.raises(ValueError, match="MEMBER_SET_MISMATCH"):
        validate_kakao_concept_request_bytes(work, canonical_bytes(request.model_dump(mode="json")))


@pytest.mark.parametrize("change", ["duplicate", "path", "blob", "dimension", "media"])
def test_work_pointer_model_rejects_duplicate_unsafe_or_non_image_files(change):
    value = work_value()
    if change == "duplicate":
        value["files"] *= 2
    elif change == "path":
        value["files"][0]["relative_path"] = "images/../private.png"
    elif change == "blob":
        value["payload"] = "not-a-pointer"
    elif change == "dimension":
        value["files"][0].update(width_pixels=30000, height_pixels=30000)
    else:
        value["files"][0]["source"]["media_type"] = "application/octet-stream"
    with pytest.raises(ValueError):
        KakaoConceptWork.model_validate(value)


def test_artifact_bytes_hash_and_canonical_serialization_are_required():
    request = plan_request()
    work = KakaoConceptWork.model_validate(work_value(request))
    raw = canonical_bytes(request.model_dump(mode="json"))
    for wrong in (raw + b"\n", raw.replace(b"PLAN", b"WRONG")):
        with pytest.raises(ValueError, match="REQUEST_HASH_MISMATCH"):
            validate_kakao_concept_request_bytes(work, wrong)
    pretty = json.dumps(request.model_dump(mode="json"), indent=2).encode()
    value = work.model_dump(mode="json")
    value["request_bytes"] = len(pretty)
    value["request_member"]["sha256"] = sha256(pretty)
    with pytest.raises(ValueError, match="REQUEST_MISMATCH"):
        validate_kakao_concept_request_bytes(KakaoConceptWork.model_validate(value), pretty)


@pytest.mark.parametrize("change", ["attempt", "role", "protocol", "purpose", "upstream"])
def test_phase_cannot_run_as_another_role_or_adopt_foreign_workflow_artifacts(change):
    value = message()
    if change == "attempt":
        value["attempt"] = 2
    elif change == "role":
        value["role"] = "authoring"
    elif change == "protocol":
        value["protocol_version"] = "workflow-role/1.40.0"
    elif change == "purpose":
        value["request"]["request_name"] = "MATERIAL_LEARNING_REQUEST"
    else:
        value["upstream_artifacts"] = [dict(unrelated="artifact")]
    with pytest.raises(ValueError):
        validate_role_input(value, "support", "workflow-role/1.41.0")


@pytest.mark.parametrize("compose", [False, True])
def test_role_and_codex_schema_use_actual_task_phase_and_artifact_identity(compose):
    request = compose_request() if compose else plan_request()
    frame = message(request)
    parsed = validate_role_input(frame, "support", "workflow-role/1.41.0")
    Draft202012Validator(load_role_input_schema("support", "workflow-role/1.41.0")).validate(frame)
    projected = constrained_result_schema("kakao-concepts-result@1.0", parsed)
    validate_codex_structured_output_schema(projected)
    value = {
        key: frame[key]
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
        completed_at="2026-11-17T08:00:00Z",
        output=result(request, composed() if compose else plan()),
    )
    Draft202012Validator(projected).validate(value)
    Draft202012Validator(load_role_result_schema("kakao-concepts-result@1.0")).validate(value)
    checked = validate_role_result_for_request(
        value, "support", "kakao-concepts-result@1.0", parsed
    )
    assert isinstance(checked, KakaoConceptRoleResult)
    assert checked.output.task_id == request.task_id
    assert (
        "KakaoConcept_" + ("plan_result" if compose else "compose_result") not in projected["$defs"]
    )
    for field in ("job_id", "workflow_id", "step_run_id"):
        changed = deepcopy(value)
        changed[field] = field.removesuffix("_id") + "_" + "f" * 32
        with pytest.raises(ValueError):
            validate_role_result_for_request(
                changed, "support", "kakao-concepts-result@1.0", parsed
            )
    changed = deepcopy(value)
    changed["output"]["request_sha256"] = sha256(b"stale")
    with pytest.raises(ValueError):
        validate_role_result_for_request(changed, "support", "kakao-concepts-result@1.0", parsed)


def test_generation_projection_does_not_weaken_canonical_status_guards():
    request = plan_request()
    frame = message(request)
    parsed = validate_role_input(frame, "support", "workflow-role/1.41.0")
    value = {
        key: frame[key]
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
    output = plan()
    output["queries"] = []
    value.update(status="ok", completed_at="2026-11-17T08:00:00Z", output=result(request, output))
    with pytest.raises(ValueError):
        validate_role_result_for_request(value, "support", "kakao-concepts-result@1.0", parsed)
    validate_codex_structured_output_schema(load_codex_result_schema("kakao-concepts-result@1.0"))


def test_one_step_definition_and_exact_plan_preserve_ordinary_pool_isolation():
    compiled = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    assert compiled.definition.definition_key == "kakao-concepts"
    assert compiled.definition.limits.max_step_attempts == 1
    assert result_schema_protocol("kakao-concepts-result@1.0") == "workflow-role/1.41.0"
    value = plan_value()
    validate_control_contract("resolved-execution-plan-v42", value)
    plan = KakaoConceptExecutionPlan.model_validate(value)
    assert plan.steps[0].worker_pool_key == "support"
    assert plan.steps[0].network == "disabled"
    for field, wrong in (
        ("step_key", "learn"),
        ("worker_pool_key", "customer-support"),
        ("network", "enabled"),
        ("general_knowledge_mode", "ALLOWED_WITH_PROVENANCE"),
    ):
        changed = deepcopy(value)
        changed["steps"][0][field] = wrong
        rehash(changed)
        with pytest.raises(ValueError):
            KakaoConceptExecutionPlan.model_validate(changed)


def test_ordinary_core_import_and_past_role_read_do_not_require_optional_kakao_wheel():
    script = """
import importlib.abc, sys
class BlockKakao(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('eom_kakao_archive_contracts'):
            raise ModuleNotFoundError('optional wheel deliberately absent')
sys.meta_path.insert(0, BlockKakao())
from eom_workflow.models import RoleWorkerInput, RoleResult
from eom_workflow.schemas import load_role_input_schema, load_role_result_schema
assert load_role_input_schema('support', 'workflow-role/1.37.0')
assert load_role_result_schema('material-learning-result@1.0')
assert not any(name.startswith('eom_kakao_archive_contracts') for name in sys.modules)
"""
    process = subprocess.run(
        [sys.executable, "-B", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert process.returncode == 0, process.stderr


def test_dedicated_instruction_distinguishes_execution_envelope_and_local_inputs():
    text = (
        ROOT / "config/control-plane/kakao-concepts-v1/instructions/kakao-concepts.md"
    ).read_text()
    assert "source/concepts/request.json" in text
    assert "source/concepts/files/x" in text
    assert "job/workflow/step/artifact" in text
    assert "task/request hash/phase" in text

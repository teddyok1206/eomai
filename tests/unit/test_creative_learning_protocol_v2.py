"""Released predecessor hashes and source-bound successor wire admission."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.external_item_learning_result_v2 import (
    stamp_external_item_learning_result_v2,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.orchestrator import Orchestrator
from eom_workflow.models import ExternalItemLearningRoleResultV2, RoleWorkerInput
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator

from tests.unit.test_external_item_learning_result_v2 import result_v2
from tests.unit.test_external_item_learning_role_schemas import _input
from tests.unit.test_external_item_learning_workflow_models import _references


def role_input():
    value = deepcopy(_input())
    value["protocol_version"] = "workflow-role/1.34.0"
    return value


def role_result():
    value = role_input()
    value.pop("request")
    value.pop("upstream_artifacts")
    value.pop("attempt")
    value.update(status="ok", completed_at="2026-10-29T02:00:00Z")
    result = result_v2()
    result.pop("result_sha256")
    source = role_input()["request"]["work_input"]["source"]
    for field in ("source_id", "source_revision_id", "external_number"):
        result[field] = source[field]
    result["input_sha256"] = source["input_sha256"]
    value["output"] = {"learning_result": result}
    return value


def test_source_role_successor_reuses_the_exact_work_input_contract():
    original = _input()
    parsed = validate_role_input(role_input(), "support", "workflow-role/1.34.0")
    assert parsed.request.model_dump(mode="json") == RoleWorkerInput.model_validate(
        original
    ).request.model_dump(mode="json")
    with pytest.raises(ValueError):
        validate_role_input(role_input(), "support", "workflow-role/1.33.0")


def test_new_role_result_is_owner_stamped_and_survives_canonical_replay():
    original = role_result()
    admitted = validate_role_result(original, "support", "external-item-learning-result@2.0")
    assert isinstance(admitted, ExternalItemLearningRoleResultV2)
    assert "result_sha256" not in original["output"]["learning_result"]
    assert (
        validate_role_result(
            admitted.model_dump(mode="json"), "support", "external-item-learning-result@2.0"
        )
        == admitted
    )
    assert admitted.output.learning_result.proposal.content.score.state == "UNPRINTED"
    assert admitted.output.learning_result.solution_report.answer_labels == ("1",)


def test_codex_projection_and_constrained_source_reference_closure():
    projected = load_codex_result_schema("external-item-learning-result@2.0")
    raw = role_result()
    normalized = stamp_external_item_learning_result_v2(
        raw["output"]["learning_result"]
    ).model_dump(mode="json")
    normalized.pop("result_sha256")
    raw["output"]["learning_result"] = normalized
    Draft202012Validator(projected).validate(raw)
    constrained = constrained_result_schema(
        "external-item-learning-result@2.0", RoleWorkerInput.model_validate(role_input())
    )
    Draft202012Validator(constrained).validate(raw)
    definitions = constrained["$defs"]
    props = definitions["ExternalItemLearningResultV2"]["properties"]
    assert "result_sha256" not in props
    assert props["input_sha256"]["const"] == raw["output"]["learning_result"]["input_sha256"]
    assert definitions["ExternalItemLearningResult_region"]["properties"]["physical_page"][
        "maximum"
    ] == len(role_input()["request"]["work_input"]["page_set"]["pages"])
    assert all(
        ref.startswith("#/$defs/")
        for ref in _references(load_role_result_schema("external-item-learning-result@2.0"))
    )


def test_supplied_wrong_hash_is_not_replaced_by_normalization():
    value = role_result()
    value["output"]["learning_result"]["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="hash differs"):
        validate_role_result(value, "support", "external-item-learning-result@2.0")


@pytest.mark.parametrize("location", ["source", "independent"])
def test_generation_rejects_duplicate_choice_and_text_answer_representations(location):
    value = role_result()
    learning = value["output"]["learning_result"]
    if location == "source":
        learning["proposal"]["content"]["solution"]["accepted_answers"] = ["1"]
    else:
        learning["solution_report"]["accepted_answers"] = ["1"]
    validator = Draft202012Validator(load_codex_result_schema("external-item-learning-result@2.0"))
    assert not validator.is_valid(value)
    with pytest.raises(ValueError):
        validate_role_result(value, "support", "external-item-learning-result@2.0")


def test_generation_accepts_an_honest_undetermined_independent_solution():
    value = role_result()
    report = value["output"]["learning_result"]["solution_report"]
    report.update(
        answer_state="UNDETERMINED",
        answer_labels=[],
        accepted_answers=[],
        answer_cross_check="NOT_DETERMINED",
        editorial_region_ids=[],
    )
    assert Draft202012Validator(
        load_codex_result_schema("external-item-learning-result@2.0")
    ).is_valid(value)


def test_registering_a_wire_contract_does_not_authorize_model_execution():
    request = RoleWorkerInput.model_validate(role_input()).request
    orchestrator = object.__new__(Orchestrator)
    with pytest.raises(ControlPlaneError) as caught:
        orchestrator.submit_workflow_role(
            workflow_id="workflow_" + "a" * 32,
            step_run_id="steprun_" + "b" * 32,
            step_key="extract",
            attempt=1,
            role="support",
            request=request,
            upstream_artifacts=(),
            result_schema="external-item-learning-result@2.0",
            idempotency_key="source-successor-not-activated",
            prompt_text="fixture only",
        )
    assert caught.value.code == "CONTROL_CREATIVE_LEARNING_NOT_ACTIVATED"


@pytest.mark.parametrize(
    "version,expected",
    [
        (
            "workflow-role/1.0.1",
            "sha256:6fff452bb8c39ed8bc98487c29ad8f7f68e0b152181849a007c7f7eec56636a7",
        ),
        (
            "workflow-role/1.4.0",
            "sha256:c385885dc445cee96ae8f0c2a122678c3db68f9b10d8162c7695108fbcc47b4b",
        ),
        (
            "workflow-role/1.33.0",
            "sha256:926c8f0ecce98016b62515561b2fbf25a594b1ba5c4cfc8791fa6ab7323db025",
        ),
    ],
)
def test_released_predecessor_schema_bundles_remain_unchanged(version, expected):
    assert role_schema_bundle_hash(version) == expected

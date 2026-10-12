"""Generation-only absent-hash derivation; no worker, runtime, DB or model invocation."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_pair_result_v11 import (
    PairComparisonResultV11,
    parse_pair_comparison_result_v11,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_PROTOCOL_V11,
    TRANSFER_PAIR_RESULT_SCHEMA,
    TRANSFER_PAIR_RESULT_SCHEMA_V11,
    InferenceTransferPairWorkerRequestV11,
    validate_inference_transfer_worker_result_v11,
)
from eom_workflow.models import (
    ArtifactSpec,
    CustomerSupportRoleResult,
    InferenceTransferPairRoleResult,
    InferenceTransferPairRoleResultV11,
    RoleWorkerInput,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import NOW, profile, request, result, sha
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_v11

ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "job_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
STEP_RUN_ID = "steprun_" + "3" * 32


def _artifact() -> ArtifactSpec:
    return ArtifactSpec(
        logical_artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
    )


def _worker_request() -> InferenceTransferPairWorkerRequestV11:
    return InferenceTransferPairWorkerRequestV11(
        comparison=request(), left_profile=profile("a"), right_profile=profile("b")
    )


def _worker_input() -> RoleWorkerInput:
    return RoleWorkerInput(
        protocol_version=TRANSFER_PAIR_PROTOCOL_V11,
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="support",
        request=_worker_request(),
        upstream_artifacts=(),
        artifact=_artifact(),
    )


def _document() -> dict[str, Any]:
    return InferenceTransferPairRoleResultV11(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        artifact=_artifact(),
        completed_at=NOW,
        output=pair_result_v11(),
    ).model_dump(mode="json")


def _without_hash() -> dict[str, Any]:
    document = _document()
    del document["output"]["result_sha256"]
    return document


def _validate(document: object) -> InferenceTransferPairRoleResultV11:
    parsed = validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA_V11)
    assert isinstance(parsed, InferenceTransferPairRoleResultV11)
    return parsed


@pytest.mark.parametrize(
    "canonical,packaged,expected",
    [
        (
            "schemas/knowledge/item-inference-transfer-pair-result-v1_1.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
            "item-inference-transfer-pair-result-v1_1.schema.json",
            "sha256:5dd12768a41eef7d91edfbeb9effc399f2ad7525306f213bb945c3c7a3ec1451",
        ),
        (
            "schemas/workflow/roles/item-inference-transfer-pair-result-v2.schema.json",
            "packages/workflow/eom_workflow/resources/roles/"
            "item-inference-transfer-pair-result-v2.schema.json",
            "sha256:9589e3a32f065901e39abddb59580b74b1b7333bfc1995cfbad4686ca234ebfd",
        ),
        (
            "schemas/workflow/roles/item-inference-transfer-pair-input-v2.schema.json",
            "packages/workflow/eom_workflow/resources/roles/"
            "item-inference-transfer-pair-input-v2.schema.json",
            "sha256:ddaa82ef4a8d401a00e2990b1ea2332b218942f5903a3b5a79422fd6e57056fd",
        ),
    ],
)
def test_canonical_schema_bytes_and_package_mirrors_are_unchanged(
    canonical: str, packaged: str, expected: str
) -> None:
    payload = (ROOT / canonical).read_bytes()
    assert payload == (ROOT / packaged).read_bytes()
    assert sha256_bytes(payload) == expected


@pytest.mark.parametrize(
    "protocol,expected",
    [
        (
            TRANSFER_PAIR_PROTOCOL,
            "sha256:fc65246c255e51d9500797abc976bc68d4a3eb81483301c132e098b74614f8dc",
        ),
        (
            TRANSFER_PAIR_PROTOCOL_V11,
            "sha256:023510a8bb3071fd89336ee799725ec2a7335a2c2846f966e44353fbfcd2f800",
        ),
    ],
)
def test_role_schema_bundle_hash_remains_the_released_literal(protocol: str, expected: str) -> None:
    assert role_schema_bundle_hash(protocol) == expected


def test_generation_removes_only_inner_hash_without_mutating_canonical_schema() -> None:
    canonical = load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)
    before = canonical_json_bytes(canonical)
    generation = load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)
    original = canonical["$defs"]["InferenceTransferPairResultV11"]
    projected = generation["$defs"]["InferenceTransferPairResultV11"]
    assert "result_sha256" in original["properties"]
    assert "result_sha256" in original["required"]
    assert set(projected["properties"]) == set(original["properties"]) - {"result_sha256"}
    assert set(projected["required"]) == set(original["required"]) - {"result_sha256"}
    for name in ("request_id", "request_sha256", "left_profile", "right_profile", "rubric"):
        assert projected["properties"][name] == original["properties"][name]
    for name in ("job_id", "workflow_id", "step_run_id", "artifact", "output"):
        assert generation["properties"][name] == canonical["properties"][name]
    assert canonical_json_bytes(load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)) == before
    projected["properties"]["request_sha256"]["description"] = "test-only mutation"
    assert canonical_json_bytes(load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)) == before


def test_omitted_hash_passes_generation_then_becomes_strict_canonical_result() -> None:
    document = _without_hash()
    before = copy.deepcopy(document)
    expected = content_sha256(document["output"])
    Draft202012Validator(load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)).validate(
        document
    )
    parsed = _validate(document)
    assert parsed.output.result_sha256 == expected
    assert parsed.model_dump(mode="json") == before | {
        "output": before["output"] | {"result_sha256": expected}
    }
    validate_inference_transfer_worker_result_v11(_worker_request(), parsed.output)
    assert document == before
    assert "result_sha256" not in document["output"]


def test_constrained_generation_omits_hash_and_keeps_exact_worker_closure() -> None:
    document = _without_hash()
    schema = constrained_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11, _worker_input())
    Draft202012Validator(schema).validate(document)
    document["output"]["left_profile"]["profile_sha256"] = sha("f")
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(document)


def test_direct_canonical_boundaries_still_require_hash() -> None:
    document = _without_hash()
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)).validate(
            document
        )
    with pytest.raises(ValidationError):
        InferenceTransferPairRoleResultV11.model_validate(document)
    with pytest.raises(ValidationError):
        PairComparisonResultV11.model_validate(document["output"])
    with pytest.raises(JsonSchemaValidationError):
        parse_pair_comparison_result_v11(document["output"])


def test_correct_supplied_hash_is_preserved_and_input_is_immutable() -> None:
    document = _document()
    before = canonical_json_bytes(document)
    parsed = _validate(document)
    assert parsed.output.result_sha256 == document["output"]["result_sha256"]
    assert canonical_json_bytes(parsed.model_dump(mode="json")) == before
    assert canonical_json_bytes(document) == before


@pytest.mark.parametrize("supplied", [sha("f"), None, "", "not-a-digest", 123])
def test_supplied_wrong_null_or_malformed_hash_is_not_repaired(supplied: object) -> None:
    document = _document()
    document["output"]["result_sha256"] = supplied
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


def test_derived_hash_includes_axes_preserves_body_and_excludes_envelope() -> None:
    document = _without_hash()
    original_hash = content_sha256(document["output"])
    document["output"]["axes"][1]["explanation"] = "새 합성 소재 설명: 정확한 원문을 보존한다."
    document["completed_at"] = "2026-10-11T09:00:00Z"
    before = copy.deepcopy(document)
    expected = content_sha256(document["output"])
    parsed = _validate(document)
    assert parsed.output.result_sha256 == expected
    assert expected != original_hash
    assert expected != content_sha256(
        {name: value for name, value in document["output"].items() if name != "axes"}
    )
    assert expected != content_sha256(document)
    assert parsed.output.model_dump(mode="json", exclude={"result_sha256"}) == before["output"]
    assert document == before


def test_supplied_hash_cannot_hide_axis_content_change() -> None:
    document = _document()
    document["output"]["axes"][0]["explanation"] = "수정된 합성 개념 설명"
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


@pytest.mark.parametrize(
    "path,invalid",
    [
        (("axes",), None),
        (("axes",), []),
        (("axes", 0, "explanation"), ""),
        (("axes", 0, "explanation"), "  \n\t"),
        (("axes", 0, "explanation"), "hidden\x00text"),
        (("axes", 1, "axis"), "CONCEPT"),
        (("axes", 2, "judgement"), "DIFFERENT"),
        (("axes", 0, "left_claim_ids"), ["not-a-claim-id"]),
        (("axes", 0, "left_claim_ids"), ["transferclaim_decisive"] * 2),
        (("axes", 0, "left_claim_ids"), []),
        (("mappings", 0, "facet"), "UNKNOWN"),
        (("shared_idea",), None),
        (("assessment_kind",), "HUMAN_VERIFIED"),
    ],
)
def test_omitted_hash_does_not_repair_malformed_axis_content_or_refs(
    path: tuple[str | int, ...], invalid: object
) -> None:
    document = _without_hash()
    target: Any = document["output"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = invalid
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


def test_omitted_hash_does_not_reorder_axes_or_fill_missing_axis() -> None:
    reversed_axes = _without_hash()
    reversed_axes["output"]["axes"].reverse()
    before = copy.deepcopy(reversed_axes)
    with pytest.raises(WorkflowSchemaError):
        _validate(reversed_axes)
    assert reversed_axes == before
    missing_axes = _without_hash()
    del missing_axes["output"]["axes"]
    with pytest.raises(WorkflowSchemaError):
        _validate(missing_axes)
    assert "axes" not in missing_axes["output"]


def test_omitted_hash_does_not_reorder_mappings_to_repair_canonical_admission() -> None:
    document = _without_hash()
    document["output"]["mappings"].reverse()
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError, match="mapping IDs must be sorted and unique"):
        _validate(document)
    assert document == before


@pytest.mark.parametrize("output", [None, [], "not-an-output-object"])
def test_nonobject_output_remains_rejected_without_input_mutation(output: object) -> None:
    document = _without_hash()
    document["output"] = output
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        _validate(document)
    assert document == before


@pytest.mark.parametrize(
    "path,foreign",
    [
        (("axes", 0, "left_claim_ids"), ["transferclaim_foreign"]),
        (("mappings", 0, "right_claim_ids"), ["transferclaim_foreign"]),
        (("left_profile", "profile_sha256"), sha("f")),
        (("request_sha256",), sha("f")),
    ],
)
def test_derived_hash_does_not_authorize_foreign_refs_at_worker_closure(
    path: tuple[str | int, ...], foreign: object
) -> None:
    document = _without_hash()
    target: Any = document["output"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = foreign
    before = copy.deepcopy(document)
    parsed = _validate(document)
    with pytest.raises(ValueError):
        validate_inference_transfer_worker_result_v11(_worker_request(), parsed.output)
    assert document == before


def test_legacy_generation_and_validation_remain_hash_required() -> None:
    document = InferenceTransferPairRoleResult(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        artifact=_artifact(),
        completed_at=NOW,
        output=result(),
    ).model_dump(mode="json")
    generation = load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA)
    assert content_sha256(generation) == (
        "sha256:e999f0a95f4401a0e3b94d6a53e22786c7e46946551714c36ca0d895c656991b"
    )
    parsed = validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA)
    assert isinstance(parsed, InferenceTransferPairRoleResult)
    assert parsed.model_dump(mode="json") == document
    del document["output"]["result_sha256"]
    before = copy.deepcopy(document)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(generation).validate(document)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA)
    assert document == before


def test_other_support_purpose_generation_and_validation_remain_unchanged() -> None:
    document = _document()
    document["protocol_version"] = "workflow-role/1.22.0"
    document["output"] = {
        "classification": "TRANSIENT_RUNTIME",
        "answer_text": "합성 고객 지원 응답",
        "recommended_actions": [{"title": "확인", "instruction": "현재 상태를 확인한다."}],
        "needs_operator": False,
        "operator_summary": None,
        "confidence": "MEDIUM",
        "mutation_performed": False,
    }
    before = copy.deepcopy(document)
    generation = load_codex_result_schema("customer-support-result@1.0")
    assert content_sha256(generation) == (
        "sha256:6cbcf1b113924aa01e8304eaeb52782f2740f1e79d05e5682d37f05c498452e2"
    )
    Draft202012Validator(generation).validate(document)
    parsed = validate_role_result(document, "support", "customer-support-result@1.0")
    assert isinstance(parsed, CustomerSupportRoleResult)
    assert parsed.model_dump(mode="json") == before
    assert document == before
    assert "result_sha256" not in document["output"]


def test_wrong_role_does_not_derive_a_missing_pair_hash() -> None:
    document = _without_hash()
    before = copy.deepcopy(document)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(document, "review", TRANSFER_PAIR_RESULT_SCHEMA_V11)
    assert document == before

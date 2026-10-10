"""Selected-pair public contract tests; no API, SQL, member read or worker execution."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_invocation as contract
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadResult,
    parse_pair_submit_request,
    parse_workflow_read_request,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_invocation_fixtures import (
    WORKFLOW_ID,
    read_request,
    read_result,
    rehash,
    role_result_document,
    submit_request,
)


def test_schema_first_resources_and_closed_202012_family() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-invocation"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    schema = load_schema("item-inference-transfer-invocation")
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-invocation/1.0"


def test_public_submission_reuses_small_selection_and_no_profile_payload() -> None:
    value = submit_request()
    assert parse_pair_submit_request(value.model_dump(mode="json")) == value
    assert len(canonical_json_bytes(value.model_dump(mode="json"))) < 32 * 1024
    assert not hasattr(value, "left_profile")
    assert not hasattr(value, "actor_id")
    with pytest.raises(ValidationError):
        value.expected_header_sha256 = sha("b")


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "operator_" + "a" * 32),
        ("role", "ADMIN"),
        ("permissions", ["ALL"]),
        ("requester_permissions_sha256", sha()),
        ("execution_preset_key", "customer-support"),
        ("left_profile", {"full": "profile payload is not accepted"}),
        ("token", "synthetic-not-a-token"),
    ],
)
def test_public_submission_rejects_caller_authority_and_profiles(field: str, value: Any) -> None:
    body = rehash(submit_request().model_dump(mode="json") | {field: value}, "submission_sha256")
    with pytest.raises(SchemaValidationError):
        parse_pair_submit_request(body)
    with pytest.raises(ValidationError):
        InferenceTransferPairSubmitRequest.model_validate(body)


def test_nested_prepare_cannot_be_reinterpreted_as_another_phase_or_principal() -> None:
    body = submit_request().model_dump(mode="json")
    body["snapshot_prepare"]["phase"] = "READ"
    with pytest.raises(SchemaValidationError):
        parse_pair_submit_request(rehash(body, "submission_sha256"))
    body["snapshot_prepare"]["phase"] = "PREPARE"
    body["snapshot_prepare"]["actor_id"] = "operator_" + "a" * 32
    with pytest.raises(SchemaValidationError):
        parse_pair_submit_request(rehash(body, "submission_sha256"))


@pytest.mark.parametrize("field", ["submission_sha256", "expected_header_sha256"])
def test_outer_submission_hash_closes_exact_header_and_selection(field: str) -> None:
    body = submit_request().model_dump(mode="json")
    body[field] = sha("f")
    with pytest.raises(ValidationError):
        parse_pair_submit_request(body)


def test_nested_model_copy_hash_bypass_is_rejected_before_submission() -> None:
    value = submit_request()
    copied = value.comparison.model_copy(update={"request_sha256": sha("f")})
    body = value.model_dump(mode="json") | {"comparison": copied.model_dump(mode="json")}
    with pytest.raises(ValidationError):
        InferenceTransferPairSubmitRequest.model_validate(rehash(body, "submission_sha256"))


def test_submission_byte_bound_is_canonical_encoded_size(monkeypatch: pytest.MonkeyPatch) -> None:
    body = submit_request().model_dump(mode="json")
    monkeypatch.setattr(
        contract, "MAX_TRANSFER_SUBMISSION_BYTES", len(canonical_json_bytes(body)) - 1
    )
    with pytest.raises(ValidationError, match="byte budget"):
        parse_pair_submit_request(body)


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_read_request_is_frozen_exact_workflow_and_mode(mode: str) -> None:
    query = read_request(mode)
    assert parse_workflow_read_request(query.model_dump(mode="json")) == query


@pytest.mark.parametrize(
    "workflow_state,verified",
    [
        ("REQUESTED", False),
        ("RUNNING", False),
        ("FAILED", False),
        ("CANCELLED", False),
        ("COMPLETED", False),
        ("COMPLETED", True),
    ],
)
def test_reachable_purpose_states_have_explicit_result_resolution(
    workflow_state: str, verified: bool
) -> None:
    value = read_result(workflow_state, verified=verified)
    assert parse_workflow_read_result(value.model_dump(mode="json")) == value
    validate_workflow_read_result_context(
        read_request("CANONICAL_RESULT" if verified else "STATUS_ONLY"), value
    )


@pytest.mark.parametrize("state", ["APPROVED", "REGISTERING", "AWAITING_HUMAN_APPROVAL"])
def test_item_workflow_states_cannot_be_reclassified_as_comparison_states(state: str) -> None:
    body = rehash(
        read_result("RUNNING").model_dump(mode="json") | {"workflow_state": state}, "result_sha256"
    )
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResult.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_path", "outputs/comparison.json"),
        ("schema_ref", "eom://schemas/knowledge/item-inference-transfer/1.0"),
        ("media_type", "image/png"),
        ("artifact_revision_id", "current"),
    ],
)
def test_result_artifact_pins_outer_envelope_member_schema_and_revision(
    field: str, value: str
) -> None:
    body = read_result().model_dump(mode="json")
    body["result_artifact"][field] = value
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result(rehash(body, "result_sha256"))


def test_outer_artifact_hash_and_inner_comparison_hash_remain_distinct() -> None:
    value = read_result()
    assert value.result_artifact is not None and value.result is not None
    assert value.result_artifact.sha256 == sha256_bytes(
        canonical_json_bytes(role_result_document())
    )
    assert value.result_artifact.sha256 != value.result.result_sha256
    # This unit fixture is not evidence that any actual member has been read.


@pytest.mark.parametrize(
    "state,patch",
    [
        ("RUNNING", {"result_state": "MEMBER_VERIFIED"}),
        ("FAILED", {"result_state": "PENDING"}),
        ("COMPLETED", {"result_artifact": None}),
        ("COMPLETED", {"result_state": "POINTER_ONLY"}),
        ("COMPLETED", {"result": None}),
        ("COMPLETED", {"failure_code": "WORKER_RESULT_INVALID"}),
    ],
)
def test_state_pointer_content_and_failure_null_closure(state: str, patch: dict[str, Any]) -> None:
    body = rehash(read_result(state).model_dump(mode="json") | patch, "result_sha256")
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResult.model_validate(body)


@pytest.mark.parametrize("field", ["request_id", "request_sha256", "left_profile", "rubric"])
def test_inner_comparison_exact_request_profile_rubric_closure(field: str) -> None:
    body = read_result().model_dump(mode="json")
    result = body["result"]
    if field == "request_id":
        result[field] = "transferrequest_" + "f" * 32
    elif field == "request_sha256":
        result[field] = sha("f")
    elif field == "left_profile":
        result[field]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
    else:
        result[field]["rubric_revision_id"] = "transferrubricrev_" + "f" * 32
    body["result"] = rehash(result, "result_sha256")
    with pytest.raises(ValidationError, match="pinned request"):
        parse_workflow_read_result(rehash(body, "result_sha256"))


def test_inner_comparison_cannot_reference_unselected_claims() -> None:
    body = read_result().model_dump(mode="json")
    result = body["result"]
    result["new_reasoning"] = [
        {
            "left_claim_ids": ["transferclaim_unselected"],
            "right_claim_ids": [],
            "explanation": "합성 차이",
        }
    ]
    body["result"] = rehash(result, "result_sha256")
    with pytest.raises(ValidationError, match="unselected claim"):
        parse_workflow_read_result(rehash(body, "result_sha256"))


def test_current_result_mode_and_workflow_context_are_not_implicit_latest() -> None:
    with pytest.raises(ValueError, match="different exact Workflow"):
        validate_workflow_read_result_context(
            read_request(workflow_id="workflow_" + "f" * 32), read_result()
        )
    with pytest.raises(ValueError, match="requested mode"):
        validate_workflow_read_result_context(read_request("STATUS_ONLY"), read_result())
    with pytest.raises(ValueError, match="requested mode"):
        validate_workflow_read_result_context(
            read_request("CANONICAL_RESULT"), read_result(verified=False)
        )
    assert read_request().workflow_id == WORKFLOW_ID


@pytest.mark.parametrize("resource_version", [True, 0, 1.5, "2"])
def test_read_resource_version_is_strict_positive_integer(resource_version: Any) -> None:
    # Invalid numbers must be rejected before canonical hashing (which itself
    # forbids floats); retain the prior digest to test schema-first field checks.
    body = read_result().model_dump(mode="json") | {"resource_version": resource_version}
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResult.model_validate(body)


def test_contract_has_no_runtime_or_database_authority_dependency() -> None:
    path = Path(contract.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        module.startswith(
            (
                "sqlalchemy",
                "subprocess",
                "eom_api",
                "eom_orchestrator",
                "eom_catalog_service",
                "eom_workflow_runner",
            )
        )
        for module in imports
    )

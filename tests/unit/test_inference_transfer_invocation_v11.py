"""New three-axis public/private wire boundaries, not runtime authorization proof."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_invocation_v11 as invocation
from eom_catalog_contracts import inference_transfer_workflow_binding_v11 as binding
from eom_catalog_contracts.inference_transfer_invocation import (
    parse_pair_submit_request,
    parse_workflow_read_request,
    parse_workflow_read_result,
)
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
    parse_pair_submit_request_v11,
    parse_workflow_read_request_v11,
    parse_workflow_read_result_v11,
    validate_workflow_read_result_context_v11,
)
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    parse_workflow_binding_reply,
    parse_workflow_binding_request,
)
from eom_catalog_contracts.inference_transfer_workflow_binding_v11 import (
    InferenceTransferWorkflowBindingReplyV11,
    InferenceTransferWorkflowBindingRequestV11,
    parse_workflow_binding_reply_v11,
    parse_workflow_binding_request_v11,
    validate_workflow_binding_reply_v11,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_invocation_fixtures import (
    ACTOR_ID,
    WORKFLOW_ID,
    binding_pair,
    read_request,
    read_result,
    rehash,
    role_result_document,
    submit_request,
)
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_body_v11


def _submission() -> InferenceTransferPairSubmitRequestV11:
    body = submit_request().model_dump(mode="json")
    body["schema_version"] = "inference-transfer-pair-submit/1.1"
    return parse_pair_submit_request_v11(rehash(body, "submission_sha256"))


def _read_request(
    mode: str = "CANONICAL_RESULT", *, workflow_id: str = WORKFLOW_ID
) -> InferenceTransferWorkflowReadRequestV11:
    body = read_request(mode, workflow_id).model_dump(mode="json")
    body["schema_version"] = "inference-transfer-workflow-read-request/1.1"
    return parse_workflow_read_request_v11(rehash(body, "read_sha256"))


def _read_result(
    state: str = "COMPLETED", *, verified: bool = True
) -> InferenceTransferWorkflowReadResultV11:
    body = read_result(state, verified=verified).model_dump(mode="json")
    body["schema_version"] = "inference-transfer-workflow-read-result/1.1"
    if body["result_artifact"] is not None:
        outer = role_result_document() | {
            "protocol_version": "workflow-role/1.30.0",
            "output": pair_result_body_v11(),
        }
        body["result_artifact"]["schema_ref"] = invocation.TRANSFER_RESULT_MEMBER_SCHEMA
        body["result_artifact"]["sha256"] = content_sha256(outer)
    if body["result"] is not None:
        body["result"] = pair_result_body_v11()
    return parse_workflow_read_result_v11(rehash(body, "result_sha256"))


def _binding_pair(
    *, mode: str = "CANONICAL_RESULT", state: str = "COMPLETED"
) -> tuple[InferenceTransferWorkflowBindingRequestV11, InferenceTransferWorkflowBindingReplyV11]:
    query = parse_workflow_binding_request_v11(
        rehash(
            {
                "schema_version": "inference-transfer-workflow-binding-request/1.1",
                "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
                "actor_id": ACTOR_ID,
                "request": _read_request(mode).model_dump(mode="json"),
            },
            "binding_sha256",
        )
    )
    reply = parse_workflow_binding_reply_v11(
        rehash(
            {
                "schema_version": "inference-transfer-workflow-binding-reply/1.1",
                "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
                "actor_id": ACTOR_ID,
                "request_binding_sha256": query.binding_sha256,
                "status": "SUCCESS",
                "result": _read_result(state, verified=mode == "CANONICAL_RESULT").model_dump(
                    mode="json"
                ),
                "error_code": None,
            },
            "reply_sha256",
        )
    )
    return query, reply


@pytest.mark.parametrize(
    "name,family",
    [
        ("item-inference-transfer-invocation-v1.1", "item-inference-transfer-invocation"),
        (
            "item-inference-transfer-workflow-binding-v1.1",
            "item-inference-transfer-workflow-binding",
        ),
    ],
)
def test_successor_schema_is_canonical_mirrored_and_registered_202012(
    name: str, family: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES[name]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == f"eom://schemas/knowledge/{family}/1.1"


def test_new_submission_is_actor_free_exact_small_selection_not_profile_context() -> None:
    value = _submission()
    assert value.comparison == submit_request().comparison
    assert value.snapshot_prepare == submit_request().snapshot_prepare
    assert value.expected_header_sha256 == submit_request().expected_header_sha256
    assert len(canonical_json_bytes(value.model_dump(mode="json"))) < 32 * 1024
    assert not hasattr(value, "actor_id") and not hasattr(value, "left_profile")
    with pytest.raises(ValidationError):
        value.expected_header_sha256 = sha("f")


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", ACTOR_ID),
        ("role", "ADMIN"),
        ("permissions", ["ALL"]),
        ("requester_permissions_sha256", sha()),
        ("execution_preset_key", "customer-support"),
        ("left_profile", {"full": "not accepted"}),
        ("token", "synthetic-not-a-token"),
    ],
)
def test_successor_public_submission_still_rejects_client_authority_and_full_profiles(
    field: str, value: Any
) -> None:
    body = rehash(_submission().model_dump(mode="json") | {field: value}, "submission_sha256")
    with pytest.raises(SchemaValidationError):
        parse_pair_submit_request_v11(body)
    with pytest.raises(ValidationError):
        InferenceTransferPairSubmitRequestV11.model_validate(body)


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_new_read_and_private_binding_preserve_reachable_state_and_current_mode(
    mode: str, state: str
) -> None:
    query, reply = _binding_pair(mode=mode, state=state)
    validate_workflow_binding_reply_v11(query, reply)
    assert reply.result is not None
    validate_workflow_read_result_context_v11(query.request, reply.result)
    assert reply.actor_id == ACTOR_ID
    assert reply.request_binding_sha256 == query.binding_sha256
    if state == "COMPLETED" and mode == "CANONICAL_RESULT":
        assert reply.result.result is not None
        assert len(reply.result.result.axes) == 3
        assert reply.result.result.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"


@pytest.mark.parametrize("state", ["APPROVED", "REGISTERING", "AWAITING_HUMAN_APPROVAL"])
def test_item_lifecycle_states_cannot_be_interpreted_as_comparison_states(state: str) -> None:
    body = rehash(
        _read_result("RUNNING").model_dump(mode="json") | {"workflow_state": state},
        "result_sha256",
    )
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result_v11(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResultV11.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_path", "comparison.json"),
        ("schema_ref", "eom://schemas/knowledge/item-inference-transfer-pair-result/1.1"),
        (
            "schema_ref",
            "https://eom.local/schemas/workflow/roles/item-inference-transfer-pair-result-v1.schema.json",
        ),
        ("media_type", "image/png"),
        ("artifact_revision_id", "current"),
    ],
)
def test_outer_v2_result_member_identity_is_not_inner_v11_or_legacy_outer(
    field: str, value: str
) -> None:
    body = _read_result().model_dump(mode="json")
    body["result_artifact"][field] = value
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result_v11(rehash(body, "result_sha256"))
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResultV11.model_validate(rehash(body, "result_sha256"))


def test_outer_member_hash_remains_distinct_from_inner_three_axis_result_hash() -> None:
    value = _read_result()
    assert value.result_artifact is not None and value.result is not None
    outer = role_result_document() | {
        "protocol_version": "workflow-role/1.30.0",
        "output": value.result.model_dump(mode="json"),
    }
    assert value.result_artifact.sha256 == sha256_bytes(canonical_json_bytes(outer))
    assert value.result_artifact.sha256 != value.result.result_sha256
    # This synthetic digest is not proof that an actual Artifact member was read.


@pytest.mark.parametrize("axis_index", [0, 1, 2])
@pytest.mark.parametrize("side", ["left_claim_ids", "right_claim_ids"])
def test_every_new_axis_is_closed_to_exact_selected_claims(axis_index: int, side: str) -> None:
    body = _read_result().model_dump(mode="json")
    body["result"]["axes"][axis_index][side] = ["transferclaim_unselected"]
    body["result"] = rehash(body["result"], "result_sha256")
    with pytest.raises(ValidationError, match="unselected claim"):
        parse_workflow_read_result_v11(rehash(body, "result_sha256"))


@pytest.mark.parametrize("field", ["request_id", "request_sha256", "left_profile", "rubric"])
def test_three_axis_result_cannot_change_exact_request_profile_or_rubric(field: str) -> None:
    body = _read_result().model_dump(mode="json")
    nested = body["result"]
    if field == "request_id":
        nested[field] = "transferrequest_" + "f" * 32
    elif field == "request_sha256":
        nested[field] = sha("f")
    elif field == "left_profile":
        nested[field]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
    else:
        nested[field]["rubric_revision_id"] = "transferrubricrev_" + "f" * 32
    body["result"] = rehash(nested, "result_sha256")
    with pytest.raises(ValidationError, match="pinned request"):
        parse_workflow_read_result_v11(rehash(body, "result_sha256"))


def test_new_result_requires_axes_instead_of_silent_legacy_upgrade() -> None:
    body = _read_result().model_dump(mode="json")
    del body["result"]["axes"]
    body["result"] = rehash(body["result"], "result_sha256")
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result_v11(rehash(body, "result_sha256"))


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
def test_new_read_state_pointer_content_and_failure_presence_remain_closed(
    state: str, patch: dict[str, Any]
) -> None:
    body = rehash(_read_result(state).model_dump(mode="json") | patch, "result_sha256")
    with pytest.raises(SchemaValidationError):
        parse_workflow_read_result_v11(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowReadResultV11.model_validate(body)


def test_read_context_rejects_foreign_workflow_wrong_mode_and_model_copy_bypass() -> None:
    value = _read_result()
    with pytest.raises(ValueError, match="different exact Workflow"):
        validate_workflow_read_result_context_v11(
            _read_request(workflow_id="workflow_" + "f" * 32), value
        )
    with pytest.raises(ValueError, match="requested mode"):
        validate_workflow_read_result_context_v11(_read_request("STATUS_ONLY"), value)
    copied = value.model_copy(update={"result_sha256": sha("f")})
    with pytest.raises(ValidationError):
        validate_workflow_read_result_context_v11(_read_request(), copied)
    changed_request = _read_request().model_copy(update={"mode": "LATEST"})
    with pytest.raises(SchemaValidationError):
        validate_workflow_read_result_context_v11(changed_request, value)


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("field", ["actor_id", "request_binding_sha256"])
def test_new_private_binding_requires_same_actual_principal_and_exact_request_on_replay(
    failed: bool, field: str
) -> None:
    query, reply = _binding_pair()
    body = reply.model_dump(mode="json") | {
        field: "operator_" + "f" * 32 if field == "actor_id" else sha("f")
    }
    if failed:
        body.update(status="FAILED", result=None, error_code="INFERENCE_TRANSFER_FORBIDDEN")
    changed = parse_workflow_binding_reply_v11(rehash(body, "reply_sha256"))
    with pytest.raises(ValueError, match="exact request binding"):
        validate_workflow_binding_reply_v11(query, changed)


@pytest.mark.parametrize("field", ["actor_id", "request_binding_sha256"])
def test_failed_private_context_cannot_have_only_one_identity_field(field: str) -> None:
    _, reply = _binding_pair()
    body = rehash(
        reply.model_dump(mode="json")
        | {
            "status": "FAILED",
            "result": None,
            "error_code": "INFERENCE_TRANSFER_FORBIDDEN",
            field: None,
        },
        "reply_sha256",
    )
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply_v11(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowBindingReplyV11.model_validate(body)


def test_malformed_frame_failure_has_no_fabricated_actor_and_never_result_content() -> None:
    query, reply = _binding_pair()
    body = rehash(
        reply.model_dump(mode="json")
        | {
            "status": "FAILED",
            "actor_id": None,
            "request_binding_sha256": None,
            "result": None,
            "error_code": "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
        },
        "reply_sha256",
    )
    failed = parse_workflow_binding_reply_v11(body)
    validate_workflow_binding_reply_v11(query, failed)
    assert failed.result is None


@pytest.mark.parametrize(
    "patch",
    [
        {"error_code": "PRIVATE_SQL_TRACEBACK"},
        {"error_code": "INFERENCE_TRANSFER_FORBIDDEN", "error_detail": "synthetic detail"},
        {"error_code": None},
        {"actor_id": None, "request_binding_sha256": None, "status": "SUCCESS"},
    ],
)
def test_new_private_errors_are_closed_safe_and_cannot_establish_permission(
    patch: dict[str, Any],
) -> None:
    _, reply = _binding_pair()
    body = reply.model_dump(mode="json") | {
        "status": "FAILED",
        "result": None,
        "error_code": "INFERENCE_TRANSFER_FORBIDDEN",
    }
    body.update(patch)
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply_v11(rehash(body, "reply_sha256"))


def test_public_and_private_encoded_bounds_reject_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = _submission().model_dump(mode="json")
    monkeypatch.setattr(
        invocation, "MAX_TRANSFER_SUBMISSION_BYTES", len(canonical_json_bytes(public)) - 1
    )
    with pytest.raises(ValidationError, match="byte budget"):
        parse_pair_submit_request_v11(public)
    query, _ = _binding_pair()
    private = query.model_dump(mode="json")
    monkeypatch.setattr(
        binding, "MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES", len(canonical_json_bytes(private)) - 1
    )
    with pytest.raises(ValidationError, match="byte budget"):
        parse_workflow_binding_request_v11(private)


def test_released_v1_and_new_v11_parsers_do_not_reinterpret_each_other() -> None:
    legacy_query, legacy_reply = binding_pair()
    new_query, new_reply = _binding_pair()
    cases = [
        (parse_pair_submit_request, _submission().model_dump(mode="json")),
        (parse_pair_submit_request_v11, submit_request().model_dump(mode="json")),
        (parse_workflow_read_request, _read_request().model_dump(mode="json")),
        (parse_workflow_read_request_v11, read_request().model_dump(mode="json")),
        (parse_workflow_read_result, _read_result().model_dump(mode="json")),
        (parse_workflow_read_result_v11, read_result().model_dump(mode="json")),
        (parse_workflow_binding_request, new_query.model_dump(mode="json")),
        (parse_workflow_binding_request_v11, legacy_query.model_dump(mode="json")),
        (parse_workflow_binding_reply, new_reply.model_dump(mode="json")),
        (parse_workflow_binding_reply_v11, legacy_reply.model_dump(mode="json")),
    ]
    for parser, body in cases:
        with pytest.raises(SchemaValidationError):
            parser(body)


def test_successor_contract_modules_have_no_runtime_authority_dependencies() -> None:
    for module in (invocation, binding):
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any(
            name.startswith(
                ("eom_api", "eom_orchestrator", "eom_catalog_service", "sqlalchemy", "subprocess")
            )
            for name in imports
        )

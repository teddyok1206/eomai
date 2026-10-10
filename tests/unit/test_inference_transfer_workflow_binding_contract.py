"""Private Workflow read identity/null closure, without socket/owner/runtime effects."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_workflow_binding as contract
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    InferenceTransferWorkflowBindingReply,
    InferenceTransferWorkflowBindingRequest,
    parse_workflow_binding_reply,
    parse_workflow_binding_request,
    validate_workflow_binding_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_invocation_fixtures import ACTOR_ID, binding_pair, rehash


def test_schema_first_private_resource_is_exact_closed_202012() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-workflow-binding"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    schema = load_schema("item-inference-transfer-workflow-binding")
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-workflow-binding/1.0"


@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_private_round_trip_binds_actual_principal_exact_request_and_mode(
    mode: str, state: str
) -> None:
    request, reply = binding_pair(mode=mode, state=state)
    assert parse_workflow_binding_request(request.model_dump(mode="json")) == request
    assert parse_workflow_binding_reply(reply.model_dump(mode="json")) == reply
    validate_workflow_binding_reply(request, reply)


@pytest.mark.parametrize(
    "error_code",
    [
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND",
        "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
        "INFERENCE_TRANSFER_WORKFLOW_CHANGED",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE",
        "INFERENCE_TRANSFER_RESULT_INVALID",
        "INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED",
    ],
)
def test_parsed_failure_echoes_context_without_mutating_success_history(error_code: str) -> None:
    request, reply = binding_pair()
    body = reply.model_dump(mode="json") | {
        "status": "FAILED",
        "result": None,
        "error_code": error_code,
    }
    failed = parse_workflow_binding_reply(rehash(body, "reply_sha256"))
    validate_workflow_binding_reply(request, failed)
    assert failed.actor_id == ACTOR_ID


def test_unparseable_request_failure_has_no_manufactured_principal() -> None:
    request, reply = binding_pair()
    body = reply.model_dump(mode="json") | {
        "status": "FAILED",
        "actor_id": None,
        "request_binding_sha256": None,
        "result": None,
        "error_code": "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
    }
    failed = parse_workflow_binding_reply(rehash(body, "reply_sha256"))
    validate_workflow_binding_reply(request, failed)
    assert failed.result is None


@pytest.mark.parametrize("field", ["actor_id", "request_binding_sha256"])
def test_private_failure_context_must_be_jointly_present_or_absent(field: str) -> None:
    _, reply = binding_pair()
    body = reply.model_dump(mode="json") | {
        "status": "FAILED",
        "result": None,
        "error_code": "INFERENCE_TRANSFER_FORBIDDEN",
        field: None,
    }
    body = rehash(body, "reply_sha256")
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply(body)
    with pytest.raises(ValidationError, match="jointly present"):
        InferenceTransferWorkflowBindingReply.model_validate(body)


def test_private_success_never_accepts_absent_principal_or_request_identity() -> None:
    _, reply = binding_pair()
    body = rehash(
        reply.model_dump(mode="json") | {"actor_id": None, "request_binding_sha256": None},
        "reply_sha256",
    )
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowBindingReply.model_validate(body)


@pytest.mark.parametrize(
    "status,result_present,error_present",
    [
        ("SUCCESS", False, False),
        ("SUCCESS", True, True),
        ("FAILED", True, True),
        ("FAILED", False, False),
    ],
)
def test_private_status_result_error_closure(
    status: str, result_present: bool, error_present: bool
) -> None:
    _, reply = binding_pair()
    body = rehash(
        reply.model_dump(mode="json")
        | {
            "status": status,
            "result": reply.result.model_dump(mode="json")
            if result_present and reply.result is not None
            else None,
            "error_code": "INFERENCE_TRANSFER_FORBIDDEN" if error_present else None,
        },
        "reply_sha256",
    )
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowBindingReply.model_validate(body)


@pytest.mark.parametrize("field", ["actor_id", "request_binding_sha256"])
@pytest.mark.parametrize("failed", [False, True])
def test_foreign_private_actor_or_request_is_not_accepted_on_success_or_failure(
    field: str, failed: bool
) -> None:
    request, reply = binding_pair()
    body = reply.model_dump(mode="json") | {
        field: "operator_" + "f" * 32 if field == "actor_id" else sha("f")
    }
    if failed:
        body.update(status="FAILED", result=None, error_code="INFERENCE_TRANSFER_FORBIDDEN")
    changed = parse_workflow_binding_reply(rehash(body, "reply_sha256"))
    with pytest.raises(ValueError, match="exact request binding"):
        validate_workflow_binding_reply(request, changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "ADMIN"),
        ("permissions", ["ALL"]),
        ("token", "synthetic-not-a-token"),
        ("operation", "INFERENCE_TRANSFER_SNAPSHOT"),
        ("actor_id", "system"),
    ],
)
def test_private_envelope_rejects_model_supplied_role_and_foreign_operation(
    field: str, value: Any
) -> None:
    request, _ = binding_pair()
    body = rehash(request.model_dump(mode="json") | {field: value}, "binding_sha256")
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_request(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowBindingRequest.model_validate(body)


@pytest.mark.parametrize("request_side", [True, False])
def test_request_and_reply_canonical_hash_tampering_is_rejected(request_side: bool) -> None:
    request, reply = binding_pair()
    body = request.model_dump(mode="json") if request_side else reply.model_dump(mode="json")
    body["binding_sha256" if request_side else "reply_sha256"] = sha("f")
    parser = parse_workflow_binding_request if request_side else parse_workflow_binding_reply
    with pytest.raises(ValidationError, match="canonical private"):
        parser(body)


def test_nested_model_copy_cannot_bypass_workflow_mode_or_hash_validation() -> None:
    request, reply = binding_pair()
    changed = reply.model_copy(update={"reply_sha256": sha("f")})
    with pytest.raises(ValidationError):
        validate_workflow_binding_reply(request, changed)
    changed_request = request.model_copy(update={"operation": "INFERENCE_TRANSFER_SNAPSHOT"})
    with pytest.raises(SchemaValidationError):
        validate_workflow_binding_reply(changed_request, reply)


def test_unknown_error_or_untrusted_error_detail_is_never_returned() -> None:
    _, reply = binding_pair()
    body = reply.model_dump(mode="json") | {
        "status": "FAILED",
        "result": None,
        "error_code": "PRIVATE_SQL_TRACEBACK",
    }
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply(rehash(body, "reply_sha256"))
    body.update(error_code="INFERENCE_TRANSFER_FORBIDDEN", error_detail="synthetic private detail")
    with pytest.raises(SchemaValidationError):
        parse_workflow_binding_reply(rehash(body, "reply_sha256"))


def test_binding_byte_bound_and_dependency_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    request, _ = binding_pair()
    monkeypatch.setattr(contract, "MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES", 128)
    with pytest.raises(ValidationError, match="byte budget"):
        parse_workflow_binding_request(request.model_dump(mode="json"))
    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        module.startswith(("eom_api", "eom_catalog_service", "eom_orchestrator", "sqlalchemy"))
        for module in modules
    )

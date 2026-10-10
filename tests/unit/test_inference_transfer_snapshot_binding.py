"""Private identity closure tests; actual principal/peer/source auth is owner-owned."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import SuppliedGraphBaseline
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    validate_snapshot_read_result,
    validate_snapshot_read_result_context,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    InferenceTransferSnapshotBindingReply,
    InferenceTransferSnapshotBindingRequest,
    parse_binding_reply,
    parse_binding_request,
    validate_binding_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_snapshot_binding_fixtures import binding_pair
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
)


def test_schema_first_mirror_hash_and_registered_family() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-snapshot-binding"]
    canonical = (root / entry.canonical_path).read_bytes()
    resource = (
        root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    assert canonical == resource
    assert sha256_bytes(canonical) == entry.sha256
    schema = load_schema("item-inference-transfer-snapshot-binding")
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-snapshot-binding/1.0"


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_exact_round_trip_for_each_private_phase(phase: str) -> None:
    request, reply = binding_pair(phase)
    assert parse_binding_request(request.model_dump(mode="json")) == request
    assert parse_binding_reply(reply.model_dump(mode="json")) == reply
    validate_binding_reply(request, reply)


@pytest.mark.parametrize(
    "error_code",
    [
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED",
        "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
        "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
    ],
)
def test_stable_failure_allowlist_has_no_untrusted_error_text(error_code: Any) -> None:
    reply = InferenceTransferSnapshotBindingReply(
        status="FAILED", result=None, error_code=error_code
    )
    assert parse_binding_reply(reply.model_dump(mode="json")) == reply
    validate_binding_reply(binding_pair()[0], reply)


@pytest.mark.parametrize(
    "status,result_present,error_present",
    [
        ("SUCCESS", False, False),
        ("SUCCESS", True, True),
        ("FAILED", True, True),
        ("FAILED", False, False),
    ],
)
def test_reply_status_result_and_error_null_closure(
    status: Any, result_present: bool, error_present: bool
) -> None:
    result = binding_pair()[1].result
    body = {
        "schema_version": "inference-transfer-snapshot-binding-reply/1.0",
        "operation": "INFERENCE_TRANSFER_SNAPSHOT",
        "status": status,
        "result": result.model_dump(mode="json") if result is not None and result_present else None,
        "error_code": "INFERENCE_TRANSFER_FORBIDDEN" if error_present else None,
    }
    with pytest.raises(SchemaValidationError):
        parse_binding_reply(body)
    with pytest.raises(ValidationError):
        InferenceTransferSnapshotBindingReply.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "ADMIN"),
        ("permissions", ["ALL"]),
        ("token", "synthetic-not-a-token"),
        ("path", "/mnt/nas/private"),
        ("operation", "CHAT_RAG"),
    ],
)
def test_private_request_is_not_a_model_role_or_arbitrary_operation(field: str, value: Any) -> None:
    body = binding_pair()[0].model_dump(mode="json") | {field: value}
    with pytest.raises(SchemaValidationError):
        parse_binding_request(body)


def test_unknown_error_and_error_message_are_rejected_without_exposing_internal_details() -> None:
    body = {
        "schema_version": "inference-transfer-snapshot-binding-reply/1.0",
        "operation": "INFERENCE_TRANSFER_SNAPSHOT",
        "status": "FAILED",
        "result": None,
        "error_code": "PRIVATE_INTERNAL_TRACEBACK",
    }
    with pytest.raises(SchemaValidationError):
        parse_binding_reply(body)
    body["error_code"] = "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    body["error_message"] = "synthetic internal information"
    with pytest.raises(SchemaValidationError):
        parse_binding_reply(body)


@pytest.mark.parametrize("phase", ["READ", "AUTHORIZE"])
def test_frozen_header_owner_cannot_be_replayed_under_another_private_principal(phase: str) -> None:
    request, _ = binding_pair(phase)
    with pytest.raises(ValidationError, match="frozen header owner"):
        InferenceTransferSnapshotBindingRequest(
            actor_id="different-operator", request=request.request
        )


def test_prepare_reply_actor_and_request_hash_do_not_become_a_bearer_capability() -> None:
    request, reply = binding_pair()
    foreign = request.model_copy(update={"actor_id": "different-operator"})
    with pytest.raises(ValueError, match="another actor"):
        validate_binding_reply(foreign, reply)
    assert isinstance(reply.result, InferenceTransferSnapshotPrepareResult)
    prepared = reply.result.model_copy(
        update={"header": reply.result.header.model_copy(update={"actor_id": "different-operator"})}
    )
    # Copied frozen nested header with a stale SHA is rejected before reply use.
    with pytest.raises(ValueError, match="header_sha256"):
        validate_binding_reply(request, reply.model_copy(update={"result": prepared}))


@pytest.mark.parametrize("phase", ["PREPARE", "READ", "AUTHORIZE"])
def test_reply_must_match_exact_request_phase_not_only_success(phase: str) -> None:
    request, _ = binding_pair(phase)
    other_phase = "AUTHORIZE" if phase == "PREPARE" else "PREPARE"
    reply = binding_pair(other_phase)[1]
    with pytest.raises(ValueError, match="requested phase"):
        validate_binding_reply(request, reply)


def test_private_read_context_checks_exact_selected_refs_not_a_guessed_full_index() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared, selected_index_entries=prepared.index[:1])
    result = snapshot_read_result(request=request)
    with pytest.raises(ValueError, match="exact selected chunk"):
        validate_snapshot_read_result_context(request, result)
    private = InferenceTransferSnapshotBindingRequest(
        actor_id=prepared.header.actor_id, request=request
    )
    reply = InferenceTransferSnapshotBindingReply(status="SUCCESS", result=result, error_code=None)
    with pytest.raises(ValueError, match="exact selected chunk"):
        validate_binding_reply(private, reply)


def test_context_only_guard_does_not_claim_full_candidate_membership() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(request=request)
    baseline = result.baselines[0]
    foreign = baseline.ordered_candidates[0].model_copy(update={"profile_sha256": sha("0")})
    baseline = hashed(
        SuppliedGraphBaseline,
        "result_sha256",
        query=baseline.query,
        command_sha256=baseline.command_sha256,
        ordered_candidates=(foreign,),
    )
    result = hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(result.model_dump(mode="json", exclude={"result_sha256"}) | {"baselines": (baseline,)}),
    )
    # The transport cannot authenticate sources absent from this bounded chunk.
    validate_snapshot_read_result_context(request, result)
    with pytest.raises(ValueError, match="outside exact eligible"):
        validate_snapshot_read_result(request, result, index=prepared.index)


def test_binding_model_copy_revalidates_nested_request_hash_and_result_pins() -> None:
    request, reply = binding_pair("READ")
    assert isinstance(request.request, InferenceTransferSnapshotReadRequest)
    forged = request.model_copy(
        update={"request": request.request.model_copy(update={"read_sha256": sha("0")})}
    )
    with pytest.raises(ValueError, match="read_sha256"):
        validate_binding_reply(forged, reply)
    request, reply = binding_pair("AUTHORIZE")
    assert isinstance(reply.result, InferenceTransferSnapshotAuthorizeResult)
    changed = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        **(
            reply.result.model_dump(mode="json", exclude={"result_sha256"})
            | {"staged_entry_set_sha256": sha("0")}
        ),
    )
    with pytest.raises(ValueError, match="exact assembled request"):
        validate_binding_reply(request, reply.model_copy(update={"result": changed}))


def test_binding_has_no_peer_auth_filesystem_database_or_network_behavior() -> None:
    import eom_catalog_contracts.inference_transfer_snapshot_binding as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        name.split(".")[0]
        in {
            "sqlalchemy",
            "subprocess",
            "socket",
            "pathlib",
            "eom_catalog_service",
            "eom_orchestrator",
            "requests",
            "httpx",
        }
        for name in imports
    )

"""Closed synthetic preparation messages; never source/current-user/native admission."""

from pathlib import Path

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareRequest,
    validate_reference_query_prepare_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_similarity_context_contracts import context_request_body


def request_body():
    context = context_request_body()
    return seal(
        {
            "schema_version": "system-rag-reference-query-prepare-request/1.0",
            "operation": "PREPARE_REFERENCE_QUERY",
            "operation_id": "queryprepare_" + "a" * 32,
            "idempotency_key": "synthetic-item-start:original",
            "source_item_revision_id": context["anchor"]["source"]["item_revision_id"],
            "graph_snapshot": context["graph_snapshot"],
            "policy_revision_id": context["policy_revision_id"],
            "policy_sha256": context["policy_sha256"],
        },
        "request_sha256",
    )


def reply_body(request=None, *, status="PENDING"):
    request = request or ReferenceQueryPrepareRequest.model_validate(request_body())
    body = {
        "schema_version": "system-rag-reference-query-prepare-reply/1.0",
        "operation": "PREPARE_REFERENCE_QUERY",
        "operation_id": request.operation_id,
        "request_sha256": request.request_sha256,
        "status": status,
        "workflow_id": "workflow_" + "b" * 32,
        "selection": None,
        "error_code": None,
    }
    if status == "READY":
        body["selection"] = {
            "workflow_id": body["workflow_id"],
            "workflow_request_sha256": "sha256:" + "c" * 64,
            "context_request_sha256": "sha256:" + "d" * 64,
        }
    elif status == "UNAVAILABLE":
        body.update(workflow_id=None, error_code="ANCHOR_REPORT_MISSING")
    elif status == "FAILED":
        body.update(workflow_id=None, error_code="REFERENCE_QUERY_PREPARE_UNAVAILABLE")
    return body


def test_mirror_hash_closed_schema_and_old_refs_resolve_offline():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-reference-query-prepare"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema("system-rag-reference-query-prepare")
    Draft202012Validator.check_schema(schema)
    for key in ("request", "reply"):
        definition = schema["$defs"][key]
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == set(definition["required"])
    assert "actor_id" not in schema["$defs"]["request"]["properties"]


@pytest.mark.parametrize("status", ("PENDING", "READY", "UNAVAILABLE", "FAILED"))
def test_exact_roundtrip_and_status_semantics(status):
    request = ReferenceQueryPrepareRequest.model_validate(request_body())
    reply = ReferenceQueryPrepareReply.model_validate(reply_body(request, status=status))
    validate_reference_query_prepare_reply(request, reply)
    assert ReferenceQueryPrepareRequest.model_validate(request.model_dump(mode="json")) == request
    assert ReferenceQueryPrepareReply.model_validate(reply.model_dump(mode="json")) == reply
    assert (reply.selection is not None) == (status == "READY")


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "operator_" + "f" * 32),
        ("roles", ["ADMIN"]),
        ("capture", {}),
        ("bundle", {}),
        ("resource_profile", {}),
        ("path", "/mnt/nas"),
        ("operation", "START_OTHER_WORK"),
        ("idempotency_key", "x" * 129),
        ("source_item_revision_id", True),
        ("policy_sha256", "sha256:" + "x" * 64),
    ),
)
def test_no_caller_authority_path_control_or_coercion(field, value):
    body = request_body()
    body[field] = value
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequest.model_validate(seal(body, "request_sha256"))


@pytest.mark.parametrize("fault", ("hash", "graph", "hidden", "budget"))
def test_bad_hash_hidden_fields_and_budget_fail_before_use(fault):
    body = request_body()
    if fault == "hash":
        body["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "graph":
        body["graph_snapshot"]["manifest_sha256"] = "sha256:" + "0" * 64
        body = seal(body, "request_sha256")
    elif fault == "budget":
        body["payload"] = "x" * 8193
    else:
        body = ReferenceQueryPrepareRequest.model_validate(body).model_copy(
            update={"roles": ["ADMIN"]}
        )
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequest.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    (
        "pending_selection",
        "ready_missing",
        "wrong_target",
        "absent_with_target",
        "absence_is_not_denial",
        "failed_no_error",
        "wrong_reply_hash",
    ),
)
def test_reply_cannot_turn_pending_or_denied_work_into_ready(fault):
    request = ReferenceQueryPrepareRequest.model_validate(request_body())
    body = reply_body(
        request, status="READY" if fault in {"ready_missing", "wrong_target"} else "PENDING"
    )
    if fault == "pending_selection":
        body["selection"] = reply_body(request, status="READY")["selection"]
    elif fault == "ready_missing":
        body["selection"] = None
    elif fault == "wrong_target":
        body["workflow_id"] = "workflow_" + "e" * 32
    elif fault == "absent_with_target":
        body.update(status="UNAVAILABLE", error_code="INDEX_NOT_PREPARED")
    elif fault == "absence_is_not_denial":
        body.update(status="UNAVAILABLE", workflow_id=None, error_code="SOURCE_ACCESS_DENIED")
    elif fault == "failed_no_error":
        body.update(status="FAILED", workflow_id=None)
    else:
        body["request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, SchemaError)):
        validate_reference_query_prepare_reply(
            request, ReferenceQueryPrepareReply.model_validate(body)
        )

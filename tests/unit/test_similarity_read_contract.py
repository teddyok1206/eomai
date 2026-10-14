"""Small exact RPC contracts; synthetic values are not current source authority."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_read import (
    CompletedSimilarityQuerySelection,
    SimilarityContextReadReply,
    SimilarityContextReadRequest,
    validate_similarity_read_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_similarity_context_contracts import context_body


def pair():
    result = parse_similarity_context(context_body())
    selection = CompletedSimilarityQuerySelection(
        workflow_id="workflow_" + "a" * 32,
        workflow_request_sha256="sha256:" + "b" * 64,
        context_request_sha256=result.request.request_sha256,
    )
    request = SimilarityContextReadRequest(
        schema_version="system-rag-similarity-read-request/1.0",
        operation="READ_SIMILARITY_CONTEXT",
        actor_id="operator_" + "c" * 32,
        selection=selection,
    )
    reply = SimilarityContextReadReply(
        schema_version="system-rag-similarity-read-reply/1.0",
        operation="READ_SIMILARITY_CONTEXT",
        status="SUCCESS",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        result=result,
        error_code=None,
    )
    return request, reply


def test_schema_resource_is_exact_closed_draft202012():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-read"]
    canonical = (root / entry.canonical_path).read_bytes()
    assert (
        canonical
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(canonical) == entry.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-similarity-read"))


def test_exact_round_trip_and_reply_binding():
    request, reply = pair()
    assert SimilarityContextReadRequest.model_validate(request) == request
    assert SimilarityContextReadReply.model_validate(reply.model_dump(mode="json")) == reply
    validate_similarity_read_reply(request, reply)
    assert set(request.selection.model_dump()) == {
        "workflow_id",
        "workflow_request_sha256",
        "context_request_sha256",
    }


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "ADMIN"),
        ("operation", "LAUNCH_QUERY"),
        ("permissions", ["ALL"]),
        ("runtime_bundle", {}),
        ("vectors", [[1.0]]),
        ("token", "not-a-credential"),
    ),
)
def test_untrusted_authority_and_extra_payloads_are_rejected(field, value):
    request, _ = pair()
    body = request.model_dump(mode="json")
    body[field] = value
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadRequest.model_validate(body)


@pytest.mark.parametrize("field", ("schema_version", "operation", "actor_id", "selection"))
def test_missing_wire_fields_do_not_use_constructor_defaults(field):
    request, _ = pair()
    body = request.model_dump(mode="json")
    del body[field]
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadRequest.model_validate(body)


@pytest.mark.parametrize("fault", ("actor", "binding", "context"))
def test_well_formed_but_substituted_reply_is_rejected(fault):
    request, reply = pair()
    if fault == "actor":
        body = reply.model_dump(mode="json") | {"actor_id": "operator_" + "d" * 32}
        reply = SimilarityContextReadReply.model_validate(body)
    elif fault == "binding":
        body = reply.model_dump(mode="json") | {"request_sha256": "sha256:" + "d" * 64}
        reply = SimilarityContextReadReply.model_validate(body)
    else:
        selection = request.selection.model_dump(mode="json") | {
            "context_request_sha256": "sha256:" + "d" * 64
        }
        request = SimilarityContextReadRequest.model_validate(
            request.model_dump(mode="json") | {"selection": selection}
        )
        reply = SimilarityContextReadReply.model_validate(
            reply.model_dump(mode="json")
            | {"request_sha256": content_sha256(request.model_dump(mode="json"))}
        )
    with pytest.raises(ValueError, match="differs"):
        validate_similarity_read_reply(request, reply)


@pytest.mark.parametrize("fault", ("status", "error", "partial", "unknown_error", "unpaired"))
def test_failure_cannot_disclose_partial_values_or_arbitrary_exception_text(fault):
    _, reply = pair()
    body = reply.model_dump(mode="json")
    if fault == "status":
        body["status"] = "FAILED"
    elif fault == "error":
        body["error_code"] = "SOURCE_ACCESS_DENIED"
    elif fault == "partial":
        body |= {"status": "FAILED", "error_code": "SOURCE_REVOKED"}
    elif fault == "unknown_error":
        body |= {"status": "FAILED", "result": None, "error_code": "private exception"}
    else:
        body |= {
            "status": "FAILED",
            "result": None,
            "error_code": "SOURCE_REVOKED",
            "actor_id": None,
        }
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadReply.model_validate(body)


def test_constructed_or_copied_nested_extra_never_serializes_away():
    request, _ = pair()
    forged = copy.deepcopy(request.selection)
    forged.__dict__["permission"] = "ADMIN"
    with pytest.raises((ValueError, SchemaError)):
        SimilarityContextReadRequest.model_validate(
            request.model_copy(update={"selection": forged})
        )

"""Explicit ordinary/review preparation input; old wire remains strict and byte-stable."""

from pathlib import Path

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareRequest,
    ReferenceQueryPrepareRequestV11,
    parse_supported_reference_query_prepare_request,
    validate_reference_query_prepare_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body


def body(purpose="ITEM_AUTHORING"):
    return seal(
        request_body()
        | {
            "schema_version": "system-rag-reference-query-prepare-request/1.1",
            "consumer_purpose": purpose,
        },
        "request_sha256",
    )


def test_successor_schema_and_package_mirror_are_independently_pinned():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-reference-query-prepare-v1.1"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == resource.sha256
        == "sha256:d6a9e8f99ecd8173497d6283f8a8f58e9124a1890cee00fed795b2fc86d8cb0f"
    )
    Draft202012Validator.check_schema(load_schema("system-rag-reference-query-prepare-v1.1"))
    predecessor = CATALOG_SCHEMA_RESOURCES["system-rag-reference-query-prepare"]
    assert sha256_bytes((root / predecessor.canonical_path).read_bytes()) == (
        "sha256:ebc804f035eae57c9b4a649316cd63471203218ecb04603454eb08f2bfa15720"
    )


@pytest.mark.parametrize("purpose", ("ITEM_AUTHORING", "ITEM_REVIEW"))
def test_new_input_roundtrips_with_original_reply_and_old_parser_refuses_it(purpose):
    value = ReferenceQueryPrepareRequestV11.model_validate(body(purpose))
    assert parse_supported_reference_query_prepare_request(value) == value
    assert parse_supported_reference_query_prepare_request(value.model_dump(mode="json")) == value
    assert value.consumer_purpose == purpose
    for status in ("PENDING", "READY", "UNAVAILABLE", "FAILED"):
        reply = ReferenceQueryPrepareReply.model_validate(reply_body(value, status=status))
        validate_reference_query_prepare_reply(value, reply)
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequest.model_validate(value)


def test_predecessor_keeps_implicit_variation_and_exact_original_document():
    raw = request_body()
    value = parse_supported_reference_query_prepare_request(raw)
    assert type(value) is ReferenceQueryPrepareRequest
    assert value.model_dump(mode="json") == raw and "consumer_purpose" not in raw
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequestV11.model_validate(value)


@pytest.mark.parametrize(
    "purpose", ("PAST_EXAM_VARIATION", "GENERAL_CHAT_READ", "MOCK_EXAM_OBSERVATION", True)
)
def test_new_input_does_not_alias_old_or_unoffered_consumers(purpose):
    with pytest.raises((ValueError, SchemaError)):
        parse_supported_reference_query_prepare_request(body(purpose))


@pytest.mark.parametrize("fault", ("extra", "hidden", "unknown", "missing", "unhashed_purpose"))
def test_raw_invalid_successor_fails_before_authority_or_dispatch(fault):
    raw = body()
    if fault == "extra":
        raw = seal(raw | {"actor_id": "ADMIN"}, "request_sha256")
    elif fault == "hidden":
        raw = ReferenceQueryPrepareRequestV11.model_validate(raw).model_copy(
            update={"authority": "ADMIN"}
        )
    elif fault == "unknown":
        raw = seal(
            raw | {"schema_version": "system-rag-reference-query-prepare-request/9.0"},
            "request_sha256",
        )
    elif fault == "missing":
        raw.pop("consumer_purpose")
    else:
        raw["consumer_purpose"] = "ITEM_REVIEW"
    with pytest.raises((ValueError, SchemaError)):
        parse_supported_reference_query_prepare_request(raw)


def test_same_source_and_key_with_changed_purpose_has_distinct_hash_and_foreign_reply_is_rejected():
    author = ReferenceQueryPrepareRequestV11.model_validate(body())
    review = ReferenceQueryPrepareRequestV11.model_validate(body("ITEM_REVIEW"))
    assert author.idempotency_key == review.idempotency_key
    assert (
        author.operation_id == review.operation_id
        and author.request_sha256 != review.request_sha256
    )
    with pytest.raises(ValueError, match="REPLY_BINDING_INVALID"):
        validate_reference_query_prepare_reply(
            review, ReferenceQueryPrepareReply.model_validate(reply_body(author, status="READY"))
        )

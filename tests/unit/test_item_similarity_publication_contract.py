"""Pointer-only protocol fixtures; no source/IAM/native publication acceptance."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_catalog_contracts.item_similarity_publication import (
    MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES,
    MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
    ItemSimilarityPublication,
    ItemSimilarityPublicationReply,
    ItemSimilarityPublicationRequest,
    validate_item_similarity_publication_reply,
)
from eom_catalog_contracts.similarity_delivery import SimilarityContextDelivery
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_similarity_read_contract import pair as read_pair


def pair():
    original, read = read_pair()
    context = read.result
    publication = ItemSimilarityPublication(
        owner_job_id="job_" + "1" * 32,
        delivery=SimilarityContextDelivery(
            schema_version="system-rag-similarity-delivery/1.0",
            context_member=ArtifactMemberPointer(
                artifact_id="artifact_" + "2" * 32,
                artifact_revision_id="rev_" + "3" * 32,
                member_path="context.json",
                schema_ref="eom://schemas/knowledge/system-rag-similarity-context/1.0",
                media_type="application/json",
                sha256=sha256_bytes(canonical_json_bytes(context)),
            ),
            request_sha256=original.selection.context_request_sha256,
            context_sha256=context.context_sha256,
        ),
        manifest_sha256="sha256:" + "4" * 64,
    )
    request = ItemSimilarityPublicationRequest(
        schema_version="system-rag-item-similarity-publication-request/1.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        actor_id=original.actor_id,
        selection=original.selection,
    )
    reply = ItemSimilarityPublicationReply(
        schema_version="system-rag-item-similarity-publication-reply/1.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        status="SUCCESS",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        publication=publication,
        error_code=None,
    )
    return request, reply


def test_schema_and_packaged_resource_are_exact_closed_draft202012():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["system-rag-item-similarity-publication"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-item-similarity-publication"))


def test_exact_round_trip_is_pointer_only_and_bounded():
    request, reply = pair()
    validate_item_similarity_publication_reply(request, reply)
    assert ItemSimilarityPublicationRequest.model_validate(request) == request
    assert ItemSimilarityPublicationReply.model_validate(reply.model_dump(mode="json")) == reply
    assert len(canonical_json_bytes(request)) + 1 < MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES
    assert len(canonical_json_bytes(reply)) + 1 < MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES
    assert set(reply.publication.model_dump()) == {"delivery", "owner_job_id", "manifest_sha256"}


@pytest.mark.parametrize("field", ("schema_version", "operation", "actor_id", "selection"))
def test_missing_request_fields_are_not_constructor_defaults(field):
    request, _ = pair()
    value = request.model_dump(mode="json")
    del value[field]
    with pytest.raises((ValueError, SchemaError)):
        ItemSimilarityPublicationRequest.model_validate(value)


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "operation",
        "status",
        "actor_id",
        "request_sha256",
        "publication",
        "error_code",
    ),
)
def test_missing_reply_fields_are_not_constructor_defaults(field):
    _, reply = pair()
    value = reply.model_dump(mode="json")
    del value[field]
    with pytest.raises((ValueError, SchemaError)):
        ItemSimilarityPublicationReply.model_validate(value)


@pytest.mark.parametrize(
    "field", ("permission", "token", "path", "context", "item", "request", "native_command")
)
def test_extra_authority_content_and_execution_fields_are_rejected(field):
    request, reply = pair()
    for model, value in (
        (ItemSimilarityPublicationRequest, request),
        (ItemSimilarityPublicationReply, reply),
    ):
        with pytest.raises((ValueError, SchemaError)):
            model.model_validate(value.model_dump(mode="json") | {field: "not-allowed"})


@pytest.mark.parametrize("fault", ("actor", "request", "query"))
def test_valid_but_substituted_reply_is_rejected(fault):
    request, reply = pair()
    body = reply.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "9" * 32
    elif fault == "request":
        body["request_sha256"] = "sha256:" + "9" * 64
    else:
        body["publication"]["delivery"]["request_sha256"] = "sha256:" + "9" * 64
    with pytest.raises(ValueError, match="REPLY_BINDING_INVALID"):
        validate_item_similarity_publication_reply(
            request, ItemSimilarityPublicationReply.model_validate(body)
        )


@pytest.mark.parametrize("fault", ("partial", "error_on_success", "unknown_error", "unpaired"))
def test_failure_envelope_cannot_leak_partial_receipts(fault):
    _, reply = pair()
    body = reply.model_dump(mode="json")
    if fault == "partial":
        body |= {"status": "FAILED", "error_code": "SOURCE_REVOKED"}
    elif fault == "error_on_success":
        body["error_code"] = "SOURCE_ACCESS_DENIED"
    else:
        body |= {"status": "FAILED", "publication": None, "error_code": "SOURCE_REVOKED"}
        if fault == "unknown_error":
            body["error_code"] = "private exception text"
        else:
            body["actor_id"] = None
    with pytest.raises((ValueError, SchemaError)):
        ItemSimilarityPublicationReply.model_validate(body)


def test_forged_nested_values_cannot_serialize_away_extra_fields():
    request, reply = pair()
    forged = copy.deepcopy(request.selection)
    forged.__dict__["permission"] = "ALL"
    with pytest.raises((ValueError, SchemaError)):
        ItemSimilarityPublicationRequest.model_validate(
            request.model_copy(update={"selection": forged})
        )
    forged_publication = copy.deepcopy(reply.publication)
    forged_publication.__dict__["path"] = "/not-allowed"
    with pytest.raises((ValueError, SchemaError)):
        ItemSimilarityPublicationReply.model_validate(
            reply.model_copy(update={"publication": forged_publication})
        )

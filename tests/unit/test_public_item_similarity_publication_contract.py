"""Closed publication2 values and transport fixtures only; no user/source/worker authority."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from eom_catalog_contracts.item_similarity_publication import (
    MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES,
    MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
    ItemSimilarityPublicationReply,
    ItemSimilarityPublicationReplyV2,
    ItemSimilarityPublicationRequest,
    ItemSimilarityPublicationRequestV2,
    ItemSimilarityPublicationV2,
    parse_supported_item_similarity_publication_request,
    validate_public_item_similarity_publication_reply,
)
from eom_catalog_contracts.public_solution_delivery import parse_public_solution_similarity_delivery
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_public_solution_delivery import public_delivery_body
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)

ERRORS = (ValueError, SchemaError)


@lru_cache(maxsize=2)
def public_publication_pair(version=4):
    _, context, *_ = (public_similarity_case if version == 3 else registered_similarity_case)()
    publication = ItemSimilarityPublicationV2(
        owner_job_id="job_" + "1" * 32,
        delivery=parse_public_solution_similarity_delivery(public_delivery_body(context)),
        manifest_sha256="sha256:" + "2" * 64,
    )
    request = ItemSimilarityPublicationRequestV2(
        schema_version="system-rag-item-similarity-publication-request/2.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        actor_id="operator_" + "a" * 32,
        selection=CompletedSimilarityQuerySelection(
            workflow_id="workflow_" + "9" * 32,
            workflow_request_sha256="sha256:" + "9" * 64,
            context_request_sha256=context.request.request_sha256,
        ),
    )
    reply = ItemSimilarityPublicationReplyV2(
        schema_version="system-rag-item-similarity-publication-reply/2.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        status="SUCCESS",
        actor_id=request.actor_id,
        request_sha256=content_sha256(request.model_dump(mode="json")),
        publication=publication,
        error_code=None,
    )
    return request, reply


@pytest.fixture(params=(3, 4))
def pair(request):
    return public_publication_pair(request.param)


def test_mirrored_offline_schema_is_pinned_and_predecessor_bytes_are_unchanged():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-item-similarity-publication-v2"]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-item-similarity-publication-v2"))
    assert sha256_bytes(
        (
            root / "schemas/knowledge/system-rag-item-similarity-publication-v1.schema.json"
        ).read_bytes()
    ) == ("sha256:38eeb30316421482d0770dc5e97cf014738a967277ed5c662dab0fd044ae001a")


def test_exact_publication_is_small_and_dispatch_retains_explicit_family(pair):
    request, reply = pair
    validate_public_item_similarity_publication_reply(request, reply)
    assert parse_supported_item_similarity_publication_request(request) == request
    assert ItemSimilarityPublicationReplyV2.model_validate_json(reply.model_dump_json()) == reply
    assert len(canonical_json_bytes(request)) + 1 < MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES
    assert len(canonical_json_bytes(reply)) + 1 < MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES
    for model, value in (
        (ItemSimilarityPublicationRequest, request),
        (ItemSimilarityPublicationReply, reply),
    ):
        with pytest.raises(ERRORS):
            model.model_validate(value.model_dump(mode="json"))


@pytest.mark.parametrize("field", ("schema_version", "operation", "actor_id", "selection"))
def test_required_request_fields_cannot_be_filled_by_defaults(pair, field):
    request, _ = pair
    body = request.model_dump(mode="json")
    del body[field]
    with pytest.raises(ERRORS):
        parse_supported_item_similarity_publication_request(body)


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
def test_required_reply_fields_cannot_be_filled_by_defaults(pair, field):
    _, reply = pair
    body = reply.model_dump(mode="json")
    del body[field]
    with pytest.raises(ERRORS):
        ItemSimilarityPublicationReplyV2.model_validate(body)


@pytest.mark.parametrize(
    "field", ("permission", "token", "path", "context", "native_command", "schema_name")
)
def test_metadata_cannot_override_authority_schema_or_include_source_payload(pair, field):
    request, reply = pair
    for model, value in (
        (ItemSimilarityPublicationRequestV2, request),
        (ItemSimilarityPublicationReplyV2, reply),
    ):
        with pytest.raises(ERRORS):
            model.model_validate(value.model_dump(mode="json") | {field: "not-allowed"})


@pytest.mark.parametrize("fault", ("actor", "request", "query"))
def test_resealed_or_valid_reply_for_another_identity_is_not_a_replay(pair, fault):
    request, reply = pair
    body = reply.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "0" * 32
    elif fault == "request":
        body["request_sha256"] = "sha256:" + "0" * 64
    else:
        body["publication"]["delivery"]["request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="REPLY_BINDING_INVALID"):
        validate_public_item_similarity_publication_reply(
            request, ItemSimilarityPublicationReplyV2.model_validate(body)
        )


@pytest.mark.parametrize(
    "fault",
    ("partial", "success_error", "unknown_error", "unpaired", "legacy_delivery", "unchecked"),
)
def test_failure_closure_and_nested_forgery_do_not_leak_a_publication(pair, fault):
    _, reply = pair
    body = reply.model_dump(mode="json")
    if fault == "partial":
        body.update(status="FAILED", error_code="SOURCE_REVOKED")
    elif fault == "success_error":
        body["error_code"] = "SOURCE_REVOKED"
    elif fault == "legacy_delivery":
        body["publication"]["delivery"]["schema_version"] = "system-rag-similarity-delivery/1.0"
    elif fault == "unchecked":
        body = reply.model_copy(
            update={"publication": reply.publication.model_copy(update={"permission": "ALL"})}
        )
    else:
        body.update(status="FAILED", publication=None, error_code="SOURCE_REVOKED")
        if fault == "unknown_error":
            body["error_code"] = "private/path should-not-echo"
        else:
            body["actor_id"] = None
    with pytest.raises(ERRORS):
        ItemSimilarityPublicationReplyV2.model_validate(body)


def test_request_dispatch_never_falls_through_to_legacy_for_unknown_version(pair):
    request, _ = pair
    body = deepcopy(request.model_dump(mode="json"))
    body["schema_version"] = "system-rag-item-similarity-publication-request/3.0"
    with pytest.raises(ERRORS):
        parse_supported_item_similarity_publication_request(body)

"""Small auxiliary pins and pure closure; no source grant, storage resolution or activation."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import SimilarityContextDelivery
from eom_catalog_contracts.similarity_context import (
    parse_similarity_context,
    parse_similarity_context_request,
)
from eom_catalog_contracts.similarity_delivery import (
    SIMILARITY_DELIVERY_SCHEMA,
    parse_similarity_context_delivery,
    validate_deliverable_similarity_context,
    validate_similarity_context_delivery,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_similarity_context_contracts import context_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def delivery_body(context: Any) -> dict[str, Any]:
    return {
        "schema_version": "system-rag-similarity-delivery/1.0",
        "context_member": {
            "artifact_id": "artifact_" + "f" * 32,
            "artifact_revision_id": "rev_" + "f" * 32,
            "member_path": "context.json",
            "schema_ref": "eom://schemas/knowledge/system-rag-similarity-context/1.0",
            "media_type": "application/json",
            "sha256": content_sha256(context.model_dump(mode="json")),
        },
        "request_sha256": context.request.request_sha256,
        "context_sha256": context.context_sha256,
    }


def test_new_schema_mirror_hash_and_offline_ref_closure_are_exact() -> None:
    entry = CATALOG_SCHEMA_RESOURCES[SIMILARITY_DELIVERY_SCHEMA]
    canonical = (ROOT / entry.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == entry.sha256
    assert entry.sha256 == "sha256:c403071c18e44cdad39d96ccb7e6c6454ac27fd76c83d7ac6e98e4b938c3fa65"
    schema = load_schema(SIMILARITY_DELIVERY_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]) == {
        "schema_version",
        "context_member",
        "request_sha256",
        "context_sha256",
    }


@pytest.mark.parametrize("required", (False, True))
def test_ready_context_has_distinct_raw_and_semantic_pins(required: bool) -> None:
    context = parse_similarity_context(context_body(required=required))
    delivery = parse_similarity_context_delivery(delivery_body(context))
    assert isinstance(delivery, SimilarityContextDelivery)
    assert delivery.context_member.sha256 != delivery.context_sha256
    assert (
        validate_similarity_context_delivery(delivery, context, expected_request=context.request)
        == context
    )
    assert parse_similarity_context_delivery(delivery) == delivery
    assert len(canonical_json_bytes(delivery.model_dump(mode="json"))) < 1024
    with pytest.raises(ValueError):
        delivery.context_sha256 = "sha256:" + "0" * 64


@pytest.mark.parametrize("missing_report", (False, True))
def test_optional_unavailability_remains_explicit_without_fake_vectors(
    missing_report: bool,
) -> None:
    context = parse_similarity_context(context_body(ready=False, missing_report=missing_report))
    delivery = parse_similarity_context_delivery(delivery_body(context))
    result = validate_similarity_context_delivery(
        delivery, context, expected_request=context.request
    )
    assert result == context and result.status == "PARTIAL" and result.query_execution is None


def test_required_unavailability_is_not_deliverable_graph_fallback() -> None:
    context = parse_similarity_context(context_body(ready=False, required=True))
    with pytest.raises(ValueError, match="REQUIRED_VECTOR_UNAVAILABLE"):
        validate_deliverable_similarity_context(context, expected_request=context.request)


def test_failed_context_cannot_be_delivered_or_reinterpreted_as_empty() -> None:
    body = context_body()
    body.update(
        status="FAILED",
        population=None,
        query_execution=None,
        graph_evidence=None,
        candidates=[],
        error_code="SOURCE_REVOKED",
    )
    context = parse_similarity_context(seal(body, "context_sha256"))
    with pytest.raises(ValueError, match="DELIVERY_INVALID"):
        validate_deliverable_similarity_context(context, expected_request=context.request)


@pytest.mark.parametrize(
    "which", ("request_sha256", "context_sha256", "raw_sha", "expected_request")
)
def test_wrong_supplied_hash_or_expected_request_fails_instead_of_repair(which: str) -> None:
    context = parse_similarity_context(context_body())
    body = delivery_body(context)
    expected = context.request
    if which == "raw_sha":
        body["context_member"]["sha256"] = "sha256:" + "0" * 64
    elif which == "expected_request":
        expected = context.request.model_copy(
            update={"request_id": "similarityrequest_" + "0" * 32}
        )
    else:
        body[which] = "sha256:" + "0" * 64
    with pytest.raises(ERRORS):
        validate_similarity_context_delivery(
            parse_similarity_context_delivery(body), context, expected_request=expected
        )


def test_another_valid_request_is_not_a_replay_or_latest_substitute() -> None:
    context = parse_similarity_context(context_body())
    expected = parse_similarity_context_request(
        seal(
            context.request.model_dump(mode="json")
            | {"request_id": "similarityrequest_" + "0" * 32},
            "request_sha256",
        )
    )
    with pytest.raises(ValueError, match="DELIVERY_INVALID"):
        validate_similarity_context_delivery(
            parse_similarity_context_delivery(delivery_body(context)),
            context,
            expected_request=expected,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("member_path", "../context.json"),
        ("member_path", "latest.json"),
        ("media_type", "text/markdown"),
        ("schema_ref", "eom://schemas/knowledge/evidence/1.0"),
        ("artifact_id", "latest"),
        ("artifact_revision_id", "current"),
        ("sha256", True),
        ("role", "ADMIN"),
        ("path", "/mnt/nas/private"),
    ),
)
def test_closed_member_pin_rejects_wrong_schema_media_path_identity_or_authority(
    field: str, value: Any
) -> None:
    context = parse_similarity_context(context_body())
    body = delivery_body(context)
    body["context_member"][field] = value
    with pytest.raises(ERRORS):
        parse_similarity_context_delivery(body)


@pytest.mark.parametrize("field", ("actor", "approved", "text", "vectors", "delivery_sha256"))
def test_delivery_has_no_grant_body_binary_or_independent_lifecycle(field: str) -> None:
    context = parse_similarity_context(context_body())
    body = delivery_body(context) | {field: True}
    with pytest.raises(ERRORS):
        parse_similarity_context_delivery(body)


@pytest.mark.parametrize("how", ("copy", "construct", "nested_copy", "cycle", "huge"))
def test_raw_nested_values_are_revalidated_before_dump_or_coercion(how: str) -> None:
    context = parse_similarity_context(context_body())
    delivery = parse_similarity_context_delivery(delivery_body(context))
    bad: Any
    if how == "copy":
        bad = delivery.model_copy(update={"role": "ADMIN"})
    elif how == "construct":
        bad = SimilarityContextDelivery.model_construct(
            **(delivery.model_dump() | {"context_sha256": True})
        )
    elif how == "nested_copy":
        bad = delivery.model_copy(
            update={"context_member": delivery.context_member.model_copy(update={"sha256": True})}
        )
    else:
        bad = copy.deepcopy(delivery_body(context))
        bad["context_member"]["sha256"] = bad if how == "cycle" else "x" * 16384
    with pytest.raises(ERRORS):
        parse_similarity_context_delivery(bad)

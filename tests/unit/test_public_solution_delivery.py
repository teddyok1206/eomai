"""Public delivery pins only: synthetic evidence, never live permission or consumer activation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.public_solution_delivery import (
    PUBLIC_SOLUTION_DELIVERY_SCHEMA,
    PublicSolutionSimilarityDelivery,
    parse_public_solution_similarity_delivery,
    validate_public_solution_similarity_delivery,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_delivery import parse_similarity_context_delivery
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)
from tests.unit.test_similarity_context_contracts import context_body
from tests.unit.test_similarity_delivery_contracts import delivery_body

ERRORS = (ValueError, SchemaError)


@pytest.fixture(params=(3, 4))
def case(request):
    factory = public_similarity_case if request.param == 3 else registered_similarity_case
    return factory()[:2]


def public_delivery_body(context: Any) -> dict[str, Any]:
    body = delivery_body(context)
    body["schema_version"] = "system-rag-similarity-delivery/2.0"
    body["context_member"]["schema_ref"] = {
        "system-rag-similarity-context/3.0": "eom://schemas/knowledge/system-rag-similarity-context/3.0",
        "system-rag-similarity-context/4.0": "eom://schemas/knowledge/system-rag-similarity-context/4.0",
    }[context.schema_version]
    return body


def test_schema_is_pinned_mirrored_and_old_delivery_bytes_are_unchanged():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[PUBLIC_SOLUTION_DELIVERY_SCHEMA]
    canonical = (root / resource.canonical_path).read_bytes()
    packaged = (
        root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged and sha256_bytes(canonical) == resource.sha256
    schema = load_schema(PUBLIC_SOLUTION_DELIVERY_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    predecessor = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-delivery"]
    assert sha256_bytes((root / predecessor.canonical_path).read_bytes()) == (
        "sha256:c403071c18e44cdad39d96ccb7e6c6454ac27fd76c83d7ac6e98e4b938c3fa65"
    )


def test_small_exact_delivery_preserves_context_family_hashes_and_replay(case):
    request, context = case
    body = public_delivery_body(context)
    validate_contract(PUBLIC_SOLUTION_DELIVERY_SCHEMA, body)
    pin = parse_public_solution_similarity_delivery(body)
    assert len(canonical_json_bytes(pin.model_dump(mode="json"))) < 1024
    assert pin.context_member.sha256 != pin.context_sha256
    assert (
        validate_public_solution_similarity_delivery(pin, context, expected_request=request)
        == context
    )
    assert parse_public_solution_similarity_delivery(pin) == pin
    with pytest.raises(ValueError):
        pin.context_sha256 = "sha256:" + "0" * 64
    with pytest.raises(ERRORS):
        parse_similarity_context_delivery(body)


@pytest.mark.parametrize("status", ("PARTIAL", "EMPTY"))
def test_partial_and_empty_are_observations_not_promoted_to_ready(case, status):
    request, original = case
    body = original.model_dump(mode="json")
    if status == "PARTIAL":
        body["population"]["authorized_source_count"] += 1
        body["limitations"].append("PARTIAL_REPORT_COVERAGE")
    else:
        body["candidates"] = []
        body["population"]["scored_count"] = 0
    body["status"] = status
    context = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    pin = parse_public_solution_similarity_delivery(public_delivery_body(context))
    checked = validate_public_solution_similarity_delivery(pin, context, expected_request=request)
    assert checked.status == status and checked == context


def test_failed_context_is_not_deliverable_or_reinterpreted_as_empty(case):
    request, original = case
    body = original.model_dump(mode="json")
    body.update(
        status="FAILED",
        population=None,
        query_execution=None,
        candidates=[],
        error_code="SOURCE_REVOKED",
    )
    context = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    pin = parse_public_solution_similarity_delivery(public_delivery_body(context))
    with pytest.raises(ValueError, match="DELIVERY_INVALID"):
        validate_public_solution_similarity_delivery(pin, context, expected_request=request)


@pytest.mark.parametrize(
    "fault", ("raw_sha", "request_sha256", "context_sha256", "schema_family", "expected_request")
)
def test_wrong_original_pins_and_resealed_foreign_request_fail_without_latest_repair(case, fault):
    request, context = case
    body = public_delivery_body(context)
    if fault == "raw_sha":
        body["context_member"]["sha256"] = "sha256:" + "0" * 64
    elif fault == "schema_family":
        body["context_member"]["schema_ref"] = {
            "system-rag-similarity-context/3.0": "eom://schemas/knowledge/system-rag-similarity-context/4.0",
            "system-rag-similarity-context/4.0": "eom://schemas/knowledge/system-rag-similarity-context/3.0",
        }[context.schema_version]
    elif fault == "expected_request":
        request = parse_supported_public_solution_similarity_request(
            seal(
                request.model_dump(mode="json") | {"request_id": "similarityrequest_" + "0" * 32},
                "request_sha256",
            )
        )
    else:
        body[fault] = "sha256:" + "0" * 64
    with pytest.raises(ERRORS):
        validate_public_solution_similarity_delivery(
            parse_public_solution_similarity_delivery(body), context, expected_request=request
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema_ref", "eom://schemas/knowledge/system-rag-similarity-context/1.0"),
        ("schema_ref", "eom://schemas/knowledge/system-rag-similarity-context/2.0"),
        ("schema_ref", "eom://schemas/knowledge/evidence/1.0"),
        ("member_path", "../context.json"),
        ("member_path", "latest.json"),
        ("media_type", "image/png"),
        ("artifact_id", "current"),
        ("artifact_revision_id", "latest"),
        ("sha256", True),
        ("authority", "ADMIN"),
    ),
)
def test_closed_member_rejects_legacy_family_path_media_identity_and_authority(case, field, value):
    _, context = case
    body = public_delivery_body(context)
    body["context_member"][field] = value
    with pytest.raises(ERRORS):
        parse_public_solution_similarity_delivery(body)


@pytest.mark.parametrize("field", ("actor", "approved", "text", "vectors", "delivery_sha256"))
def test_small_pin_cannot_include_authority_payload_or_new_lifecycle(case, field):
    _, context = case
    with pytest.raises(ERRORS):
        parse_public_solution_similarity_delivery(public_delivery_body(context) | {field: True})


@pytest.mark.parametrize("fault", ("copy", "construct", "nested_copy", "cycle", "huge"))
def test_unchecked_models_nested_mutations_cycles_and_budget_are_validated_raw(case, fault):
    _, context = case
    body = public_delivery_body(context)
    pin = parse_public_solution_similarity_delivery(body)
    if fault == "copy":
        value = pin.model_copy(update={"actor": "ADMIN"})
    elif fault == "construct":
        value = PublicSolutionSimilarityDelivery.model_construct(
            **(pin.model_dump() | {"request_sha256": True})
        )
    elif fault == "nested_copy":
        value = pin.model_copy(
            update={"context_member": pin.context_member.model_copy(update={"sha256": True})}
        )
    else:
        value = deepcopy(body)
        value["context_member"]["sha256"] = value if fault == "cycle" else "x" * 16384
    with pytest.raises(ERRORS):
        parse_public_solution_similarity_delivery(value)


def test_legacy_context_is_not_a_public_delivery_even_if_relabelled():
    body = context_body()
    body["schema_version"] = "system-rag-similarity-context/3.0"
    with pytest.raises(ERRORS):
        parse_supported_public_solution_similarity_context(body)

"""Pointer contracts and real temporary publication, never current source/GPU authority."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV3,
    ReferenceQueryPrepareRequestV3,
    ReferenceQueryPrepareRequestV4,
    parse_single_reference_query_prepare_request,
    parse_supported_reference_query_prepare_reply,
    parse_supported_reference_query_prepare_request,
    routed_reference_query_error_reply,
    validate_supported_reference_query_prepare_reply,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.reference_query_routed_preparation import (
    PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF,
    PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256,
    PublicRoutedReferenceQueryPreparation,
    RoutedReferenceQueryPreparation,
    parse_reference_query_routed_preparation,
    parse_supported_reference_query_routed_preparation,
)
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_public_solution_query_batch_plan import public_parent_case


def public_prepare_request(count=1):
    case = public_parent_case()
    return ReferenceQueryPrepareRequestV4.model_validate(
        seal(
            dict(
                schema_version="system-rag-reference-query-prepare-request/4.0",
                operation="PREPARE_REFERENCE_QUERY",
                operation_id="queryprepare_" + "1" * 32,
                idempotency_key="public-query-synthetic-key",
                source_item_revision_ids=[f"itemrev_{index + 1:032x}" for index in range(count)],
                graph_snapshot=case.context.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=case.context.policy_revision_id,
                policy_sha256=case.context.policy_sha256,
                consumer_purpose="ITEM_DATABASE_SEARCH",
                top_k=8,
            ),
            "request_sha256",
        )
    )


def preparation():
    case = public_parent_case()
    return PublicRoutedReferenceQueryPreparation.model_validate(
        seal(
            dict(
                schema_version="reference-query-routed-preparation/2.0",
                operator_id=case.request.scope.actor_id,
                idempotency_key="public-query-synthetic-key",
                intent_sha256=case.request.parent_request_sha256,
                owner_configuration_sha256="sha256:" + "a" * 64,
                parent=case.request.model_dump(mode="json"),
            ),
            "preparation_sha256",
        )
    )


@pytest.mark.parametrize("count", (1, 5, 32))
def test_public_prepare_has_one_bounded_scope_and_preserves_requested_order(count):
    request = public_prepare_request(count)
    assert parse_supported_reference_query_prepare_request(request) == request
    validate_contract("system-rag-reference-query-prepare-v4", request.model_dump(mode="json"))
    failure = routed_reference_query_error_reply(
        request, status="UNAVAILABLE", error_code="INDEX_NOT_PREPARED"
    )
    assert failure.schema_version == "system-rag-reference-query-prepare-reply/4.0"
    assert parse_supported_reference_query_prepare_reply(failure) == failure
    validate_supported_reference_query_prepare_reply(request, failure)
    with pytest.raises(ValueError):
        parse_single_reference_query_prepare_request(request)
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequestV3.model_validate(request.model_dump(mode="json"))
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareReplyV3.model_validate(failure.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault", ("empty", "large", "duplicate", "unknown", "bool", "hash", "graph")
)
def test_public_prepare_rejects_unbounded_ambiguous_or_unhashed_inputs(fault):
    body = deepcopy(public_prepare_request().model_dump(mode="json"))
    if fault == "empty":
        body["source_item_revision_ids"] = []
    elif fault == "large":
        body["source_item_revision_ids"] = [f"itemrev_{index + 1:032x}" for index in range(33)]
    elif fault == "duplicate":
        body["source_item_revision_ids"] *= 2
    elif fault == "unknown":
        body["actor_id"] = "operator_" + "a" * 32
    elif fault == "bool":
        body["top_k"] = True
    elif fault == "graph":
        body["graph_snapshot"]["manifest_sha256"] = "sha256:" + "b" * 64
    else:
        body["request_sha256"] = "sha256:" + "b" * 64
    with pytest.raises((ValueError, SchemaError)):
        ReferenceQueryPrepareRequestV4.model_validate(
            body if fault == "hash" else seal(body, "request_sha256")
        )


def test_public_preparation_pins_parent14_and_keeps_legacy_decoder_closed():
    value = preparation()
    raw = canonical_json_bytes(value)
    assert parse_supported_reference_query_routed_preparation(raw) == value
    for operation in (
        lambda: RoutedReferenceQueryPreparation.model_validate(value.model_dump(mode="json")),
        lambda: parse_reference_query_routed_preparation(raw),
        lambda: parse_supported_reference_query_routed_preparation(raw + b" "),
    ):
        with pytest.raises(ValueError):
            operation()


def test_public_preparation_reuses_original_indexed_publication_and_hash(tmp_path):
    publisher, engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    value = preparation()
    first = controls.publish_public_routed_reference_query_preparation(value)
    assert controls.publish_public_routed_reference_query_preparation(value) == first
    assert first.member.schema_ref == PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_REF
    assert (
        controls.find_public_routed_reference_query_preparation(
            operator_id=value.operator_id, idempotency_key=value.idempotency_key
        )
        == first.member
    )
    with pytest.raises(ValueError):
        controls.publish_routed_reference_query_preparation(value)
    engine.dispose()


def test_public_prepare_and_preparation_schema_mirrors_are_registered_and_pinned():
    root = Path(__file__).resolve().parents[2]
    name = "reference-query-routed-preparation-v2.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == PUBLIC_ROUTED_QUERY_PREPARATION_SCHEMA_SHA256
    name = "system-rag-reference-query-prepare-v4.schema.json"
    raw = (root / "schemas/knowledge" / name).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
        ).read_bytes()
    )
    assert load_schema("system-rag-reference-query-prepare-v4")["$id"].endswith("/4.0")

"""Original pointer metadata only; no current source/Identity or model authority."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_batch_plan_v12 import EmbeddingBatchPlanRequestV12
from eom_workflow.reference_query_routed_preparation import (
    ROUTED_QUERY_PREPARATION_SCHEMA_SHA256,
    RoutedReferenceQueryPreparation,
    parse_reference_query_routed_preparation,
    reference_query_routed_preparation_schema,
    routed_reference_query_preparation_key,
)
from jsonschema import Draft202012Validator

from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import seal


def preparation_case(*, key="synthetic-routed-query", operator_id="operator_" + "1" * 32):
    value = paired_query_case(actor_id=operator_id)
    return RoutedReferenceQueryPreparation.model_validate(
        seal(
            dict(
                schema_version="reference-query-routed-preparation/1.0",
                operator_id=operator_id,
                idempotency_key=key,
                intent_sha256=value.request.parent_request_sha256,
                owner_configuration_sha256="sha256:" + "c" * 64,
                parent=value.request.model_dump(mode="json"),
            ),
            "preparation_sha256",
        )
    )


def test_offline_schema_mirror_exact_roundtrip_and_parent_is_not_a_new_latest_lookup():
    root = Path(__file__).resolve().parents[2]
    name = "reference-query-routed-preparation-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == ROUTED_QUERY_PREPARATION_SCHEMA_SHA256
    schema = reference_query_routed_preparation_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])
    value = preparation_case()
    assert parse_reference_query_routed_preparation(canonical_json_bytes(value)) == value
    assert isinstance(value.parent, EmbeddingBatchPlanRequestV12)
    assert len(canonical_json_bytes(value)) < 16384


@pytest.mark.parametrize(
    "fault", ("actor", "intent", "parent", "hash", "schema", "authority", "password", "nested")
)
def test_invalid_or_foreign_original_metadata_never_becomes_authority(fault):
    value = preparation_case()
    body = value.model_dump(mode="json")
    if fault == "actor":
        body["operator_id"] = "operator_" + "a" * 32
    elif fault == "intent":
        body["intent_sha256"] = "sha256:" + "a" * 64
    elif fault == "parent":
        body["parent"]["purpose"] = "INDEX"
        body["parent"] = seal(body["parent"], "request_sha256")
    elif fault == "schema":
        body["schema_version"] = "reference-query-routed-preparation/2.0"
    elif fault == "authority":
        body["roles"] = ["ADMIN"]
    elif fault == "password":
        body["password"] = "synthetic-not-secret"
    elif fault == "nested":
        body["parent"]["source_permission"] = True
    body = seal(body, "preparation_sha256")
    if fault == "hash":
        body["preparation_sha256"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        RoutedReferenceQueryPreparation.model_validate(body)


@pytest.mark.parametrize("fault", ("newline", "duplicate", "constant", "oversized", "copied"))
def test_raw_input_or_constructed_models_cannot_bypass_canonical_validation(fault):
    value = preparation_case()
    raw = canonical_json_bytes(value)
    if fault == "newline":
        raw += b"\n"
    elif fault == "duplicate":
        raw = raw[:-1] + b',"operator_id":"operator_' + b"1" * 32 + b'"}'
    elif fault == "constant":
        raw = b'{"parent":NaN}'
    elif fault == "oversized":
        raw = b" " * 65537
    else:
        value = value.model_copy(update={"roles": ["ADMIN"]})
    with pytest.raises(ValueError):
        if fault == "copied":
            RoutedReferenceQueryPreparation.model_validate(value)
        else:
            parse_reference_query_routed_preparation(raw)


def test_publication_identity_is_scoped_by_actual_operator_and_original_key():
    first = routed_reference_query_preparation_key("operator_" + "1" * 32, "original-key")
    assert first == routed_reference_query_preparation_key("operator_" + "1" * 32, "original-key")
    assert len(first) <= 128
    assert first != routed_reference_query_preparation_key("operator_" + "2" * 32, "original-key")
    assert first != routed_reference_query_preparation_key("operator_" + "1" * 32, "another-key")


@pytest.mark.parametrize(
    "operator,key",
    (
        (True, "original-key"),
        ("ADMIN", "original-key"),
        ("operator_" + "1" * 32, True),
        ("operator_" + "1" * 32, "short"),
        ("operator_" + "1" * 32, "bad/key-here"),
    ),
)
def test_publication_key_does_not_coerce_or_broaden_actor_syntax(operator, key):
    with pytest.raises(ValueError):
        routed_reference_query_preparation_key(operator, key)

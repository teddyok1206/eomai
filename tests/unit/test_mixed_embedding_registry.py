"""Schema2 metadata only; no current source, Artifact or registration authority."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_registry import parse_embedding_registration_command
from eom_catalog_contracts.mixed_embedding_index import MIXED_EMBEDDING_INDEX_SCHEMA_REF
from eom_catalog_contracts.mixed_embedding_registry import (
    MIXED_EMBEDDING_REGISTRY_SCHEMA,
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
    parse_embedding_registration_command_v2,
    parse_embedding_registration_result_v2,
    validate_embedding_registration_result_v2,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_contracts import registration_command, registration_result

INVALID = (ValueError, TypeError, SchemaError)
ROOT = Path(__file__).resolve().parents[2]


def mixed_registration_command() -> RegisterEmbeddingIndexCommandV2:
    body = registration_command().model_dump(mode="json")
    body["schema_version"] = "embedding-registry-registration-command/2.0"
    body["namespace"]["projection_version"] = "mixed-solution-comparison/2.0"
    body["index_manifest"]["schema_ref"] = MIXED_EMBEDDING_INDEX_SCHEMA_REF
    return parse_embedding_registration_command_v2(seal(body, "request_sha256"))


def mixed_registration_result() -> EmbeddingIndexRegistrationResultV2:
    body = registration_result().model_dump(mode="json")
    command = mixed_registration_command()
    body.update(
        schema_version="embedding-registry-registration-result/2.0",
        request_sha256=command.request_sha256,
        index_manifest=command.index_manifest.model_dump(mode="json"),
    )
    return parse_embedding_registration_result_v2(seal(body, "result_sha256"))


def test_schema_first_mirror_draft_identity_and_both_closed_round_trips():
    entry = CATALOG_SCHEMA_RESOURCES[MIXED_EMBEDDING_REGISTRY_SCHEMA]
    raw = (ROOT / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(MIXED_EMBEDDING_REGISTRY_SCHEMA))
    command, result = mixed_registration_command(), mixed_registration_result()
    assert validate_embedding_registration_result_v2(command, result) == result
    assert command.namespace.accepts_projection("accepted-solution-comparison/1.0")
    assert command.namespace.accepts_projection("registered-item-review-comparison/1.0")
    assert not command.namespace.accepts_projection("mixed-solution-comparison/2.0")
    assert not registration_command().namespace.accepts_projection(
        "registered-item-review-comparison/1.0"
    )
    for value, parser in (
        (command, parse_embedding_registration_command_v2),
        (result, parse_embedding_registration_result_v2),
    ):
        assert parser(value) == value
        assert parser(value.model_dump(mode="json")) == value
        assert canonical_json_bytes(parser(value)) == canonical_json_bytes(value)
    with pytest.raises(INVALID):
        parse_embedding_registration_command(command.model_dump(mode="json"))
    with pytest.raises(INVALID):
        parse_embedding_registration_command_v2(registration_command())


@pytest.mark.parametrize(
    "field,value",
    (
        ("expected_lock_version", True),
        ("expected_lock_version", 2),
        ("eligible_source_count", 0),
        ("eligible_source_count", 1025),
        ("binding_count", 2),
        ("binding_count", 0),
        ("expected_current_index_revision_id", "SELF"),
        ("requested_at", "2026-10-19T09:00:00+09:00"),
        ("operation", "AUTHORIZE"),
        ("request_sha256", "sha256:" + "f" * 64),
    ),
)
def test_shared_head_coverage_timestamp_and_hash_guards(field, value):
    body = mixed_registration_command().model_dump(mode="json")
    body[field] = body["index_revision_id"] if value == "SELF" else value
    with pytest.raises(INVALID):
        parse_embedding_registration_command_v2(
            body if field == "request_sha256" else seal(body, "request_sha256")
        )


@pytest.mark.parametrize(
    "target,field,value",
    (
        ("namespace", "projection_version", "accepted-solution-comparison/1.0"),
        ("namespace", "population_scope", "OCCURRENCE_BACKED_PAST_EXAM"),
        ("index_manifest", "schema_ref", "eom://schemas/knowledge/embedding-index-manifest/1.0"),
        ("index_manifest", "member_path", "../index.json"),
        ("index_manifest", "media_type", "text/plain"),
        ("graph_snapshot", "manifest_sha256", "sha256:" + "f" * 64),
    ),
)
def test_new_namespace_and_exact_manifest_do_not_reinterpret_legacy(target, field, value):
    body = mixed_registration_command().model_dump(mode="json")
    body[target][field] = value
    with pytest.raises(INVALID):
        parse_embedding_registration_command_v2(seal(body, "request_sha256"))


@pytest.mark.parametrize(
    "field,value",
    (
        ("replayed", 1),
        ("is_current", False),
        ("current_lock_version", 1),
        ("current_lock_version", 3),
        ("previous_index_revision_id", "SELF"),
    ),
)
def test_shared_receipt_generation_rules_are_identical(field, value):
    body = mixed_registration_result().model_dump(mode="json")
    body[field] = body["index_revision_id"] if value == "SELF" else value
    with pytest.raises(INVALID):
        parse_embedding_registration_result_v2(seal(body, "result_sha256"))


def test_historical_replay_receipt_retains_exact_request_but_does_not_roll_back_current():
    command = mixed_registration_command()
    body = mixed_registration_result().model_dump(mode="json")
    body.update(
        replayed=True,
        is_current=False,
        current_lock_version=3,
        current_index_revision_id="embeddingindexrev_" + "f" * 32,
    )
    result = parse_embedding_registration_result_v2(seal(body, "result_sha256"))
    assert validate_embedding_registration_result_v2(command, result) == result
    body["request_sha256"] = "sha256:" + "f" * 64
    result = parse_embedding_registration_result_v2(seal(body, "result_sha256"))
    with pytest.raises(INVALID):
        validate_embedding_registration_result_v2(command, result)


@pytest.mark.parametrize("target", ("root", "namespace", "pointer", "missing"))
def test_forged_frozen_values_do_not_erase_extra_fields_or_missing_data(target):
    command = mixed_registration_command()
    if target == "root":
        forged = command.model_copy(update={"role": "ADMIN"})
    elif target == "namespace":
        forged = command.model_copy(
            update={"namespace": command.namespace.model_copy(update={"role": "ADMIN"})}
        )
    elif target == "pointer":
        forged = command.model_copy(
            update={"index_manifest": command.index_manifest.model_copy(update={"role": "ADMIN"})}
        )
    else:
        forged = RegisterEmbeddingIndexCommandV2.model_construct(
            schema_version=command.schema_version
        )
    with pytest.raises(INVALID):
        parse_embedding_registration_command_v2(forged)

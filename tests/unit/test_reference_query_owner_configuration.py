"""Pure root-selection fixtures; no installed provider, database, account or authority."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import identity_provider_code_members
from eom_workflow.reference_query_owner_configuration import (
    REFERENCE_QUERY_OWNER_SCHEMA_SHA256,
    ReferenceQueryOwnerConfigurationError,
    ReferenceQueryServiceConfiguration,
    parse_reference_query_service_configuration,
    reference_query_owner_configuration_schema,
    reference_query_service_configuration_bytes,
)
from jsonschema import Draft202012Validator

from tests.unit.test_reference_query_owner_admission import source as source


def owner_body(source):
    config = source.owner.configuration
    return {
        "schema_version": "reference-query-owner-configuration/1.0",
        "owner_source_commit": "a" * 40,
        "corpus_id": config.registry.corpus_id,
        "namespace": config.registry.namespace.model_dump(mode="json"),
        "recipe": config.registry.recipe.model_dump(mode="json"),
        "source_classes": list(config.registry.source_classes),
        "native_execution_policy": config.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": config.native_execution_policy_sha256,
        "runtime_bundle": config.runtime_bundle.model_dump(mode="json"),
        "database_owner": {"role_name": "eom_app", "role_oid": 12345},
        "runtime_verifier": {"source_commit": "b" * 40, "script_raw_sha256": "sha256:" + "c" * 64},
        "cpu_environment_raw_sha256": "sha256:" + "d" * 64,
        "owner_environment_raw_sha256": "sha256:" + "e" * 64,
        "api_provider": {
            "source_commit": "f" * 40,
            "wheel_sha256": "sha256:" + "1" * 64,
            "configuration_sha256": "sha256:" + "2" * 64,
            "code_members": [
                {"member": member, "sha256": "sha256:" + "3" * 64}
                for member in identity_provider_code_members()
            ],
        },
    }


def test_closed_mirror_hash_offline_refs_and_exact_canonical_roundtrip(source):
    root = Path(__file__).resolve().parents[2]
    name = "reference-query-owner-configuration-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == REFERENCE_QUERY_OWNER_SCHEMA_SHA256
    schema = reference_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])
    value = ReferenceQueryServiceConfiguration.model_validate(owner_body(source))
    encoded = reference_query_service_configuration_bytes(value)
    assert parse_reference_query_service_configuration(encoded) == value


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "operator_" + "a" * 32),
        ("password", "not-a-real-credential"),
        ("socket", "/tmp/not-native.sock"),
        ("maximum_authentication_age_seconds", 86400),
        ("model", "foreign"),
        ("source_ids", []),
        ("graph_snapshot", {}),
        ("owner_source_commit", True),
    ),
)
def test_no_authority_credential_path_source_or_expiry_selection(source, field, value):
    body = owner_body(source)
    body[field] = value
    with pytest.raises(ValueError, match="REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID"):
        ReferenceQueryServiceConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault", ("role", "oid_bool", "recipe", "unsorted", "duplicate", "path", "hidden")
)
def test_bad_native_selection_or_provider_members_fail_closed(source, fault):
    body = owner_body(source)
    if fault == "role":
        body["database_owner"]["role_name"] = "postgres"
    elif fault == "oid_bool":
        body["database_owner"]["role_oid"] = True
    elif fault == "recipe":
        body["namespace"]["recipe_sha256"] = "sha256:" + "0" * 64
    elif fault == "unsorted":
        body["api_provider"]["code_members"].reverse()
    elif fault == "duplicate":
        rows = body["api_provider"]["code_members"]
        rows[1] = {**rows[0], "sha256": "sha256:" + "4" * 64}
    elif fault == "path":
        body["api_provider"]["code_members"][0]["member"] = "../../api.env"
    else:
        body = ReferenceQueryServiceConfiguration.model_validate(body).model_copy(
            update={"roles": ["ADMIN"]}
        )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID"):
        ReferenceQueryServiceConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ("whitespace", "duplicate", "oversized", "nan"))
def test_raw_parser_never_normalizes_external_configuration_bytes(source, fault):
    raw = canonical_json_bytes(owner_body(source))
    if fault == "whitespace":
        raw = b" " + raw
    elif fault == "duplicate":
        raw = raw[:-1] + b',"corpus_id":"corpus_' + b"f" * 32 + b'"}'
    elif fault == "oversized":
        raw = b" " * 65537
    else:
        raw = b'{"bad":NaN}'
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        parse_reference_query_service_configuration(raw)

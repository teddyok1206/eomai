"""Pure configuration fixtures; no installed runtime/source/identity authorization."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.private_chat_query_owner_configuration import (
    MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES,
    PRIVATE_CHAT_QUERY_OWNER_SCHEMA_SHA256,
    PrivateChatQueryOwnerConfigurationError,
    PrivateChatQueryServiceConfiguration,
    parse_private_chat_query_service_configuration,
    private_chat_query_owner_configuration_schema,
    private_chat_query_service_configuration_bytes,
    require_private_chat_query_reference_configuration,
)
from eom_workflow.reference_query_owner_configuration import (
    ReferenceQueryServiceConfiguration,
    reference_query_service_configuration_bytes,
)
from jsonschema import Draft202012Validator

from tests.unit.test_private_chat_query_source_owner import source as source
from tests.unit.test_reference_query_owner_configuration import owner_body


def reference_configuration(source):
    # Metadata fixture only: no assertion that this pointer resolves as a real
    # reference policy. Real startup must resolve its separate canonical controls.
    body = owner_body(source)
    body["native_execution_policy"]["schema_ref"] = (
        "eom://schemas/workflow/reference-query-execution-policy/1.0"
    )
    return ReferenceQueryServiceConfiguration.model_validate(body)


def private_body(source, reference):
    config = source.owner.configuration
    return {
        "schema_version": "private-chat-query-owner-configuration/1.0",
        "reference_configuration_raw_sha256": sha256_bytes(
            reference_query_service_configuration_bytes(reference)
        ),
        "corpus_id": config.registry.corpus_id,
        "namespace": config.registry.namespace.model_dump(mode="json"),
        "recipe": config.registry.recipe.model_dump(mode="json"),
        "source_classes": list(config.registry.source_classes),
        "native_execution_policy": config.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": config.native_execution_policy_sha256,
        "runtime_bundle": config.runtime_bundle.model_dump(mode="json"),
        "owner_environment_raw_sha256": "sha256:" + "e" * 64,
    }


def test_schema_mirror_hash_closed_offline_references_and_canonical_roundtrip(source):
    root = Path(__file__).resolve().parents[2]
    name = "private-chat-query-owner-configuration-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == PRIVATE_CHAT_QUERY_OWNER_SCHEMA_SHA256
    schema = private_chat_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    reference = reference_configuration(source)
    checked = PrivateChatQueryServiceConfiguration.model_validate(private_body(source, reference))
    encoded = private_chat_query_service_configuration_bytes(checked)
    assert parse_private_chat_query_service_configuration(encoded) == checked
    require_private_chat_query_reference_configuration(checked, reference)


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_id", "operator_" + "a" * 32),
        ("password", "synthetic-not-a-credential"),
        ("roles", ["ADMIN"]),
        ("socket", "/tmp/not-private.sock"),
        ("maximum_authentication_age_seconds", 86400),
        ("database_owner", {"role_name": "postgres", "role_oid": 1}),
        ("runtime_verifier", {"source_commit": "b" * 40}),
        ("cpu_environment_raw_sha256", "sha256:" + "c" * 64),
        ("reference_configuration_raw_sha256", True),
    ),
)
def test_no_authority_path_login_or_shared_baseline_override(source, field, value):
    body = private_body(source, reference_configuration(source))
    body[field] = value
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID"):
        PrivateChatQueryServiceConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault", ("view", "recipe", "duplicate", "unsorted", "reference_policy", "path", "hidden")
)
def test_private_purpose_content_view_and_immutable_selection_are_enforced(source, fault):
    body = private_body(source, reference_configuration(source))
    if fault == "view":
        body["namespace"]["view"] = "CONCRETE_FACETS"
    elif fault == "recipe":
        body["namespace"]["recipe_sha256"] = "sha256:" + "f" * 64
    elif fault == "duplicate":
        body["source_classes"] = ["PAST_EXAM", "PAST_EXAM"]
    elif fault == "unsorted":
        body["source_classes"] = ["PAST_EXAM", "APPROVED_ITEM"]
    elif fault == "reference_policy":
        body["native_execution_policy"]["schema_ref"] = (
            "eom://schemas/workflow/reference-query-execution-policy/1.0"
        )
    elif fault == "path":
        body["native_execution_policy"]["member_path"] = "../policy.json"
    else:
        body = PrivateChatQueryServiceConfiguration.model_validate(body).model_copy(
            update={"role": "ADMIN"}
        )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID"):
        PrivateChatQueryServiceConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ("whitespace", "duplicate", "oversized", "nan", "str"))
def test_parser_does_not_normalize_untrusted_configuration(source, fault):
    raw = canonical_json_bytes(private_body(source, reference_configuration(source)))
    if fault == "whitespace":
        raw = b" " + raw
    elif fault == "duplicate":
        raw = raw[:-1] + b',"schema_version":"private-chat-query-owner-configuration/1.0"}'
    elif fault == "oversized":
        raw = b" " * (MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES + 1)
    elif fault == "nan":
        raw = b'{"bad":NaN}'
    else:
        raw = raw.decode()
    with pytest.raises(PrivateChatQueryOwnerConfigurationError):
        parse_private_chat_query_service_configuration(raw)


def test_changed_reference_deployment_cannot_reuse_old_private_configuration(source):
    reference = reference_configuration(source)
    private = PrivateChatQueryServiceConfiguration.model_validate(private_body(source, reference))
    body = reference.model_dump(mode="json")
    body["cpu_environment_raw_sha256"] = "sha256:" + "1" * 64
    changed = ReferenceQueryServiceConfiguration.model_validate(body)
    with pytest.raises(PrivateChatQueryOwnerConfigurationError):
        require_private_chat_query_reference_configuration(private, changed)

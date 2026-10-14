"""Closed non-secret owner metadata only; no runtime/DB/source grant or model."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_indexing_owner_configuration import (
    LOCAL_INDEXING_OWNER_SCHEMA_REF,
    LOCAL_INDEXING_OWNER_SCHEMA_SHA256,
    LocalIndexingOwnerConfiguration,
    LocalIndexingOwnerConfigurationError,
    local_indexing_owner_configuration_bytes,
    local_indexing_owner_configuration_schema,
    parse_local_indexing_owner_configuration,
)
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES,
)
from jsonschema import Draft202012Validator

from tests.unit.local_embedding_service_fixtures import service_fixture

ROOT = Path(__file__).resolve().parents[2]


def document():
    c = service_fixture()
    return {
        "schema_version": "local-indexing-owner-configuration/1.0",
        "corpus_id": c.request.corpus_id,
        "namespace": c.request.namespace.model_dump(mode="json"),
        "recipe": c.base.plan.recipe.model_dump(mode="json"),
        "source_classes": ["PAST_EXAM"],
        "service_policy_revision_id": c.grant.access_policy_revision_id,
        "service_policy_sha256": c.grant.content_sha256,
        "native_execution_policy": c.request.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": c.policy.policy_sha256,
        "runtime_profile": c.policy.profiles[0].model_dump(mode="json"),
        "database_owner": {"role_name": "synthetic_ddl_owner", "role_oid": 12001},
        "runtime_verifier": {"source_commit": "4" * 40, "script_raw_sha256": "sha256:" + "5" * 64},
        "cpu_environment_raw_sha256": "sha256:" + "6" * 64,
        "owner_environment_raw_sha256": "sha256:" + "7" * 64,
        "poll_interval_seconds": 60,
        "maximum_targets": 64,
        "maximum_sources": 1024,
    }


def test_schema_mirror_and_local_reference_closure_preserve_existing_families():
    raw = (ROOT / "schemas/workflow/local-indexing-owner-configuration-v1.schema.json").read_bytes()
    packaged = (
        ROOT
        / "packages/workflow/eom_workflow/resources"
        / "local-indexing-owner-configuration-v1.schema.json"
    ).read_bytes()
    assert raw == packaged and sha256_bytes(raw) == LOCAL_INDEXING_OWNER_SCHEMA_SHA256
    schema = local_indexing_owner_configuration_schema()
    assert schema["$id"] == LOCAL_INDEXING_OWNER_SCHEMA_REF
    Draft202012Validator.check_schema(schema)
    assert len(LOCAL_EMBEDDING_SCHEMA_RESOURCES) == 4
    assert len(LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES) == 2
    parsed = LocalIndexingOwnerConfiguration.model_validate(document())
    assert (
        parse_local_indexing_owner_configuration(local_indexing_owner_configuration_bytes(parsed))
        == parsed
    )
    assert not hasattr(parsed, "password") and not hasattr(parsed, "permissions")


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_targets", True),
        ("maximum_targets", 0),
        ("maximum_targets", 1025),
        ("poll_interval_seconds", True),
        ("poll_interval_seconds", 1),
        ("poll_interval_seconds", "60"),
        ("service_policy_revision_id", "latest"),
        ("service_policy_sha256", "0" * 64),
        ("source_classes", ["PAST_EXAM", "PAST_EXAM"]),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
        ("source_classes", ["TEXTBOOK"]),
        ("password", "not-a-real-secret"),
        ("operator_id", "operator_" + "a" * 32),
        ("roles", ["ADMIN"]),
    ],
)
def test_closed_selection_rejects_coercion_latest_or_authority(field, value):
    body = document() | {field: value}
    with pytest.raises(ValueError):
        LocalIndexingOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ["space", "recipe", "owner", "old_policy", "verifier_path"])
def test_exact_selection_does_not_infer_or_substitute(fault):
    body = document()
    if fault in {"space", "recipe"}:
        body["namespace"]["space_sha256" if fault == "space" else "recipe_sha256"] = (
            "sha256:" + "f" * 64
        )
    elif fault == "owner":
        body["database_owner"]["role_name"] = "eom_catalog_manager_runtime"
    elif fault == "old_policy":
        body["native_execution_policy"]["schema_ref"] = (
            "eom://schemas/workflow/local-embedding-execution-policy/1.0"
        )
    else:
        body["runtime_verifier"]["path"] = "/tmp/untrusted.py"
    with pytest.raises(ValueError):
        LocalIndexingOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ["root_extra", "nested_extra", "nested_bool"])
def test_copied_models_are_revalidated_before_lossy_serialization(fault):
    value = LocalIndexingOwnerConfiguration.model_validate(document())
    if fault == "root_extra":
        value = value.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "nested_extra":
        value = value.model_copy(
            update={
                "database_owner": value.database_owner.model_copy(update={"password": "hidden"})
            }
        )
    else:
        value = value.model_copy(
            update={"database_owner": value.database_owner.model_copy(update={"role_oid": True})}
        )
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        local_indexing_owner_configuration_bytes(value)


@pytest.mark.parametrize("fault", ["duplicate", "noncanonical", "nan", "large", "deep"])
def test_wire_failures_are_bounded_and_content_free(fault):
    raw = canonical_json_bytes(document())
    if fault == "duplicate":
        raw = raw[:-1] + b',"maximum_targets":64}'
    elif fault == "noncanonical":
        raw += b"\n"
    elif fault == "nan":
        raw = raw.replace(b'"maximum_targets":64', b'"maximum_targets":NaN')
    elif fault == "large":
        raw = b" " * (64 * 1024 + 1)
    else:
        raw = b"[" * 2000 + b"0" + b"]" * 2000
    with pytest.raises(LocalIndexingOwnerConfigurationError) as failure:
        parse_local_indexing_owner_configuration(raw)
    assert str(failure.value) == "LOCAL_INDEXING_OWNER_CONFIGURATION_INVALID"


def test_schema_returns_independent_values_not_mutable_cached_authority():
    original = copy.deepcopy(local_indexing_owner_configuration_schema())
    changed = local_indexing_owner_configuration_schema()
    changed["properties"].clear()
    assert local_indexing_owner_configuration_schema() == original

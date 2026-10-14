"""Exact non-secret configuration values; synthetic pins do not admit a runtime."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.similarity_reader_configuration import (
    MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
    SimilarityReaderConfiguration,
    parse_similarity_reader_configuration,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_reference_query_execution_contracts import case


def document():
    value = case()
    selection = value.request.context_request.views[0]
    return {
        "schema_version": "system-rag-similarity-reader-configuration/1.0",
        "corpus_id": "corpus_" + "a" * 32,
        "namespace": EmbeddingIndexNamespace(
            storage_partition=selection.index.storage_partition,
            space_sha256=value.policy.spaces.document.space_sha256,
            view=selection.view,
            recipe_sha256=selection.recipe.recipe_sha256,
            population_scope="OCCURRENCE_BACKED_PAST_EXAM",
        ).model_dump(mode="json"),
        "document_space": value.policy.spaces.document.model_dump(mode="json"),
        "recipe": selection.recipe.model_dump(mode="json"),
        "source_classes": ["APPROVED_ITEM", "PAST_EXAM"],
        "native_execution_policy": value.request.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": value.request.native_execution_policy_sha256,
        "runtime_bundle": value.request.runtime_bundle.model_dump(mode="json"),
        "database_owner": {"role_name": "synthetic_database_owner", "role_oid": 12345},
    }


def test_configuration_schema_resource_mirror_and_canonical_round_trip():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-reader-configuration"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-similarity-reader-configuration"))
    value = SimilarityReaderConfiguration.model_validate(document())
    assert parse_similarity_reader_configuration(canonical_json_bytes(value)) == value


@pytest.mark.parametrize(
    "field,value",
    (
        ("operator_id", "operator_" + "e" * 32),
        ("token", "synthetic-no-credential"),
        ("permissions", ["ADMIN"]),
        ("model_path", "/arbitrary"),
        ("queue", "new-queue"),
        ("source_classes", ["TEXTBOOK"]),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
    ),
)
def test_untrusted_authority_or_extra_configuration_is_rejected(field, value):
    body = document() | {field: value}
    with pytest.raises((ValueError, SchemaError)):
        SimilarityReaderConfiguration.model_validate(body)


@pytest.mark.parametrize(
    "fault",
    (
        "namespace_space",
        "namespace_recipe",
        "query_space",
        "policy_member",
        "policy_schema",
        "policy_media",
        "owner_runtime_role",
        "owner_bool_oid",
        "owner_zero_oid",
        "owner_extra",
    ),
)
def test_mismatched_namespace_controls_and_owner_values_are_rejected(fault):
    body = document()
    if fault.startswith("namespace_"):
        body["namespace"]["space_sha256" if fault.endswith("space") else "recipe_sha256"] = (
            "sha256:" + "f" * 64
        )
    elif fault == "query_space":
        body["document_space"]["purpose"] = "QUERY"
    elif fault.startswith("policy_"):
        key, value = {
            "policy_member": ("member_path", "other.json"),
            "policy_schema": (
                "schema_ref",
                "eom://schemas/workflow/local-embedding-execution-policy/1.0",
            ),
            "policy_media": ("media_type", "text/plain"),
        }[fault]
        body["native_execution_policy"][key] = value
    elif fault == "owner_runtime_role":
        body["database_owner"]["role_name"] = "eom_catalog_manager_runtime"
    elif fault == "owner_bool_oid":
        body["database_owner"]["role_oid"] = True
    elif fault == "owner_zero_oid":
        body["database_owner"]["role_oid"] = 0
    else:
        body["database_owner"]["permissions"] = ["ADMIN"]
    with pytest.raises((ValueError, SchemaError)):
        SimilarityReaderConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ("duplicate", "newline", "float", "oversize", "empty"))
def test_raw_configuration_bytes_are_bounded_canonical_and_unambiguous(fault):
    raw = canonical_json_bytes(document())
    if fault == "duplicate":
        raw = b'{"corpus_id":"hidden",' + raw[1:]
    elif fault == "newline":
        raw += b"\n"
    elif fault == "float":
        raw = raw.replace(b'"role_oid":12345', b'"role_oid":12345.0')
    elif fault == "oversize":
        raw = b" " * (MAX_SIMILARITY_READER_CONFIGURATION_BYTES + 1)
    else:
        raw = b""
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_reader_configuration(raw)


def test_constructed_nested_extras_cannot_be_removed_by_model_dump():
    value = SimilarityReaderConfiguration.model_validate(document())
    copied = copy.deepcopy(value.database_owner)
    copied.__dict__["authority"] = "ADMIN"
    with pytest.raises((ValueError, SchemaError)):
        SimilarityReaderConfiguration.model_validate(
            value.model_copy(update={"database_owner": copied})
        )

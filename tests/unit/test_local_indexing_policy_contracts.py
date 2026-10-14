"""Synthetic service-only policy metadata, not installed source permission."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.knowledge import EducationRetrievalAccessPolicy
from eom_catalog_contracts.local_indexing_policy import (
    LOCAL_INDEXING_ACCESS_POLICY_SCHEMA,
    MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES,
    LocalIndexingAccessPolicy,
    local_indexing_access_policy_bytes,
    parse_local_indexing_access_policy,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import local_indexing_service_reference
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.inference_transfer_embedding_fixtures import view_recipe as recipe
from tests.unit.test_embedding_registry_contracts import registration_command
from tests.unit.test_local_indexing_service_contracts import identity

ROOT = Path(__file__).resolve().parents[2]


def policy_document(**changes: object) -> dict[str, Any]:
    command = registration_command()
    values = dict(
        schema_version="education-retrieval-access-policy/1.1",
        access_policy_revision_id="accessrev_" + "e" * 32,
        source_access_policy_revision_id=command.policy_revision_id,
        source_access_policy_sha256=command.policy_sha256,
        state="RELEASED",
        purpose="LOCAL_EMBEDDING_INDEX",
        service=local_indexing_service_reference(identity()).model_dump(mode="json"),
        runtime_configuration_sha256="sha256:" + "3" * 64,
        corpus_id=command.corpus_id,
        graph_id=command.graph_snapshot.graph_id,
        source_classes=["PAST_EXAM"],
        namespaces=[command.namespace.model_dump(mode="json")],
        space=embedding_space().model_dump(mode="json"),
        recipe=recipe().model_dump(mode="json"),
        native_execution_policy_sha256="sha256:" + "4" * 64,
        resource_profile_sha256="sha256:" + "5" * 64,
        maximum_sources=1024,
        answer_bearing_use="ACCEPTED_SOLUTION_PROJECTION_ONLY",
        created_at="2026-10-14T00:00:00Z",
    )
    values.update(changes)
    values["content_sha256"] = content_sha256(values)
    return values


def test_closed_mirrored_registered_schema_and_canonical_round_trip() -> None:
    path = "knowledge/education-retrieval-access-policy-v1_1.schema.json"
    raw = (ROOT / "schemas" / path).read_bytes()
    assert (
        raw
        == (ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / path).read_bytes()
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "2ba2fc1fd906fef5a17acb3a7ba7d7e3351aa9a2e863a4386f0913b4bf7f7152"
    )
    assert load_schema(LOCAL_INDEXING_ACCESS_POLICY_SCHEMA) == json.loads(raw)
    values = policy_document()
    validate_contract(LOCAL_INDEXING_ACCESS_POLICY_SCHEMA, values)
    policy = LocalIndexingAccessPolicy.model_validate(values)
    assert local_indexing_access_policy_bytes(policy) == canonical_json_bytes(values)
    assert parse_local_indexing_access_policy(canonical_json_bytes(values)) == policy
    assert not hasattr(policy, "roles") and not hasattr(policy, "operator_id")
    with pytest.raises(ValueError):
        EducationRetrievalAccessPolicy.model_validate(values)
    with pytest.raises(SchemaError):
        validate_contract("education-retrieval-access-policy", values)
    # Version1.0 retains its original bytes/hash and cannot acquire service grants.
    assert (
        hashlib.sha256(
            (
                ROOT / "schemas/knowledge/education-retrieval-access-policy-v1.schema.json"
            ).read_bytes()
        ).hexdigest()
        == "83e7fd1dc6cc78e74f3b35556a1eaf3039745e9d52fce04e46ad254490219afe"
    )


@pytest.mark.parametrize(
    "field", ["token", "password", "roles", "operator_id", "path", "permissions"]
)
def test_no_credentials_or_fake_operator_authority(field: str) -> None:
    values = policy_document()
    values[field] = "MUST_NOT_BE_ECHOED"
    with pytest.raises(ValueError) as caught:
        LocalIndexingAccessPolicy.model_validate(values)
    assert "MUST_NOT_BE_ECHOED" not in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "ACTIVE"),
        ("purpose", "ITEM_AUTHORING"),
        ("maximum_sources", True),
        ("maximum_sources", 1025),
        ("maximum_sources", 0),
        ("source_classes", ["TEXTBOOK"]),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
        ("source_classes", ["PAST_EXAM", "PAST_EXAM"]),
        ("runtime_configuration_sha256", "latest"),
        ("graph_id", "graph_" + "A" * 32),
        ("answer_bearing_use", "UNRESTRICTED"),
        ("created_at", "2026-10-14T09:00:00+09:00"),
    ],
)
def test_schema_and_scope_reject_invalid_untrusted_policy(field: str, value: object) -> None:
    values = policy_document(**{field: value})
    with pytest.raises(ValueError):
        LocalIndexingAccessPolicy.model_validate(values)


@pytest.mark.parametrize(
    "fault",
    [
        "space",
        "recipe",
        "partition",
        "population",
        "duplicate_view",
        "unsorted_views",
        "occurrence_mixed",
    ],
)
def test_namespaces_are_one_exact_model_recipe_partition_population(fault: str) -> None:
    values = policy_document()
    first = values["namespaces"][0]
    second = {**first, "view": "METADATA_ONLY"}
    if fault in {"space", "recipe"}:
        first[fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        second["storage_partition"] = "another"
    elif fault == "population":
        second["population_scope"] = (
            "OCCURRENCE_BACKED_PAST_EXAM"
            if first["population_scope"] == "ALL_ADMITTED_GRAPH_ITEMS"
            else "ALL_ADMITTED_GRAPH_ITEMS"
        )
    elif fault == "duplicate_view":
        second["view"] = first["view"]
    elif fault == "unsorted_views":
        first["view"], second["view"] = "METADATA_ONLY", "CONTENT_ONLY"
    else:
        first["population_scope"] = second["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
        values["source_classes"] = ["APPROVED_ITEM", "PAST_EXAM"]
    values["namespaces"] = [first, second]
    values["content_sha256"] = content_sha256(
        {k: v for k, v in values.items() if k != "content_sha256"}
    )
    with pytest.raises(ValueError):
        LocalIndexingAccessPolicy.model_validate(values)


def test_hash_and_all_copied_nested_models_revalidate_before_field_dropping() -> None:
    values = policy_document()
    values["maximum_sources"] = 100
    with pytest.raises(ValueError):
        LocalIndexingAccessPolicy.model_validate(values)
    policy = LocalIndexingAccessPolicy.model_validate(policy_document())
    for forged in (
        policy.model_copy(update={"roles": ["ADMIN"]}),
        policy.model_copy(
            update={"service": policy.service.model_copy(update={"roles": ["ADMIN"]})}
        ),
        policy.model_copy(update={"space": policy.space.model_copy(update={"roles": ["ADMIN"]})}),
        policy.model_copy(
            update={"namespaces": (policy.namespaces[0].model_copy(update={"roles": ["ADMIN"]}),)}
        ),
        policy.model_copy(update={"recipe": policy.recipe.model_copy(update={"roles": ["ADMIN"]})}),
    ):
        with pytest.raises(ValueError):
            local_indexing_access_policy_bytes(forged)
    for field in type(policy).model_fields:
        missing = deepcopy(policy_document())
        del missing[field]
        with pytest.raises(ValueError):
            LocalIndexingAccessPolicy.model_validate(missing)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"null",
        b"[]",
        b"\xff",
        b'{"state":"a","state":"b"}',
        b'{"maximum_sources":NaN}',
        b'{"a":' * 1100 + b"{}" + b"}" * 1100,
        b"x" * (MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES + 1),
    ],
)
def test_wire_bounded_duplicate_free_nonfinite_and_canonical(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_local_indexing_access_policy(raw)

"""Pure registration contracts; no source authority, DB, model or NAS execution."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
    parse_embedding_registration_command,
    parse_embedding_registration_result,
    validate_embedding_registration_result,
)
from eom_catalog_contracts.embedding_registry import EMBEDDING_REGISTRY_SCHEMA
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.inference_transfer_embedding_fixtures import index_manifest, index_pointer, seal
from tests.unit.inference_transfer_fixtures import NOW, sha

ROOT = Path(__file__).resolve().parents[2]


def registration_command() -> RegisterEmbeddingIndexCommand:
    index = index_manifest()
    binding = index.bindings[0]
    return RegisterEmbeddingIndexCommand.model_validate(
        seal(
            {
                "schema_version": "embedding-registry-registration-command/1.0",
                "operation": "REGISTER_EMBEDDING_INDEX",
                "operation_key": "synthetic-index-registration:first",
                "corpus_id": "corpus_" + "a" * 32,
                "namespace": {
                    "storage_partition": index.storage_partition,
                    "space_sha256": index.space.space_sha256,
                    "view": index.view,
                    "recipe_sha256": index.recipe.recipe_sha256,
                    "projection_version": binding.projection_version,
                    "population_scope": "ALL_ADMITTED_GRAPH_ITEMS",
                },
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": index_pointer(index).model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "graph_snapshot": binding.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": binding.policy_revision_id,
                "policy_sha256": binding.policy_sha256,
                "expected_current_index_revision_id": None,
                "expected_lock_version": 1,
                "source_set_sha256": sha("e"),
                "binding_set_sha256": content_sha256([binding.binding_sha256]),
                "eligible_source_count": 1,
                "binding_count": 1,
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "request_sha256",
        )
    )


def registration_result() -> EmbeddingIndexRegistrationResult:
    command = registration_command()
    return EmbeddingIndexRegistrationResult.model_validate(
        seal(
            {
                "schema_version": "embedding-registry-registration-result/1.0",
                "operation_key": command.operation_key,
                "request_sha256": command.request_sha256,
                "index_id": command.index_id,
                "index_revision_id": command.index_revision_id,
                "previous_index_revision_id": None,
                "index_manifest": command.index_manifest.model_dump(mode="json"),
                "index_sha256": command.index_sha256,
                "registered_lock_version": 2,
                "current_index_revision_id": command.index_revision_id,
                "current_lock_version": 2,
                "replayed": False,
                "is_current": True,
                "registered_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "result_sha256",
        )
    )


def test_schema_mirror_hash_draft_and_released_embedding_bytes() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_REGISTRY_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    Draft202012Validator.check_schema(load_schema(EMBEDDING_REGISTRY_SCHEMA))
    predecessor = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-embedding"]
    assert predecessor.sha256 == (
        "sha256:36495b830932ac0f7afdaca7a0909652c61dc16a13d01488651cf84978d83b52"
    )
    assert sha256_bytes((ROOT / predecessor.canonical_path).read_bytes()) == predecessor.sha256


@pytest.mark.parametrize(
    "factory,parser",
    [
        (registration_command, parse_embedding_registration_command),
        (registration_result, parse_embedding_registration_result),
    ],
)
def test_closed_frozen_roundtrip_and_canonical_hash(factory: Any, parser: Any) -> None:
    value = factory()
    document = value.model_dump(mode="json")
    before = copy.deepcopy(document)
    assert parser(document) == value
    assert document == before
    assert canonical_json_bytes(document) == canonical_json_bytes(
        parser(document).model_dump(mode="json")
    )
    with pytest.raises(ValidationError):
        value.operation_key = "changed"
    document["requester_role"] = "ADMIN"
    with pytest.raises((SchemaError, ValueError)):
        parser(document)


@pytest.mark.parametrize(
    "path,value",
    [
        (("expected_lock_version",), True),
        (("expected_lock_version",), 1.0),
        (("expected_lock_version",), 2),
        (("eligible_source_count",), 1025),
        (("binding_count",), 0),
        (("binding_count",), 2),
        (("index_manifest", "member_path"), "../index.json"),
        (("index_manifest", "schema_ref"), "eom://schemas/knowledge/embedding-index-manifest/1.1"),
        (("index_manifest", "media_type"), "application/octet-stream"),
        (("namespace", "population_scope"), "ALL_FILES"),
        (("graph_snapshot", "manifest_sha256"), sha("0")),
        (("requested_at",), "2026-10-12T09:00:00+09:00"),
    ],
)
def test_registration_negative_pins(path: tuple[str, ...], value: object) -> None:
    body = registration_command().model_dump(mode="json")
    target = body
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises((SchemaError, ValueError, TypeError)):
        parse_embedding_registration_command(seal(body, "request_sha256"))


def test_hash_mismatch_and_nested_model_copy_are_revalidated() -> None:
    command = registration_command()
    body = command.model_dump(mode="json")
    body["request_sha256"] = sha("0")
    with pytest.raises(ValueError):
        parse_embedding_registration_command(body)
    forged = command.model_copy(
        update={"namespace": command.namespace.model_copy(update={"population_scope": "ADMIN"})}
    )
    with pytest.raises(ValueError):
        RegisterEmbeddingIndexCommand.model_validate(forged)


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_current", False),
        ("is_current", 1),
        ("replayed", 0),
        ("current_lock_version", 1),
        ("current_lock_version", 3),
        ("previous_index_revision_id", "embeddingindexrev_" + "2" * 32),
    ],
)
def test_receipt_current_selection_and_strict_flags(field: str, value: object) -> None:
    body = registration_result().model_dump(mode="json")
    body[field] = value
    with pytest.raises((SchemaError, ValueError)):
        parse_embedding_registration_result(seal(body, "result_sha256"))


def test_historical_replay_receipt_does_not_claim_current() -> None:
    body = registration_result().model_dump(mode="json")
    body.update(
        replayed=True,
        is_current=False,
        current_lock_version=3,
        current_index_revision_id="embeddingindexrev_" + "f" * 32,
    )
    receipt = parse_embedding_registration_result(seal(body, "result_sha256"))
    assert receipt.replayed and not receipt.is_current
    assert validate_embedding_registration_result(registration_command(), receipt) == receipt


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_key", "another-registration"),
        ("request_sha256", sha("f")),
        ("index_id", "embeddingindex_" + "f" * 32),
        ("index_revision_id", "embeddingindexrev_" + "f" * 32),
        ("index_sha256", sha("f")),
        ("previous_index_revision_id", "embeddingindexrev_" + "f" * 32),
        ("registered_lock_version", 3),
    ],
)
def test_receipt_command_closure_rejects_resealed_foreign_request(
    field: str, value: object
) -> None:
    body = registration_result().model_dump(mode="json")
    body[field] = value
    if field == "index_revision_id":
        body["current_index_revision_id"] = value
    if field == "registered_lock_version":
        body["current_lock_version"] = value
    result = parse_embedding_registration_result(seal(body, "result_sha256"))
    with pytest.raises(ValueError, match="exact command"):
        validate_embedding_registration_result(registration_command(), result)


def test_receipt_resealed_wrong_member_and_equal_generation_stale_replay() -> None:
    body = registration_result().model_dump(mode="json")
    body["index_manifest"]["sha256"] = sha("f")
    result = parse_embedding_registration_result(seal(body, "result_sha256"))
    with pytest.raises(ValueError, match="exact command"):
        validate_embedding_registration_result(registration_command(), result)
    body = registration_result().model_dump(mode="json")
    body.update(
        replayed=True, is_current=False, current_index_revision_id="embeddingindexrev_" + "f" * 32
    )
    with pytest.raises(ValueError, match="newer head"):
        parse_embedding_registration_result(seal(body, "result_sha256"))
    assert (
        validate_embedding_registration_result(registration_command(), registration_result())
        == registration_result()
    )


def test_contract_module_has_no_infrastructure_or_runtime_source_dependency() -> None:
    path = ROOT / "packages/catalog_contracts/eom_catalog_contracts/embedding_registry.py"
    tree = ast.parse(path.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name.startswith(("eom_catalog_service", "eom_orchestrator", "sqlalchemy", "torch"))
        for name in imports
    )
    assert "subprocess" not in path.read_text()
    command = registration_command().model_dump(mode="json")
    validate_contract(EMBEDDING_REGISTRY_SCHEMA, command)
    assert not {"requester_role", "authority", "permissions", "text", "vectors"} & command.keys()

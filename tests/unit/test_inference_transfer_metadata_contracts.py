"""Schema-first metadata closure and identity checks; no source authorization is implied."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_metadata import (
    InferenceTransferMetadataBindingReply,
    InferenceTransferMetadataBindingRequest,
    InferenceTransferMetadataResolveResult,
    parse_metadata_binding_reply,
    parse_metadata_binding_request,
    parse_metadata_request,
    parse_metadata_result,
    validate_metadata_binding_reply,
    validate_metadata_result,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_metadata_fixtures import ACTOR, metadata_request, metadata_result
from tests.unit.inference_transfer_snapshot_fixtures import hashed


def test_schema_registry_mirror_hash_and_pure_layer() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-metadata"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("item-inference-transfer-metadata"))
    tree = ast.parse(
        (
            root / "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_metadata.py"
        ).read_text()
    )
    assert not any(
        isinstance(n, ast.ImportFrom)
        and n.module
        and n.module.startswith(
            ("eom_catalog_service", "eom_api", "sqlalchemy", "eom_orchestrator")
        )
        for n in ast.walk(tree)
    )


def test_exact_roundtrip_distinguishes_semantic_and_manifest_hashes() -> None:
    request, result = metadata_request(), metadata_result()
    assert result.snapshot_sha256 != result.graph_snapshot.manifest_sha256
    assert parse_metadata_request(request.model_dump(mode="json")) == request
    assert parse_metadata_result(result.model_dump(mode="json")) == result
    validate_metadata_result(request, result)
    binding = InferenceTransferMetadataBindingRequest(actor_id=ACTOR, request=request)
    reply = InferenceTransferMetadataBindingReply(
        status="SUCCESS",
        actor_id=ACTOR,
        request_sha256=request.request_sha256,
        result=result,
        error_code=None,
    )
    assert parse_metadata_binding_request(binding.model_dump(mode="json")) == binding
    validate_metadata_binding_reply(binding, reply)


@pytest.mark.parametrize(
    "field", ["actor_id", "role", "permissions", "preset_id", "path", "latest"]
)
def test_public_authority_and_latest_fields_are_absent(field: str) -> None:
    with pytest.raises(SchemaError):
        parse_metadata_request(metadata_request().model_dump(mode="json") | {field: ACTOR})


@pytest.mark.parametrize(
    "classes", [("PAST_EXAM", "APPROVED_ITEM"), ("PAST_EXAM", "PAST_EXAM"), (), ("TEXTBOOK",)]
)
def test_sorted_closed_unique_classes(classes) -> None:
    with pytest.raises(ValidationError):
        metadata_request(source_classes=classes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_sha256", sha("2")),
        ("snapshot_sha256", sha("2")),
        ("access_policy_revision_id", "accessrev_" + "2" * 32),
        ("access_policy_sha256", sha("2")),
        ("source_classes", ("APPROVED_ITEM",)),
    ],
)
def test_valid_hash_foreign_pins_cannot_replace_request(field, value) -> None:
    result = hashed(
        InferenceTransferMetadataResolveResult,
        "result_sha256",
        **(metadata_result().model_dump(mode="json", exclude={"result_sha256"}) | {field: value}),
    )
    with pytest.raises(ValueError, match="exact pinned"):
        validate_metadata_result(metadata_request(), result)


def test_model_copy_stale_hash_is_revalidated_before_use() -> None:
    with pytest.raises(ValueError):
        validate_metadata_result(
            metadata_request().model_copy(update={"expected_snapshot_sha256": sha("3")}),
            metadata_result(),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("media_type", "image/png"),
        ("schema_ref", "eom://schemas/knowledge/knowledge-analysis-result/10.0"),
        ("member_path", "source/manifest.json"),
        ("logical_name", "other.json"),
        ("sha256", sha("1")),
    ],
)
def test_manifest_member_contract_is_not_arbitrary(field, value) -> None:
    body = metadata_result().model_dump(mode="json", exclude={"result_sha256"})
    body["graph_snapshot"]["manifest_artifact"][field] = value
    with pytest.raises(ValidationError):
        hashed(InferenceTransferMetadataResolveResult, "result_sha256", **body)


def test_private_reply_malformed_failure_has_no_invented_actor_but_cannot_match_valid_request() -> (
    None
):
    reply = InferenceTransferMetadataBindingReply(
        status="FAILED",
        actor_id=None,
        request_sha256=None,
        result=None,
        error_code="INFERENCE_TRANSFER_METADATA_REQUEST_INVALID",
    )
    assert parse_metadata_binding_reply(reply.model_dump(mode="json")) == reply
    with pytest.raises(ValueError, match="principal"):
        validate_metadata_binding_reply(
            InferenceTransferMetadataBindingRequest(actor_id=ACTOR, request=metadata_request()),
            reply,
        )


def test_private_reply_foreign_principal_cannot_be_replayed() -> None:
    request = metadata_request()
    reply = InferenceTransferMetadataBindingReply(
        status="SUCCESS",
        actor_id="operator_" + "2" * 32,
        request_sha256=request.request_sha256,
        result=metadata_result(),
        error_code=None,
    )
    with pytest.raises(ValueError, match="principal"):
        validate_metadata_binding_reply(
            InferenceTransferMetadataBindingRequest(actor_id=ACTOR, request=request), reply
        )

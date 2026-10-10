"""Pure bootstrap contract tests; no publisher, DB, Codex invocation or release."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.control_schemas import (
    CONTROL_SCHEMA_RESOURCES,
    load_control_schema,
    validate_control_contract,
)
from eom_workflow.inference_transfer_bootstrap_contract import (
    InferenceTransferBootstrapManifest,
    InferenceTransferReviewedInstructionMember,
    validate_inference_transfer_bootstrap_manifest,
    validate_inference_transfer_reviewed_instruction,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_bootstrap_fixtures import (
    PLATFORM_BYTES,
    RUBRIC_BYTES,
    bootstrap_manifest,
)


def rehash(body: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in body.items() if key != "manifest_sha256"}
    return body | {"manifest_sha256": content_sha256(body)}


def test_schema_first_resource_mirror_hash_and_202012_are_exact() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CONTROL_SCHEMA_RESOURCES["inference-transfer-control-bootstrap"]
    canonical = (root / entry.canonical_path).read_bytes()
    resource = (root / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
    assert canonical == resource
    assert sha256_bytes(canonical) == entry.sha256
    schema = load_control_schema("inference-transfer-control-bootstrap")
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "eom://schemas/workflow/inference-transfer-control-bootstrap/1.0"


def test_manifest_and_raw_reviewed_markdown_round_trip() -> None:
    manifest = bootstrap_manifest()
    assert (
        validate_inference_transfer_bootstrap_manifest(manifest.model_dump(mode="json")) == manifest
    )
    validate_inference_transfer_reviewed_instruction(
        manifest, layer="PLATFORM", payload=PLATFORM_BYTES
    )
    validate_inference_transfer_reviewed_instruction(manifest, layer="ROLE", payload=RUBRIC_BYTES)
    assert manifest.rubric.rubric_sha256 == manifest.rubric_instruction.sha256
    assert manifest.capacity.capacity_policy_revision_id != manifest.capacity.capacity_policy_id
    assert not hasattr(manifest.capacity, "artifact_id")
    assert not hasattr(manifest.rubric_instruction, "artifact_id")


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_definition_key", "customer-support"),
        ("workflow_definition_version", "2.0.0"),
        ("workflow_role_schema_version", "workflow-role/1.28.0"),
        ("result_schema", "support-result@1.0"),
        ("schema_version", "customer-support-control-bootstrap/1.0"),
    ],
)
def test_other_purpose_protocol_and_result_cannot_consume_this_manifest(
    field: str, value: str
) -> None:
    body = rehash(bootstrap_manifest().model_dump(mode="json") | {field: value})
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(body)
    with pytest.raises(ValidationError):
        InferenceTransferBootstrapManifest.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("auth_binding_id", "authbinding_" + "0" * 32),
        ("token", "synthetic-not-a-token"),
        ("availability", "READY"),
        ("quality_score_permille", 1000),
        ("release_approved", True),
        ("activate", True),
        ("slot_key", "slot07"),
        ("actor_role", "ADMIN"),
        ("content_pack", "fake-pack"),
    ],
)
def test_closed_manifest_is_not_authority_observation_or_fake_pack(field: str, value: Any) -> None:
    body = rehash(bootstrap_manifest().model_dump(mode="json") | {field: value})
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(body)
    with pytest.raises(ValidationError):
        InferenceTransferBootstrapManifest.model_validate(body)


@pytest.mark.parametrize(
    "path",
    [
        "transfer-rubric.md",
        "instructions/../transfer-rubric.md",
        "/mnt/nas/transfer-rubric.md",
        "references/transfer-rubric.md",
    ],
)
def test_reviewed_rubric_exact_relative_and_logical_member_names(path: str) -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["rubric_instruction"]["relative_path"] = path
    body["rubric_instruction"]["logical_name"] = path
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(rehash(body))
    with pytest.raises(ValidationError):
        InferenceTransferBootstrapManifest.model_validate(rehash(body))


@pytest.mark.parametrize(
    "field,value",
    [
        ("layer", "PLATFORM"),
        ("media_type", "application/json"),
        ("schema_ref", "eom://schemas/workflow/customer-support/1.0"),
        ("logical_name", "instructions/platform.md"),
    ],
)
def test_member_layer_media_schema_and_logical_name_do_not_fall_back(
    field: str, value: str
) -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["rubric_instruction"][field] = value
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(rehash(body))
    with pytest.raises(ValidationError):
        InferenceTransferBootstrapManifest.model_validate(rehash(body))


def test_reviewed_logical_rubric_hash_is_independent_but_equal_to_raw_member_hash() -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["rubric"]["rubric_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="logical revision"):
        InferenceTransferBootstrapManifest.model_validate(rehash(body))
    manifest = bootstrap_manifest()
    changed = manifest.model_dump(mode="json")
    changed["rubric"]["rubric_revision_id"] = "transferrubricrev_" + "0" * 32
    changed = rehash(changed)
    assert (
        InferenceTransferBootstrapManifest.model_validate(changed).manifest_sha256
        != manifest.manifest_sha256
    )


@pytest.mark.parametrize("field", ["source_commit", "source_tree"])
def test_reviewed_source_revisions_are_exact_not_latest_or_short_hashes(field: str) -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["source"][field] = "main"
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(rehash(body))


@pytest.mark.parametrize("reviewed_at", ["2026-10-10T18:00:00+09:00", "2026-10-10T09:00:00"])
def test_review_timestamp_is_utc_not_naive_or_user_display_zone(reviewed_at: str) -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["source"]["reviewed_at"] = reviewed_at
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(rehash(body))
    with pytest.raises(ValidationError):
        InferenceTransferBootstrapManifest.model_validate(rehash(body))


@pytest.mark.parametrize(
    "field,value",
    [
        ("capacity_policy_revision_id", "latest"),
        ("capacity_policy_id", "capacityrev_" + "0" * 32),
        ("schema_version", "worker-capacity-policy/9.0"),
        ("artifact_id", "artifact_" + "0" * 32),
    ],
)
def test_capacity_is_native_exact_pin_not_fabricated_artifact(field: str, value: str) -> None:
    body = bootstrap_manifest().model_dump(mode="json")
    body["capacity"][field] = value
    with pytest.raises(SchemaValidationError):
        validate_inference_transfer_bootstrap_manifest(rehash(body))


@pytest.mark.parametrize(
    "model,effort",
    [
        ("future-compatible-candidate", "high"),
        ("another-reviewed-model", "low"),
    ],
)
def test_model_candidate_is_data_not_a_historical_model_literal(model: str, effort: str) -> None:
    manifest = bootstrap_manifest(model_candidate={"model": model, "reasoning_effort": effort})
    validate_control_contract(
        "inference-transfer-control-bootstrap", manifest.model_dump(mode="json")
    )
    assert manifest.model_candidate.model == model
    assert manifest.model_candidate.reasoning_effort == effort


@pytest.mark.parametrize("timeout", [29, 901, True])
def test_timeout_is_bounded_and_strict_not_a_bool(timeout: Any) -> None:
    with pytest.raises(ValidationError):
        bootstrap_manifest(timeout_seconds=timeout)


def test_model_copy_and_manifest_sha_cannot_bypass_reviewed_input_closure() -> None:
    manifest = bootstrap_manifest()
    body = manifest.model_dump(mode="json")
    body["model_candidate"]["model"] = "changed-unreviewed-candidate"
    with pytest.raises(ValidationError, match="manifest hash"):
        InferenceTransferBootstrapManifest.model_validate(body)
    forged = manifest.model_copy(update={"manifest_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValidationError, match="manifest hash"):
        validate_inference_transfer_reviewed_instruction(forged, layer="ROLE", payload=RUBRIC_BYTES)


@pytest.mark.parametrize(
    "layer,payload",
    [
        ("PLATFORM", PLATFORM_BYTES + b"\n"),
        ("ROLE", RUBRIC_BYTES[:-1]),
        ("ROLE", PLATFORM_BYTES),
    ],
)
def test_raw_reviewed_markdown_bytes_cannot_be_trimmed_or_substituted(
    layer: Any, payload: bytes
) -> None:
    with pytest.raises(ValueError, match="reviewed"):
        validate_inference_transfer_reviewed_instruction(
            bootstrap_manifest(), layer=layer, payload=payload
        )


def test_payload_sha_is_raw_byte_hash_not_canonical_json_string_hash() -> None:
    manifest = bootstrap_manifest()
    changed = manifest.model_dump(mode="json")
    changed["rubric_instruction"]["sha256"] = content_sha256(RUBRIC_BYTES.decode())
    changed["rubric"]["rubric_sha256"] = changed["rubric_instruction"]["sha256"]
    manifest = InferenceTransferBootstrapManifest.model_validate(rehash(changed))
    with pytest.raises(ValueError, match="reviewed SHA"):
        validate_inference_transfer_reviewed_instruction(
            manifest, layer="ROLE", payload=RUBRIC_BYTES
        )


def test_reviewed_invalid_utf8_is_not_published_as_markdown() -> None:
    changed = bootstrap_manifest().model_dump(mode="json")
    payload = b"\xff\xfe"
    changed["rubric_instruction"].update(sha256=sha256_bytes(payload), size_bytes=len(payload))
    changed["rubric"]["rubric_sha256"] = sha256_bytes(payload)
    manifest = InferenceTransferBootstrapManifest.model_validate(rehash(changed))
    with pytest.raises(ValueError, match="UTF-8"):
        validate_inference_transfer_reviewed_instruction(manifest, layer="ROLE", payload=payload)


def test_reviewed_instruction_byte_bound_and_no_fake_artifact_identity() -> None:
    body = bootstrap_manifest().rubric_instruction.model_dump(mode="json")
    for value in (0, 262145, True):
        with pytest.raises(ValidationError):
            InferenceTransferReviewedInstructionMember.model_validate(body | {"size_bytes": value})
    with pytest.raises(ValidationError):
        InferenceTransferReviewedInstructionMember.model_validate(
            body | {"artifact_revision_id": "rev_" + "0" * 32}
        )


def test_contract_has_no_runtime_git_database_publisher_or_cli_dependency() -> None:
    import eom_workflow.inference_transfer_bootstrap_contract as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        name.split(".")[0]
        in {
            "sqlalchemy",
            "subprocess",
            "pathlib",
            "socket",
            "eom_orchestrator",
            "eom_catalog_service",
            "yaml",
            "requests",
            "transformers",
            "torch",
        }
        for name in imports
    )

"""Synthetic runtime-bundle closure only; no storage, model imports or device execution."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Literal

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import (
    NUMERICAL_RUNTIME_SCHEMA_REF,
    RUNTIME_BUNDLE_SCHEMA,
    RUNTIME_BUNDLE_SCHEMA_REF,
    EmbeddingNumericalDevice,
    EmbeddingNumericalRecipe,
    EmbeddingNumericalRuntimeDescriptor,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    embedding_payload_file_set_sha256,
    embedding_runtime_bundle_bytes,
    parse_embedding_numerical_runtime,
    parse_embedding_runtime_bundle,
    validate_embedding_payload_manifest,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    catalog_schema_registry,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ValidationError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import embedding_model, sha

ROOT = Path(__file__).resolve().parents[2]
Device = Literal["CPU", "CUDA"]


def _payload() -> LocalEmbeddingModelSpec:
    body = embedding_model("intfloat/multilingual-e5-small").model_dump(mode="json")
    versions = {
        "torch": "2.7.1+cpu",
        "transformers": "4.56.2",
        "safetensors": "0.6.2",
        "tokenizers": "0.22.2",
    }
    body["runtime_versions"] = [
        {"name": name, "version": version} for name, version in sorted(versions.items())
    ]
    return LocalEmbeddingModelSpec.model_validate(seal(body, "manifest_sha256"))


def _runtime(device: Device = "CUDA") -> EmbeddingNumericalRuntimeDescriptor:
    versions = {pin.name: pin.version for pin in _payload().runtime_versions}
    if device == "CUDA":
        versions["torch"] = "2.7.1+cu128"
    recipe = EmbeddingNumericalRecipe(
        cublas_workspace=":4096:8" if device == "CUDA" else None, batch_size=4, threads=4
    )
    value = {
        "schema_version": "embedding-numerical-runtime/1.0",
        "python_version": "3.12.13",
        "implementations": [
            {"component": component, "recipe_version": "synthetic/1.0", "sha256": sha("c")}
            for component in ("FLOAT32_CODEC", "HOST_L2", "OFFLINE_ENCODER")
        ],
        "libraries": [
            {"name": name, "version": version, "distribution_sha256": sha("d")}
            for name, version in sorted(versions.items())
        ],
        "device": {
            "kind": device,
            "platform": "LINUX_X86_64",
            "hardware_model": "synthetic-cuda" if device == "CUDA" else "synthetic-cpu",
            "compute_capability": [12, 0] if device == "CUDA" else None,
            "driver_version": "580.126.09" if device == "CUDA" else None,
        },
        "recipe": recipe.model_dump(mode="json"),
        "torch_build_cuda_version": "12.8" if device == "CUDA" else None,
    }
    return EmbeddingNumericalRuntimeDescriptor.model_validate(seal(value, "runtime_sha256"))


def _bundle(device: Device = "CUDA") -> EmbeddingRuntimeBundle:
    payload, runtime = _payload(), _runtime(device)
    execution = payload.model_dump(mode="json")
    execution["model_revision_id"] = "embeddingmodelrev_" + "e" * 32
    versions = {pin.name: pin.version for pin in runtime.libraries}
    execution["runtime_versions"] = [
        {"name": pin.name, "version": versions[pin.name]} for pin in payload.runtime_versions
    ]
    body = {
        "schema_version": "embedding-runtime-bundle/1.0",
        "bundle_id": "embeddingbundle_" + "1" * 32,
        "bundle_revision_id": "embeddingbundlerev_" + "2" * 32,
        "payload_pointer": {
            "model_id": payload.model_id,
            "model_revision_id": payload.model_revision_id,
            "schema_ref": "eom://schemas/knowledge/item-inference-transfer/1.0#/$defs/localEmbeddingModel",
            "manifest_sha256": payload.manifest_sha256,
            "manifest_raw_sha256": sha256_bytes(
                canonical_json_bytes(payload.model_dump(mode="json"))
            ),
            "file_set_sha256": embedding_payload_file_set_sha256(payload),
        },
        "payload_model_spec": payload.model_dump(mode="json"),
        "execution_model_spec": seal(execution, "manifest_sha256"),
        "numerical_runtime": runtime.model_dump(mode="json"),
    }
    return EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))


def _pointer(bundle: EmbeddingRuntimeBundle) -> EmbeddingRuntimeBundlePointer:
    raw_hash = sha256_bytes(embedding_runtime_bundle_bytes(bundle))
    member = ArtifactMemberPointer(
        artifact_id="artifact_" + "3" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path="bundle.json",
        schema_ref=RUNTIME_BUNDLE_SCHEMA_REF,
        media_type="application/json",
        sha256=raw_hash,
    )
    return EmbeddingRuntimeBundlePointer(
        bundle_id=bundle.bundle_id,
        bundle_revision_id=bundle.bundle_revision_id,
        bundle_sha256=bundle.bundle_sha256,
        bundle_raw_sha256=raw_hash,
        manifest_member=member,
    )


def test_schema_package_mirror_registration_and_nested_uri_are_exact() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[RUNTIME_BUNDLE_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    schema = load_schema(RUNTIME_BUNDLE_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    assert (
        catalog_schema_registry().resolver().lookup(NUMERICAL_RUNTIME_SCHEMA_REF).contents["$id"]
        == NUMERICAL_RUNTIME_SCHEMA_REF
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_bundle_and_descriptor_roundtrip_are_frozen_and_metadata_only(device: Device) -> None:
    bundle = _bundle(device)
    body = bundle.model_dump(mode="json")
    before = copy.deepcopy(body)
    assert parse_embedding_runtime_bundle(body) == bundle
    assert parse_embedding_numerical_runtime(body["numerical_runtime"]) == bundle.numerical_runtime
    assert body == before
    with pytest.raises(ValidationError):
        bundle.bundle_revision_id = "altered"
    assert len(embedding_runtime_bundle_bytes(bundle)) < 64 * 1024
    assert not any(isinstance(value, bytes) for value in body.values())


def test_flat_execution_spec_can_fit_unchanged_space_without_claiming_adapter_support() -> None:
    bundle = _bundle()
    value = {
        "model_spec": bundle.execution_model_spec.model_dump(mode="json"),
        "purpose": "DOCUMENT",
        "runtime": {
            "device": "CUDA",
            "precision": "FLOAT32",
            "tf32_enabled": False,
            "execution_runtime_sha256": bundle.numerical_runtime.runtime_sha256,
        },
    }
    space = EmbeddingSpace.model_validate(seal(value, "space_sha256"))
    assert space.model_spec == bundle.execution_model_spec
    assert space.model_spec != bundle.payload_model_spec
    # This structural closure is deliberately not an installed resolver or CUDA capability check.


def test_semantic_raw_member_and_model_hashes_remain_separate() -> None:
    bundle = _bundle()
    raw = embedding_runtime_bundle_bytes(bundle)
    pointer = _pointer(bundle)
    assert pointer.bundle_sha256 != pointer.bundle_raw_sha256
    assert pointer.manifest_member.sha256 == pointer.bundle_raw_sha256
    assert bundle.payload_model_spec.manifest_sha256 != bundle.execution_model_spec.manifest_sha256
    validate_contract(RUNTIME_BUNDLE_SCHEMA, pointer.model_dump(mode="json"))
    validate_embedding_runtime_bundle_pointer(bundle, pointer, raw)
    validate_embedding_payload_manifest(
        bundle, canonical_json_bytes(bundle.payload_model_spec.model_dump(mode="json"))
    )


@pytest.mark.parametrize(
    "field", ["model_id", "model_revision_id", "manifest_sha256", "file_set_sha256"]
)
def test_mismatched_payload_pointer_fails_after_resealing(field: str) -> None:
    body = _bundle().model_dump(mode="json")
    body["payload_pointer"][field] = (
        "embeddingmodel_" + "f" * 32
        if field == "model_id"
        else "embeddingmodelrev_" + "f" * 32
        if field == "model_revision_id"
        else sha("f")
    )
    with pytest.raises(ValueError, match="payload pointer"):
        EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_id", "embeddingmodel_" + "f" * 32),
        ("upstream_revision", "f" * 40),
        ("maximum_tokens", 256),
        ("dimension", 1024),
        ("query_prefix", ""),
        ("normalization", "NONE"),
        ("truncation", "TRUNCATE"),
    ],
)
def test_execution_successor_cannot_change_any_payload_or_recipe(field: str, value: object) -> None:
    body = _bundle().model_dump(mode="json")
    body["execution_model_spec"][field] = value
    body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
    with pytest.raises(ValueError):
        EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))


@pytest.mark.parametrize("member_path", ["model.safetensors", "tokenizer.json"])
@pytest.mark.parametrize("field,value", [("sha256", sha("f")), ("size_bytes", 2)])
def test_execution_successor_cannot_change_weight_or_tokenizer_member(
    member_path: str, field: str, value: object
) -> None:
    body = _bundle().model_dump(mode="json")
    member = next(
        member
        for member in body["execution_model_spec"]["files"]
        if member["member_path"] == member_path
    )
    member[field] = value
    body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
    with pytest.raises(ValueError, match="canonical payload"):
        EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))


def test_same_execution_revision_and_drifted_runtime_library_fail() -> None:
    body = _bundle().model_dump(mode="json")
    body["execution_model_spec"]["model_revision_id"] = body["payload_model_spec"][
        "model_revision_id"
    ]
    body["execution_model_spec"] = seal(body["execution_model_spec"], "manifest_sha256")
    with pytest.raises(ValueError, match="distinct immutable revision"):
        EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    body = _bundle().model_dump(mode="json")
    body["numerical_runtime"]["libraries"][0]["version"] = "9.9.9"
    body["numerical_runtime"] = seal(body["numerical_runtime"], "runtime_sha256")
    with pytest.raises(ValueError, match="library pins differ"):
        EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))


@pytest.mark.parametrize("section", ["libraries", "implementations"])
def test_duplicate_missing_or_unordered_numeric_pins_fail(section: str) -> None:
    body = _runtime().model_dump(mode="json")
    for values in (
        body[section][::-1],
        body[section][:-1],
        [body[section][0]] * len(body[section]),
    ):
        changed = body | {section: values}
        with pytest.raises(ValueError):
            EmbeddingNumericalRuntimeDescriptor.model_validate(seal(changed, "runtime_sha256"))


@pytest.mark.parametrize("value", [True, 0, 1.0, "4"])
def test_batch_thread_and_capability_integers_are_not_coerced(value: object) -> None:
    for field in ("batch_size", "threads"):
        body = _runtime().model_dump(mode="json")
        body["recipe"][field] = value
        with pytest.raises(ValueError):
            EmbeddingNumericalRecipe.model_validate(body["recipe"])
    body = _runtime().device.model_dump(mode="json")
    body["compute_capability"] = [value, 0]
    with pytest.raises(ValueError):
        EmbeddingNumericalDevice.model_validate(body)


@pytest.mark.parametrize(
    "field", ["matmul_tf32", "cudnn_tf32", "autocast", "compile", "attention", "precision"]
)
def test_fast_precision_or_execution_tricks_fail_in_schema_and_model(field: str) -> None:
    body = _runtime().model_dump(mode="json")
    body["recipe"][field] = "ENABLED"
    with pytest.raises((JsonSchemaError, ValueError)):
        parse_embedding_numerical_runtime(seal(body, "runtime_sha256"))


def test_cpu_cuda_conditional_device_build_and_workspace_closure() -> None:
    for field in ("compute_capability", "driver_version"):
        body = _runtime().device.model_dump(mode="json")
        body[field] = None
        with pytest.raises(ValueError):
            EmbeddingNumericalDevice.model_validate(body)
    body = _runtime("CPU").device.model_dump(mode="json") | {"driver_version": "580.126.09"}
    with pytest.raises(ValueError):
        EmbeddingNumericalDevice.model_validate(body)
    for field in ("torch_build_cuda_version", "cublas_workspace"):
        body = _runtime().model_dump(mode="json")
        if field == "cublas_workspace":
            body["recipe"][field] = None
        else:
            body[field] = None
        with pytest.raises(ValueError):
            EmbeddingNumericalRuntimeDescriptor.model_validate(seal(body, "runtime_sha256"))


@pytest.mark.parametrize(
    "field",
    [
        "source_git_commit",
        "platform_release_sha256",
        "filesystem_path",
        "actor_role",
        "gpu_lease_token",
    ],
)
def test_unrelated_release_paths_and_authority_are_not_descriptor_fields(field: str) -> None:
    body = _runtime().model_dump(mode="json") | {field: "untrusted"}
    with pytest.raises((JsonSchemaError, ValueError)):
        parse_embedding_numerical_runtime(seal(body, "runtime_sha256"))


def test_relevant_numeric_changes_affect_fingerprint_but_external_release_is_absent() -> None:
    original = _runtime()
    changed = original.model_dump(mode="json")
    changed["implementations"][2]["sha256"] = sha("f")
    assert (
        parse_embedding_numerical_runtime(seal(changed, "runtime_sha256")).runtime_sha256
        != original.runtime_sha256
    )
    changed = original.model_dump(mode="json")
    changed["recipe"]["threads"] = 2
    assert (
        parse_embedding_numerical_runtime(seal(changed, "runtime_sha256")).runtime_sha256
        != original.runtime_sha256
    )
    assert not {"source_git_commit", "platform_release_sha256"}.intersection(original.model_dump())


def test_raw_bytes_not_semantic_hash_substitution_and_noncanonical_bytes_fail() -> None:
    bundle = _bundle()
    pointer = _pointer(bundle)
    raw = embedding_runtime_bundle_bytes(bundle)
    for bad in (raw + b"\n", raw.replace(b"CUDA", b"CPU"), b"{}"):
        with pytest.raises(ValueError):
            validate_embedding_runtime_bundle_pointer(bundle, pointer, bad)
    body = pointer.model_dump(mode="json")
    body["bundle_raw_sha256"] = bundle.bundle_sha256
    body["manifest_member"]["sha256"] = bundle.bundle_sha256
    substituted = EmbeddingRuntimeBundlePointer.model_validate(body)
    with pytest.raises(ValueError):
        validate_embedding_runtime_bundle_pointer(bundle, substituted, raw)
    with pytest.raises(ValueError):
        validate_embedding_payload_manifest(bundle, b"{}")


def test_payload_canonical_newline_flavor_requires_its_exact_raw_pin() -> None:
    bundle = _bundle()
    raw = canonical_json_bytes(bundle.payload_model_spec.model_dump(mode="json")) + b"\n"
    with pytest.raises(ValueError):
        validate_embedding_payload_manifest(bundle, raw)
    body = bundle.model_dump(mode="json")
    body["payload_pointer"]["manifest_raw_sha256"] = sha256_bytes(raw)
    successor = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    validate_embedding_payload_manifest(successor, raw)
    assert successor.payload_model_spec == bundle.payload_model_spec
    assert successor.bundle_sha256 != bundle.bundle_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_path", "../bundle.json"),
        ("member_path", "other.json"),
        ("schema_ref", "eom://schemas/knowledge/embedding-runtime-bundle/2.0"),
        ("media_type", "application/octet-stream"),
        ("sha256", sha("f")),
    ],
)
def test_bundle_member_schema_media_path_and_hash_fail(field: str, value: str) -> None:
    body = _pointer(_bundle()).model_dump(mode="json")
    body["manifest_member"][field] = value
    with pytest.raises((JsonSchemaError, ValueError)):
        validate_contract(RUNTIME_BUNDLE_SCHEMA, body)
        EmbeddingRuntimeBundlePointer.model_validate(body)


@pytest.mark.parametrize("field", ["bundle_id", "bundle_revision_id", "bundle_sha256"])
def test_stale_or_wrong_bundle_identity_fails(field: str) -> None:
    bundle = _bundle()
    pointer = _pointer(bundle)
    body = pointer.model_dump(mode="json")
    body[field] = (
        "embeddingbundle_" + "f" * 32
        if field == "bundle_id"
        else ("embeddingbundlerev_" + "f" * 32 if field == "bundle_revision_id" else sha("f"))
    )
    with pytest.raises(ValueError):
        validate_embedding_runtime_bundle_pointer(
            bundle,
            EmbeddingRuntimeBundlePointer.model_validate(body),
            embedding_runtime_bundle_bytes(bundle),
        )


def test_model_copy_bypass_is_revalidated_at_bundle_boundary() -> None:
    bundle = _bundle()
    forged = bundle.execution_model_spec.model_copy(update={"dimension": 4096})
    with pytest.raises(ValueError):
        EmbeddingRuntimeBundle.model_validate(
            bundle.model_copy(update={"execution_model_spec": forged}).model_dump(mode="json")
        )


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "item-inference-transfer",
            "sha256:79e197f598d5fadea0ef757208bd01f05783e83499317680ee804f43600fdff2",
        ),
        (
            "item-inference-transfer-embedding",
            "sha256:36495b830932ac0f7afdaca7a0909652c61dc16a13d01488651cf84978d83b52",
        ),
        (
            "item-inference-transfer-experiment",
            "sha256:becaa7e8281f429267ba9cdcfb03129a5f51ecf53f06b4fcfdf7b9b0789df91b",
        ),
    ],
)
def test_released_model_space_input_and_experiment_bytes_are_unchanged(
    name: str, expected: str
) -> None:
    resource = CATALOG_SCHEMA_RESOURCES[name]
    assert resource.sha256 == expected
    assert sha256_bytes((ROOT / resource.canonical_path).read_bytes()) == expected


def test_contract_dependency_direction_has_no_runtime_or_storage_imports() -> None:
    path = ROOT / "packages/catalog_contracts/eom_catalog_contracts/embedding_runtime_bundle.py"
    tree = ast.parse(path.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        name
        and name.split(".")[0]
        in {
            "torch",
            "transformers",
            "sqlalchemy",
            "subprocess",
            "pathlib",
            "eom_orchestrator",
            "eom_catalog_service",
            "requests",
            "socket",
        }
        for name in imports
    )

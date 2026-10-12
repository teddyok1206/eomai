"""Source-only config closure; synthetic metadata is never an installed admission proof."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
    installed_runtime_proof_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA,
    EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA_REF,
    MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    EmbeddingNativeRuntimeConfig,
    EmbeddingNativeRuntimeResources,
    embedding_native_runtime_config_bytes,
    parse_embedding_native_runtime_config,
    parse_embedding_native_runtime_config_bytes,
    validate_embedding_native_runtime_config_raw,
    validate_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_runtime_bundle_bytes,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal

ROOT = Path(__file__).resolve().parents[2]
PROFILES: tuple[EmbeddingRuntimeProfile, ...] = ("CPU_INDEX_FP32", "CUDA_INDEX_FP32")
INTEGER_FIELDS = tuple(
    name for name in EmbeddingNativeRuntimeResources.model_fields if name != "resource_sha256"
)


def test_schema_is_closed_2020_12_byte_identical_and_raw_pinned() -> None:
    schema = load_schema(EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA_REF
    assert all(
        schema["$defs"][name]["additionalProperties"] is False for name in ("config", "resources")
    )
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256


@pytest.mark.parametrize("profile", PROFILES)
def test_exact_canonical_config_and_external_metadata_closure(
    profile: EmbeddingRuntimeProfile,
) -> None:
    config, bundle, proof = native_config_metadata(profile)
    raw = embedding_native_runtime_config_bytes(config)
    assert parse_embedding_native_runtime_config_bytes(raw) == config
    assert raw == canonical_json_bytes(config.model_dump(mode="json"))
    validate_contract(EMBEDDING_NATIVE_RUNTIME_CONFIG_SCHEMA, config.model_dump(mode="json"))
    validate_embedding_native_runtime_config_raw(config, raw, sha256_bytes(raw))
    validate_embedding_native_runtime_config_references(
        config,
        bundle,
        embedding_runtime_bundle_bytes(bundle),
        proof,
        installed_runtime_proof_bytes(proof),
    )
    assert config.resources.vram_limit_bytes == (0 if profile == "CPU_INDEX_FP32" else 8 * 1024**3)
    assert config.resources.resource_sha256 == content_sha256(
        config.resources.model_dump(mode="json", exclude={"resource_sha256"})
    )
    assert config.config_sha256 == content_sha256(
        config.model_dump(mode="json", exclude={"config_sha256"})
    )
    assert sha256_bytes(raw) != config.config_sha256
    with pytest.raises(ValueError):
        config.profile = "CUDA_INDEX_FP32"


def test_logical_revision_resource_semantic_and_raw_identity_are_distinct() -> None:
    cpu, _, _ = native_config_metadata()
    cuda, _, _ = native_config_metadata("CUDA_INDEX_FP32")
    assert cpu.configuration_id == cuda.configuration_id
    assert cpu.configuration_revision_id != cuda.configuration_revision_id
    assert cpu.config_sha256 != cuda.config_sha256
    assert cpu.resources.resource_sha256 != cuda.resources.resource_sha256


@pytest.mark.parametrize("field", INTEGER_FIELDS)
@pytest.mark.parametrize("bad", (True, False, 4.0, "4", None))
def test_resource_integers_reject_raw_bool_coercion_and_noninteger(field: str, bad: object) -> None:
    config, _, _ = native_config_metadata()
    body = config.model_dump(mode="json")
    body["resources"][field] = bad
    with pytest.raises((ValueError, TypeError)):
        parse_embedding_native_runtime_config(body)
    with pytest.raises((ValueError, TypeError)):
        EmbeddingNativeRuntimeResources.model_validate(body["resources"])


@pytest.mark.parametrize("field", INTEGER_FIELDS)
def test_resource_fixed_limits_cannot_be_rewritten(field: str) -> None:
    config, _, _ = native_config_metadata()
    body = config.model_dump(mode="json")
    body["resources"][field] += 1
    body["resources"] = seal(body["resources"], "resource_sha256")
    with pytest.raises((ValueError, SchemaValidationError)):
        parse_embedding_native_runtime_config(seal(body, "config_sha256"))


@pytest.mark.parametrize("copied", (True, False))
def test_raw_constructed_copied_bool_is_rejected_before_any_dump(
    copied: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _, _ = native_config_metadata()
    resource = (
        config.resources.model_copy(update={"interop_threads": True})
        if copied
        else EmbeddingNativeRuntimeResources.model_construct(
            **{**config.resources.model_dump(), "maximum_active_launches": True}
        )
    )
    poisoned = config.model_copy(update={"resources": resource})

    def forbidden_dump(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid raw value was dumped")

    monkeypatch.setattr(EmbeddingNativeRuntimeConfig, "model_dump", forbidden_dump)
    monkeypatch.setattr(EmbeddingNativeRuntimeResources, "model_dump", forbidden_dump)
    with pytest.raises(ValueError, match="exact raw integers"):
        embedding_native_runtime_config_bytes(poisoned)
    with pytest.raises(ValueError, match="exact raw integers"):
        EmbeddingNativeRuntimeConfig.model_validate(poisoned)


@pytest.mark.parametrize("level", ("config", "resources", "bundle", "installed_proof", "member"))
def test_copied_undeclared_fields_fail_before_serialization(level: str) -> None:
    config, _, _ = native_config_metadata()
    if level == "config":
        poisoned = config.model_copy(update={"authority": "ADMIN"})
    elif level == "resources":
        poisoned = config.model_copy(
            update={"resources": config.resources.model_copy(update={"fallback": True})}
        )
    elif level == "bundle":
        poisoned = config.model_copy(
            update={"bundle": config.bundle.model_copy(update={"path": "/tmp/worker"})}
        )
    elif level == "installed_proof":
        poisoned = config.model_copy(
            update={
                "installed_proof": config.installed_proof.model_copy(update={"installed": True})
            }
        )
    else:
        poisoned = config.model_copy(
            update={
                "bundle": config.bundle.model_copy(
                    update={
                        "manifest_member": config.bundle.manifest_member.model_copy(
                            update={"path": "/tmp/worker"}
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError, match=r"extra|undeclared"):
        embedding_native_runtime_config_bytes(poisoned)


@pytest.mark.parametrize(
    "field",
    (
        "path",
        "executable",
        "module",
        "role",
        "authority",
        "operator",
        "service",
        "default",
        "fallback",
        "activated",
    ),
)
def test_config_contains_no_paths_authority_grants_or_activation(field: str) -> None:
    config, _, _ = native_config_metadata()
    body = config.model_dump(mode="json")
    body[field] = "worker choice"
    with pytest.raises(ValueError, match="undeclared"):
        parse_embedding_native_runtime_config(body)


@pytest.mark.parametrize(
    "field",
    (
        "profile",
        "resources",
        "installed_proof",
        "runtime_sha256",
        "bundle",
        "configuration_revision_id",
        "config_sha256",
    ),
)
def test_configuration_identity_device_and_hash_changes_fail(field: str) -> None:
    config, bundle, proof = native_config_metadata()
    body = config.model_dump(mode="json")
    if field == "profile":
        body[field] = "CUDA_INDEX_FP32"
    elif field == "resources":
        body[field]["vram_limit_bytes"] = 8 * 1024**3
        body[field] = seal(body[field], "resource_sha256")
    elif field == "installed_proof":
        body[field]["profile"] = "CUDA_INDEX_FP32"
    elif field == "bundle":
        body[field]["bundle_revision_id"] = "embeddingbundlerev_" + "9" * 32
    elif field == "configuration_revision_id":
        body[field] = "embeddingnativeconfigrev_" + "9" * 32
    else:
        body[field] = "sha256:" + "0" * 64
    if field not in ("config_sha256", "configuration_revision_id"):
        body = seal(body, "config_sha256")
    with pytest.raises((ValueError, SchemaValidationError)):
        changed = parse_embedding_native_runtime_config(body)
        validate_embedding_native_runtime_config_references(
            changed,
            bundle,
            embedding_runtime_bundle_bytes(bundle),
            proof,
            installed_runtime_proof_bytes(proof),
        )


@pytest.mark.parametrize(
    "changed",
    ("bundle_raw", "proof_raw", "bundle_object", "proof_object", "proof_archive", "runtime_recipe"),
)
def test_external_raw_and_numeric_closure_rejects_stale_or_changed_evidence(changed: str) -> None:
    config, bundle, proof = native_config_metadata()
    bundle_raw, proof_raw = (
        embedding_runtime_bundle_bytes(bundle),
        installed_runtime_proof_bytes(proof),
    )
    if changed == "bundle_raw":
        bundle_raw += b"\n"
    elif changed == "proof_raw":
        proof_raw += b"\n"
    elif changed == "bundle_object":
        bundle = bundle.model_copy(update={"bundle_revision_id": "embeddingbundlerev_" + "9" * 32})
    elif changed == "proof_object":
        proof = proof.model_copy(
            update={"proof_revision_id": "embeddingruntimeproofrev_" + "9" * 32}
        )
    elif changed == "proof_archive":
        proof_body = proof.model_dump(mode="json")
        proof_body["numeric_libraries"][0]["archive"]["sha256"] = "sha256:" + "0" * 64
        proof = EmbeddingInstalledRuntimeProof.model_validate(seal(proof_body, "proof_sha256"))
        proof_raw = installed_runtime_proof_bytes(proof)
        body = config.model_dump(mode="json")
        body["installed_proof"]["proof_sha256"] = proof.proof_sha256
        body["installed_proof"]["proof_raw_sha256"] = sha256_bytes(proof_raw)
        config = parse_embedding_native_runtime_config(seal(body, "config_sha256"))
    else:
        bundle_body = bundle.model_dump(mode="json")
        bundle_body["numerical_runtime"]["recipe"]["threads"] = 1
        bundle_body["numerical_runtime"] = seal(bundle_body["numerical_runtime"], "runtime_sha256")
        bundle = EmbeddingRuntimeBundle.model_validate(seal(bundle_body, "bundle_sha256"))
        bundle_raw = embedding_runtime_bundle_bytes(bundle)
        body = config.model_dump(mode="json")
        body["runtime_sha256"] = bundle.numerical_runtime.runtime_sha256
        body["bundle"]["bundle_sha256"] = bundle.bundle_sha256
        body["bundle"]["bundle_raw_sha256"] = sha256_bytes(bundle_raw)
        body["bundle"]["manifest_member"]["sha256"] = sha256_bytes(bundle_raw)
        config = parse_embedding_native_runtime_config(seal(body, "config_sha256"))
    with pytest.raises(ValueError):
        validate_embedding_native_runtime_config_references(
            config, bundle, bundle_raw, proof, proof_raw
        )


@pytest.mark.parametrize(
    "field",
    ("python", "device", "build", "batch", "library_sha", "library_version", "library_missing"),
)
def test_independently_resealed_bundle_cannot_override_proof_or_resource_closure(
    field: str,
) -> None:
    config, bundle, proof = native_config_metadata()
    body = bundle.model_dump(mode="json")
    runtime = body["numerical_runtime"]
    if field == "python":
        runtime["python_version"] = "3.12.12"
    elif field == "device":
        runtime["device"]["hardware_model"] = "Different CPU"
    elif field == "build":
        runtime["torch_build_cuda_version"] = "12.8"
    elif field == "batch":
        runtime["recipe"]["batch_size"] = 1
    elif field == "library_sha":
        runtime["libraries"][0]["distribution_sha256"] = "sha256:" + "0" * 64
    elif field == "library_version":
        runtime["libraries"][0]["version"] = "2.4.5"
    else:
        runtime["libraries"] = runtime["libraries"][1:]
    body["numerical_runtime"] = seal(runtime, "runtime_sha256")
    bundle = EmbeddingRuntimeBundle.model_validate(seal(body, "bundle_sha256"))
    bundle_raw = embedding_runtime_bundle_bytes(bundle)
    config_body = config.model_dump(mode="json")
    config_body["runtime_sha256"] = bundle.numerical_runtime.runtime_sha256
    config_body["bundle"]["bundle_sha256"] = bundle.bundle_sha256
    config_body["bundle"]["bundle_raw_sha256"] = sha256_bytes(bundle_raw)
    config_body["bundle"]["manifest_member"]["sha256"] = sha256_bytes(bundle_raw)
    config = parse_embedding_native_runtime_config(seal(config_body, "config_sha256"))
    with pytest.raises(ValueError, match="numeric runtime closure"):
        validate_embedding_native_runtime_config_references(
            config, bundle, bundle_raw, proof, installed_runtime_proof_bytes(proof)
        )


def test_config_reference_helper_rejects_copied_bool_before_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, bundle, proof = native_config_metadata()
    bundle_raw, proof_raw = (
        embedding_runtime_bundle_bytes(bundle),
        installed_runtime_proof_bytes(proof),
    )
    config = config.model_copy(
        update={"resources": config.resources.model_copy(update={"interop_threads": True})}
    )

    def forbidden_dump(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid config reached serialization")

    monkeypatch.setattr(EmbeddingNativeRuntimeConfig, "model_dump", forbidden_dump)
    with pytest.raises(ValueError, match="exact raw integers"):
        validate_embedding_native_runtime_config_references(
            config, bundle, bundle_raw, proof, proof_raw
        )


def test_canonical_semantic_hashes_are_not_optional_or_replaced_with_raw_sha() -> None:
    config, _, _ = native_config_metadata()
    body = config.model_dump(mode="json")
    body["resources"]["resource_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="canonical hash"):
        parse_embedding_native_runtime_config(seal(body, "config_sha256"))


@pytest.mark.parametrize("changed", ("missing", "revision", "hash"))
def test_missing_or_stale_proof_pointer_never_uses_latest(changed: str) -> None:
    config, bundle, proof = native_config_metadata()
    body = config.model_dump(mode="json")
    if changed == "missing":
        del body["installed_proof"]
    elif changed == "revision":
        body["installed_proof"]["proof_revision_id"] = "embeddingruntimeproofrev_" + "9" * 32
    else:
        body["installed_proof"]["proof_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, SchemaValidationError)):
        config = parse_embedding_native_runtime_config(seal(body, "config_sha256"))
        validate_embedding_native_runtime_config_references(
            config,
            bundle,
            embedding_runtime_bundle_bytes(bundle),
            proof,
            installed_runtime_proof_bytes(proof),
        )


@pytest.mark.parametrize("changed", ("pin", "newline", "mutation", "oversize"))
def test_expected_raw_pin_is_external_and_requires_exact_canonical_bytes(changed: str) -> None:
    config, _, _ = native_config_metadata()
    raw = embedding_native_runtime_config_bytes(config)
    expected = sha256_bytes(raw)
    if changed == "pin":
        expected = "sha256:" + "0" * 64
    elif changed == "newline":
        raw += b"\n"
        expected = sha256_bytes(raw)
    elif changed == "mutation":
        raw = raw.replace(b"CPU_INDEX_FP32", b"CUDA_INDEX_FP32")
        expected = sha256_bytes(raw)
    else:
        raw = b" " * (MAX_NATIVE_RUNTIME_CONFIG_BYTES + 1)
    with pytest.raises(ValueError):
        validate_embedding_native_runtime_config_raw(config, raw, expected)


@pytest.mark.parametrize("kind", ("text", "bytearray", "memoryview"))
def test_direct_raw_validator_rejects_mutable_or_nonbyte_values(kind: str) -> None:
    config, _, _ = native_config_metadata()
    raw = embedding_native_runtime_config_bytes(config)
    values: dict[str, Any] = {
        "text": raw.decode(),
        "bytearray": bytearray(raw),
        "memoryview": memoryview(raw),
    }
    with pytest.raises(ValueError):
        validate_embedding_native_runtime_config_raw(config, values[kind], sha256_bytes(raw))


@pytest.mark.parametrize(
    "raw",
    (
        b'{"a":1,"a":2}',
        b'{"a":1.0}',
        b'{"a":NaN}',
        b'{"a":123456789012345678901}',
        b"[]",
        b"{",
        b'{"a":' + b"[" * 17 + b"0" + b"]" * 17 + b"}",
    ),
)
def test_bounded_json_rejects_duplicate_nonfinite_float_integer_and_wrong_shape(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_embedding_native_runtime_config_bytes(raw)


@pytest.mark.parametrize("raw", (b" " * (MAX_NATIVE_RUNTIME_CONFIG_BYTES + 1), b"{" + b"[" * 17))
def test_byte_and_depth_bounds_precede_json_allocation(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_loads(*args: object, **kwargs: object) -> Any:
        raise AssertionError("unbounded JSON allocation")

    monkeypatch.setattr(json, "loads", forbidden_loads)
    with pytest.raises(ValueError, match="bound"):
        parse_embedding_native_runtime_config_bytes(raw)


@pytest.mark.parametrize("raw", ("{}", bytearray(b"{}"), memoryview(b"{}")))
def test_raw_members_require_exact_immutable_bytes(raw: object) -> None:
    with pytest.raises(ValueError, match="external byte bound"):
        parse_embedding_native_runtime_config_bytes(cast(bytes, raw))


@pytest.mark.parametrize("cycle", (True, False))
def test_python_deep_or_cyclic_inputs_fail_without_recursive_dump(cycle: bool) -> None:
    config, _, _ = native_config_metadata()
    body = config.model_dump(mode="json")
    nested: dict[str, Any] = {}
    child = nested
    if cycle:
        nested["runtime_sha256"] = nested
    else:
        for _ in range(2000):
            child["runtime_sha256"] = {}
            child = child["runtime_sha256"]
    body["runtime_sha256"] = nested
    with pytest.raises(ValueError, match="bounded strings"):
        parse_embedding_native_runtime_config(body)


def test_dependency_direction_and_fresh_public_import_remain_metadata_only() -> None:
    source = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/embedding_native_runtime_config.py"
    )
    tree = ast.parse(source.read_text())
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert all(
        not name.startswith(
            (
                "torch",
                "transformers",
                "numpy",
                "eom_workflow",
                "eom_catalog_service",
                "pathlib",
                "os",
            )
        )
        for name in imports
    )
    result = subprocess.run(
        [
            "/srv/eom/conda/envs/eom-api/bin/python",
            "-c",
            "import sys; import eom_catalog_contracts; "
            "assert not any(n in sys.modules for n in "
            "('torch','transformers','numpy','eom_workflow'))",
        ],
        check=False,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr.decode()

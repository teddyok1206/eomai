"""Explicit installed successor metadata; no OS snapshot resolution or runtime activation."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingRuntimeProfile,
    installed_runtime_proof_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA,
    EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA_REF,
    EmbeddingNativeRuntimeConfig,
    EmbeddingNativeRuntimeConfigV11,
    embedding_native_runtime_config_bytes,
    installed_embedding_native_runtime_config_bytes,
    parse_embedding_native_runtime_config,
    parse_embedding_native_runtime_config_bytes,
    parse_installed_embedding_native_runtime_config,
    parse_installed_embedding_native_runtime_config_bytes,
    validate_embedding_native_runtime_config_raw,
    validate_installed_embedding_native_runtime_config_raw,
    validate_installed_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.embedding_native_runtime_config_v11_fixtures import native_config_metadata_v11
from tests.unit.inference_transfer_embedding_fixtures import seal

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def successor_body(profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32") -> dict[str, Any]:
    config, _bundle, _proof = native_config_metadata_v11(profile)
    return config.model_dump(mode="json")


def test_v11_closed_schema_mirror_and_317_predecessor_resources_are_frozen() -> None:
    schema = load_schema(EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA_REF
    assert schema["$defs"]["config"]["additionalProperties"] is False
    assert "host_configuration" in schema["$defs"]["config"]["required"]
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    previous = {
        name: item
        for name, item in CATALOG_SCHEMA_RESOURCES.items()
        if name != EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA
    }
    assert len(previous) == 317
    assert content_sha256({name: asdict(item) for name, item in previous.items()}) == (
        "sha256:fbd8a1580577dd0ba0c3a68d6509b4d57e3ed6e2852d0a2e53ca5ef0df46e23b"
    )
    for item in previous.values():
        before = (ROOT / item.canonical_path).read_bytes()
        assert (
            before
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / item.resource_path
            ).read_bytes()
        )
        assert sha256_bytes(before) == item.sha256
    import eom_catalog_contracts as public

    assert public.EmbeddingNativeRuntimeConfigV11 is EmbeddingNativeRuntimeConfigV11
    assert (
        public.parse_installed_embedding_native_runtime_config
        is parse_installed_embedding_native_runtime_config
    )


@pytest.mark.parametrize("profile", ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
def test_installed_family_is_explicit_and_preserves_numerical_identity(
    profile: EmbeddingRuntimeProfile,
) -> None:
    old, bundle, proof = native_config_metadata(profile)
    old_raw = embedding_native_runtime_config_bytes(old)
    new = EmbeddingNativeRuntimeConfigV11.model_validate(successor_body(profile))
    raw = installed_embedding_native_runtime_config_bytes(new)
    assert old.runtime_sha256 == new.runtime_sha256
    assert old.bundle == new.bundle and old.installed_proof == new.installed_proof
    assert old.resources == new.resources and old.configuration_id == new.configuration_id
    assert old.configuration_revision_id != new.configuration_revision_id
    assert old.config_sha256 != new.config_sha256 and sha256_bytes(old_raw) != sha256_bytes(raw)
    assert parse_installed_embedding_native_runtime_config_bytes(raw) == new
    assert parse_installed_embedding_native_runtime_config_bytes(old_raw) == old
    assert installed_embedding_native_runtime_config_bytes(old) == old_raw
    validate_installed_embedding_native_runtime_config_raw(new, raw, sha256_bytes(raw))
    validate_installed_embedding_native_runtime_config_references(
        new,
        bundle,
        embedding_runtime_bundle_bytes(bundle),
        proof,
        installed_runtime_proof_bytes(proof),
    )
    validate_contract(EMBEDDING_NATIVE_RUNTIME_CONFIG_V11_SCHEMA, new.model_dump(mode="json"))
    with pytest.raises(ValueError):
        new.runtime_sha256 = "sha256:" + "f" * 64


@pytest.mark.parametrize("reader", ("model", "dict", "bytes", "serializer", "raw"))
def test_strict_predecessor_readers_do_not_reinterpret_successor(reader: str) -> None:
    config = EmbeddingNativeRuntimeConfigV11.model_validate(successor_body())
    raw = installed_embedding_native_runtime_config_bytes(config)
    unchecked: Any = config
    operations: dict[str, Callable[[], object]] = {
        "model": lambda: EmbeddingNativeRuntimeConfig.model_validate(
            config.model_dump(mode="json")
        ),
        "dict": lambda: parse_embedding_native_runtime_config(config.model_dump(mode="json")),
        "bytes": lambda: parse_embedding_native_runtime_config_bytes(raw),
        "serializer": lambda: embedding_native_runtime_config_bytes(unchecked),
        "raw": lambda: validate_embedding_native_runtime_config_raw(
            unchecked, raw, sha256_bytes(raw)
        ),
    }
    with pytest.raises(ERRORS):
        operations[reader]()


@pytest.mark.parametrize(
    "fault",
    (
        "missing_host",
        "missing_version",
        "unknown_version",
        "path",
        "authority",
        "host_bool",
        "device",
        "resource",
        "semantic_hash",
    ),
)
def test_invalid_snapshot_or_configuration_cannot_be_silently_defaulted(fault: str) -> None:
    body = successor_body()
    if fault == "missing_host":
        del body["host_configuration"]
    elif fault == "missing_version":
        del body["schema_version"]
    elif fault == "unknown_version":
        body["schema_version"] = "embedding-native-runtime-config/1.2"
    elif fault in {"path", "authority"}:
        body["host_configuration"][fault] = "/tmp/untrusted" if fault == "path" else "ADMIN"
    elif fault == "host_bool":
        body["host_configuration"]["manifest_byte_count"] = True
    elif fault == "device":
        body["installed_proof"]["profile"] = "CUDA_INDEX_FP32"
    elif fault == "resource":
        body["resources"]["vram_limit_bytes"] = 8 * 1024**3
        body["resources"] = seal(body["resources"], "resource_sha256")
    else:
        body["config_sha256"] = "sha256:" + "f" * 64
    if fault != "semantic_hash":
        body = seal(body, "config_sha256")
    with pytest.raises(ERRORS):
        parse_installed_embedding_native_runtime_config(body)


@pytest.mark.parametrize(
    "fault", ("extra", "host_extra", "host_bool", "resource_float", "stale_hash")
)
def test_constructed_or_copied_models_are_revalidated_raw(fault: str) -> None:
    config = EmbeddingNativeRuntimeConfigV11.model_validate(successor_body())
    if fault == "extra":
        config = config.model_copy(update={"authority": "ADMIN"})
    elif fault in {"host_extra", "host_bool"}:
        pointer = config.host_configuration.model_copy(
            update={
                "path" if fault == "host_extra" else "manifest_byte_count": "/tmp/untrusted"
                if fault == "host_extra"
                else True
            }
        )
        config = config.model_copy(update={"host_configuration": pointer})
    elif fault == "resource_float":
        config = config.model_copy(
            update={"resources": config.resources.model_copy(update={"threads": 4.0})}
        )
    else:
        config = config.model_copy(update={"config_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ERRORS):
        installed_embedding_native_runtime_config_bytes(config)


@pytest.mark.parametrize("fault", ("raw_pin", "trailing_bytes", "revision", "snapshot_hash"))
def test_installed_raw_pin_and_revision_are_not_self_authorization(fault: str) -> None:
    config = EmbeddingNativeRuntimeConfigV11.model_validate(successor_body())
    raw = installed_embedding_native_runtime_config_bytes(config)
    expected = sha256_bytes(raw)
    if fault == "raw_pin":
        expected = "sha256:" + "f" * 64
    elif fault == "trailing_bytes":
        raw += b"\n"
        expected = sha256_bytes(raw)
    else:
        body = copy.deepcopy(config.model_dump(mode="json"))
        field = "configuration_revision_id" if fault == "revision" else "snapshot_sha256"
        body["host_configuration"][field] = (
            "embeddinghostconfigrev_" + "f" * 32 if fault == "revision" else "sha256:" + "f" * 64
        )
        config = EmbeddingNativeRuntimeConfigV11.model_validate(seal(body, "config_sha256"))
    with pytest.raises(ERRORS):
        validate_installed_embedding_native_runtime_config_raw(config, raw, expected)

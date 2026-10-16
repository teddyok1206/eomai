"""Explicit CUDA installation successors; metadata never admits a CUDA execution."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import CudaHostExtensionSnapshot
from eom_catalog_contracts.embedding_installed_runtime_proof import installed_runtime_proof_bytes
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalInstallationEvidenceError,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfigV11,
    EmbeddingNativeRuntimeConfigV12,
    installed_embedding_native_runtime_config_bytes,
    parse_embedding_native_runtime_config,
    parse_installed_embedding_native_runtime_config_bytes,
    validate_installed_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_cuda_host_closure as closure
from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service import embedding_runtime_prefix_closure as prefix
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_host_extension import body, pointer
from tests.unit.test_embedding_native_installation_evidence import (
    INVENTORY_DRAFT,
    RECEIPT_DRAFT,
    inventory_body,
    receipt_body,
)
from tests.unit.test_embedding_runtime_prefix_closure import _fixture, _input

ROOT = Path(__file__).resolve().parents[2]
NATIVE = "embedding-native-runtime-config-v1.2"
PREFIX = "embedding-prefix-audit-input-v1.2"
ERRORS = (ValueError, SchemaError)


def native():
    old, bundle, proof = native_config_metadata("CUDA_INDEX_FP32")
    extension = CudaHostExtensionSnapshot.model_validate(body())
    document = old.model_dump(mode="json")
    document.update(
        schema_version="embedding-native-runtime-config/1.2",
        cuda_host_extension=pointer(extension).model_dump(mode="json"),
    )
    return (
        EmbeddingNativeRuntimeConfigV12.model_validate(seal(document, "config_sha256")),
        bundle,
        proof,
    )


def prefix_document(tmp_path, monkeypatch):
    plan, _staged, owned, _helper, _locks = _fixture(
        tmp_path, monkeypatch, profile="CUDA_INDEX_FP32"
    )
    with owned:
        document = _input(plan)
    extension = CudaHostExtensionSnapshot.model_validate(body())
    document.update(
        schema_version="embedding-prefix-audit-input/1.2",
        cuda_host_extension=pointer(extension).model_dump(mode="json"),
        host_seed_sha256=extension.host_seed_sha256,
    )
    document["bootstrap"] = [
        {"filename": name, "sha256": "sha256:" + "a" * 64, "size_bytes": 1}
        for name in sorted(prefix._CUDA_BOOTSTRAP)
    ]
    document["public_archives"].extend(
        {
            "filename": f"unused_{i:03d}-1.0-py3-none-any.whl",
            "size_bytes": 1,
            "sha256": "sha256:" + "b" * 64,
        }
        for i in range(70 - len(document["public_archives"]))
    )
    document["public_archives"].sort(key=lambda row: row["filename"])
    monkeypatch.setattr(prefix, "_COUNTS", {"CPU_INDEX_FP32": 55, "CUDA_INDEX_FP32": 70})
    return document


@pytest.mark.parametrize("name", (NATIVE, PREFIX))
def test_closed_successor_schemas_and_runtime_mirrors_are_exact(name):
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    resource = CATALOG_SCHEMA_RESOURCES[name]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )


def test_native_successor_uses_same_numeric_rules_and_strict_old_readers_reject_it():
    config, bundle, proof = native()
    raw = installed_embedding_native_runtime_config_bytes(config)
    assert parse_installed_embedding_native_runtime_config_bytes(raw) == config
    validate_installed_embedding_native_runtime_config_references(
        config,
        bundle,
        embedding_runtime_bundle_bytes(bundle),
        proof,
        installed_runtime_proof_bytes(proof),
    )
    for reader in (
        parse_embedding_native_runtime_config,
        EmbeddingNativeRuntimeConfigV11.model_validate,
    ):
        with pytest.raises(ERRORS):
            reader(config.model_dump(mode="json"))
    import eom_catalog_contracts as public

    assert public.EmbeddingNativeRuntimeConfigV12 is EmbeddingNativeRuntimeConfigV12


def test_cpu_only_sealed_receipt_cannot_admit_cuda_successor_metadata():
    config, _, _ = native()
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(inventory_body()), schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    cpu_config, _, _ = native_config_metadata()
    document = receipt_body(inventory, cpu_config)
    document.update(
        configuration={
            "configuration_id": config.configuration_id,
            "configuration_revision_id": config.configuration_revision_id,
            "configuration_raw_sha256": sha256_bytes(
                installed_embedding_native_runtime_config_bytes(config)
            ),
            "configuration_sha256": config.config_sha256,
        },
        installed_proof=config.installed_proof.model_dump(mode="json"),
        bundle=config.bundle.model_dump(mode="json"),
        runtime_sha256=config.runtime_sha256,
    )
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_native_admission_receipt_metadata(
            canonical_json_bytes(seal(document, "receipt_sha256")),
            schema_raw=RECEIPT_DRAFT.read_bytes(),
        )


@pytest.mark.parametrize(
    "field,bad",
    (
        ("profile", "CPU_INDEX_FP32"),
        ("schema_version", "embedding-native-runtime-config/1.1"),
        ("cuda_host_extension", None),
        ("host_configuration", {}),
        ("authority", "ADMIN"),
    ),
)
def test_cuda_configuration_cannot_be_cpu_legacy_or_path_authority(field, bad):
    config, _, _ = native()
    document = config.model_dump(mode="json")
    document[field] = bad
    with pytest.raises(ERRORS):
        EmbeddingNativeRuntimeConfigV12.model_validate(seal(document, "config_sha256"))


def test_prefix_successor_has_nine_pins_and_no_independent_base_or_cpu_fallback(
    tmp_path, monkeypatch
):
    document = prefix_document(tmp_path, monkeypatch)
    validate_contract(PREFIX, document)
    raw = canonical_json_bytes(document)
    selected = prefix.parse_installed_embedding_prefix_audit_input(raw)
    assert selected.host_configuration is None and selected.cuda_host_extension is not None
    assert len(selected.bootstrap) == 9
    assert len(prefix._BOOTSTRAP) == 6 and len(prefix._SNAPSHOT_BOOTSTRAP) == 7
    with pytest.raises(InstalledRuntimeProofError, match="INPUT_INVALID"):
        prefix.parse_embedding_prefix_audit_input(raw)
    calls = []
    captured, mounted, result = object(), object(), object()
    monkeypatch.setattr(
        capture, "resolve_cuda_host_extension", lambda pin: calls.append(pin) or captured
    )
    monkeypatch.setattr(
        base_capture,
        "require_host_configuration_snapshot_mount",
        lambda value: calls.append(value) or mounted,
    )

    def compose(**kwargs):
        assert kwargs["snapshot_mount"] is mounted
        assert kwargs["expected_seed_sha256"] == selected.host_seed_sha256
        return result

    monkeypatch.setattr(closure, "capture_cuda_embedding_host", compose)
    monkeypatch.setattr(
        prefix, "capture_protected_embedding_host", lambda **kwargs: pytest.fail("no CPU fallback")
    )
    assert (
        prefix.capture_prefix_audit_host(selected, files=NumericalRuntimeFileSnapshots()) is result
    )
    assert calls == [selected.cuda_host_extension, captured]


def test_only_new_cuda_owner_input_requires_canonical_bytes(tmp_path, monkeypatch):
    document = prefix_document(tmp_path, monkeypatch)
    with pytest.raises(InstalledRuntimeProofError, match="INPUT_INVALID"):
        prefix.parse_installed_embedding_prefix_audit_input(json.dumps(document).encode())


@pytest.mark.parametrize(
    "fault",
    (
        "cpu",
        "missing_pointer",
        "old_field",
        "seven_pins",
        "extra_pin",
        "wrong_pin",
        "bad_pointer",
        "boolean_size",
    ),
)
def test_cuda_prefix_input_rejects_malformed_shape_before_capture(tmp_path, monkeypatch, fault):
    document = prefix_document(tmp_path, monkeypatch)
    if fault == "cpu":
        document["profile"] = "CPU_INDEX_FP32"
    elif fault == "missing_pointer":
        del document["cuda_host_extension"]
    elif fault == "old_field":
        document["host_configuration"] = {}
    elif fault == "seven_pins":
        document["bootstrap"] = document["bootstrap"][:7]
    elif fault == "extra_pin":
        document["bootstrap"].append(document["bootstrap"][0])
    elif fault == "wrong_pin":
        document["bootstrap"][0]["filename"] = "unknown.py"
    elif fault == "bad_pointer":
        document["cuda_host_extension"]["configuration_revision_id"] = "latest"
    else:
        document["cuda_host_extension"]["manifest_byte_count"] = True
    with pytest.raises(SchemaError):
        validate_contract(PREFIX, document)
    with pytest.raises(InstalledRuntimeProofError, match="INPUT_INVALID"):
        prefix.parse_installed_embedding_prefix_audit_input(canonical_json_bytes(document))


def test_all_323_predecessor_schema_records_and_bytes_remain_pinned():
    previous = {
        name: asdict(value)
        for name, value in CATALOG_SCHEMA_RESOURCES.items()
        if name not in {NATIVE, PREFIX}
    }
    assert len(previous) == 323
    assert content_sha256(previous) == (
        "sha256:c56c4771df2bfd000a945c4820060afd1de5383ac7b9657f3e187851bd0d30df"
    )
    for name in previous:
        resource = CATALOG_SCHEMA_RESOURCES[name]
        raw = (ROOT / resource.canonical_path).read_bytes()
        assert sha256_bytes(raw) == resource.sha256
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
            ).read_bytes()
        )

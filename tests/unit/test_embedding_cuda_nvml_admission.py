"""Synthetic explicit1.3/2.1 admission family; no root seal, GPU, lease or model run."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import (
    CudaHostExtensionSnapshotV11,
    cuda_host_extension_bytes,
)
from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    CUDA_ADMISSION_V21_DRAFT_RAW_SHA256,
    RootLocalCudaAdmissionReceiptMetadata,
    RootLocalCudaAdmissionReceiptMetadataV21,
    parse_rootlocal_cuda_admission_receipt_metadata,
    parse_rootlocal_cuda_admission_receipt_metadata_v21,
    rootlocal_cuda_admission_receipt_metadata_bytes,
    validate_rootlocal_cuda_installation_metadata_references,
)
from eom_catalog_contracts.embedding_native_cuda_probe import (
    NativeCudaProbeInput,
    NativeCudaProbeLeaseReady,
    NativeCudaProbeResult,
    validate_native_cuda_probe_configuration,
    validate_native_cuda_probe_progression,
    validate_native_cuda_probe_ready_references,
    validate_native_cuda_probe_references,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalInstallationEvidenceError,
    parse_rootlocal_prefix_inventory_candidate,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfigV12,
    EmbeddingNativeRuntimeConfigV13,
    installed_embedding_native_runtime_config_bytes,
    parse_installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_catalog_service import embedding_bundle_resolver as bundles
from eom_catalog_service import embedding_native_cuda_probe as worker_probe
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service import embedding_runtime_files as runtime_files
from eom_catalog_service import embedding_runtime_prefix_closure as prefix
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_host_extension import rehash
from tests.unit.test_embedding_cuda_host_nvml import nvml_body, nvml_pointer
from tests.unit.test_embedding_cuda_installation_admission import (
    capture,
    current,
    state_for_metadata,
)
from tests.unit.test_embedding_cuda_installation_evidence import DRAFT as OLD_DRAFT
from tests.unit.test_embedding_cuda_installation_evidence import metadata as old_metadata
from tests.unit.test_embedding_cuda_installation_input import native, prefix_document
from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_installation_evidence import INVENTORY_DRAFT

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs/architecture/embedding-native-admission-receipt-v2.1.schema.proposal.json"
ERRORS = (ValueError, TypeError, SchemaError)
ADDITIONS = {"embedding-native-runtime-config-v1.3", "embedding-prefix-audit-input-v1.3"}


def metadata():
    facts = old_metadata()
    config, _bundle, _proof = native()
    document = nvml_body()
    document["configuration_revision_id"] = "embeddingcudahostrev_" + "d" * 32
    snapshot = CudaHostExtensionSnapshotV11.model_validate(rehash(document))
    pointer = nvml_pointer(snapshot)
    document = config.model_dump(mode="json")
    document.update(
        schema_version="embedding-native-runtime-config/1.3",
        configuration_revision_id="embeddingnativeconfigrev_" + "e" * 32,
        cuda_host_extension=pointer.model_dump(mode="json"),
    )
    config = EmbeddingNativeRuntimeConfigV13.model_validate(seal(document, "config_sha256"))
    config_raw = installed_embedding_native_runtime_config_bytes(config)
    document = facts["inventory"].model_dump(mode="json")
    document["host_seed_sha256"] = snapshot.host_seed_sha256
    inventory_raw = canonical_json_bytes(seal(document, "inventory_sha256"))
    inventory = parse_rootlocal_prefix_inventory_candidate(
        inventory_raw, schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    document = facts["receipt"].model_dump(mode="json")
    document.update(
        schema_version="embedding-native-admission-receipt/2.1",
        configuration={
            "configuration_id": config.configuration_id,
            "configuration_revision_id": config.configuration_revision_id,
            "configuration_sha256": config.config_sha256,
            "configuration_raw_sha256": sha256_bytes(config_raw),
        },
        inventory={
            "schema_ref": document["inventory"]["schema_ref"],
            "inventory_raw_sha256": sha256_bytes(inventory_raw),
            "inventory_sha256": inventory.inventory_sha256,
        },
        cuda_host_extension=pointer.model_dump(mode="json"),
    )
    receipt_raw = canonical_json_bytes(seal(document, "receipt_sha256"))
    receipt = parse_rootlocal_cuda_admission_receipt_metadata_v21(
        receipt_raw, schema_raw=DRAFT.read_bytes()
    )
    facts.update(
        receipt=receipt,
        receipt_raw=receipt_raw,
        expected_receipt_raw_sha256=sha256_bytes(receipt_raw),
        config=config,
        config_raw=config_raw,
        inventory=inventory,
        inventory_raw=inventory_raw,
        host_snapshot=snapshot,
        host_snapshot_raw=cuda_host_extension_bytes(snapshot),
    )
    return facts


def test_both_packaged_schemas_and_root_receipt_draft_have_exact_identity_and_bytes():
    for name in ADDITIONS:
        Draft202012Validator.check_schema(load_schema(name))
        resource = CATALOG_SCHEMA_RESOURCES[name]
        raw = (ROOT / resource.canonical_path).read_bytes()
        assert sha256_bytes(raw) == resource.sha256
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
            ).read_bytes()
        )
    assert sha256_bytes(DRAFT.read_bytes()) == CUDA_ADMISSION_V21_DRAFT_RAW_SHA256


def test_all330_predecessor_records_and_schema_bytes_remain_unchanged():
    # Pin the historical family, not the size of a registry that admits successors.
    names = set(
        json.loads(
            (ROOT / "tests/fixtures/embedding_predecessor_schema_names_323.json").read_bytes()
        )
    ) | {
        "embedding-cuda-host-extension-v1.1",
        "embedding-native-cuda-probe",
        "embedding-native-cuda-probe-lease-ready",
        "embedding-native-runtime-config-v1.2",
        "embedding-prefix-audit-input-v1.2",
        "system-rag-exam-observation",
        "system-rag-exam-observation-read",
    }
    previous = {name: asdict(CATALOG_SCHEMA_RESOURCES[name]) for name in names}
    assert len(previous) == 330
    assert content_sha256(previous) == (
        "sha256:cee7697e19c0d4e2ae0c9f9bebe8495dbf0fb155f2cfa5f07af60479b83a12c7"
    )
    for name in previous:
        resource = CATALOG_SCHEMA_RESOURCES[name]
        assert sha256_bytes((ROOT / resource.canonical_path).read_bytes()) == resource.sha256


def test_explicit_family_closes_all_metadata_and_preserves_numeric_bundle_and_resources():
    facts = metadata()
    assert isinstance(facts["receipt"], RootLocalCudaAdmissionReceiptMetadataV21)
    validate_rootlocal_cuda_installation_metadata_references(**facts)
    assert (
        parse_installed_embedding_native_runtime_config_bytes(facts["config_raw"])
        == facts["config"]
    )
    assert rootlocal_cuda_admission_receipt_metadata_bytes(facts["receipt"]) == facts["receipt_raw"]
    previous = old_metadata()
    for field in ("bundle", "bundle_raw", "proof", "proof_raw"):
        assert facts[field] == previous[field]
    assert facts["config"].resources == previous["config"].resources
    assert facts["config"].runtime_sha256 == previous["config"].runtime_sha256
    with pytest.raises(ERRORS):
        EmbeddingNativeRuntimeConfigV12.model_validate(facts["config"].model_dump(mode="json"))
    with pytest.raises(ERRORS):
        RootLocalCudaAdmissionReceiptMetadata.model_validate(
            facts["receipt"].model_dump(mode="json")
        )
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata(
            facts["receipt_raw"], schema_raw=DRAFT.read_bytes()
        )
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata_v21(
            previous["receipt_raw"], schema_raw=OLD_DRAFT.read_bytes()
        )


@pytest.mark.parametrize("field", ("config", "receipt", "host_snapshot", "inventory"))
def test_cross_family_metadata_is_not_implicitly_converted_or_relabelled(field):
    facts = metadata()
    old = old_metadata()
    facts[field] = old[field]
    facts[field + "_raw"] = old[field + "_raw"]
    if field == "receipt":
        facts["expected_receipt_raw_sha256"] = old["expected_receipt_raw_sha256"]
    with pytest.raises(RootLocalInstallationEvidenceError):
        validate_rootlocal_cuda_installation_metadata_references(**facts)


def test_prefix1_3_selects_only_host1_1_and_old_prefix_reader_stays_strict(tmp_path, monkeypatch):
    document = prefix_document(tmp_path, monkeypatch)
    facts = metadata()
    document.update(
        schema_version="embedding-prefix-audit-input/1.3",
        cuda_host_extension=facts["config"].cuda_host_extension.model_dump(mode="json"),
        host_seed_sha256=facts["host_snapshot"].host_seed_sha256,
    )
    validate_contract("embedding-prefix-audit-input-v1.3", document)
    raw = canonical_json_bytes(document)
    selected = prefix.parse_installed_embedding_prefix_audit_input(raw)
    assert selected.cuda_host_extension.schema_ref.endswith("/1.1#/$defs/snapshot")
    with pytest.raises(ValueError):
        prefix.parse_embedding_prefix_audit_input(raw)
    document["cuda_host_extension"] = old_metadata()["config"].cuda_host_extension.model_dump(
        mode="json"
    )
    with pytest.raises(ERRORS):
        validate_contract("embedding-prefix-audit-input-v1.3", document)
    with pytest.raises(ValueError):
        prefix.parse_installed_embedding_prefix_audit_input(canonical_json_bytes(document))


@pytest.mark.parametrize(
    "fault", ("unknown-version", "old-host", "cpu-profile", "bool-resource", "extra")
)
def test_native1_3_unknown_or_mixed_configuration_is_rejected(fault):
    document = metadata()["config"].model_dump(mode="json")
    if fault == "unknown-version":
        document["schema_version"] = "embedding-native-runtime-config/1.4"
    elif fault == "old-host":
        document["cuda_host_extension"] = old_metadata()["config"].cuda_host_extension.model_dump(
            mode="json"
        )
    elif fault == "cpu-profile":
        document["profile"] = "CPU_INDEX_FP32"
    elif fault == "bool-resource":
        document["resources"]["threads"] = True
    else:
        document["allow_unpinned_host"] = True
    with pytest.raises(ERRORS):
        parse_installed_embedding_native_runtime_config_bytes(
            canonical_json_bytes(seal(document, "config_sha256"))
        )


def test_receipt2_1_unknown_fields_or_copied_invalid_probe_counters_are_not_trusted():
    facts = metadata()
    body = facts["receipt"].model_dump(mode="json")
    body["schema_version"] = "embedding-native-admission-receipt/2.2"
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata_v21(
            canonical_json_bytes(seal(body, "receipt_sha256")),
            schema_raw=DRAFT.read_bytes(),
        )
    body = facts["receipt"].model_dump(mode="json")
    body["allow_unverified"] = True
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata_v21(
            canonical_json_bytes(seal(body, "receipt_sha256")),
            schema_raw=DRAFT.read_bytes(),
        )
    probe = facts["receipt"].unit_probe.model_copy(update={"model_constructor_calls": 1})
    with pytest.raises(ValueError):
        rootlocal_cuda_admission_receipt_metadata_bytes(
            facts["receipt"].model_copy(update={"unit_probe": probe})
        )


def test_existing_probe_input1_0_can_pin_new_configuration_without_new_authority(case):
    facts = metadata()
    request = NativeCudaProbeInput.model_validate(
        {
            "schema_version": "embedding-native-cuda-probe-input/1.0",
            "execution_id": "b" * 32,
            "profile": "CUDA_INDEX_FP32",
            "configuration": facts["receipt"].configuration.model_dump(mode="json"),
            "installed_proof": facts["config"].installed_proof.model_dump(mode="json"),
            "payload": facts["bundle"].payload_pointer.model_dump(mode="json"),
            "shared_lease_gid": 2468,
        }
    )
    refs = {
        "configuration": facts["config"],
        "configuration_raw": facts["config_raw"],
        **{key: facts[key] for key in ("bundle", "bundle_raw", "proof", "proof_raw")},
    }
    validate_native_cuda_probe_configuration(request, **refs)
    result = NativeCudaProbeResult.model_validate(
        case[2].model_dump(mode="json")
        | {"input_raw_sha256": sha256_bytes(canonical_json_bytes(request))}
    )
    shared = (
        "execution_id",
        "input_raw_sha256",
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "supplementary_gids",
        "payload_file_set_sha256",
        "resource_fds",
    )
    ready = NativeCudaProbeLeaseReady.model_validate(
        {
            **{name: getattr(result, name) for name in shared},
            "schema_version": "embedding-native-cuda-probe-lease-ready/1.0",
            "evidence_state": "RETENTION_REQUESTED_NOT_CUDA_ADMITTED",
            "configuration": request.configuration.model_dump(mode="json"),
            "fdstore_name": "eom-gpu0-lease",
            "expected_device_capture": result.device_capture.model_dump(mode="json"),
            "cuda_initialization_calls": 0,
            "cuda_synchronize_calls": 0,
            "model_constructor_calls": 0,
            "tokenizer_constructor_calls": 0,
            "forward_calls": 0,
        }
    )
    raw = canonical_json_bytes(request)
    validate_native_cuda_probe_ready_references(request, raw, ready, **refs)
    validate_native_cuda_probe_references(request, raw, result, **refs)
    validate_native_cuda_probe_progression(request, raw, ready, result)
    assert not hasattr(request, "assert_owned")
    bad = copy.copy(refs)
    bad["configuration"] = old_metadata()["config"]
    bad["configuration_raw"] = old_metadata()["config_raw"]
    with pytest.raises(ValueError):
        validate_native_cuda_probe_configuration(request, **bad)


def test_worker_metadata_loader_reads_exact1_3_without_importing_ml_or_loading_a_model(monkeypatch):
    import sys

    facts = metadata()
    request = NativeCudaProbeInput.model_validate(
        {
            "schema_version": "embedding-native-cuda-probe-input/1.0",
            "execution_id": "b" * 32,
            "profile": "CUDA_INDEX_FP32",
            "configuration": facts["receipt"].configuration.model_dump(mode="json"),
            "installed_proof": facts["config"].installed_proof.model_dump(mode="json"),
            "payload": facts["bundle"].payload_pointer.model_dump(mode="json"),
            "shared_lease_gid": 2468,
        }
    )
    reads, checks = [], []
    config, proof = facts["config"], facts["proof"]
    source = {
        worker_probe._CONFIG_ROOT
        / config.configuration_id
        / config.configuration_revision_id
        / "config.json": facts["config_raw"],
        worker_probe._PROOF_ROOT / proof.proof_id / proof.proof_revision_id / "proof.json": facts[
            "proof_raw"
        ],
    }

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            raw = source[path]
            assert sha256_bytes(raw) == sha256 and len(raw) <= maximum
            reads.append(path)
            return raw

        def assert_unchanged(self):
            checks.append("files")

        def observe_protected_member_identity(self, path):
            pytest.fail("bundle adapter was not replaced with the synthetic port")

    resolved = SimpleNamespace(
        bundle=facts["bundle"],
        manifest=SimpleNamespace(raw=facts["bundle_raw"]),
        assert_unchanged=lambda: checks.append("bundle"),
    )

    def resolve(given, *, observe_member_identity):
        assert given == bundles.ConfiguredEmbeddingBundle(
            worker_probe._BUNDLE_ROOT,
            worker_probe._MODEL_ROOT,
            config.bundle,
        )
        assert isinstance(observe_member_identity.__self__, Files)
        checks.append("bundle-resolution")
        return resolved

    monkeypatch.setattr(runtime_files, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(
        runtime_files, "require_cuda_loader_working_directory", lambda files: checks.append("cwd")
    )
    monkeypatch.setattr(bundles, "resolve_configured_embedding_bundle", resolve)
    modules = set(sys.modules)
    loaded = worker_probe._load_probe_metadata(request)
    assert loaded[1] == config and isinstance(loaded[1], EmbeddingNativeRuntimeConfigV13)
    assert loaded[-1] is resolved and len(reads) == 2
    assert checks == ["cwd", "bundle-resolution", "files", "bundle"]
    assert not any(
        name == library or name.startswith(library + ".")
        for name in set(sys.modules) - modules
        for library in ("torch", "transformers", "numpy", "tokenizers", "safetensors")
    )


def test_protected_reader_supports_exact2_1_but_does_not_create_physical_ownership(monkeypatch):
    state = state_for_metadata(monkeypatch, metadata(), DRAFT)
    with capture(state) as value:
        assert not hasattr(value, "assert_owned")
        assert state.host_closes == state.resource_closes == 0
        assert len(state.reads) == len(set(state.reads)) == len(state.files)
        before = len(state.reads)
        for _ in range(3):
            current(state, value)
        assert len(state.reads) == before
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize(
    "fault", ("missing-schema", "hash-schema", "unknown-version", "mount", "resources", "host")
)
def test_new_reader_retains_fail_closed_source_and_resource_checks(monkeypatch, fault):
    state = state_for_metadata(monkeypatch, metadata(), DRAFT)
    if fault.endswith("schema"):
        key = next(
            path for path in state.files if path.name == "admission-receipt-v2.1.schema.json"
        )
        if fault == "missing-schema":
            del state.files[key]
        else:
            state.files[key] = OLD_DRAFT.read_bytes()
    elif fault == "unknown-version":
        key = next(path for path in state.files if path.name == "receipt.json")
        body = state.receipt.model_dump(mode="json")
        body["schema_version"] = "embedding-native-admission-receipt/2.2"
        raw = canonical_json_bytes(seal(body, "receipt_sha256"))
        state.files[key] = raw
        state.receipt_pin = sha256_bytes(raw)
    else:
        state.broken = fault
    with pytest.raises(admission.NativeInstallationAdmissionError):
        capture(state)
    if fault.endswith("schema") or fault == "unknown-version":
        assert "resolve_host" not in state.events and "capture_resources" not in state.events

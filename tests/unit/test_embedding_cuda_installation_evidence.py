"""Synthetic CUDA metadata only; no unit, root seal, kernel/device/lease or model acceptance."""

from __future__ import annotations

import copy
import json
import stat
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import (
    CudaHostExtensionSnapshot,
    cuda_host_extension_bytes,
)
from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    CUDA_ADMISSION_DRAFT_RAW_SHA256,
    CUDA_ADMISSION_EVIDENCE_REF,
    RootLocalCudaAdmissionReceiptMetadata,
    parse_rootlocal_cuda_admission_receipt_metadata,
    rootlocal_cuda_admission_receipt_metadata_bytes,
    validate_rootlocal_cuda_installation_metadata_references,
)
from eom_catalog_contracts.embedding_host_configuration import (
    host_configuration_snapshot_bytes,
    parse_host_configuration_snapshot,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import installed_runtime_proof_bytes
from eom_catalog_contracts.embedding_native_installation_evidence import (
    ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
    RootLocalInstallationEvidenceError,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_prefix_inventory_candidate_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_catalog_contracts.validation import catalog_schema_registry
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_host_extension import body as host_body
from tests.unit.test_embedding_cuda_installation_input import native
from tests.unit.test_embedding_host_configuration_contracts import snapshot_body
from tests.unit.test_embedding_native_installation_evidence import (
    INVENTORY_DRAFT,
    RECEIPT_DRAFT,
    inventory_body,
    receipt_body,
)

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs/architecture/embedding-native-admission-receipt-v2.schema.proposal.json"


def metadata():
    config, bundle, proof = native()
    host = CudaHostExtensionSnapshot.model_validate(host_body())
    base = parse_host_configuration_snapshot(snapshot_body())
    document = inventory_body()
    document.update(
        profile="CUDA_INDEX_FP32",
        host_seed_sha256=host.host_seed_sha256,
        boot_id=proof.device_capture.boot_id,
    )
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(seal(document, "inventory_sha256")),
        schema_raw=INVENTORY_DRAFT.read_bytes(),
    )
    cpu, _, _ = native_config_metadata()
    body = receipt_body(inventory, cpu)
    body.update(
        schema_version="embedding-native-admission-receipt/2.0",
        profile="CUDA_INDEX_FP32",
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
        cuda_host_extension=config.cuda_host_extension.model_dump(mode="json"),
        device_capture=proof.device_capture.model_dump(mode="json"),
        device_nodes=[
            {
                "role": role,
                "path": path,
                "epoch": [1, 200 + i, 0, 0, stat.S_IFCHR | 0o666, 1, 0, 1000, 1000],
                "rdev_major": major,
                "rdev_minor": minor,
            }
            for i, (role, path, major, minor) in enumerate(
                (
                    ("NVIDIA0", "/dev/nvidia0", 195, 0),
                    ("NVIDIACTL", "/dev/nvidiactl", 195, 255),
                    ("NVIDIA_UVM", "/dev/nvidia-uvm", 511, 0),
                    ("NVIDIA_UVM_TOOLS", "/dev/nvidia-uvm-tools", 511, 1),
                )
            )
        ],
        shared_gpu_lease={
            "source": "ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0",
            "resource_id": "GPU0",
            "lock_path": "/run/eom-gpu-lease/gpu0.lock",
            "filesystem": "tmpfs",
            "lease_gid": 2468,
            "parent_epoch": [2, 3000, 0, 2468, stat.S_IFDIR | 0o750],
            "lock_epoch": [2, 3001, 0, 2468, stat.S_IFREG | 0o640, 1, 0, 1000, 1000],
            "holder_pid": 123,
            "holder_start_time_ticks": 987,
        },
    )
    body["unit_probe"].update(
        recipe="NATIVE_CUDA_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
        supplementary_gids=[2468],
        observed_runtime_sha256=config.runtime_sha256,
        cuda_initialization_calls=1,
        cuda_synchronize_calls=1,
        terminal_probe_gpu_client_count=0,
    )
    receipt = parse_rootlocal_cuda_admission_receipt_metadata(
        canonical_json_bytes(seal(body, "receipt_sha256")), schema_raw=DRAFT.read_bytes()
    )
    return {
        "receipt": receipt,
        "receipt_raw": rootlocal_cuda_admission_receipt_metadata_bytes(receipt),
        "expected_receipt_raw_sha256": sha256_bytes(
            rootlocal_cuda_admission_receipt_metadata_bytes(receipt)
        ),
        "inventory": inventory,
        "inventory_raw": rootlocal_prefix_inventory_candidate_bytes(inventory),
        "config": config,
        "config_raw": installed_embedding_native_runtime_config_bytes(config),
        "proof": proof,
        "proof_raw": installed_runtime_proof_bytes(proof),
        "bundle": bundle,
        "bundle_raw": embedding_runtime_bundle_bytes(bundle),
        "host_snapshot": host,
        "host_snapshot_raw": cuda_host_extension_bytes(host),
        "base_snapshot": base,
        "base_snapshot_raw": host_configuration_snapshot_bytes(base),
    }


@pytest.fixture(scope="module")
def case():
    return metadata()


def parse(body):
    return parse_rootlocal_cuda_admission_receipt_metadata(
        canonical_json_bytes(seal(body, "receipt_sha256")), schema_raw=DRAFT.read_bytes()
    )


def test_explicit_v2_schema_and_all_existing_reference_closures(case):
    raw = DRAFT.read_bytes()
    assert sha256_bytes(raw) == CUDA_ADMISSION_DRAFT_RAW_SHA256
    schema = json.loads(raw)
    assert schema["$id"] == CUDA_ADMISSION_EVIDENCE_REF
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, registry=catalog_schema_registry()).validate(
        case["receipt"].model_dump(mode="json")
    )
    validate_rootlocal_cuda_installation_metadata_references(**case)
    assert case["receipt_raw"] == rootlocal_cuda_admission_receipt_metadata_bytes(case["receipt"])
    assert len(case["receipt_raw"]) < 32768


def test_cpu_schema_bytes_parser_and_canonical_values_are_unchanged(case):
    assert sha256_bytes(RECEIPT_DRAFT.read_bytes()) == ADMISSION_EVIDENCE_DRAFT_RAW_SHA256
    cpu, _, _ = native_config_metadata()
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(inventory_body()), schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    raw = canonical_json_bytes(receipt_body(inventory, cpu))
    legacy = parse_rootlocal_native_admission_receipt_metadata(
        raw, schema_raw=RECEIPT_DRAFT.read_bytes()
    )
    assert canonical_json_bytes(legacy.model_dump(mode="json")) == raw
    for old_raw, reader, schema in (
        (case["receipt_raw"], parse_rootlocal_native_admission_receipt_metadata, RECEIPT_DRAFT),
        (raw, parse_rootlocal_cuda_admission_receipt_metadata, DRAFT),
        (case["receipt_raw"], parse_rootlocal_cuda_admission_receipt_metadata, RECEIPT_DRAFT),
    ):
        with pytest.raises(RootLocalInstallationEvidenceError):
            reader(old_raw, schema_raw=schema.read_bytes())


@pytest.mark.parametrize(
    "field",
    [
        "expected_receipt_raw_sha256",
        "inventory_raw",
        "config_raw",
        "proof_raw",
        "bundle_raw",
        "host_snapshot_raw",
        "base_snapshot_raw",
    ],
)
def test_each_reference_raw_pin_is_independent_and_cannot_be_changed(case, field):
    changed = dict(case)
    changed[field] = (
        "sha256:" + "f" * 64 if field == "expected_receipt_raw_sha256" else changed[field] + b" "
    )
    with pytest.raises(
        RootLocalInstallationEvidenceError, match="CUDA_INSTALLATION_REFERENCE_INVALID"
    ):
        validate_rootlocal_cuda_installation_metadata_references(**changed)


@pytest.mark.parametrize(
    "fault",
    [
        "cpu_profile",
        "cpu_recipe",
        "model_call",
        "cuda_init_missing",
        "cuda_sync_missing",
        "gpu_client_left",
        "supplement_missing",
        "supplement_extra",
        "supplement_wrong",
        "same_primary_group",
        "holder_pid",
        "holder_start",
        "runtime",
        "seal_before_end",
        "nonutc",
        "extra",
        "missing",
        "node_order",
        "node_duplicate",
        "node_path",
        "node_regular",
        "node_suid",
        "node_link",
        "node_size",
        "node_owner",
        "node_alias",
        "nvidia_major",
        "uvm_major",
        "lease_path",
        "lease_fs",
        "lease_parent_owner",
        "lease_parent_mode",
        "lease_file_mode",
        "lease_parent_gid",
        "lease_gid",
        "lease_cross_fs",
        "lease_alias",
        "lease_device_alias",
        "lease_link",
        "lease_size",
        "cpu_proof",
    ],
)
def test_incomplete_or_forged_device_lease_process_metadata_is_rejected(case, fault):
    body = case["receipt"].model_dump(mode="json")
    probe, lease, nodes = body["unit_probe"], body["shared_gpu_lease"], body["device_nodes"]
    if fault == "cpu_profile":
        body["profile"] = "CPU_INDEX_FP32"
    elif fault == "cpu_recipe":
        probe["recipe"] = "NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"
    elif fault == "model_call":
        probe["model_constructor_calls"] = 1
    elif fault == "cuda_init_missing":
        probe["cuda_initialization_calls"] = 0
    elif fault == "cuda_sync_missing":
        probe["cuda_synchronize_calls"] = 0
    elif fault == "gpu_client_left":
        probe["terminal_probe_gpu_client_count"] = 1
    elif fault == "supplement_missing":
        probe["supplementary_gids"] = []
    elif fault == "supplement_extra":
        probe["supplementary_gids"].append(9999)
    elif fault == "supplement_wrong":
        probe["supplementary_gids"] = [9999]
    elif fault == "same_primary_group":
        probe["worker_gid"] = lease["lease_gid"]
    elif fault == "holder_pid":
        lease["holder_pid"] += 1
    elif fault == "holder_start":
        lease["holder_start_time_ticks"] += 1
    elif fault == "runtime":
        probe["observed_runtime_sha256"] = "sha256:" + "f" * 64
    elif fault == "seal_before_end":
        body["sealed_at_utc"] = "2026-10-12T00:00:00Z"
    elif fault == "nonutc":
        probe["terminated_at_utc"] = "2026-10-13T09:00:00+09:00"
    elif fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "missing":
        del body["cuda_host_extension"]
    elif fault == "node_order":
        nodes.reverse()
    elif fault == "node_duplicate":
        nodes[1] = copy.deepcopy(nodes[0])
    elif fault == "node_path":
        nodes[0]["path"] = "/dev/nvidia1"
    elif fault == "node_regular":
        nodes[0]["epoch"][4] = stat.S_IFREG | 0o666
    elif fault == "node_suid":
        nodes[0]["epoch"][4] |= 0o4000
    elif fault == "node_link":
        nodes[0]["epoch"][5] = 2
    elif fault == "node_size":
        nodes[0]["epoch"][6] = 1
    elif fault == "node_owner":
        nodes[0]["epoch"][2] = 1000
    elif fault == "node_alias":
        nodes[1]["epoch"] = list(nodes[0]["epoch"])
    elif fault == "nvidia_major":
        nodes[0]["rdev_major"] = 999
    elif fault == "uvm_major":
        nodes[3]["rdev_major"] += 1
    elif fault == "lease_path":
        lease["lock_path"] = "/var/lib/eom-image/gpu0.lock"
    elif fault == "lease_fs":
        lease["filesystem"] = "nfs"
    elif fault == "lease_parent_owner":
        lease["parent_epoch"][2] = 1000
    elif fault == "lease_parent_mode":
        lease["parent_epoch"][4] |= 0o020
    elif fault == "lease_file_mode":
        lease["lock_epoch"][4] |= 0o020
    elif fault == "lease_parent_gid":
        lease["parent_epoch"][3] += 1
    elif fault == "lease_gid":
        lease["lease_gid"] += 1
    elif fault == "lease_cross_fs":
        lease["lock_epoch"][0] += 1
    elif fault == "lease_alias":
        lease["lock_epoch"][1] = lease["parent_epoch"][1]
    elif fault == "lease_device_alias":
        lease["parent_epoch"][0] = nodes[0]["epoch"][0]
        lease["lock_epoch"][:2] = nodes[0]["epoch"][:2]
    elif fault == "lease_link":
        lease["lock_epoch"][5] = 2
    elif fault == "lease_size":
        lease["lock_epoch"][6] = 1
    elif fault == "cpu_proof":
        body["installed_proof"]["profile"] = "CPU_INDEX_FP32"
    else:
        raise AssertionError(fault)
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse(body)


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", -1, 18446744073709551616])
def test_integer_fields_cannot_be_coerced_in_root_or_constructed_values(case, bad):
    body = case["receipt"].model_dump(mode="json")
    body["unit_probe"]["cuda_initialization_calls"] = bad
    with pytest.raises(ValueError):
        RootLocalCudaAdmissionReceiptMetadata.model_validate(body)
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata(
            json.dumps(body, separators=(",", ":")).encode(), schema_raw=DRAFT.read_bytes()
        )


@pytest.mark.parametrize(
    "fault", ["boot", "host_seed", "physical_uuid", "host_revision", "host_driver", "legacy_config"]
)
def test_cross_artifact_device_boot_snapshot_and_version_mismatches_fail(case, fault):
    changed = dict(case)
    if fault in {"boot", "host_seed"}:
        body = changed["inventory"].model_dump(mode="json")
        body["boot_id" if fault == "boot" else "host_seed_sha256"] = (
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" if fault == "boot" else "sha256:" + "f" * 64
        )
        changed["inventory"] = parse_rootlocal_prefix_inventory_candidate(
            canonical_json_bytes(seal(body, "inventory_sha256")),
            schema_raw=INVENTORY_DRAFT.read_bytes(),
        )
        changed["inventory_raw"] = rootlocal_prefix_inventory_candidate_bytes(changed["inventory"])
        receipt = changed["receipt"].model_dump(mode="json")
        receipt["inventory"]["inventory_raw_sha256"] = sha256_bytes(changed["inventory_raw"])
        receipt["inventory"]["inventory_sha256"] = changed["inventory"].inventory_sha256
        changed["receipt"] = parse(receipt)
    elif fault in {"physical_uuid", "host_revision"}:
        receipt = changed["receipt"].model_dump(mode="json")
        if fault == "physical_uuid":
            receipt["device_capture"]["gpu_uuid"] = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        else:
            receipt["cuda_host_extension"]["configuration_revision_id"] = (
                "embeddingcudahostrev_" + "f" * 32
            )
        changed["receipt"] = parse(receipt)
    elif fault == "host_driver":
        body = changed["host_snapshot"].model_dump(mode="json")
        from tests.unit.test_embedding_cuda_host_extension import pointer, rehash

        body["driver_release"] = "580.126.10"
        changed["host_snapshot"] = CudaHostExtensionSnapshot.model_validate(rehash(body))
        changed["host_snapshot_raw"] = cuda_host_extension_bytes(changed["host_snapshot"])
        receipt = changed["receipt"].model_dump(mode="json")
        receipt["cuda_host_extension"] = pointer(changed["host_snapshot"]).model_dump(mode="json")
        config_body = changed["config"].model_dump(mode="json")
        config_body["cuda_host_extension"] = receipt["cuda_host_extension"]
        changed["config"] = type(changed["config"]).model_validate(
            seal(config_body, "config_sha256")
        )
        changed["config_raw"] = installed_embedding_native_runtime_config_bytes(changed["config"])
        receipt["configuration"]["configuration_raw_sha256"] = sha256_bytes(changed["config_raw"])
        receipt["configuration"]["configuration_sha256"] = changed["config"].config_sha256
        inventory_doc = changed["inventory"].model_dump(mode="json")
        inventory_doc["host_seed_sha256"] = changed["host_snapshot"].host_seed_sha256
        changed["inventory"] = parse_rootlocal_prefix_inventory_candidate(
            canonical_json_bytes(seal(inventory_doc, "inventory_sha256")),
            schema_raw=INVENTORY_DRAFT.read_bytes(),
        )
        changed["inventory_raw"] = rootlocal_prefix_inventory_candidate_bytes(changed["inventory"])
        receipt["inventory"]["inventory_raw_sha256"] = sha256_bytes(changed["inventory_raw"])
        receipt["inventory"]["inventory_sha256"] = changed["inventory"].inventory_sha256
        changed["receipt"] = parse(receipt)
    else:
        changed["config"], _, _ = native_config_metadata("CUDA_INDEX_FP32")
        changed["config_raw"] = installed_embedding_native_runtime_config_bytes(changed["config"])
    changed["receipt_raw"] = rootlocal_cuda_admission_receipt_metadata_bytes(changed["receipt"])
    changed["expected_receipt_raw_sha256"] = sha256_bytes(changed["receipt_raw"])
    with pytest.raises(RootLocalInstallationEvidenceError):
        validate_rootlocal_cuda_installation_metadata_references(**changed)


@pytest.mark.parametrize(
    "fault",
    [
        "extra_constructed",
        "changed_copy",
        "wrong_schema",
        "duplicate",
        "whitespace",
        "oversized",
        "deep",
        "integer_lexeme",
        "float_json",
    ],
)
def test_constructed_objects_and_noncanonical_or_unbounded_raw_input_are_rejected(case, fault):
    if fault == "extra_constructed":
        value = case["receipt"].model_copy(update={"authority": "ADMIN"})
        with pytest.raises(ValueError):
            rootlocal_cuda_admission_receipt_metadata_bytes(value)
        return
    if fault == "changed_copy":
        value = case["receipt"].model_copy(
            update={
                "unit_probe": case["receipt"].unit_probe.model_copy(
                    update={"cuda_initialization_calls": True}
                )
            }
        )
        with pytest.raises(ValueError):
            rootlocal_cuda_admission_receipt_metadata_bytes(value)
        return
    raw = case["receipt_raw"]
    schema = DRAFT.read_bytes()
    if fault == "wrong_schema":
        schema += b" "
    elif fault == "duplicate":
        raw = b'{"profile":"CUDA_INDEX_FP32",' + raw[1:]
    elif fault == "whitespace":
        raw += b"\n"
    elif fault == "oversized":
        raw = b" " * 32769
    elif fault == "deep":
        raw = b"[" * 17 + b"0" + b"]" * 17
    elif fault == "integer_lexeme":
        raw = b'{"value":' + b"9" * 21 + b"}"
    elif fault == "float_json":
        raw = raw.replace(b'"cuda_initialization_calls":1', b'"cuda_initialization_calls":1.0')
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_cuda_admission_receipt_metadata(raw, schema_raw=schema)

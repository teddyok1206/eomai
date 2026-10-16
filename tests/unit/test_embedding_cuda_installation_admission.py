"""Synthetic protected CUDA2.0 reader composition; never an actual owner seal or GPU grant."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    parse_rootlocal_cuda_admission_receipt_metadata,
    rootlocal_cuda_admission_receipt_metadata_bytes,
)
from eom_catalog_service import embedding_cuda_host_capture as hosts
from eom_catalog_service import embedding_cuda_host_closure as closures
from eom_catalog_service import embedding_cuda_probe_resource_files as resources
from eom_catalog_service import embedding_host_configuration_capture as mounts
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service import embedding_runtime_files as runtime_files
from eom_catalog_service import embedding_runtime_os_identity as identity
from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_installation_evidence import DRAFT, metadata
from tests.unit.test_embedding_native_installation_evidence import INVENTORY_DRAFT

PREFIX = Path("/opt/eom/conda/envs/eom-embedding-cuda")
PROBE_MEMBER = "lib/python3.12/site-packages/eom_catalog_service/embedding_native_cuda_probe.py"


@pytest.fixture
def state(monkeypatch):
    facts = metadata()
    body = facts["receipt"].model_dump(mode="json")
    body["unit_probe"]["unit_template_sha256"] = sha256_bytes(b"synthetic CUDA unit")
    body["unit_probe"]["probe_code_sha256"] = sha256_bytes(b"synthetic CUDA probe")
    receipt = parse_rootlocal_cuda_admission_receipt_metadata(
        canonical_json_bytes(seal(body, "receipt_sha256")), schema_raw=DRAFT.read_bytes()
    )
    config, proof, bundle = facts["config"], facts["proof"], facts["bundle"]
    base = admission._EVIDENCE_ROOT / config.configuration_id / config.configuration_revision_id
    raw = rootlocal_cuda_admission_receipt_metadata_bytes(receipt)
    files = {
        base / "receipt.json": raw,
        base / "inventory.json": facts["inventory_raw"],
        admission._EVIDENCE_ROOT / "schemas/admission-receipt-v2.schema.json": DRAFT.read_bytes(),
        admission._EVIDENCE_ROOT
        / "schemas/prefix-inventory-v1.schema.json": INVENTORY_DRAFT.read_bytes(),
        admission._CONFIG_ROOT
        / config.configuration_id
        / config.configuration_revision_id
        / "config.json": facts["config_raw"],
        admission._PROOF_ROOT / proof.proof_id / proof.proof_revision_id / "proof.json": facts[
            "proof_raw"
        ],
        admission._BUNDLE_ROOT
        / bundle.bundle_id
        / bundle.bundle_revision_id
        / "bundle.json": facts["bundle_raw"],
        Path(
            "/etc/systemd/system/eom-embedding-native-cuda-probe@.service"
        ): b"synthetic CUDA unit",
        PREFIX / PROBE_MEMBER: b"synthetic CUDA probe",
    }
    s = SimpleNamespace(
        facts=facts,
        receipt=receipt,
        configuration=receipt.configuration,
        receipt_pin=sha256_bytes(raw),
        files=files,
        reads=[],
        events=[],
        host_closes=0,
        resource_closes=0,
        broken=None,
        uid=receipt.unit_probe.worker_uid,
        gid=receipt.unit_probe.worker_gid,
        primary_gid=receipt.unit_probe.worker_gid,
        lease_gid=receipt.shared_gpu_lease.lease_gid,
        groups=[receipt.unit_probe.worker_gid, receipt.shared_gpu_lease.lease_gid],
        boot=receipt.device_capture.boot_id,
    )

    class Files:
        def __init__(self, owner_uid):
            assert owner_uid == 0

        def read(self, path, *, sha256, maximum):
            s.reads.append(path)
            value = s.files[path]
            assert 0 < len(value) <= maximum and sha256_bytes(value) == sha256
            return value

        def assert_unchanged(self):
            s.events.append("files")
            if s.broken == "files":
                raise ValueError("synthetic protected-file drift")

    class Host:
        def assert_current(self):
            s.events.append("host")
            if s.broken == "host":
                raise ValueError("synthetic host drift")

        def close(self):
            s.host_closes += 1
            if s.broken == "host_close":
                raise ValueError("synthetic host close failure")

    class Resources:
        def assert_current(self):
            s.events.append("resources")
            if s.broken == "resources":
                raise ValueError("synthetic device/lease file drift")

        def close(self):
            s.resource_closes += 1
            if s.broken == "resource_close":
                raise ValueError("synthetic resource close failure")

    resolved = SimpleNamespace(
        snapshot_raw=facts["host_snapshot_raw"],
        base_configuration=SimpleNamespace(snapshot_raw=facts["base_snapshot_raw"]),
    )

    def resolve(pin):
        assert pin.configuration_id == config.cuda_host_extension.configuration_id
        s.events.append("resolve_host")
        if s.broken == "resolve":
            raise ValueError("synthetic missing/revoked host")
        return resolved

    def mount(given):
        assert given is resolved
        s.events.append("mount")
        if s.broken == "mount":
            raise ValueError("synthetic wrong loader-cache mount")
        return SimpleNamespace(configuration=given)

    def host(*, expected_seed_sha256, files, snapshot_mount):
        assert expected_seed_sha256 == facts["inventory"].host_seed_sha256 and isinstance(
            files, Files
        )
        assert snapshot_mount.configuration is resolved
        s.events.append("capture_host")
        return Host()

    def resource(nodes, lease):
        assert nodes == receipt.device_nodes and lease == receipt.shared_gpu_lease
        s.events.append("capture_resources")
        return Resources()

    def prefix(current):
        assert current.prefix == PREFIX and current.owner_uid == 0
        s.events.append("prefix")
        if s.broken == "prefix":
            raise ValueError("synthetic prefix drift")

    def interpreter(given):
        assert given == PREFIX
        if s.broken == "interpreter":
            raise ValueError("synthetic interpreter drift")

    def cwd(files):
        assert isinstance(files, Files)
        s.events.append("cwd")
        if s.broken == "cwd":
            raise ValueError("synthetic nonempty/changed cwd")

    def device(given):
        assert given == receipt.device_capture
        if s.broken == "device":
            raise ValueError("synthetic GPU/driver/UUID/boot drift")

    monkeypatch.setattr(admission, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(admission, "require_native_runtime_interpreter", interpreter)
    monkeypatch.setattr(
        admission, "read_live_runtime_os_file", lambda *_a, **_kw: (s.boot + "\n").encode()
    )
    monkeypatch.setattr(
        admission.pwd,
        "getpwnam",
        lambda name: (
            SimpleNamespace(pw_uid=s.uid, pw_gid=s.primary_gid)
            if name == "eom-embedding-cuda"
            else pytest.fail("wrong worker")
        ),
    )
    monkeypatch.setattr(
        admission.grp,
        "getgrnam",
        lambda name: SimpleNamespace(gr_gid=s.lease_gid if name == "eom-gpu-lease" else s.gid),
    )
    monkeypatch.setattr(admission.os, "getgrouplist", lambda *_: s.groups)
    monkeypatch.setattr(PrefixRuntimeInventory, "assert_unchanged", prefix)
    monkeypatch.setattr(hosts, "resolve_cuda_host_extension", resolve)
    monkeypatch.setattr(mounts, "require_host_configuration_snapshot_mount", mount)
    monkeypatch.setattr(closures, "capture_cuda_embedding_host", host)
    monkeypatch.setattr(resources, "capture_cuda_installation_resource_files", resource)
    monkeypatch.setattr(runtime_files, "require_cuda_loader_working_directory", cwd)
    monkeypatch.setattr(identity, "observe_runtime_device", device)
    return s


def capture(state):
    return admission.ProtectedNativeCudaEmbeddingInstallationAdmission(
        state.configuration, expected_receipt_raw_sha256=state.receipt_pin
    )


def current(state, value, **changes):
    value.assert_current(
        **(
            {
                "profile": "CUDA_INDEX_FP32",
                "configuration_id": state.configuration.configuration_id,
                "configuration_revision_id": state.configuration.configuration_revision_id,
                "configuration_raw_sha256": state.configuration.configuration_raw_sha256,
            }
            | changes
        )
    )


def test_exact_cuda2_capture_reuses_metadata_and_does_not_mint_physical_ownership(
    state, monkeypatch
):
    with capture(state) as value:
        assert not hasattr(value, "assert_owned")
        assert len(state.reads) == len(state.files) and len(set(state.reads)) == len(state.files)
        before = len(state.reads)
        monkeypatch.setattr(
            hosts, "resolve_cuda_host_extension", lambda *_: pytest.fail("no repeated resolution")
        )
        monkeypatch.setattr(
            admission,
            "parse_installed_embedding_native_runtime_config_bytes",
            lambda *_: pytest.fail("no repeated parse"),
        )
        for _ in range(3):
            current(state, value)
        assert len(state.reads) == before
    assert state.host_closes == state.resource_closes == 1
    value.close()
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize(
    "suffix",
    (
        "receipt.json",
        "inventory.json",
        "config.json",
        "proof.json",
        "bundle.json",
        "admission-receipt-v2.schema.json",
        "prefix-inventory-v1.schema.json",
        "eom-embedding-native-cuda-probe@.service",
        "embedding_native_cuda_probe.py",
    ),
)
@pytest.mark.parametrize("fault", ("missing", "hash"))
def test_pinned_missing_or_changed_files_have_no_latest_fallback(state, suffix, fault):
    (path,) = [p for p in state.files if p.name == suffix]
    if fault == "missing":
        del state.files[path]
    else:
        state.files[path] += b"changed"
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"):
        capture(state)
    assert state.host_closes == state.resource_closes == 0


@pytest.mark.parametrize(
    "broken", ("files", "prefix", "host", "resources", "cwd", "device", "interpreter")
)
def test_current_drift_rejects_and_closes_all_owned_scopes(state, broken):
    value = capture(state)
    state.broken = broken
    with pytest.raises(admission.NativeInstallationAdmissionError, match="INSTALLATION_CHANGED"):
        current(state, value)
    with pytest.raises(admission.NativeInstallationAdmissionError, match="INSTALLATION_CHANGED"):
        value.close()
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize("broken", ("host_close", "resource_close"))
def test_all_cleanup_callbacks_run_even_if_one_fails(state, broken):
    value = capture(state)
    state.broken = broken
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CLEANUP_UNCERTAIN"):
        value.close()
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize(
    "field,value",
    (
        ("uid", 0),
        ("gid", 0),
        ("primary_gid", 0),
        ("lease_gid", 9999),
        ("groups", [2013]),
        ("groups", [2013, 2468, 0]),
        ("boot", "00000000-0000-0000-0000-000000000000"),
    ),
)
def test_boot_account_and_single_expected_lease_group_are_current_not_historical(
    state, field, value
):
    reader = capture(state)
    setattr(state, field, value)
    with pytest.raises(admission.NativeInstallationAdmissionError, match="INSTALLATION_CHANGED"):
        current(state, reader)
    with pytest.raises(admission.NativeInstallationAdmissionError):
        reader.close()
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize(
    "field,value",
    (
        ("profile", "CPU_INDEX_FP32"),
        ("configuration_revision_id", "embeddingnativeconfigrev_" + "f" * 32),
        ("configuration_raw_sha256", "sha256:" + "f" * 64),
        ("configuration_id", True),
    ),
)
def test_exact_profile_and_external_configuration_pin_are_required(state, field, value):
    with capture(state) as reader:
        before = len(state.reads)
        with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_MISMATCH"):
            current(state, reader, **{field: value})
        assert len(state.reads) == before


def test_failed_mount_after_resource_capture_still_closes_resources(state):
    state.broken = "mount"
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"):
        capture(state)
    assert state.resource_closes == 1 and state.host_closes == 0


def test_self_declared_sealed_state_does_not_replace_the_independent_receipt_pin(state):
    state.receipt_pin = "sha256:" + "f" * 64
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"):
        capture(state)
    assert state.host_closes == state.resource_closes == 0


def test_rehashed_receipt_cannot_replace_the_separately_selected_configuration(state):
    (path,) = [p for p in state.files if p.name == "receipt.json"]
    body = json.loads(state.files[path])
    body["configuration"]["configuration_raw_sha256"] = "sha256:" + "f" * 64
    state.files[path] = canonical_json_bytes(seal(body, "receipt_sha256"))
    state.receipt_pin = sha256_bytes(state.files[path])
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"):
        capture(state)
    assert len(state.reads) == 2 and "resolve_host" not in state.events


def test_constructor_failure_after_captures_closes_both_once(state):
    state.broken = "prefix"
    with pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"):
        capture(state)
    assert state.host_closes == state.resource_closes == 1


def test_failed_context_entry_closes_both_and_cannot_be_reused(state):
    value = capture(state)
    state.broken = "resources"
    with pytest.raises(admission.NativeInstallationAdmissionError), value:
        pytest.fail("changed installation must not enter")
    assert state.host_closes == state.resource_closes == 1


def test_cpu_reader_import_does_not_load_cuda_infrastructure_or_optional_ml():
    code = """
import sys
import eom_catalog_service.embedding_native_installation_admission as readers
assert readers.ProtectedNativeCudaEmbeddingInstallationAdmission
for name in ('torch', 'transformers', 'eom_gpu_lease',
             'eom_catalog_service.embedding_cuda_host_closure',
             'eom_catalog_service.embedding_cuda_probe_resource_files'):
    assert name not in sys.modules, name
print('CPU_READER_IMPORT_UNCHANGED=PASS')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True, timeout=15
    )
    assert result.stdout.strip() == "CPU_READER_IMPORT_UNCHANGED=PASS" and not result.stderr


def test_real_cuda_reader_is_not_a_substitute_for_the_factorys_physical_ownership_gate(state):
    from eom_catalog_service.embedding_native_factory import (
        NativeEmbeddingFactoryError,
        native_embedding_backend_scope,
    )

    with (
        capture(state) as reader,
        pytest.raises(NativeEmbeddingFactoryError, match="OWNERSHIP_REQUIRED"),
    ):
        native_embedding_backend_scope(
            profile="CUDA_INDEX_FP32",
            configuration_id=state.configuration.configuration_id,
            configuration_revision_id=state.configuration.configuration_revision_id,
            configuration_raw_sha256=state.configuration.configuration_raw_sha256,
            admission=reader,
        )

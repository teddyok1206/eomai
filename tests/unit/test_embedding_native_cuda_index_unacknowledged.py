"""Real local record IO; synthetic root/unit/device ports, no GPU or privileged effects."""

from __future__ import annotations

import ast
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_native_cuda_index_unacknowledged as owner
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    TerminalCudaLeaseIdentity,
    UnacknowledgedNativeCudaIndexGpuResources,
)
from eom_catalog_service.embedding_native_cuda_index_entry import NativeCudaIndexLaunchPins
from eom_catalog_service.embedding_runtime_files import ObservedRuntimeMemberBytes
from eom_catalog_service.unit_effect_records import write_unit_effect_record
from eom_identifiers import sha256_bytes

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_cuda_nvml_admission import metadata
from tests.unit.test_embedding_native_probe_observation import terminal


@pytest.fixture
def failed(tmp_path, monkeypatch):
    native = native_fixture(device="CUDA")
    launch = NativeCudaIndexLaunchPins(
        "a" * 32,
        native.native_input.job_id,
        native.association.association_sha256,
        native.association.owned_input.sha256,
        1,
        "embeddingnativeconfig_" + "c" * 32,
        "embeddingnativeconfigrev_" + "d" * 32,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "sha256:" + "1" * 64,
    )
    ended = terminal()
    ended = replace(
        ended,
        fragment_path="/etc/systemd/system/" + owner.CUDA_INDEX_TEMPLATE,
        status=replace(
            ended.status,
            active_state="failed",
            sub_state="failed",
            result="exit-code",
            exec_main_status=1,
        ),
    )
    receipt = metadata()["receipt"]
    lease = receipt.shared_gpu_lease
    resources = UnacknowledgedNativeCudaIndexGpuResources(
        receipt.device_nodes,
        TerminalCudaLeaseIdentity(lease.lease_gid, lease.parent_epoch, lease.lock_epoch, 123),
        80,
    )
    captured = object.__new__(owner.CapturedNativeCudaIndexLaunchFiles)
    object.__setattr__(captured, "basis", SimpleNamespace(launch=launch))
    object.__setattr__(captured, "device", receipt.device_capture)
    object.__setattr__(captured, "lease_gid", lease.lease_gid)
    raw = b'{"partial":'
    epoch = (1, 2, 0, 1000, stat.S_IFREG | 0o640, 1, len(raw), 2, 3)
    state = SimpleNamespace(
        captured=captured,
        launch=launch,
        unit=ended,
        name=owner.native_cuda_index_unit(launch.execution_id),
        store=1,
        resources=resources,
        fault=None,
        events=[],
        effects=[],
        retired=False,
        root=tmp_path,
        held=False,
        rechecks=0,
        metadata_calls=0,
        ready=(sha256_bytes(raw), epoch),
        ack_present=False,
        raw=raw,
    )

    def current(self):
        assert self is captured
        state.events.append("capture")
        if state.fault == "capture":
            raise ValueError("synthetic changed immutable file")

    def absent(root, name, invocation, phase):
        assert root == owner.NATIVE_CUDA_INDEX_LIFETIME_ROOT
        assert name == state.name and invocation == ended.invocation_id and phase == "ack"
        if state.ack_present:
            raise ValueError("RECORD_PHASE_PRESENT")

    def inspect(name, *, template):
        assert name == state.name and template == owner.CUDA_INDEX_TEMPLATE and not state.retired
        state.rechecks += 1
        return replace(state.unit, invocation_id="f" * 32) if state.fault == "unit" else state.unit

    def actual_metadata(name, *, template, expected):
        assert (
            name == state.name and template == owner.CUDA_INDEX_TEMPLATE and expected == state.unit
        )
        state.metadata_calls += 1
        if state.fault == "metadata":
            raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
        if state.fault == "late_store" and state.metadata_calls > 1:
            return 123, 0
        return 123, state.store

    def physical(**kwargs):
        assert kwargs == dict(unit=state.name, terminal_pid=123, lease_gid=lease.lease_gid)
        assert state.store == 1
        state.events.append("physical")
        if state.fault == "physical":
            raise ValueError("synthetic lost PID1 lock")
        return state.resources

    def gpu(actual):
        assert actual == receipt.device_capture and (state.store == 1 or state.held)
        state.events.append("gpu")
        return ("busy",) if state.fault == "gpu" else ()

    def device(actual):
        assert actual == receipt.device_capture
        state.events.append("device")

    def reserve(root, name, invocation, phase):
        assert root == owner.NATIVE_CUDA_INDEX_LIFETIME_ROOT
        assert name == state.name and invocation == ended.invocation_id and phase == "retirement"
        directory = tmp_path / phase
        directory.mkdir(mode=0o700)
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def effect(action, name):
        assert name == state.name
        assert (tmp_path / "retirement" / "intent.json").exists()
        assert not (tmp_path / "retirement" / "result.json").exists()
        assert action in {"RESET_FAILED", "CLEAN_FDSTORE"}
        state.effects.append(action)
        if state.fault == action:
            raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_EFFECT_UNCERTAIN")
        if action == "RESET_FAILED":
            state.retired = True
            if state.fault == "reset_released":
                state.store = 0
        else:
            assert state.store == 1
            state.store = 0

    def stopped(name, *, template, invocation):
        assert name == state.name and template == owner.CUDA_INDEX_TEMPLATE
        assert invocation == ended.invocation_id and state.retired
        if state.fault == "stopped":
            raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
        return owner.StoppedGpuUnit("loaded", invocation, state.store)

    @contextmanager
    def released(actual, *, unit):
        assert actual == resources and unit == state.name and state.store == 0
        if state.fault == "locked":
            raise ValueError("synthetic retained lock")
        state.events.append("hold")
        state.held = True
        try:
            yield
        finally:
            state.events.append("close-hold")
            state.held = False

    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(owner.CapturedNativeCudaIndexLaunchFiles, "assert_current", current)
    monkeypatch.setattr(owner, "require_unit_effect_phase_absent", absent)
    monkeypatch.setattr(owner, "inspect_cpu_unit", inspect)
    monkeypatch.setattr(owner, "observe_failed_gpu_unit_metadata", actual_metadata)
    monkeypatch.setattr(
        owner, "root_owned_unit_processes", lambda *_a: (42,) if state.fault == "process" else ()
    )
    monkeypatch.setattr(owner, "_ready_metadata", lambda *_a: state.ready)
    monkeypatch.setattr(
        owner, "observe_native_cuda_index_unit_policy", lambda *_a: "sha256:" + "9" * 64
    )
    monkeypatch.setattr(owner, "observe_unacknowledged_native_cuda_index_gpu_resources", physical)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", gpu)
    monkeypatch.setattr(owner, "observe_runtime_device", device)
    monkeypatch.setattr(owner, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(owner, "apply_native_cuda_index_effect", effect)
    monkeypatch.setattr(owner, "observe_stopped_gpu_unit", stopped)
    monkeypatch.setattr(owner, "hold_released_unacknowledged_native_cuda_index_resources", released)
    return state


def observe(state):
    return owner.observe_unacknowledged_native_cuda_index_terminal(
        state.captured, expected_unit=state.unit
    )


@pytest.mark.parametrize("store", (0, 1))
def test_actual_failed_metadata_without_ready_or_live_owner(store, failed):
    failed.store = store
    result = observe(failed)
    assert result.original_outcome == "FAILED" and result.terminal_pid == 123
    assert result.ready_raw_sha256 == sha256_bytes(failed.raw)
    assert result.stored_descriptors == store
    assert (result.resources is None) == (store == 0)
    assert not hasattr(result, "ready") and not hasattr(result, "acknowledged")
    if store == 0:
        assert not {"gpu", "device", "physical"}.intersection(failed.events)
    with pytest.raises(FrozenInstanceError):
        result.terminal_pid = 9


@pytest.mark.parametrize(
    "fault", ("capture", "unit", "metadata", "late_store", "process", "physical", "gpu")
)
def test_uncertain_original_failed_observation_never_effects(failed, fault):
    failed.fault = fault
    with pytest.raises(ValueError):
        observe(failed)
    assert not failed.effects and not tuple(failed.root.iterdir())


def test_existing_even_partial_ack_reservation_blocks_unacknowledged_path(failed):
    failed.ack_present = True
    with pytest.raises(ValueError, match="RECORD_PHASE_PRESENT"):
        observe(failed)
    assert not failed.effects


@pytest.mark.parametrize("store", (0, 1))
def test_retirement_preserves_failure_and_records_only_original_metadata(failed, store):
    failed.store = store
    original = observe(failed)
    failed.events.clear()
    result = owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert result.original_terminal is original and original.original_outcome == "FAILED"
    assert result.retired_unit.stored_descriptors == 0
    assert failed.effects == (["RESET_FAILED"] if store == 0 else ["RESET_FAILED", "CLEAN_FDSTORE"])
    if store == 0:
        assert not {"gpu", "device", "physical", "hold"}.intersection(failed.events)
    else:
        assert "hold" in failed.events and failed.events[-1] == "close-hold"
    payload = json.loads((failed.root / "retirement" / "result.json").read_bytes())
    assert payload["admission_granted"] is False
    assert payload["observation"]["original_terminal"]["original_outcome"] == "FAILED"
    assert "inputs" not in json.dumps(payload) and "vectors" not in json.dumps(payload)


@pytest.mark.parametrize("action", ("RESET_FAILED", "CLEAN_FDSTORE"))
def test_uncertain_effect_cannot_be_replayed(failed, action):
    original = observe(failed)
    failed.fault = action
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    before = tuple(failed.effects)
    # Even if the unit remained failed after an uncertain reset, the phase is reserved.
    failed.retired = False
    failed.fault = None
    with pytest.raises(ValueError, match="EFFECT_ALREADY_RESERVED"):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert tuple(failed.effects) == before


@pytest.mark.parametrize("member", ("intent.json", "result.json"))
def test_partial_record_does_not_authorize_effect_replay(failed, monkeypatch, member):
    original = observe(failed)

    def partial(directory, name, raw):
        if name == member:
            write_unit_effect_record(directory, name, raw[:3])
            raise OSError("synthetic uncertain write")
        write_unit_effect_record(directory, name, raw)

    monkeypatch.setattr(owner, "write_unit_effect_record", partial)
    with pytest.raises(ValueError, match="RECORD_UNCERTAIN"):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    before = tuple(failed.effects)
    failed.retired = False
    failed.store = 1
    with pytest.raises(ValueError, match="EFFECT_ALREADY_RESERVED"):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert tuple(failed.effects) == before


@pytest.mark.parametrize("store", (0, 1))
def test_readonly_reconciliation_has_no_effect_or_owner_deadline_dependency(failed, store):
    failed.store = store
    original = observe(failed)
    failed.retired = True
    failed.store = 0
    failed.events.clear()
    result = owner.observe_retired_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert result.original_terminal is original and not failed.effects
    assert not tuple(failed.root.iterdir())
    if store == 0:
        assert not {"gpu", "device", "physical", "hold"}.intersection(failed.events)


@pytest.mark.parametrize(
    "field,value",
    (
        ("execution_id", "f" * 32),
        ("job_id", "job_" + "f" * 32),
        ("association_sha256", "sha256:" + "f" * 64),
        ("input_raw_sha256", "sha256:" + "f" * 64),
        ("environment_raw_sha256", "sha256:" + "f" * 64),
        ("ready_raw_sha256", "sha256:" + "f" * 64),
        ("terminal_pid", True),
        ("stored_descriptors", True),
        ("resources", None),
        ("original_outcome", "SUCCEEDED"),
    ),
)
def test_changed_original_basis_never_mutates(failed, field, value):
    original = replace(observe(failed), **{field: value})
    with pytest.raises(ValueError):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert not failed.effects and not tuple(failed.root.iterdir())


def test_reset_already_released_original_store_needs_no_clean_but_full_release_proof(failed):
    original = observe(failed)
    failed.fault = "reset_released"
    result = owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert result.original_terminal == original and result.retired_unit.stored_descriptors == 0
    assert failed.effects == ["RESET_FAILED"] and "hold" in failed.events


def test_nonroot_or_borrowed_terminal_never_mutates(failed, monkeypatch):
    original = observe(failed)
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
    assert not failed.effects


def test_one_original_concurrent_retirement_winner(failed):
    failed.store = 0
    original = observe(failed)

    # Stop the synthetic inspector from changing during the two contenders' rechecks.
    def contender(_):
        try:
            owner.retire_unacknowledged_native_cuda_index_unit(original, failed.captured)
            return "retired"
        except (ValueError, AssertionError):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(contender, range(2)))
    assert results.count("retired") == 1 and failed.effects == ["RESET_FAILED"]


def test_no_benchmark_authority_or_model_admission_and_no_fake_process_birth():
    source = Path(owner.__file__).read_text()
    modules = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any("benchmark" in name for name in modules)
    assert not any(name.startswith(("torch", "transformers", "sqlalchemy")) for name in modules)
    assert "time.monotonic" not in source and "owner_pid" not in source
    assert "FDSTOREREMOVE" not in source and "LOCK_UN" not in source


@pytest.mark.parametrize("raw", (b"", b'{"partial":', b"not valid JSON"))
def test_raw_ready_metadata_preserves_empty_partial_without_parsing(failed, monkeypatch, raw):
    runtime = failed.root / "execution"
    runtime.mkdir()
    path = runtime / "ready.json"
    path.write_bytes(raw)
    epoch = owner._epoch(path.lstat())
    object.__setattr__(failed.captured, "ready_identity", epoch[:6])
    monkeypatch.setattr(
        owner.CapturedNativeCudaIndexLaunchFiles, "execution", property(lambda _: runtime)
    )
    # Restore only the method under test, leaving the synthetic root/file closure.
    monkeypatch.setattr(owner, "_ready_metadata", REAL_READY_METADATA)

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def observe_protected_member_bytes(self, actual, *, maximum):
            assert actual == path and len(raw) <= maximum
            return ObservedRuntimeMemberBytes(sha256_bytes(raw), len(raw), raw)

        def assert_unchanged(self):
            pass

    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    assert owner._ready_metadata(failed.captured) == (sha256_bytes(raw), epoch)


REAL_READY_METADATA = owner._ready_metadata

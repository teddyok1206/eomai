"""Actual pre-ACK observation logic, synthetic root/unit/file/driver ports only."""

import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_observation as ready_owner
from eom_catalog_service import embedding_benchmark_cuda_unacknowledged as owner
from eom_catalog_service import gpu_unit_terminal_observation as terminal_reader
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    TerminalCudaLeaseIdentity,
    UnacknowledgedBenchmarkGpuResources,
)
from eom_catalog_service.embedding_runtime_files import ObservedRuntimeMemberBytes
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import terminal as terminal_unit


@pytest.fixture
def unacknowledged(benchmark, monkeypatch):
    state = benchmark
    success = terminal_unit()
    state.unit = replace(
        success,
        fragment_path="/etc/systemd/system/" + owner.CUDA_BENCHMARK_TEMPLATE,
        status=replace(
            success.status,
            active_state="failed",
            sub_state="failed",
            result="exit-code",
            exec_main_status=1,
        ),
    )
    state.expected_terminal = state.unit
    state.pids = ()
    state.ready_raw = b""
    state.ack_present = False
    state.stored = 1
    state.metadata_fault = None
    state.metadata_calls = 0
    state.physical_reads = 0
    original = ready_owner.NumericalRuntimeFileSnapshots
    lease = state.resources.shared_gpu_lease
    state.unack_resources = UnacknowledgedBenchmarkGpuResources(
        state.resources.device_nodes,
        TerminalCudaLeaseIdentity(lease.lease_gid, lease.parent_epoch, lease.lock_epoch, 123),
        state.resources.pid1_descriptor,
    )

    class Files(original):
        def observe_protected_member_bytes(self, path, *, maximum):
            assert path.name == "cuda-ready.json" and self.uid == 1234
            if len(state.ready_raw) > maximum:
                raise ValueError("synthetic bounded ready member")
            return ObservedRuntimeMemberBytes(
                sha256_bytes(state.ready_raw), len(state.ready_raw), state.ready_raw
            )

    def no_ack(root, unit, invocation, phase):
        assert root == owner.BENCHMARK_CUDA_LIFETIME_ROOT and unit == state.unit_name
        assert invocation == state.expected_terminal.invocation_id and phase == "ack"
        if state.ack_present:
            raise ValueError("RECORD_PHASE_PRESENT")

    def metadata(args, **kwargs):
        assert args[:3] == ("/usr/bin/systemctl", "show", state.unit_name)
        assert set(args[3:]) == {
            "--property=" + key
            for key in (
                "ExecMainPID",
                "NFileDescriptorStore",
                "InvocationID",
                "ExecMainStartTimestampMonotonic",
            )
        }
        assert kwargs == dict(
            capture_output=True, check=False, timeout=10, env=terminal_reader._ENV
        )
        state.metadata_calls += 1
        fields = dict(
            ExecMainPID="123",
            NFileDescriptorStore=str(state.stored),
            InvocationID=state.unit.invocation_id,
            ExecMainStartTimestampMonotonic=str(state.unit.status.exec_main_started_monotonic),
        )
        if state.metadata_fault == "timeout":
            raise subprocess.TimeoutExpired(args, 10)
        if state.metadata_fault == "late_store" and state.metadata_calls > 1:
            fields["NFileDescriptorStore"] = "0"
        if state.metadata_fault in fields:
            fields[state.metadata_fault] = "wrong"
        return SimpleNamespace(
            returncode=0,
            stdout="".join(f"{key}={value}\n" for key, value in fields.items()).encode(),
            stderr=b"",
        )

    def physical(**kwargs):
        assert kwargs == dict(unit=state.unit_name, terminal_pid=123, lease_gid=2468)
        state.physical_reads += 1
        if state.fault == "physical" and state.physical_reads > 1:
            return replace(state.unack_resources, pid1_descriptor=81)
        return state.unack_resources

    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(owner, "require_unit_effect_phase_absent", no_ack)
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *_a, **_kw: state.unit)
    monkeypatch.setattr(owner, "root_owned_unit_processes", lambda *_a: state.pids)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda identity: identity)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda *_a: state.clients)
    monkeypatch.setattr(owner, "observe_unacknowledged_benchmark_gpu_resources", physical)
    monkeypatch.setattr(
        terminal_reader,
        "subprocess",
        SimpleNamespace(run=metadata, TimeoutExpired=subprocess.TimeoutExpired),
    )
    return state


def observe(state):
    return owner.observe_unacknowledged_benchmark_cuda_terminal(
        state.invocation,
        state.environment,
        expected_unit=state.expected_terminal,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )


@pytest.mark.parametrize("stored", (0, 1))
@pytest.mark.parametrize("raw", (b"", b'{"partial":', b"not a ready message"))
def test_failed_pre_ack_observation_preserves_raw_hash_without_inventing_ready_or_birth(
    unacknowledged, stored, raw
):
    state = unacknowledged
    state.stored, state.ready_raw = stored, raw
    if not stored:
        state.clients = (999,)  # A competing real holder is not ours to inspect/control.
    result = observe(state)
    assert result.original_outcome == "FAILED" and result.terminal_unit is state.expected_terminal
    assert result.ready_raw_sha256 == sha256_bytes(raw) and result.ready_size_bytes == len(raw)
    assert result.stored_descriptors == stored
    assert (result.resources is None) == (stored == 0)
    assert state.physical_reads == (2 if stored else 0)
    assert not hasattr(result, "ready")
    if result.resources is not None:
        assert not hasattr(result.resources.shared_gpu_lease, "holder_start_time_ticks")


def test_pre_ack_timeout_is_failed_and_expired_actor_window_is_not_extended(
    unacknowledged, monkeypatch
):
    state = unacknowledged
    state.unit = replace(state.unit, status=replace(state.unit.status, result="timeout"))
    state.expected_terminal = state.unit
    monkeypatch.setattr(ready_owner.time, "monotonic_ns", lambda: state.pins.expires_ns + 1)
    result = observe(state)
    assert result.original_outcome == "FAILED" and result.terminal_unit.status.result == "timeout"


@pytest.mark.parametrize("fault", ("ack", "child", "gpu", "physical", "files", "root", "running"))
def test_unknown_pre_ack_state_never_grants_recovery(unacknowledged, monkeypatch, fault):
    state = unacknowledged
    if fault == "ack":
        state.ack_present = True
    elif fault == "child":
        state.pids = (124,)
    elif fault == "gpu":
        state.clients = (123,)
    elif fault == "physical":
        state.fault = fault
    elif fault == "files":
        state.drift = True
    elif fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    else:
        state.unit = replace(state.unit, main_pid=123)
    with pytest.raises(ValueError):
        observe(state)


@pytest.mark.parametrize(
    "fault",
    (
        "ExecMainPID",
        "NFileDescriptorStore",
        "InvocationID",
        "ExecMainStartTimestampMonotonic",
        "timeout",
        "late_store",
    ),
)
def test_terminal_pid_store_and_invocation_are_bound_to_actual_failed_unit(unacknowledged, fault):
    unacknowledged.metadata_fault = fault
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        observe(unacknowledged)


@pytest.mark.parametrize("field", ("job_id", "environment_raw_sha256", "ready_raw_sha256"))
def test_late_recovery_basis_cannot_substitute_another_job_or_raw_member(unacknowledged, field):
    state = unacknowledged
    terminal = observe(state)
    files = owner.capture_unacknowledged_benchmark_files(
        state.invocation, state.environment, backend=state.backend, inventory=state.inventory
    )
    changed = replace(terminal, **{field: "wrong"})
    with pytest.raises(ValueError, match="PINNED_BASIS_CHANGED"):
        owner.require_unacknowledged_benchmark_basis(changed, files)


def test_fresh_actual_nonroot_identity_is_denied_before_files_commands_or_optional_ml():
    paths = os.environ["PYTHONPATH"].split(os.pathsep)
    code = """
import builtins, os, subprocess, sys
from pathlib import Path
sys.path[:0]=sys.argv[1:]
from eom_catalog_service import embedding_benchmark_cuda_unacknowledged as observation
from eom_catalog_service import embedding_benchmark_cuda_lifetime as lifetime
from eom_catalog_service import embedding_cuda_probe_resource_observation as resources
from eom_catalog_service.unit_effect_records import require_unit_effect_phase_absent
assert os.getresuid() != (0,0,0)
def forbidden(*_a, **_kw): raise AssertionError('OS access before root guard')
builtins.open = forbidden
Path.lstat = forbidden
Path.read_bytes = forbidden
subprocess.run = forbidden
options=dict(backend=None,inventory=None,host=None)
calls=(
 (lambda: observation.observe_unacknowledged_benchmark_cuda_terminal(None,None,
     expected_unit=None,**options), 'BENCHMARK_CUDA_UNACKNOWLEDGED_ROOT_REQUIRED'),
 (lambda: observation.capture_unacknowledged_benchmark_files(None,None,
     backend=None,inventory=None), 'BENCHMARK_CUDA_OBSERVATION_ROOT_REQUIRED'),
 (lambda: observation.require_unacknowledged_benchmark_basis(None,None),
     'BENCHMARK_CUDA_UNACKNOWLEDGED_ROOT_REQUIRED'),
 (lambda: lifetime.retire_unacknowledged_benchmark_cuda_unit(None,None,None,**options),
     'BENCHMARK_CUDA_LIFETIME_ROOT_REQUIRED'),
 (lambda: lifetime.observe_retired_unacknowledged_benchmark_cuda_unit(None,None,None,**options),
     'BENCHMARK_CUDA_LIFETIME_ROOT_REQUIRED'),
 (lambda: resources.observe_unacknowledged_benchmark_gpu_resources(
     unit='eom-embedding-benchmark-cuda@'+'a'*32+'.service',terminal_pid=123,lease_gid=2468),
     'BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID'),
 (lambda: require_unit_effect_phase_absent(Path('/opt/eom/embedding-benchmark-lifetimes'),
     'eom-embedding-benchmark-cuda@'+'a'*32+'.service','b'*32,'ack'),'OWNER_REQUIRED'),
)
for action, expected in calls:
 try: action()
 except ValueError as error: assert str(error)==expected, str(error)
 else: raise AssertionError('root guard did not refuse')
assert not {'torch','numpy','transformers','sentence_transformers'}.intersection(sys.modules)
"""
    result = subprocess.run(
        (sys.executable, "-I", "-B", "-c", code, *paths), capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode()

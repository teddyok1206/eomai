"""Synthetic installed/kernel ports; no actual root unit, CUDA, source or model admission."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_service import embedding_gpu_batch_observation as observer
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
)
from eom_catalog_service.embedding_gpu_batch_handoff import PreparedEmbeddingGpuBatch
from eom_catalog_service.embedding_gpu_batch_launch import (
    native_embedding_gpu_batch_environment,
    native_embedding_gpu_batch_launch_arguments,
)
from eom_catalog_service.embedding_native_probe_observation import parse_native_executable_mappings
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_cuda_nvml_admission import metadata as cuda_facts
from tests.unit.test_embedding_gpu_batch_launch import launch_pins
from tests.unit.test_embedding_gpu_control import control_case
from tests.unit.test_embedding_native_probe_observation import maps, process_stat, running

ROOT = Path(__file__).resolve().parents[2]


def metadata(inode, *, mode=stat.S_IFREG | 0o600, gid=990, size=0, rdev=0):
    return SimpleNamespace(
        st_dev=1,
        st_ino=inode,
        st_uid=0,
        st_gid=gid,
        st_mode=mode,
        st_nlink=1,
        st_size=size,
        st_mtime_ns=2,
        st_ctime_ns=3,
        st_rdev=rdev,
    )


@pytest.fixture
def machine(monkeypatch):
    request, ready, *_ = control_case(expires_ns=100 * 10**9)
    launch = replace(
        launch_pins(),
        root_pid=456,
        allocation_raw_sha256=sha256_bytes(embedding_gpu_control_bytes(request)),
    )
    execution = observer.GPU_BATCH_RUNTIME_ROOT / launch.attempt_hex
    entry = observer._PREFIX / observer._ENTRY_MEMBER
    data = {
        Path("/etc/systemd/system") / observer.GPU_BATCH_TEMPLATE: (
            ROOT / "infra/systemd" / observer.GPU_BATCH_TEMPLATE
        ).read_bytes(),
        Path("/etc/systemd/system") / observer.GPU_BATCH_SOCKET_TEMPLATE: (
            ROOT / "infra/systemd" / observer.GPU_BATCH_SOCKET_TEMPLATE
        ).read_bytes(),
        entry: (
            ROOT / "services/catalog_service/eom_catalog_service/embedding_gpu_batch_entry.py"
        ).read_bytes(),
        execution / "allocation.json": embedding_gpu_control_bytes(request),
        execution / "launch.env": native_embedding_gpu_batch_environment(launch),
    }
    identities = {
        path: metadata(
            index,
            mode=stat.S_IFREG | (0o600 if path.parent == execution else 0o644),
            gid=990 if path.parent == execution else 0,
            size=len(raw),
        )
        for index, (path, raw) in enumerate(data.items(), 20)
    }
    for index, name in enumerate(("input.json", "result.json", "vectors.f32"), 40):
        identities[execution / name] = metadata(
            index, mode=stat.S_IFREG | (0o600 if name == "input.json" else 0o640)
        )
    for path in (observer.GPU_BATCH_RUNTIME_ROOT, execution):
        identities[path] = metadata(80, mode=stat.S_IFDIR | 0o750)
    identities[observer.CUDA_LOADER_EMPTY_DIRECTORY] = metadata(
        90, mode=stat.S_IFDIR | 0o555, gid=0
    )
    state = SimpleNamespace(
        data=data,
        identities=identities,
        ready=ready,
        request=request,
        launch=launch,
        prepared=PreparedEmbeddingGpuBatch(
            launch, request, observer._epoch(identities[execution / "input.json"])
        ),
        unit=replace(running(), fragment_path="/etc/systemd/system/" + observer.GPU_BATCH_TEMPLATE),
        unit_name="eom-embedding-native-gpu-batch@" + launch.attempt_hex + ".service",
        now=10**9,
        start=ready.start_time_ticks,
        tasks=["123"],
        pids=(123,),
        clients=(),
        closed=False,
        installation_drift=False,
        file_drift=False,
        grant_exists=False,
        unit_calls=0,
        resource_calls=0,
        policy_calls=0,
        late=None,
        output_alias=False,
        fd_flags={},
        fd_positions={},
        fd_names=["0", "1", "2", "3", "4", "5", "6"],
    )
    state.cgroup = f"0::/system.slice/{state.unit_name}\n".encode()
    state.status = (
        "Pid:\t123\nTgid:\t123\nThreads:\t1\nUid:\t1234 1234 1234 1234\n"
        "Gid:\t1234 1234 1234 1234\nGroups:\t1234 2468\nNoNewPrivs:\t1\n"
        + "\n".join(
            f"{key}:\t0000000000000000"
            for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        + "\n"
    ).encode()
    state.command = (
        b"\0".join(
            value.encode()
            for value in (
                str(observer._PREFIX / "bin/python3.12"),
                "-I",
                "-B",
                "-m",
                "eom_catalog_service.embedding_gpu_batch_entry",
                *native_embedding_gpu_batch_launch_arguments(launch),
            )
        )
        + b"\0"
    )
    state.maps = maps(path=observer._PREFIX / "bin/python3.12")
    facts = cuda_facts()["receipt"]
    state.resources = CudaProbeResourceObservation(
        facts.device_nodes,
        facts.shared_gpu_lease.model_copy(
            update={"holder_pid": ready.pid, "holder_start_time_ticks": ready.start_time_ticks}
        ),
        80,
    )
    inventory = SimpleNamespace(
        prefix=observer._PREFIX,
        entries=(
            SimpleNamespace(
                relative_member=observer._ENTRY_MEMBER,
                sha256=sha256_bytes(data[entry]),
                epoch=observer._epoch(identities[entry]),
            ),
        ),
    )

    class Files:
        def __init__(self, uid):
            assert uid == 0
            self.epochs = {}

        def read(self, path, *, sha256, maximum):
            raw = data[path]
            if len(raw) > maximum or sha256_bytes(raw) != sha256:
                raise ValueError("synthetic protected file hash mismatch")
            self.epochs[path] = observer._epoch(identities[path])
            return raw

        def verify(self, path, *, sha256, size, maximum):
            assert len(self.read(path, sha256=sha256, maximum=maximum)) == size

        def observe_empty_directory(self, path):
            assert path == observer.CUDA_LOADER_EMPTY_DIRECTORY
            self.epochs[path] = observer._epoch(identities[path])

        def assert_unchanged(self):
            if state.file_drift or any(
                observer._epoch(identities[path]) != epoch for path, epoch in self.epochs.items()
            ):
                raise ValueError("synthetic captured file drift")

    class Installation:
        def __init__(self, configuration, *, expected_receipt_raw_sha256):
            self.closed = False
            assert (
                configuration == request.configuration
                and expected_receipt_raw_sha256 == request.receipt_raw_sha256
            )
            self.configuration_sha256 = configuration.configuration_sha256
            self.inventory, self.host = inventory, object()

        def assert_current(self):
            if self.closed or state.installation_drift:
                raise ValueError("synthetic installation drift")

        def close(self):
            self.closed = True
            state.closed = True

    real_lstat, real_stat = Path.lstat, Path.stat

    def lstat(path, *args, **kwargs):
        if path == execution / "input-grant.json":
            if not state.grant_exists:
                raise FileNotFoundError(path)
            return metadata(77)
        return identities[path] if path in identities else real_lstat(path, *args, **kwargs)

    def descriptor_value(number):
        targets = {0: "input.json", 4: "allocation.json", 5: "result.json", 6: "vectors.f32"}
        if number == 7 and state.output_alias:
            number = 5
        if number in targets:
            return identities[execution / targets[number]]
        if number in (1, 2):
            return metadata(9, mode=stat.S_IFCHR | 0o666, rdev=os.makedev(1, 3))
        return metadata(1000 + number, mode=stat.S_IFSOCK | 0o600)

    def file_stat(path, *args, **kwargs):
        if path.parent == Path("/proc/123/fd"):
            return descriptor_value(int(path.name))
        if path == Path("/proc/123/cwd"):
            return identities[observer.CUDA_LOADER_EMPTY_DIRECTORY]
        return real_stat(path, *args, **kwargs)

    def read(path, *, maximum, owner_uid):
        assert owner_uid == 1234 and path.parts[1:3] == ("proc", "123")
        if path.parent.name == "fdinfo":
            number = int(path.name)
            position = len(data[execution / "allocation.json"]) if number == 4 else 0
            flags = (
                os.O_RDONLY | os.O_CLOEXEC
                if number == 4
                else os.O_RDONLY
                if number == 0
                else os.O_WRONLY | (os.O_CLOEXEC if number >= 5 else 0)
            )
            return (
                f"pos:\t{state.fd_positions.get(number, position)}\n"
                f"flags:\t{state.fd_flags.get(number, flags):o}\n"
                f"mnt_id:\t7\nino:\t{descriptor_value(number).st_ino}\n"
            ).encode()
        return {
            "stat": process_stat(123, start=state.start),
            "status": state.status,
            "cgroup": state.cgroup,
            "cmdline": state.command,
            "maps": state.maps,
        }[path.name]

    def unit(*args, **kwargs):
        state.unit_calls += 1
        return (
            replace(state.unit, invocation_id="c" * 32)
            if state.late == "unit" and state.unit_calls > 1
            else state.unit
        )

    def resources(*args, **kwargs):
        state.resource_calls += 1
        return (
            replace(state.resources, pid1_descriptor=81)
            if state.late == "resources" and state.resource_calls > 1
            else state.resources
        )

    def policy(_):
        state.policy_calls += 1
        return "sha256:" + ("c" if state.late == "policy" and state.policy_calls > 1 else "b") * 64

    @contextmanager
    def scan(path):
        assert path == Path("/proc/123/fd")
        yield iter(SimpleNamespace(name=name) for name in state.fd_names)

    monkeypatch.setattr(
        observer,
        "os",
        SimpleNamespace(
            getresuid=lambda: (0, 0, 0),
            getpid=lambda: 456,
            listxattr=lambda _: [],
            listdir=lambda _: state.tasks,
            scandir=scan,
            major=os.major,
            minor=os.minor,
            O_RDONLY=os.O_RDONLY,
            O_WRONLY=os.O_WRONLY,
            O_APPEND=os.O_APPEND,
            O_PATH=os.O_PATH,
            O_CLOEXEC=os.O_CLOEXEC,
            O_ACCMODE=os.O_ACCMODE,
        ),
    )
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", file_stat)
    monkeypatch.setattr(observer, "_accounts", lambda: (1234, 1234, 2468))
    monkeypatch.setattr(observer, "fixed_owner_identity", lambda: SimpleNamespace(owner_gid=990))
    monkeypatch.setattr(
        observer,
        "validate_embedding_gpu_batch_original",
        lambda *_: data[execution / "allocation.json"],
    )
    monkeypatch.setattr(
        observer,
        "validate_embedding_gpu_batch_reconciliation_pins",
        lambda *_: data[execution / "allocation.json"],
    )
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: state.now)
    monkeypatch.setattr(observer, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(observer, "ProtectedCudaInstallationFiles", Installation)
    monkeypatch.setattr(
        observer,
        "read_pinned_cuda_admission_receipt",
        lambda *_a, **_kw: (
            SimpleNamespace(device_capture=ready.expected_device_capture),
            b"receipt",
        ),
    )
    monkeypatch.setattr(observer, "read_live_runtime_os_file", read)
    monkeypatch.setattr(observer, "inspect_cpu_unit", unit)
    monkeypatch.setattr(observer, "root_owned_unit_processes", lambda _: state.pids)
    monkeypatch.setattr(observer, "observe_embedding_gpu_batch_unit_policy", policy)
    monkeypatch.setattr(observer, "observe_embedding_gpu_allocation_resources", resources)
    monkeypatch.setattr(observer, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(observer, "observe_cuda_probe_gpu_clients", lambda _: state.clients)
    monkeypatch.setattr(
        observer,
        "validate_native_cuda_executable_mappings",
        lambda raw, **_: parse_native_executable_mappings(raw),
    )
    return state


def test_exact_ready_has_independent_original_files_unit_pid_and_physical_observations(machine):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    result = observer.observe_embedding_gpu_batch_ready(captured, machine.ready)
    assert result.readiness == machine.ready and result.unit == machine.unit
    assert result.resources is machine.resources and machine.resource_calls == 2
    assert result.cgroup == "/system.slice/" + machine.unit_name
    assert machine.policy_calls == 2 and not hasattr(result, "source_authorized")
    captured.close()
    assert machine.closed
    with pytest.raises(ValueError):
        captured.assert_current()


@pytest.mark.parametrize(
    "fault",
    [
        "service",
        "socket",
        "entry",
        "allocation",
        "environment",
        "input",
        "output",
        "alias",
        "grant",
        "install",
    ],
)
def test_capture_rejects_original_file_runtime_or_precompute_drift(machine, fault):
    execution = observer.GPU_BATCH_RUNTIME_ROOT / machine.launch.attempt_hex
    if fault in ("service", "socket", "entry", "allocation", "environment"):
        path = {
            "service": Path("/etc/systemd/system") / observer.GPU_BATCH_TEMPLATE,
            "socket": Path("/etc/systemd/system") / observer.GPU_BATCH_SOCKET_TEMPLATE,
            "entry": observer._PREFIX / observer._ENTRY_MEMBER,
            "allocation": execution / "allocation.json",
            "environment": execution / "launch.env",
        }[fault]
        machine.data[path] += b"bad"
    elif fault in ("input", "output"):
        machine.identities[
            execution / ("input.json" if fault == "input" else "result.json")
        ].st_size = 1
    elif fault == "alias":
        machine.identities[execution / "result.json"] = machine.identities[
            execution / "vectors.f32"
        ]
    elif fault == "grant":
        machine.grant_exists = True
    else:
        machine.installation_drift = True
    with pytest.raises(ValueError):
        observer.capture_embedding_gpu_batch_machine(machine.prepared)
    assert machine.closed


@pytest.mark.parametrize(
    "fault",
    [
        "root",
        "unit",
        "pid",
        "birth",
        "uid",
        "thread",
        "cgroup",
        "pids",
        "argv",
        "cwd",
        "GPU_client",
        "input_offset",
        "metadata_offset",
        "output_flags",
        "duplicate_output",
        "missing_fd",
        "late_unit",
        "late_policy",
        "late_resources",
    ],
)
def test_claimed_ready_never_masks_changed_machine_or_descriptor(machine, monkeypatch, fault):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    ready = machine.ready
    if fault == "root":
        monkeypatch.setattr(observer.os, "getresuid", lambda: (0, 1234, 0))
    elif fault == "unit":
        machine.unit = replace(machine.unit, main_pid=124)
    elif fault == "pid":
        ready = ready.model_copy(update={"pid": 124})
    elif fault == "birth":
        machine.start += 1
    elif fault == "uid":
        machine.status = machine.status.replace(b"Uid:\t1234", b"Uid:\t9999")
    elif fault == "thread":
        machine.tasks.append("124")
    elif fault == "cgroup":
        machine.cgroup = b"0::/different.slice/untrusted.service\n"
    elif fault == "pids":
        machine.pids = (123, 124)
    elif fault == "argv":
        machine.command += b"--model=other\0"
    elif fault == "cwd":
        current = machine.identities[observer.CUDA_LOADER_EMPTY_DIRECTORY]
        machine.identities[observer.CUDA_LOADER_EMPTY_DIRECTORY] = metadata(
            current.st_ino + 1, mode=current.st_mode
        )
    elif fault == "GPU_client":
        machine.clients = (123,)
    elif fault == "input_offset":
        machine.fd_positions[0] = 1
    elif fault == "metadata_offset":
        machine.fd_positions[4] = 0
    elif fault == "output_flags":
        machine.fd_flags[5] = os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC
    elif fault == "duplicate_output":
        machine.output_alias = True
        machine.fd_names.append("7")
    elif fault == "missing_fd":
        machine.fd_names.remove("5")
    else:
        machine.late = fault.removeprefix("late_")
    with pytest.raises(ValueError):
        observer.observe_embedding_gpu_batch_ready(captured, ready)
    captured.close()


def test_source_constants_pin_the_actual_new_assets_and_keep_old_index_separate():
    assert (
        sha256_bytes((ROOT / "infra/systemd" / observer.GPU_BATCH_TEMPLATE).read_bytes())
        == observer._SERVICE_SHA
    )
    assert (
        sha256_bytes((ROOT / "infra/systemd" / observer.GPU_BATCH_SOCKET_TEMPLATE).read_bytes())
        == observer._SOCKET_SHA
    )
    assert (
        sha256_bytes(
            (
                ROOT / "services/catalog_service/eom_catalog_service/embedding_gpu_batch_entry.py"
            ).read_bytes()
        )
        == observer._ENTRY_SHA
    )


def test_dangling_intent_is_not_treated_as_absent(machine, tmp_path, monkeypatch):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    execution = tmp_path / machine.launch.attempt_hex
    execution.mkdir()
    intent = execution / "input-grant.json"
    intent.symlink_to("missing-intent.json")
    assert intent.is_symlink() and not intent.exists()
    monkeypatch.setattr(observer, "GPU_BATCH_RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(observer.CapturedEmbeddingGpuBatchMachine, "assert_current", lambda _: None)
    monkeypatch.setattr(observer, "_member", lambda *args, **kwargs: machine.prepared.input_epoch)
    with pytest.raises(ValueError):
        captured.assert_precompute()
    captured.close()


def test_controller_restart_can_recapture_original_facts_but_cannot_resume_compute(
    machine, monkeypatch
):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    original = observer.observe_embedding_gpu_batch_ready(captured, machine.ready)
    captured.close()
    monkeypatch.setattr(observer.os, "getpid", lambda: 999)
    execution = observer.GPU_BATCH_RUNTIME_ROOT / machine.launch.attempt_hex
    machine.identities[execution / "input.json"].st_size = 7
    machine.grant_exists = True
    restored = observer.capture_embedding_gpu_batch_reconciliation(machine.prepared, original)
    restored.assert_current()
    assert restored.prepared == captured.prepared
    with pytest.raises(ValueError):
        restored.assert_precompute()
    with pytest.raises(ValueError):
        observer.observe_embedding_gpu_batch_ready(restored, machine.ready)
    restored.close()


@pytest.mark.parametrize("member", ["input.json", "allocation.json", "result.json"])
def test_restart_cannot_substitute_new_inodes_for_the_original_record(machine, monkeypatch, member):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    original = observer.observe_embedding_gpu_batch_ready(captured, machine.ready)
    captured.close()
    monkeypatch.setattr(observer.os, "getpid", lambda: 999)
    path = observer.GPU_BATCH_RUNTIME_ROOT / machine.launch.attempt_hex / member
    machine.identities[path].st_ino += 1
    with pytest.raises(ValueError):
        observer.capture_embedding_gpu_batch_reconciliation(machine.prepared, original)

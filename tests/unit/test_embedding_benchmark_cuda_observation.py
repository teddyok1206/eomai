"""Synthetic root file/unit/kernel read ports, not a real root ACK, Job or CUDA run."""

import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
    BenchmarkCudaReady,
    benchmark_cuda_ready_bytes,
)
from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes
from eom_catalog_service import embedding_benchmark_cuda_observation as owner
from eom_catalog_service import gpu_unit_policy_observation as policy
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_launch_arguments,
    benchmark_launch_environment_bytes,
    parse_benchmark_launch_pins,
)
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
)
from eom_catalog_service.embedding_runtime_files import ObservedRuntimeMemberBytes
from eom_identifiers import sha256_bytes

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_cuda_environment import cuda_metadata
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import maps, process_stat, running
from tests.unit.test_image_gpu_unit_observation import policy as image_policy

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def benchmark(monkeypatch, ledger):
    metadata = cuda_metadata("2.1")
    invocation = metadata.invocation
    raw = embedding_device_benchmark_bytes(invocation)
    pins = BenchmarkLaunchPins(
        invocation.execution_id,
        sha256_bytes(raw),
        456,
        time.monotonic_ns() + 30 * 10**9,
        metadata.backend,
    )
    env_raw = benchmark_launch_environment_bytes(pins)
    environment = PreparedBenchmarkEnvironment(
        invocation.execution_id,
        invocation.job_id,
        sha256_bytes(env_raw),
        456,
        4321,
        pins.expires_ns,
    )
    _, template = benchmark_cuda_ready()
    body = template.model_dump(mode="json", exclude={"ready_sha256"})
    body.update(
        configuration=dict(
            configuration_id=metadata.backend.configuration_id,
            configuration_revision_id=metadata.backend.configuration_revision_id,
            configuration_sha256=metadata.backend.configuration_sha256,
            configuration_raw_sha256=metadata.backend.configuration_raw_sha256,
        ),
        invocation_raw_sha256=sha256_bytes(raw),
        receipt_raw_sha256=metadata.backend.receipt_raw_sha256,
    )
    ready = BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
    unit = owner.CUDA_BENCHMARK_TEMPLATE.replace(
        "@.service", "@" + invocation.execution_id + ".service"
    )
    invocation_path = owner._ROOT / invocation.execution_id
    admission = Path("/opt/eom/embedding-runtime-admission")
    arguments = (
        str(owner._PREFIX / "bin/python3.12"),
        "-I",
        "-B",
        "-m",
        "eom_catalog_service.embedding_benchmark_cuda",
        *benchmark_launch_arguments(pins),
    )
    status = (
        "Pid:\t123\nTgid:\t123\nThreads:\t1\nUid:\t1234 1234 1234 1234\n"
        "Gid:\t1234 1234 1234 1234\nGroups:\t1234 2468\nNoNewPrivs:\t1\n"
        + "\n".join(
            f"{key}:\t0000000000000000"
            for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        + f"\nSigBlk:\t{1 << (signal.SIGUSR1 - 1):016x}\n"
    ).encode()
    files = {
        Path("/etc/systemd/system") / name: (ROOT / "infra/systemd" / name).read_bytes()
        for name in (owner.CUDA_BENCHMARK_TEMPLATE, owner.CUDA_BENCHMARK_SOCKET)
    }
    files.update(
        {
            invocation_path / "invocation.json": raw,
            invocation_path / "launch.env": env_raw,
            admission
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "receipt.json": metadata.receipt_raw,
            admission / "schemas" / metadata.receipt_schema_name: metadata.receipt_schema,
        }
    )
    inventory, host, _ = ledger
    directory, regular = inventory.entries
    extra = [
        replace(directory, relative_member=name)
        for name in (
            "lib",
            "lib/python3.12",
            "lib/python3.12/site-packages",
            "lib/python3.12/site-packages/eom_catalog_service",
        )
    ]
    extra.extend(
        replace(
            regular,
            relative_member="lib/python3.12/site-packages/eom_catalog_service/" + name,
            sha256=digest,
        )
        for name, digest in owner._READY_IMPLEMENTATIONS
    )
    inventory = replace(
        inventory,
        prefix=owner._PREFIX,
        entries=tuple(
            sorted((*inventory.entries, *extra), key=lambda entry: entry.relative_member)
        ),
    )
    from tests.unit.test_embedding_cuda_nvml_admission import metadata as facts

    receipt = facts()["receipt"]
    state = SimpleNamespace(
        invocation=invocation,
        environment=environment,
        backend=metadata.backend,
        inventory=inventory,
        host=host,
        pins=pins,
        ready=ready,
        unit_name=unit,
        unit=replace(
            running(), fragment_path="/etc/systemd/system/" + owner.CUDA_BENCHMARK_TEMPLATE
        ),
        files=files,
        reads=[],
        ready_reads=0,
        snapshots=0,
        drift=False,
        status=status,
        start=ready.start_time_ticks,
        cgroup="0::/system.slice/" + unit + "\n",
        pids=(123,),
        tasks=["123"],
        owner_birth=4321,
        cwd=55,
        command=b"\0".join(value.encode() for value in arguments) + b"\0",
        maps=maps(path=owner._PREFIX / "bin/python3.12"),
        maps_reads=0,
        resources=CudaProbeResourceObservation(receipt.device_nodes, receipt.shared_gpu_lease, 80),
        resource_calls=0,
        clients=(),
        policy=image_policy().replace(b"eom-image", b"eom-embedding-cuda"),
        policy_calls=0,
        ready_mode=0o640,
        env_mode=0o600,
        env_gid=0,
        ready_gid=990,
        acl=[],
        env_acl=[],
        fault=None,
    )

    class Files:
        def __init__(self, uid=0):
            assert uid in {0, 1234}
            self.uid = uid

        def read(self, path, *, sha256, maximum):
            state.reads.append(path)
            value = state.files[path]
            if sha256_bytes(value) != sha256 or len(value) > maximum:
                raise ValueError("synthetic protected byte mismatch")
            return value

        def observe_protected_member_bytes(self, path, *, maximum):
            assert self.uid == 1234 and path == invocation_path / "cuda-ready.json"
            value = benchmark_cuda_ready_bytes(state.ready)
            assert len(value) <= maximum
            state.ready_reads += 1
            return ObservedRuntimeMemberBytes(sha256_bytes(value), len(value), value)

        def observe_empty_directory(self, path):
            assert self.uid == 0 and path == owner.CUDA_LOADER_EMPTY_DIRECTORY

        def assert_unchanged(self):
            state.snapshots += 1
            if state.drift:
                raise ValueError("synthetic protected epoch drift")

    def read(path, *, maximum, owner_uid):
        assert path.parent == Path("/proc/123") and owner_uid == 1234
        if path.name == "maps":
            state.maps_reads += 1
            if state.fault == "late_maps" and state.maps_reads > 1:
                return maps(path=owner._PREFIX / "wrong")
        return {
            "stat": process_stat(123, start=state.start),
            "status": state.status,
            "cgroup": state.cgroup.encode(),
            "cmdline": state.command,
            "maps": state.maps,
        }[path.name]

    def resources(*_args, **kwargs):
        assert kwargs == dict(unit=unit, lease_gid=2468)
        state.resource_calls += 1
        return (
            replace(state.resources, pid1_descriptor=81)
            if state.fault == "late_resources" and state.resource_calls > 1
            else state.resources
        )

    def policy_read(*_args, **_kwargs):
        assert _args[0][:3] == ("/usr/bin/systemctl", "show", unit)
        assert not {"start", "stop", "kill", "reset-failed", "clean"}.intersection(_args[0])
        state.policy_calls += 1
        value = state.policy
        if state.fault == "late_policy" and state.policy_calls > 1:
            value = value.replace(b"Restart=no", b"Restart=always")
        return SimpleNamespace(returncode=0, stdout=value, stderr=b"")

    original_lstat, original_stat = Path.lstat, Path.stat

    def lstat(path, *args, **kwargs):
        if path == owner.CUDA_LOADER_EMPTY_DIRECTORY:
            return SimpleNamespace(st_dev=1, st_ino=55)
        if path == invocation_path / "cuda-ready.json":
            return SimpleNamespace(st_mode=stat.S_IFREG | state.ready_mode, st_gid=state.ready_gid)
        if path in {invocation_path / "invocation.json", invocation_path / "launch.env"}:
            return SimpleNamespace(st_mode=stat.S_IFREG | state.env_mode, st_gid=state.env_gid)
        return original_lstat(path, *args, **kwargs)

    def file_stat(path, *args, **kwargs):
        if path == Path("/proc/123/cwd"):
            return SimpleNamespace(st_dev=1, st_ino=state.cwd)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(owner.os, "getgrouplist", lambda *_a: [1234, 2468])
    original_listdir = os.listdir
    monkeypatch.setattr(
        owner.os,
        "listdir",
        lambda path: (
            state.tasks if Path(path) == Path("/proc/123/task") else original_listdir(path)
        ),
    )
    monkeypatch.setattr(
        owner.os,
        "listxattr",
        lambda path: state.acl if path.name == "cuda-ready.json" else state.env_acl,
    )
    monkeypatch.setattr(
        owner.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(
            pw_name=name,
            pw_uid=990 if name == "eom-workflow-runner" else 1234,
            pw_gid=990 if name == "eom-workflow-runner" else 1234,
        ),
    )
    monkeypatch.setattr(
        owner.grp,
        "getgrnam",
        lambda name: SimpleNamespace(gr_gid=2468 if name == "eom-gpu-lease" else 1234),
    )
    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(
        owner,
        "_read_ready_member",
        lambda path, files: files.observe_protected_member_bytes(
            path, maximum=owner.MAX_BENCHMARK_CUDA_READY_BYTES
        ),
    )
    monkeypatch.setattr(owner, "benchmark_owner_start_ticks", lambda *_a, **_kw: state.owner_birth)
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *_a, **_kw: state.unit)
    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    monkeypatch.setattr(owner, "root_owned_unit_processes", lambda _u: state.pids)
    monkeypatch.setattr(owner, "observe_benchmark_cuda_ready_resources", resources)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _d: None)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda _d: state.clients)
    monkeypatch.setattr(policy.subprocess, "run", policy_read)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", file_stat)
    return state


def observe(state):
    return owner.observe_benchmark_cuda_ready(
        state.invocation,
        state.environment,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )


def test_root_readback_binds_ready_environment_runtime_process_maps_and_both_locks(benchmark):
    observed = observe(benchmark)
    assert observed.job_id == benchmark.invocation.job_id
    assert observed.unit == benchmark.unit and observed.pid == 123
    assert observed.start_time_ticks == benchmark.ready.start_time_ticks
    assert observed.ready_raw_sha256 == sha256_bytes(benchmark_cuda_ready_bytes(benchmark.ready))
    assert observed.environment_raw_sha256 == benchmark.environment.environment_raw_sha256
    assert observed.resources is benchmark.resources
    assert benchmark.resource_calls == 2 and benchmark.policy_calls == 2
    assert benchmark.ready_reads == 1 and benchmark.snapshots > 3


@pytest.mark.parametrize(
    "fault",
    (
        "root",
        "environment",
        "owner",
        "expired",
        "template",
        "socket",
        "invocation",
        "launch",
        "receipt",
        "ready_uid",
        "ready_gid",
        "ready_mode",
        "ready_acl",
        "env_mode",
        "env_gid",
        "env_acl",
        "policy_user",
        "unit_pid",
        "unit_status",
        "invocation_id",
        "pid_birth",
        "cgroup",
        "members",
        "uid",
        "caps",
        "groups",
        "signal",
        "thread",
        "task",
        "command",
        "cwd",
        "gpu_busy",
        "late_maps",
        "late_resources",
        "late_policy",
        "file_drift",
        "old_writer",
        "missing_entry",
    ),
)
def test_changed_or_unproven_frame_is_refused_without_any_effect(benchmark, monkeypatch, fault):
    s = benchmark
    s.fault = fault
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "environment":
        s.environment = replace(s.environment, job_id="job_" + "a" * 32)
    elif fault == "owner":
        s.owner_birth += 1
    elif fault == "expired":
        monkeypatch.setattr(owner.time, "monotonic_ns", lambda: s.pins.expires_ns)
    elif fault in {"template", "socket", "invocation", "launch", "receipt"}:
        name = {
            "template": owner.CUDA_BENCHMARK_TEMPLATE,
            "socket": owner.CUDA_BENCHMARK_SOCKET,
            "invocation": "invocation.json",
            "launch": "launch.env",
            "receipt": "receipt.json",
        }[fault]
        path = next(path for path in s.files if path.name == name)
        s.files[path] += b"x"
    elif fault == "ready_uid":
        body = s.ready.model_dump(mode="json", exclude={"ready_sha256"})
        body["worker_uid"] += 1
        s.ready = BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
    elif fault == "ready_gid":
        s.ready_gid += 1
    elif fault == "ready_mode":
        s.ready_mode = 0o660
    elif fault == "ready_acl":
        s.acl = ["system.posix_acl_access"]
    elif fault == "env_mode":
        s.env_mode = 0o644
    elif fault == "env_gid":
        s.env_gid = 990
    elif fault == "env_acl":
        s.env_acl = ["system.posix_acl_access"]
    elif fault == "policy_user":
        s.policy = s.policy.replace(b"User=eom-embedding-cuda", b"User=eom-image")
    elif fault == "unit_pid":
        s.unit = replace(s.unit, main_pid=124)
    elif fault == "unit_status":
        s.unit = replace(s.unit, status=replace(s.unit.status, active_state="active"))
    elif fault == "invocation_id":
        s.unit = replace(s.unit, invocation_id="")
    elif fault == "pid_birth":
        s.start += 1
    elif fault == "cgroup":
        s.cgroup = "0::/system.slice/another.service\n"
    elif fault == "members":
        s.pids = (123, 124)
    elif fault == "uid":
        s.status = s.status.replace(b"Uid:\t1234", b"Uid:\t1235")
    elif fault == "caps":
        s.status = s.status.replace(b"CapEff:\t0000000000000000", b"CapEff:\t0000000000000001")
    elif fault == "groups":
        s.status = s.status.replace(b"Groups:\t1234 2468", b"Groups:\t1234 2468 9999")
    elif fault == "signal":
        s.status = s.status.replace(
            f"{1 << (signal.SIGUSR1 - 1):016x}".encode(), b"0000000000000000"
        )
    elif fault == "thread":
        s.status = s.status.replace(b"Threads:\t1", b"Threads:\t2")
    elif fault == "task":
        s.tasks = ["123", "124"]
    elif fault == "command":
        s.command += b"extra\0"
    elif fault == "cwd":
        s.cwd += 1
    elif fault == "gpu_busy":
        s.clients = (777,)
    elif fault == "file_drift":
        s.drift = True
    elif fault == "old_writer":
        s.inventory = replace(
            s.inventory,
            entries=tuple(
                replace(entry, sha256="sha256:" + "a" * 64)
                if entry.relative_member.endswith("embedding_device_benchmark_files.py")
                else entry
                for entry in s.inventory.entries
            ),
        )
    elif fault == "missing_entry":
        s.inventory = replace(
            s.inventory,
            entries=tuple(
                entry
                for entry in s.inventory.entries
                if not entry.relative_member.endswith("embedding_benchmark_cuda.py")
            ),
        )
    with pytest.raises(ValueError):
        observe(s)


def test_common_environment_and_cli_roundtrip_has_one_authoritative_encoding(benchmark):
    assert parse_benchmark_launch_pins(benchmark_launch_arguments(benchmark.pins)) == benchmark.pins
    expected = benchmark.files[owner._ROOT / benchmark.invocation.execution_id / "launch.env"]
    assert benchmark_launch_environment_bytes(benchmark.pins) == expected


def test_fresh_actual_api_identity_cannot_enter_root_observation():
    if os.getuid() == 0:
        pytest.skip("This negative requires the ordinary API test identity")
    code = (
        "import sys;from eom_catalog_service.embedding_benchmark_cuda_observation "
        "import observe_benchmark_cuda_ready\n"
        "try:observe_benchmark_cuda_ready(None,None,backend=None,inventory=None,host=None)\n"
        "except ValueError as e:assert str(e)=='BENCHMARK_CUDA_OBSERVATION_ROOT_REQUIRED'\n"
        "else:raise AssertionError('wrong root identity admitted')\n"
        "assert not {'torch','numpy','transformers','eom_gpu_lease'}.intersection(sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=20)
    assert result.returncode == 0 and not result.stdout and not result.stderr


def test_reviewed_ready_implementations_and_fixed_unit_bytes_are_exact():
    for name, digest in owner._READY_IMPLEMENTATIONS:
        assert (
            sha256_bytes(
                (ROOT / "services/catalog_service/eom_catalog_service" / name).read_bytes()
            )
            == digest
        )
    for name, digest in (
        (owner.CUDA_BENCHMARK_TEMPLATE, owner.CUDA_BENCHMARK_TEMPLATE_SHA256),
        (owner.CUDA_BENCHMARK_SOCKET, owner.CUDA_BENCHMARK_SOCKET_SHA256),
    ):
        assert sha256_bytes((ROOT / "infra/systemd" / name).read_bytes()) == digest

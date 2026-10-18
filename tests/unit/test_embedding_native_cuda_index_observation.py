"""Synthetic root observation ports; no installed INDEX, root ACK, GPU or model proof."""

from __future__ import annotations

import ast
import fcntl
import os
import signal
import stat
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_native_cuda_index_ready import (
    NativeCudaIndexReady,
    native_cuda_index_ready_bytes,
)
from eom_catalog_service import embedding_native_cuda_index_observation as observer
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
)
from eom_catalog_service.embedding_native_cuda_index_entry import NativeCudaIndexLaunchPins
from eom_catalog_service.embedding_runtime_files import ObservedRuntimeMemberBytes
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_cuda_nvml_admission import metadata as cuda_facts
from tests.unit.test_embedding_cuda_probe_resource_files import metadata as kernel_metadata
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import maps, process_stat, running, terminal

ROOT = Path(__file__).resolve().parents[2]
REAL_FLOCK = fcntl.flock
owner: Any = observer


def metadata(mode: int, inode: int, *, gid: int = 0, size: int = 0, rdev: int = 0) -> Any:
    port: Any = kernel_metadata
    value = port(mode, inode, gid=gid, rdev=rdev)
    value.st_size = size
    return value


@pytest.fixture
def observed(monkeypatch: pytest.MonkeyPatch, ledger: Any) -> Any:
    fixture = native_fixture(device="CUDA")
    request = fixture.native_input
    launch = NativeCudaIndexLaunchPins(
        "a" * 32,
        request.job_id,
        fixture.association.association_sha256,
        fixture.association.owned_input.sha256,
        100_000_000_000,
        "embeddingnativeconfig_" + "c" * 32,
        "embeddingnativeconfigrev_" + "d" * 32,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "sha256:" + "1" * 64,
    )
    facts_port: Any = cuda_facts
    facts = facts_port()["receipt"]
    device = facts.device_capture
    body = {
        "schema_version": "embedding-native-cuda-index-ready/1.0",
        "purpose": "INDEX",
        "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
        "execution_id": launch.execution_id,
        "job_id": launch.job_id,
        "launch_association_sha256": launch.association_sha256,
        "input_raw_sha256": launch.input_raw_sha256,
        "request_sha256": request.request_sha256,
        "input_set_sha256": request.input_set_sha256,
        "configuration": {
            "configuration_id": launch.configuration_id,
            "configuration_revision_id": launch.configuration_revision_id,
            "configuration_sha256": launch.configuration_sha256,
            "configuration_raw_sha256": launch.configuration_raw_sha256,
        },
        "receipt_raw_sha256": launch.receipt_raw_sha256,
        "fdstore_name": "eom-gpu0-lease",
        "pid": 123,
        "start_time_ticks": 987,
        "worker_uid": 1234,
        "worker_gid": 1234,
        "supplementary_gids": [2468],
        "resource_fds": {
            "nvidia0_fd": 10,
            "nvidiactl_fd": 11,
            "nvidia_uvm_fd": 12,
            "nvidia_uvm_tools_fd": 13,
            "lease_fd": 14,
        },
        "expected_device_capture": device.model_dump(mode="json"),
        **dict.fromkeys(
            (
                "cuda_initialization_calls",
                "cuda_synchronize_calls",
                "model_constructor_calls",
                "tokenizer_constructor_calls",
                "forward_calls",
            ),
            0,
        ),
    }
    ready = NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))
    execution = owner.CUDA_INDEX_RUNTIME_ROOT / launch.execution_id
    files = {
        Path("/etc/systemd/system") / owner.CUDA_INDEX_TEMPLATE: (
            ROOT / "infra/systemd" / owner.CUDA_INDEX_TEMPLATE
        ).read_bytes(),
        owner.CUDA_INDEX_ENTRY: (
            ROOT
            / "services/catalog_service/eom_catalog_service/embedding_native_cuda_index_entry.py"
        ).read_bytes(),
        execution / "input.json": canonical_json_bytes(request.model_dump(mode="json")),
        execution / "launch.env": owner.native_cuda_index_launch_environment_bytes(launch),
        execution / "ready.json": native_cuda_index_ready_bytes(ready),
    }
    state = SimpleNamespace(
        launch=launch,
        request=request,
        ready=ready,
        files=files,
        metadata={},
        reads=[],
        closes=[],
        flock=[],
        locked=False,
        drift=False,
        installation_drift=False,
        closed=False,
        installation_calls=[],
        ready_reads=0,
        fault=None,
        unit=replace(running(), fragment_path="/etc/systemd/system/" + owner.CUDA_INDEX_TEMPLATE),
        unit_name=owner.native_cuda_index_unit(launch.execution_id),
        pid_exists=True,
        start=987,
        owner_birth=4321,
        owner_gone=False,
        pids=(123,),
        tasks=["123"],
        now=1_000_000_000,
        clients=(),
        policy="sha256:" + "2" * 64,
        policy_calls=0,
        resource_calls=0,
        resource=CudaProbeResourceObservation(facts.device_nodes, facts.shared_gpu_lease, 80),
        fd_names=["0", "1", "2", "3", "41", "57", "99"],
        fd_positions={},
        fd_flags={},
        aliases={},
        snapshots=0,
    )
    for index, path in enumerate(files, 20):
        mode = (
            0o600
            if path.name in {"input.json", "launch.env"}
            else 0o640
            if path.name == "ready.json"
            else 0o644
        )
        gid = 990 if path.parent == execution else 0
        state.metadata[path] = metadata(stat.S_IFREG | mode, index, gid=gid, size=len(files[path]))
    for index, name in enumerate(("result.json", "vectors.f32"), 40):
        state.metadata[execution / name] = metadata(stat.S_IFREG | 0o640, index, gid=990, size=0)
    for path in (owner.CUDA_INDEX_RUNTIME_ROOT, execution):
        state.metadata[path] = metadata(stat.S_IFDIR | 0o750, 88, gid=990)
    state.metadata[owner.CUDA_LOADER_EMPTY_DIRECTORY] = metadata(stat.S_IFDIR | 0o555, 55)
    state.status = (
        "Pid:\t123\nTgid:\t123\nThreads:\t1\nUid:\t1234 1234 1234 1234\n"
        "Gid:\t1234 1234 1234 1234\nGroups:\t1234 2468\nNoNewPrivs:\t1\n"
        + "\n".join(
            f"{key}:\t0000000000000000"
            for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        + f"\nSigBlk:\t{1 << (signal.SIGUSR1 - 1):016x}\n"
    ).encode()
    state.cgroup = f"0::/system.slice/{state.unit_name}\n".encode()
    state.arguments = (
        str(owner._PREFIX / "bin/python3.12"),
        "-I",
        "-B",
        str(owner.CUDA_INDEX_ENTRY),
        *owner.native_cuda_index_launch_arguments(launch),
    )
    state.command = b"\0".join(value.encode() for value in state.arguments) + b"\0"
    state.maps = maps(path=owner._PREFIX / "bin/python3.12")
    inventory, host, _checks = ledger
    inventory = replace(inventory, prefix=owner._PREFIX)
    real_lstat, real_stat = Path.lstat, Path.stat

    def lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path in state.metadata:
            return state.metadata[path]
        if path == Path("/proc/123"):
            if not state.pid_exists:
                raise FileNotFoundError(path)
            return SimpleNamespace(st_uid=1234)
        return real_lstat(path, *args, **kwargs)

    def fd_metadata(number: int) -> Any:
        target = {0: "input.json", 3: "ready.json", 41: "result.json", 57: "vectors.f32"}
        number = state.aliases.get(number, number)
        if number in target:
            return state.metadata[execution / target[number]]
        if number in {1, 2}:
            return metadata(stat.S_IFCHR | 0o666, 9, rdev=os.makedev(1, 3))
        return metadata(stat.S_IFREG | 0o444, 1999)

    def file_stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.parent == Path("/proc/123/fd"):
            return fd_metadata(int(path.name))
        if path == Path("/proc/123/cwd"):
            return state.metadata[owner.CUDA_LOADER_EMPTY_DIRECTORY]
        return real_stat(path, *args, **kwargs)

    class Files:
        def __init__(self, uid: int = 0) -> None:
            assert uid == 0
            self.epochs: dict[Path, tuple[int, ...]] = {}

        def read(self, path: Path, *, sha256: str, maximum: int) -> bytes:
            value = state.files[path]
            assert isinstance(value, bytes)
            assert len(value) <= maximum
            if sha256_bytes(value) != sha256:
                raise ValueError("synthetic raw hash mismatch")
            self.epochs[path] = owner._epoch(state.metadata[path])
            state.reads.append(path)
            return value

        def verify(self, path: Path, *, sha256: str, size: int, maximum: int) -> None:
            assert len(self.read(path, sha256=sha256, maximum=maximum)) == size

        def observe_empty_directory(self, path: Path) -> None:
            assert path == owner.CUDA_LOADER_EMPTY_DIRECTORY
            self.epochs[path] = owner._epoch(state.metadata[path])

        def observe_protected_member_bytes(self, path: Path, *, maximum: int) -> Any:
            value = state.files[path]
            assert len(value) <= maximum
            self.epochs[path] = owner._epoch(state.metadata[path])
            state.ready_reads += 1
            return ObservedRuntimeMemberBytes(sha256_bytes(value), len(value), value)

        def assert_unchanged(self) -> None:
            state.snapshots += 1
            if state.drift or any(
                owner._epoch(state.metadata[path]) != epoch for path, epoch in self.epochs.items()
            ):
                raise ValueError("synthetic protected epoch drift")

    class Installation:
        def __init__(self, configuration: Any, *, expected_receipt_raw_sha256: str) -> None:
            assert configuration == ready.configuration
            assert expected_receipt_raw_sha256 == launch.receipt_raw_sha256
            state.installation_calls.append(configuration)
            self.configuration_sha256 = launch.configuration_sha256
            self.inventory, self.host = inventory, host

        def assert_current(self) -> None:
            if state.closed or state.installation_drift:
                raise ValueError("synthetic installation closed/changed")

        def close(self) -> None:
            state.closed = True

    def read(path: Path, *, maximum: int, owner_uid: int) -> bytes:
        if path.parent == Path("/proc/456"):
            assert owner_uid == 990
            if state.owner_gone:
                raise FileNotFoundError(path)
            return (
                process_stat(456, start=state.owner_birth)
                if path.name == "stat"
                else b"Uid:\t990 990 990 990\nGid:\t990 990 990 990\n"
            )
        assert path.parts[1:3] == ("proc", "123") and owner_uid == 1234
        if path.parent.name == "fdinfo":
            number = int(path.name)
            value = fd_metadata(number)
            position = len(state.files[execution / "ready.json"]) if number == 3 else 0
            flags = (
                os.O_RDONLY
                if number == 0
                else os.O_RDWR | os.O_CLOEXEC
                if number == 3
                else os.O_WRONLY | (os.O_CLOEXEC if number >= 4 else 0)
            )
            return (
                f"pos:\t{state.fd_positions.get(number, position)}\n"
                f"flags:\t{state.fd_flags.get(number, flags):o}\n"
                f"mnt_id:\t7\nino:\t{value.st_ino}\n"
            ).encode()
        return bytes(
            {
                "stat": process_stat(123, start=state.start),
                "status": state.status,
                "cgroup": state.cgroup,
                "cmdline": state.command,
                "maps": state.maps,
            }[path.name]
        )

    def resource(*args: Any, **kwargs: Any) -> Any:
        assert kwargs == {"unit": state.unit_name, "lease_gid": 2468}
        state.resource_calls += 1
        return (
            replace(state.resource, pid1_descriptor=81)
            if state.fault == "late_resources" and state.resource_calls > 1
            else state.resource
        )

    def policy(unit: str) -> str:
        assert unit == state.unit_name
        state.policy_calls += 1
        return (
            "changed" if state.fault == "late_policy" and state.policy_calls > 1 else state.policy
        )

    @contextmanager
    def scan(path: Path) -> Any:
        assert path == Path("/proc/123/fd")
        yield iter(SimpleNamespace(name=name) for name in state.fd_names)

    def flock(fd: int, flags: int) -> None:
        assert fd == 901 and flags == fcntl.LOCK_SH | fcntl.LOCK_NB
        state.flock.append((fd, flags))
        if state.locked:
            raise BlockingIOError("synthetic original writer")

    monkeypatch.setattr(
        owner,
        "os",
        SimpleNamespace(
            getresuid=lambda: (0, 0, 0),
            getgrouplist=lambda *_: [1234, 2468],
            listxattr=lambda _: [],
            listdir=lambda _: state.tasks,
            scandir=scan,
            open=lambda path, flags: 901,
            fstat=lambda _: state.metadata[execution / "ready.json"],
            close=lambda fd: state.closes.append(fd),
            major=os.major,
            minor=os.minor,
            **{
                name: getattr(os, name)
                for name in (
                    "O_RDONLY",
                    "O_RDWR",
                    "O_WRONLY",
                    "O_NOFOLLOW",
                    "O_CLOEXEC",
                    "O_NONBLOCK",
                    "O_ACCMODE",
                    "O_APPEND",
                    "O_PATH",
                )
            },
        ),
    )
    monkeypatch.setattr(owner.fcntl, "flock", flock)
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: state.now)
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
        lambda name: SimpleNamespace(
            gr_gid=2468
            if name == "eom-gpu-lease"
            else 990
            if name == "eom-workflow-runner"
            else 1234
        ),
    )
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", file_stat)
    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(owner, "ProtectedCudaInstallationFiles", Installation)
    monkeypatch.setattr(
        owner,
        "read_pinned_cuda_admission_receipt",
        lambda *_a, **_kw: (
            SimpleNamespace(
                device_capture=device, runtime_sha256=request.space.runtime.execution_runtime_sha256
            ),
            b"receipt",
        ),
    )
    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *_a, **_kw: state.unit)
    monkeypatch.setattr(owner, "root_owned_unit_processes", lambda _: state.pids)
    monkeypatch.setattr(owner, "observe_native_cuda_index_ready_resources", resource)
    monkeypatch.setattr(
        owner, "observe_native_cuda_index_retained_resources", lambda value, **_kw: value
    )
    monkeypatch.setattr(owner, "observe_native_cuda_index_unit_policy", policy)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda _: state.clients)
    state.basis = owner.NativeCudaIndexObservationPins(launch, request, 456, 4321)
    state.capture = lambda: owner.capture_native_cuda_index_launch_files(state.basis)
    return state


def test_exact_original_ready_capture_is_frozen_facts_and_owned_close(observed: Any) -> None:
    with observed.capture() as captured:
        result = owner.observe_native_cuda_index_ready(captured)
        assert result.execution_id == observed.launch.execution_id
        assert result.association_sha256 == observed.launch.association_sha256
        assert result.ready_epoch == owner._epoch(
            observed.metadata[captured.execution / "ready.json"]
        )
        assert result.resources is observed.resource and not hasattr(result, "root_ack")
        assert (
            owner.require_native_cuda_index_observation_basis(result, captured)
            == observed.unit_name
        )
        assert observed.ready_reads == 3 and all(row[0] == 901 for row in observed.flock)
        assert len(observed.closes) == 3 and len(observed.installation_calls) == 1
    assert observed.closed
    with pytest.raises(ValueError):
        captured.assert_current()


@pytest.mark.parametrize(
    "fault",
    (
        "root",
        "basis_type",
        "input",
        "environment",
        "entry",
        "input_mode",
        "env_gid",
        "alias",
        "installation",
    ),
)
def test_launch_capture_is_exact_and_closes_owned_installation_on_failure(
    observed: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    execution = owner.CUDA_INDEX_RUNTIME_ROOT / observed.launch.execution_id
    basis = observed.basis
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "basis_type":
        basis = None
    elif fault in {"input", "environment", "entry"}:
        path = (
            owner.CUDA_INDEX_ENTRY
            if fault == "entry"
            else execution / ("input.json" if fault == "input" else "launch.env")
        )
        observed.files[path] += b"bad"
    elif fault == "input_mode":
        value = observed.metadata[execution / "input.json"]
        observed.metadata[execution / "input.json"] = metadata(
            stat.S_IFREG | 0o640, value.st_ino, gid=990, size=value.st_size
        )
    elif fault == "env_gid":
        observed.metadata[execution / "launch.env"] = metadata(
            stat.S_IFREG | 0o600, 77, gid=0, size=len(observed.files[execution / "launch.env"])
        )
    elif fault == "alias":
        observed.metadata[execution / "result.json"] = observed.metadata[execution / "vectors.f32"]
    else:
        observed.installation_drift = True
    with pytest.raises((ValueError, AssertionError)):
        owner.capture_native_cuda_index_launch_files(basis)
    assert observed.closed == (fault not in {"root", "basis_type"})


@pytest.mark.parametrize("fault", ("empty", "writer", "partial_writer"))
def test_incomplete_or_contended_ready_is_not_ready_and_never_parsed(
    observed: Any, fault: str
) -> None:
    captured = observed.capture()
    if fault == "empty":
        path = captured.execution / "ready.json"
        value = observed.metadata[path]
        observed.files[path] = b""
        observed.metadata[path] = metadata(value.st_mode, value.st_ino, gid=990, size=0)
    else:
        observed.locked = True
        if fault == "partial_writer":
            observed.files[captured.execution / "ready.json"] = b"{"
    with pytest.raises(ValueError, match="NOT_READY"):
        owner.observe_native_cuda_index_ready(captured)
    assert observed.ready_reads == 0 and observed.closes == [901]
    if fault == "empty":
        assert observed.flock == []
    else:
        assert observed.flock == [(901, fcntl.LOCK_SH | fcntl.LOCK_NB)]


@pytest.mark.parametrize(
    "fault",
    (
        "owner_birth",
        "owner_gone",
        "expired",
        "future_expiry",
        "worker_birth",
        "cgroup",
        "pids",
        "thread",
        "mask",
        "credentials",
        "argv",
        "cwd",
        "input_offset",
        "ready_offset",
        "ready_cloexec",
        "output_cloexec",
        "output_alias",
        "output_missing",
        "output_bytes",
        "stdout_file",
        "maps",
        "gpu",
        "late_resources",
        "late_policy",
        "drift",
        "installation",
    ),
)
def test_ready_requires_actual_process_descriptors_and_late_physical_equality(
    observed: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    captured = observed.capture()
    if fault == "owner_birth":
        observed.owner_birth += 1
    elif fault == "owner_gone":
        observed.owner_gone = True
    elif fault == "expired":
        observed.now = observed.launch.expires_ns
    elif fault == "future_expiry":
        observed.now = -100_000_000_000
    elif fault == "worker_birth":
        observed.start += 1
    elif fault == "cgroup":
        observed.cgroup = b"0::/wrong\n"
    elif fault == "pids":
        observed.pids = (123, 124)
    elif fault == "thread":
        observed.tasks = ["123", "124"]
    elif fault == "mask":
        observed.status = observed.status.replace(
            f"{1 << (signal.SIGUSR1 - 1):016x}".encode(), b"0000000000000000"
        )
    elif fault == "credentials":
        observed.status = observed.status.replace(b"NoNewPrivs:\t1", b"NoNewPrivs:\t0")
    elif fault == "argv":
        observed.command += b"extra\0"
    elif fault == "cwd":
        monkeypatch.setattr(Path, "stat", lambda *_a, **_kw: metadata(stat.S_IFDIR | 0o555, 999))
    elif fault == "input_offset":
        observed.fd_positions[0] = 1
    elif fault == "ready_offset":
        observed.fd_positions[3] = 0
    elif fault == "ready_cloexec":
        observed.fd_flags[3] = os.O_RDWR
    elif fault == "output_cloexec":
        observed.fd_flags[41] = os.O_WRONLY
    elif fault == "output_alias":
        observed.aliases[57] = 41
    elif fault == "output_missing":
        observed.fd_names.remove("57")
    elif fault == "output_bytes":
        path = captured.execution / "result.json"
        value = observed.metadata[path]
        observed.metadata[path] = metadata(value.st_mode, value.st_ino, gid=990, size=1)
    elif fault == "stdout_file":
        observed.aliases[1] = 41
    elif fault == "maps":
        observed.maps = maps(path=owner._PREFIX / "unknown")
    elif fault == "gpu":
        observed.clients = ("synthetic other client",)
    elif fault in {"late_resources", "late_policy"}:
        observed.fault = fault
    elif fault == "drift":
        observed.drift = True
    else:
        observed.installation_drift = True
    with pytest.raises((ValueError, FileNotFoundError)):
        owner.observe_native_cuda_index_ready(captured)


def test_output_writes_are_not_immutable_metadata_drift_but_ready_rewrite_is(observed: Any) -> None:
    captured = observed.capture()
    ready = owner.observe_native_cuda_index_ready(captured)
    path = captured.execution / "result.json"
    value = observed.metadata[path]
    observed.metadata[path] = metadata(value.st_mode, value.st_ino, gid=990, size=100)
    captured.assert_current()
    path = captured.execution / "ready.json"
    value = observed.metadata[path]
    observed.metadata[path] = SimpleNamespace(
        **(vars(value) | {"st_mtime_ns": value.st_mtime_ns + 1})
    )
    with pytest.raises(ValueError, match="PINNED_BASIS_CHANGED"):
        owner.require_native_cuda_index_observation_basis(ready, captured)


@pytest.mark.parametrize(
    "fault", ("hash", "association", "input", "configuration", "device", "trailing")
)
def test_root_ready_parser_binds_original_selection_and_never_repairs_claims(
    observed: Any, fault: str
) -> None:
    captured = observed.capture()
    body = observed.ready.model_dump(mode="json")
    if fault == "hash":
        body["pid"] += 1
    elif fault == "association":
        body["launch_association_sha256"] = "sha256:" + "0" * 64
    elif fault == "input":
        body["input_raw_sha256"] = "sha256:" + "0" * 64
    elif fault == "configuration":
        body["configuration"]["configuration_revision_id"] = "embeddingnativeconfigrev_" + "0" * 32
    elif fault == "device":
        body["expected_device_capture"]["gpu_uuid"] = "GPU-99999999-2222-3333-4444-555555555555"
    raw = canonical_json_bytes(body if fault == "hash" else seal(body, "ready_sha256"))
    if fault == "trailing":
        raw += b"\n"
    path = captured.execution / "ready.json"
    value = observed.metadata[path]
    observed.files[path] = raw
    observed.metadata[path] = metadata(value.st_mode, value.st_ino, gid=990, size=len(raw))
    with pytest.raises(ValueError):
        owner.observe_native_cuda_index_ready(captured)
    assert observed.resource_calls == 0 and observed.closes == [901]


def test_concurrent_ready_epoch_change_fails_and_closes_our_read_descriptor(
    observed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = observed.capture()
    original = owner.NumericalRuntimeFileSnapshots

    def changing_files(uid: int = 0) -> Any:
        files = original(uid)
        original_read = files.observe_protected_member_bytes

        def changing_read(path: Path, *, maximum: int) -> Any:
            member = original_read(path, maximum=maximum)
            value = observed.metadata[path]
            observed.metadata[path] = SimpleNamespace(
                **(vars(value) | {"st_ctime_ns": value.st_ctime_ns + 1})
            )
            return member

        files.observe_protected_member_bytes = changing_read
        return files

    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", changing_files)
    with pytest.raises(ValueError, match="READY_CHANGED"):
        captured.read_ready_snapshot()
    assert observed.closes == [901]


def test_duplicate_saved_output_handle_is_not_silently_selected(observed: Any) -> None:
    captured = observed.capture()
    observed.fd_names.append("42")
    observed.aliases[42] = 41
    with pytest.raises(ValueError, match="OUTPUT_CHANGED"):
        owner.observe_native_cuda_index_ready(captured)


def test_ready_reader_close_failure_never_returns_observation(
    observed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = observed.capture()

    def failed_close(_descriptor: int) -> None:
        raise OSError("synthetic close uncertainty")

    monkeypatch.setattr(owner.os, "close", failed_close)
    with pytest.raises(OSError, match="close uncertainty"):
        captured.read_ready_snapshot()


def test_terminal_cleanup_basis_survives_owner_exit_and_deadline_without_claiming_retirement(
    observed: Any,
) -> None:
    captured = observed.capture()
    ready = owner.observe_native_cuda_index_ready(captured)
    observed.unit = replace(
        terminal(), fragment_path="/etc/systemd/system/" + owner.CUDA_INDEX_TEMPLATE
    )
    observed.pid_exists, observed.owner_gone, observed.pids = False, True, ()
    observed.now = observed.launch.expires_ns + 1
    result = owner.verify_native_cuda_index_terminal(ready, captured)
    assert result.original_outcome == "SUCCEEDED" and result.ready is ready
    assert not hasattr(result, "retired_unit")
    owner.require_native_cuda_index_processes_ended(ready)


@pytest.mark.parametrize(
    "fault", ("invocation", "started", "live_pid", "nonempty", "gpu", "policy")
)
def test_terminal_requires_original_invocation_ended_process_and_retained_fence(
    observed: Any, fault: str
) -> None:
    captured = observed.capture()
    ready = owner.observe_native_cuda_index_ready(captured)
    observed.unit = replace(
        terminal(), fragment_path="/etc/systemd/system/" + owner.CUDA_INDEX_TEMPLATE
    )
    observed.pid_exists, observed.pids = False, ()
    if fault == "invocation":
        observed.unit = replace(observed.unit, invocation_id="0" * 32)
    elif fault == "started":
        observed.unit = replace(
            observed.unit, status=replace(observed.unit.status, exec_main_started_monotonic=999)
        )
    elif fault == "live_pid":
        observed.pid_exists = True
    elif fault == "nonempty":
        observed.pids = (456,)
    elif fault == "gpu":
        observed.clients = ("synthetic other client",)
    else:
        observed.policy = "changed"
    with pytest.raises(ValueError):
        owner.verify_native_cuda_index_terminal(ready, captured)


def test_real_unprivileged_exclusive_writer_blocks_ready_shared_read_without_parse(
    observed: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = observed.capture()
    path = tmp_path / "synthetic-ready.json"
    path.write_bytes(b"partially written")
    writer = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    real_open, real_close = os.open, os.close
    try:
        REAL_FLOCK(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(
            owner.os, "open", lambda *_: real_open(path, os.O_RDONLY | os.O_CLOEXEC)
        )
        monkeypatch.setattr(owner.os, "close", real_close)
        monkeypatch.setattr(owner.fcntl, "flock", REAL_FLOCK)
        with pytest.raises(ValueError, match="NOT_READY"):
            captured.read_ready_snapshot()
        assert observed.ready_reads == 0
    finally:
        real_close(writer)


def test_observer_has_no_benchmark_or_model_or_effect_imports() -> None:
    path = (
        ROOT
        / "services/catalog_service/eom_catalog_service/embedding_native_cuda_index_observation.py"
    )
    tree = ast.parse(path.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        "benchmark" in name or name.startswith(("torch", "transformers", "eom_gpu_lease"))
        for name in imports
    )
    assert "subprocess" not in {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

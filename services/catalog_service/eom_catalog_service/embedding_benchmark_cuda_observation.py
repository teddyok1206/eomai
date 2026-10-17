"""Root read-only benchmark readiness: not source/Job admission, ACK or retirement."""

from __future__ import annotations

import fcntl
import grp
import os
import pwd
import re
import signal
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
    MAX_BENCHMARK_CUDA_READY_BYTES,
    BenchmarkCudaReady,
    parse_benchmark_cuda_ready,
    validate_benchmark_cuda_ready,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_ENVELOPE_BYTES,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_benchmark_handoff import (
    PreparedBenchmarkEnvironment,
    benchmark_owner_start_ticks,
)
from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_launch_arguments,
    benchmark_launch_environment_bytes,
)
from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
    observe_benchmark_cuda_ready_resources,
    observe_benchmark_cuda_retained_resources,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_installation_admission import (
    read_pinned_cuda_admission_receipt,
)
from eom_catalog_service.embedding_native_probe_observation import (
    NativeExecutableMapping,
    parse_native_executable_mappings,
    validate_native_cuda_executable_mappings,
)
from eom_catalog_service.embedding_runtime_files import (
    CUDA_LOADER_EMPTY_DIRECTORY,
    NumericalRuntimeFileSnapshots,
    ObservedRuntimeMemberBytes,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_native_cuda_process_status,
)
from eom_catalog_service.gpu_unit_policy_observation import observe_gpu_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

CUDA_BENCHMARK_TEMPLATE = "eom-embedding-benchmark-cuda@.service"
CUDA_BENCHMARK_SOCKET = "eom-embedding-benchmark-cuda@.socket"
CUDA_BENCHMARK_TEMPLATE_SHA256 = (
    "sha256:5955e54a578c5f547019298525eb44a8d8814fcbf8afb0070861a3b0a815b6eb"
)
CUDA_BENCHMARK_SOCKET_SHA256 = (
    "sha256:81a5b7fb034402baf1255635321ef480f2b5a48cbbe35b050c6ceaa25dfa4b0f"
)
_ROOT = Path("/run/eom-incremental-embeddings/benchmark")
_PREFIX = Path("/opt/eom/conda/envs/eom-embedding-cuda")
_READY_IMPLEMENTATIONS = (
    (
        "embedding_device_benchmark_files.py",
        "sha256:0f93acf5746fd65a2aadcabd6fd6b275a243cdde542ac250f6e265d45f31f5dd",
    ),
    (
        "embedding_benchmark_cuda.py",
        "sha256:d1542cbf1f57e2edc016958690d33a9892b47850e62d7b8e1016a436f3d397e8",
    ),
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_CUDA_OBSERVATION_" + suffix)


@dataclass(frozen=True, slots=True)
class BenchmarkCudaReadyObservation:
    execution_id: str
    job_id: str
    unit: CpuUnitObservation
    pid: int
    start_time_ticks: int
    cgroup: str
    invocation_raw_sha256: str
    ready_raw_sha256: str
    environment_raw_sha256: str
    effective_policy_sha256: str
    loaded_members_sha256: str
    executable_members: tuple[NativeExecutableMapping, ...]
    resources: CudaProbeResourceObservation
    device: CudaRuntimeDeviceCapture


def _read_ready_member(
    path: Path, files: NumericalRuntimeFileSnapshots
) -> ObservedRuntimeMemberBytes:
    """An empty or currently written member is pending, never invalid worker output."""
    named = path.lstat()
    _require(
        stat.S_ISREG(named.st_mode)
        and named.st_nlink == 1
        and 0 <= named.st_size <= MAX_BENCHMARK_CUDA_READY_BYTES,
        "READY_INVALID",
    )
    if named.st_size == 0:
        raise ValueError("BENCHMARK_CUDA_OBSERVATION_NOT_READY")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("BENCHMARK_CUDA_OBSERVATION_NOT_READY") from None

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_uid,
                value.st_gid,
                value.st_mode,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        before = identity(os.fstat(descriptor))
        _require(before == identity(path.lstat()), "READY_CHANGED")
        member = files.observe_protected_member_bytes(path, maximum=MAX_BENCHMARK_CUDA_READY_BYTES)
        _require(
            before == identity(os.fstat(descriptor)) == identity(path.lstat()), "READY_CHANGED"
        )
        files.assert_unchanged()
        return member
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class CapturedBenchmarkCudaPinnedFiles:
    """Pinned file-epoch resources, not live-process or source/installation admission."""

    pins: BenchmarkLaunchPins
    ready: BenchmarkCudaReady
    ready_raw_sha256: str
    owner_uid: int
    owner_gid: int
    root_files: NumericalRuntimeFileSnapshots
    ready_files: NumericalRuntimeFileSnapshots

    def assert_current(self) -> None:
        self.root_files.assert_unchanged()
        self.ready_files.assert_unchanged()


def capture_benchmark_cuda_pinned_files(
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
) -> CapturedBenchmarkCudaPinnedFiles:
    """Same immutable basis for live/late checks; no live-owner/deadline grant."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    invocation_raw = embedding_device_benchmark_bytes(invocation)
    _require(
        type(invocation) is BenchmarkWorkerInvocation and invocation.device == "CUDA",
        "INVOCATION_INVALID",
    )
    _require(type(environment) is PreparedBenchmarkEnvironment, "ENVIRONMENT_INVALID")
    pins = BenchmarkLaunchPins(
        invocation.execution_id,
        sha256_bytes(invocation_raw),
        environment.owner_pid,
        environment.expires_ns,
        backend,
    )
    environment_raw = benchmark_launch_environment_bytes(pins)
    _require(
        environment.execution_id == invocation.execution_id
        and environment.job_id == invocation.job_id
        and environment.environment_raw_sha256 == sha256_bytes(environment_raw)
        and environment.state == "STAGED_NOT_LAUNCHED"
        and inventory.prefix == _PREFIX,
        "ENVIRONMENT_INVALID",
    )
    entries = {entry.relative_member: entry for entry in inventory.entries}
    for name, digest in _READY_IMPLEMENTATIONS:
        member = entries.get("lib/python3.12/site-packages/eom_catalog_service/" + name)
        _require(
            member is not None and stat.S_ISREG(member.epoch[4]) and member.sha256 == digest,
            "ENTRY_SOURCE_MISMATCH",
        )
    configuration = RootLocalNativeConfigurationPin(
        configuration_id=backend.configuration_id,
        configuration_revision_id=backend.configuration_revision_id,
        configuration_sha256=backend.configuration_sha256,
        configuration_raw_sha256=backend.configuration_raw_sha256,
    )
    files = NumericalRuntimeFileSnapshots(0)
    for name, digest in (
        (CUDA_BENCHMARK_TEMPLATE, CUDA_BENCHMARK_TEMPLATE_SHA256),
        (CUDA_BENCHMARK_SOCKET, CUDA_BENCHMARK_SOCKET_SHA256),
    ):
        files.read(Path("/etc/systemd/system") / name, sha256=digest, maximum=65536)
    files.observe_empty_directory(CUDA_LOADER_EMPTY_DIRECTORY)
    execution = _ROOT / invocation.execution_id
    _require(
        files.read(
            execution / "invocation.json",
            sha256=pins.invocation_raw_sha256,
            maximum=MAX_BENCHMARK_ENVELOPE_BYTES,
        )
        == invocation_raw,
        "INVOCATION_CHANGED",
    )
    _require(
        files.read(
            execution / "launch.env", sha256=environment.environment_raw_sha256, maximum=8192
        )
        == environment_raw,
        "ENVIRONMENT_CHANGED",
    )
    for name in ("invocation.json", "launch.env"):
        path = execution / name
        metadata = path.lstat()
        _require(
            stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_gid == 0
            and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                os.listxattr(path)
            ),
            "ENVIRONMENT_PROTECTION_CHANGED",
        )
    receipt, _ = read_pinned_cuda_admission_receipt(
        files, configuration, receipt_raw_sha256=backend.receipt_raw_sha256
    )
    _require(
        receipt.bundle == invocation.runtime.bundle
        and receipt.installed_proof == invocation.runtime.installed_proof
        and receipt.runtime_sha256 == invocation.runtime.numerical_runtime.runtime_sha256,
        "RUNTIME_CHANGED",
    )
    user, group = pwd.getpwnam("eom-embedding-cuda"), grp.getgrnam("eom-embedding-cuda")
    lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
    owner = pwd.getpwnam("eom-workflow-runner")
    _require(
        min(user.pw_uid, group.gr_gid, lease_gid, owner.pw_uid, owner.pw_gid) > 0
        and user.pw_gid == group.gr_gid
        and group.gr_gid != lease_gid
        and set(os.getgrouplist(user.pw_name, user.pw_gid)) == {group.gr_gid, lease_gid},
        "ACCOUNT_INVALID",
    )
    ready_files = NumericalRuntimeFileSnapshots(user.pw_uid)
    ready_path = execution / "cuda-ready.json"
    ready_member = _read_ready_member(ready_path, ready_files)
    ready = parse_benchmark_cuda_ready(ready_member.raw)
    value = ready_path.lstat()
    _require(
        stat.S_IMODE(value.st_mode) == 0o640
        and value.st_gid == owner.pw_gid
        and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(ready_path)
        )
        and (ready.worker_uid, ready.worker_gid, ready.supplementary_gids)
        == (user.pw_uid, group.gr_gid, (lease_gid,)),
        "READY_INVALID",
    )
    validate_benchmark_cuda_ready(
        invocation,
        ready,
        configuration=configuration,
        receipt_raw_sha256=backend.receipt_raw_sha256,
        expected_device=receipt.device_capture,
    )
    captured = CapturedBenchmarkCudaPinnedFiles(
        pins, ready, ready_member.sha256, owner.pw_uid, owner.pw_gid, files, ready_files
    )
    captured.assert_current()
    inventory.assert_unchanged()
    return captured


def observe_benchmark_cuda_ready(
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> BenchmarkCudaReadyObservation:
    """Re-observe before effects; neither parsed metadata nor this value grants compute."""
    captured = capture_benchmark_cuda_pinned_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    ready, pins = captured.ready, captured.pins
    uid, gid, lease_gid = ready.worker_uid, ready.worker_gid, ready.supplementary_gids[0]
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{invocation.execution_id}.service")
    cgroup = "/system.slice/" + unit
    before = inspect_cpu_unit(unit, template=CUDA_BENCHMARK_TEMPLATE)
    _require(
        before.main_pid == ready.pid
        and before.status.active_state == "activating"
        and before.status.sub_state == "start"
        and before.status.process_started
        and before.exited_monotonic == 0
        and re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is not None,
        "NOT_RUNNING",
    )
    policy = observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda")
    process = Path("/proc") / str(ready.pid)
    arguments = (
        str(_PREFIX / "bin/python3.12"),
        "-I",
        "-B",
        "-m",
        "eom_catalog_service.embedding_benchmark_cuda",
        *benchmark_launch_arguments(pins),
    )

    def read(name: str, maximum: int = 128 * 1024) -> bytes:
        return read_live_runtime_os_file(process / name, maximum=maximum, owner_uid=uid)

    def current() -> None:
        _require(time.monotonic_ns() < pins.expires_ns, "EXPIRED")
        _require(
            benchmark_owner_start_ticks(
                pins.owner_pid, uid=captured.owner_uid, gid=captured.owner_gid
            )
            == environment.owner_start_ticks,
            "OWNER_CHANGED",
        )
        _require(
            native_process_start_ticks(read("stat"), ready.pid) == ready.start_time_ticks,
            "PROCESS_CHANGED",
        )
        _require(
            read("cgroup") == f"0::{cgroup}\n".encode()
            and root_owned_unit_processes(unit) == (ready.pid,),
            "CGROUP_CHANGED",
        )
        status = read("status")
        require_native_cuda_process_status(status, uid=uid, gid=gid, lease_gid=lease_gid)
        fields = dict(line.split(":", 1) for line in status.decode("ascii").splitlines())
        mask = fields.get("SigBlk", "").strip()
        _require(
            fields.get("Pid", "").strip() == str(ready.pid)
            and fields.get("Tgid", "").strip() == str(ready.pid)
            and fields.get("Threads", "").strip() == "1"
            and os.listdir(process / "task") == [str(ready.pid)]
            and re.fullmatch(r"[0-9a-f]{16}", mask) is not None
            and bool(int(mask, 16) & (1 << (signal.SIGUSR1 - 1))),
            "ACK_FRAME_CHANGED",
        )
        _require(
            read("cmdline", 8192) == b"\0".join(value.encode() for value in arguments) + b"\0",
            "ARGUMENTS_CHANGED",
        )
        expected, cwd = CUDA_LOADER_EMPTY_DIRECTORY.lstat(), (process / "cwd").stat()
        _require((expected.st_dev, expected.st_ino) == (cwd.st_dev, cwd.st_ino), "CWD_CHANGED")
        _require(inspect_cpu_unit(unit, template=CUDA_BENCHMARK_TEMPLATE) == before, "UNIT_CHANGED")
        captured.assert_current()

    current()
    observe_runtime_device(ready.expected_device_capture)
    members = validate_native_cuda_executable_mappings(
        read("maps", 2 * 1024**2), inventory=inventory, host=host
    )
    resources = observe_benchmark_cuda_ready_resources(ready, unit=unit, lease_gid=lease_gid)
    _require(observe_cuda_probe_gpu_clients(ready.expected_device_capture) == (), "GPU_BUSY")
    current()
    _require(
        parse_native_executable_mappings(read("maps", 2 * 1024**2)) == members
        and observe_benchmark_cuda_ready_resources(ready, unit=unit, lease_gid=lease_gid)
        == resources
        and observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda") == policy,
        "PROCESS_CHANGED",
    )
    inventory.assert_unchanged()
    host.assert_current()
    observe_runtime_device(ready.expected_device_capture)
    _require(observe_cuda_probe_gpu_clients(ready.expected_device_capture) == (), "GPU_BUSY")
    current()
    return BenchmarkCudaReadyObservation(
        invocation.execution_id,
        invocation.job_id,
        before,
        ready.pid,
        ready.start_time_ticks,
        cgroup,
        pins.invocation_raw_sha256,
        captured.ready_raw_sha256,
        environment.environment_raw_sha256,
        policy,
        sha256_bytes(
            canonical_json_bytes(
                [
                    {"path": str(member.path), "device": member.device, "inode": member.inode}
                    for member in members
                ]
            )
        ),
        members,
        resources,
        ready.expected_device_capture,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkCudaTerminalObservation:
    ready: BenchmarkCudaReadyObservation
    terminal_unit: CpuUnitObservation
    original_outcome: Literal["SUCCEEDED", "FAILED"]
    observed_at_utc: str


def require_benchmark_cuda_observation_basis(
    ready: BenchmarkCudaReadyObservation, captured: CapturedBenchmarkCudaPinnedFiles
) -> str:
    """Pure pinned linkage, not process, source, model or installation authority."""
    _require(
        type(ready) is BenchmarkCudaReadyObservation
        and type(captured) is CapturedBenchmarkCudaPinnedFiles,
        "IDENTITY_INVALID",
    )
    _require(
        (ready.execution_id, ready.job_id, ready.pid, ready.start_time_ticks)
        == (
            captured.ready.execution_id,
            captured.ready.job_id,
            captured.ready.pid,
            captured.ready.start_time_ticks,
        )
        and ready.invocation_raw_sha256 == captured.pins.invocation_raw_sha256
        and ready.environment_raw_sha256
        == sha256_bytes(benchmark_launch_environment_bytes(captured.pins))
        and ready.ready_raw_sha256 == captured.ready_raw_sha256
        and ready.device == captured.ready.expected_device_capture,
        "PINNED_BASIS_CHANGED",
    )
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")
    _require(ready.cgroup == "/system.slice/" + unit, "IDENTITY_INVALID")
    return unit


def require_benchmark_cuda_processes_ended(ready: BenchmarkCudaReadyObservation) -> None:
    """Original PID/birth and exact empty-cgroup proof; never control a reused PID."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(ready) is BenchmarkCudaReadyObservation, "IDENTITY_INVALID")
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")
    _require(ready.cgroup == "/system.slice/" + unit, "IDENTITY_INVALID")
    original = Path("/proc") / str(ready.pid)
    try:
        uid = original.lstat().st_uid
        raw = read_live_runtime_os_file(original / "stat", maximum=65536, owner_uid=uid)
    except FileNotFoundError:
        pass
    else:
        _require(
            native_process_start_ticks(raw, ready.pid) != ready.start_time_ticks,
            "TERMINATION_UNCERTAIN",
        )
    try:
        members = root_owned_unit_processes(unit)
    except FileNotFoundError:
        _require(not (Path("/sys/fs/cgroup/system.slice") / unit).exists(), "TERMINATION_UNCERTAIN")
        members = ()
    _require(members == (), "TERMINATION_UNCERTAIN")


def verify_benchmark_cuda_terminal(
    ready: BenchmarkCudaReadyObservation,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> BenchmarkCudaTerminalObservation:
    """Read-only late cleanup proof, independent of live deadlines or actor authorization."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(ready) is BenchmarkCudaReadyObservation, "IDENTITY_INVALID")
    captured = capture_benchmark_cuda_pinned_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    unit = require_benchmark_cuda_observation_basis(ready, captured)
    before = inspect_cpu_unit(unit, template=CUDA_BENCHMARK_TEMPLATE)
    _require(
        before.invocation_id == ready.unit.invocation_id
        and before.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic,
        "TERMINATION_UNCERTAIN",
    )
    try:
        outcome = gpu_unit_terminal_outcome(before)
    except ValueError:
        raise ValueError("BENCHMARK_CUDA_OBSERVATION_TERMINATION_UNCERTAIN") from None

    def ended() -> None:
        require_benchmark_cuda_processes_ended(ready)
        _require(
            inspect_cpu_unit(unit, template=CUDA_BENCHMARK_TEMPLATE) == before,
            "TERMINATION_UNCERTAIN",
        )

    ended()
    observe_runtime_device(ready.device)
    observe_benchmark_cuda_retained_resources(ready.resources, unit=unit)
    _require(observe_cuda_probe_gpu_clients(ready.device) == (), "GPU_CLEANUP_UNCERTAIN")
    observe_benchmark_cuda_retained_resources(ready.resources, unit=unit)
    _require(
        observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda")
        == ready.effective_policy_sha256,
        "POLICY_CHANGED",
    )
    captured.assert_current()
    inventory.assert_unchanged()
    host.assert_current()
    observe_runtime_device(ready.device)
    ended()
    return BenchmarkCudaTerminalObservation(
        ready,
        before,
        outcome,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )

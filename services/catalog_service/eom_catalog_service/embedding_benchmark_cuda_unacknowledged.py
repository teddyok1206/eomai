"""Root pre-ACK failed-unit observations; never fake READY or process-birth evidence."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_benchmark_cuda_ready import MAX_BENCHMARK_CUDA_READY_BYTES
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_benchmark_cuda_observation import (
    CUDA_BENCHMARK_TEMPLATE,
    CapturedBenchmarkCudaLaunchFiles,
    capture_benchmark_cuda_launch_files,
)
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.embedding_benchmark_layout import (
    BENCHMARK_CUDA_LIFETIME_ROOT,
    BENCHMARK_HANDOFF_ROOT,
)
from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    UnacknowledgedBenchmarkGpuResources,
    observe_unacknowledged_benchmark_gpu_resources,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    ObservedRuntimeMemberBytes,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.gpu_unit_policy_observation import observe_gpu_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome
from eom_catalog_service.unit_effect_records import require_unit_effect_phase_absent

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_PROPERTIES = (
    "ExecMainPID",
    "NFileDescriptorStore",
    "InvocationID",
    "ExecMainStartTimestampMonotonic",
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_CUDA_UNACKNOWLEDGED_" + suffix)


@dataclass(frozen=True, slots=True)
class CapturedUnacknowledgedBenchmarkFiles:
    launch: CapturedBenchmarkCudaLaunchFiles
    job_id: str
    environment_raw_sha256: str
    ready_member: ObservedRuntimeMemberBytes
    ready_files: NumericalRuntimeFileSnapshots

    def assert_current(self) -> None:
        self.launch.assert_current()
        self.ready_files.assert_unchanged()


def capture_unacknowledged_benchmark_files(
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
) -> CapturedUnacknowledgedBenchmarkFiles:
    launch = capture_benchmark_cuda_launch_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    files = NumericalRuntimeFileSnapshots(launch.worker_uid)
    path = BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "cuda-ready.json"
    member = files.observe_protected_member_bytes(path, maximum=MAX_BENCHMARK_CUDA_READY_BYTES)
    metadata = path.lstat()
    _require(
        stat.S_IMODE(metadata.st_mode) == 0o640
        and metadata.st_gid == launch.owner_gid
        and not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(path)
        ),
        "READY_PROTECTION_CHANGED",
    )
    captured = CapturedUnacknowledgedBenchmarkFiles(
        launch, invocation.job_id, environment.environment_raw_sha256, member, files
    )
    captured.assert_current()
    return captured


@dataclass(frozen=True, slots=True)
class UnacknowledgedBenchmarkCudaTerminal:
    execution_id: str
    job_id: str
    invocation_raw_sha256: str
    environment_raw_sha256: str
    ready_raw_sha256: str
    ready_size_bytes: int
    terminal_unit: CpuUnitObservation
    terminal_pid: int
    original_outcome: Literal["FAILED"]
    stored_descriptors: Literal[0, 1]
    effective_policy_sha256: str
    device: CudaRuntimeDeviceCapture
    resources: UnacknowledgedBenchmarkGpuResources | None
    observed_at_utc: str


def require_unacknowledged_benchmark_basis(
    terminal: UnacknowledgedBenchmarkCudaTerminal, files: CapturedUnacknowledgedBenchmarkFiles
) -> str:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is UnacknowledgedBenchmarkCudaTerminal, "IDENTITY_INVALID")
    launch = files.launch
    _require(
        terminal.original_outcome == "FAILED"
        and gpu_unit_terminal_outcome(terminal.terminal_unit) == "FAILED"
        and type(terminal.stored_descriptors) is int
        and terminal.stored_descriptors in {0, 1}
        and type(terminal.terminal_pid) is int
        and 0 < terminal.terminal_pid <= 2147483647
        and ((terminal.resources is None) == (terminal.stored_descriptors == 0))
        and (
            terminal.resources is None
            or (
                type(terminal.resources) is UnacknowledgedBenchmarkGpuResources
                and terminal.resources.shared_gpu_lease.holder_pid == terminal.terminal_pid
            )
        ),
        "IDENTITY_INVALID",
    )
    _require(
        (
            terminal.execution_id,
            terminal.invocation_raw_sha256,
            terminal.ready_raw_sha256,
            terminal.ready_size_bytes,
            terminal.device,
        )
        == (
            launch.pins.execution_id,
            launch.pins.invocation_raw_sha256,
            files.ready_member.sha256,
            files.ready_member.size_bytes,
            launch.device,
        )
        and terminal.job_id == files.job_id
        and terminal.environment_raw_sha256 == files.environment_raw_sha256,
        "PINNED_BASIS_CHANGED",
    )
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{terminal.execution_id}.service")
    require_unacknowledged_benchmark_ack_absent(terminal)
    return unit


def require_unacknowledged_benchmark_ack_absent(
    terminal: UnacknowledgedBenchmarkCudaTerminal,
) -> None:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is UnacknowledgedBenchmarkCudaTerminal, "IDENTITY_INVALID")
    _require(re.fullmatch(r"[0-9a-f]{32}", terminal.execution_id) is not None, "IDENTITY_INVALID")
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{terminal.execution_id}.service")
    require_unit_effect_phase_absent(
        BENCHMARK_CUDA_LIFETIME_ROOT, unit, terminal.terminal_unit.invocation_id, "ack"
    )


def require_empty_benchmark_cuda_cgroup(unit: str) -> None:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        re.fullmatch(r"eom-embedding-benchmark-cuda@[0-9a-f]{32}\.service", unit) is not None,
        "IDENTITY_INVALID",
    )
    try:
        members = root_owned_unit_processes(unit)
    except FileNotFoundError:
        from pathlib import Path

        _require(not (Path("/sys/fs/cgroup/system.slice") / unit).exists(), "TERMINATION_UNCERTAIN")
        members = ()
    _require(members == (), "TERMINATION_UNCERTAIN")


def _terminal_metadata(unit: str, expected: CpuUnitObservation) -> tuple[int, Literal[0, 1]]:
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", unit, *("--property=" + key for key in _PROPERTIES)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("BENCHMARK_CUDA_UNACKNOWLEDGED_TERMINATION_UNCERTAIN") from None
    _require(
        result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
        "TERMINATION_UNCERTAIN",
    )
    fields: dict[str, str] = {}
    for line in result.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        _require(
            bool(separator) and key in _PROPERTIES and key not in fields, "TERMINATION_UNCERTAIN"
        )
        fields[key] = value
    _require(
        set(fields) == set(_PROPERTIES)
        and fields["InvocationID"] == expected.invocation_id
        and fields["ExecMainStartTimestampMonotonic"]
        == str(expected.status.exec_main_started_monotonic)
        and fields["NFileDescriptorStore"] in {"0", "1"}
        and re.fullmatch(r"[1-9][0-9]{0,9}", fields["ExecMainPID"]) is not None
        and 0 < int(fields["ExecMainPID"]) <= 2147483647,
        "TERMINATION_UNCERTAIN",
    )
    return int(fields["ExecMainPID"]), 1 if fields["NFileDescriptorStore"] == "1" else 0


def observe_unacknowledged_benchmark_cuda_terminal(
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    expected_unit: CpuUnitObservation,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> UnacknowledgedBenchmarkCudaTerminal:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        type(expected_unit) is CpuUnitObservation
        and re.fullmatch(r"[0-9a-f]{32}", expected_unit.invocation_id) is not None,
        "IDENTITY_INVALID",
    )
    _require(gpu_unit_terminal_outcome(expected_unit) == "FAILED", "IDENTITY_INVALID")
    captured = capture_unacknowledged_benchmark_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{invocation.execution_id}.service")
    policy = observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda")

    def current() -> tuple[int, Literal[0, 1]]:
        require_unit_effect_phase_absent(
            BENCHMARK_CUDA_LIFETIME_ROOT, unit, expected_unit.invocation_id, "ack"
        )
        _require(
            inspect_cpu_unit(unit, template=CUDA_BENCHMARK_TEMPLATE) == expected_unit,
            "TERMINATION_UNCERTAIN",
        )
        require_empty_benchmark_cuda_cgroup(unit)
        return _terminal_metadata(unit, expected_unit)

    pid, stored = current()
    observe_runtime_device(captured.launch.device)
    resources = None
    if stored:
        resources = observe_unacknowledged_benchmark_gpu_resources(
            unit=unit, terminal_pid=pid, lease_gid=captured.launch.lease_gid
        )
        _require(
            observe_cuda_probe_gpu_clients(captured.launch.device) == (), "GPU_CLEANUP_UNCERTAIN"
        )
    _require(current() == (pid, stored), "TERMINATION_UNCERTAIN")
    _require(
        observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda") == policy,
        "POLICY_CHANGED",
    )
    captured.assert_current()
    inventory.assert_unchanged()
    host.assert_current()
    observe_runtime_device(captured.launch.device)
    if resources is not None:
        _require(
            observe_unacknowledged_benchmark_gpu_resources(
                unit=unit, terminal_pid=pid, lease_gid=captured.launch.lease_gid
            )
            == resources,
            "RESOURCE_CHANGED",
        )
        _require(
            observe_cuda_probe_gpu_clients(captured.launch.device) == (), "GPU_CLEANUP_UNCERTAIN"
        )
    _require(current() == (pid, stored), "TERMINATION_UNCERTAIN")
    return UnacknowledgedBenchmarkCudaTerminal(
        invocation.execution_id,
        invocation.job_id,
        captured.launch.pins.invocation_raw_sha256,
        environment.environment_raw_sha256,
        captured.ready_member.sha256,
        captured.ready_member.size_bytes,
        expected_unit,
        pid,
        "FAILED",
        stored,
        policy,
        captured.launch.device,
        resources,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )

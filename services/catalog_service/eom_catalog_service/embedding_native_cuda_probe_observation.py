"""Root-only fixed CUDA probe observation/ACK; no dispatch, model grant or lease retirement."""

from __future__ import annotations

import grp
import os
import pwd
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_native_cpu_probe import ExecutionId
from eom_catalog_contracts.embedding_native_cuda_probe import (
    NativeCudaProbeLeaseReady,
    NativeCudaProbeResult,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
    observe_cuda_probe_resources,
    observe_cuda_probe_retained_resources,
)
from eom_catalog_service.embedding_native_probe_observation import (
    NativeExecutableMapping,
    native_probe_cgroup_members,
    parse_native_executable_mappings,
    validate_native_cuda_executable_mappings,
)
from eom_catalog_service.embedding_runtime_files import (
    CUDA_LOADER_EMPTY_DIRECTORY,
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
)
from eom_catalog_service.embedding_runtime_process_identity import (
    require_native_cuda_process_status as _require_status,
)

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

CUDA_PROBE_TEMPLATE = "eom-embedding-native-cuda-probe@.service"
CUDA_PROBE_TEMPLATE_SHA256 = (
    "sha256:911e3ef9c68a048078ae59970cc3bc9afc8fb64a11721929f0c74e58fe900b0e"
)
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
type ProbeReport = NativeCudaProbeLeaseReady | NativeCudaProbeResult


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_PROBE_" + suffix)


def _unit(execution_id: str) -> tuple[str, str]:
    identity: str = TypeAdapter(ExecutionId).validate_python(execution_id)
    name = CUDA_PROBE_TEMPLATE.replace("@.service", f"@{identity}.service")
    return name, f"/system.slice/{name}"


def require_native_cuda_probe_unit() -> tuple[int, int, int]:
    """Pin installed bytes and actual account groups, not caller/request authority."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    files = NumericalRuntimeFileSnapshots(0)
    files.read(
        Path("/etc/systemd/system") / CUDA_PROBE_TEMPLATE,
        sha256=CUDA_PROBE_TEMPLATE_SHA256,
        maximum=64 * 1024,
    )
    files.observe_empty_directory(CUDA_LOADER_EMPTY_DIRECTORY)
    user = pwd.getpwnam("eom-embedding-cuda")
    group = grp.getgrnam("eom-embedding-cuda")
    lease = grp.getgrnam("eom-gpu-lease").gr_gid
    _require(
        user.pw_uid > 0
        and group.gr_gid > 0
        and lease > 0
        and lease != group.gr_gid
        and user.pw_gid == group.gr_gid
        and set(os.getgrouplist(user.pw_name, user.pw_gid)) == {group.gr_gid, lease},
        "ACCOUNT_INVALID",
    )
    files.assert_unchanged()
    return user.pw_uid, group.gr_gid, lease


@dataclass(frozen=True, slots=True)
class NativeCudaProbeProcessObservation:
    execution_id: str
    phase: Literal["READY", "FINAL"]
    invocation_id: str
    pid: int
    start_time_ticks: int
    cgroup: str
    report_sha256: str
    loaded_members_sha256: str
    executable_members: tuple[NativeExecutableMapping, ...]
    resources: CudaProbeResourceObservation


def observe_native_cuda_probe_process(
    report: ProbeReport,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> NativeCudaProbeProcessObservation:
    """Observe both sides of live process/maps/resources before authorizing either fixed signal."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    if type(report) is NativeCudaProbeLeaseReady:
        report = NativeCudaProbeLeaseReady.model_validate(report)
        phase: Literal["READY", "FINAL"] = "READY"
        device = report.expected_device_capture
    elif type(report) is NativeCudaProbeResult:
        report = NativeCudaProbeResult.model_validate(report)
        phase = "FINAL"
        device = report.device_capture
    else:
        raise ValueError("NATIVE_CUDA_PROBE_REPORT_INVALID")
    uid, gid, lease_gid = require_native_cuda_probe_unit()
    _require(
        (report.worker_uid, report.worker_gid, report.supplementary_gids)
        == (uid, gid, (lease_gid,)),
        "ACCOUNT_INVALID",
    )
    unit, cgroup = _unit(report.execution_id)
    before = inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE)
    _require(
        before.main_pid == report.pid
        and re.fullmatch(r"[0-9a-f]{32}", before.invocation_id) is not None
        and before.status.active_state == "activating"
        and before.status.sub_state == "start"
        and before.status.process_started
        and before.exited_monotonic == 0,
        "UNIT_NOT_RUNNING",
    )
    process = Path("/proc") / str(report.pid)

    def read(name: str, maximum: int = 64 * 1024) -> bytes:
        return read_live_runtime_os_file(process / name, maximum=maximum, owner_uid=uid)

    def identity() -> None:
        _require(
            native_process_start_ticks(read("stat"), report.pid) == report.start_time_ticks,
            "PROCESS_CHANGED",
        )
        _require(
            read("cgroup") == f"0::{cgroup}\n".encode()
            and native_probe_cgroup_members(cgroup) == (report.pid,),
            "CGROUP_MISMATCH",
        )
        _require_status(read("status"), uid=uid, gid=gid, lease_gid=lease_gid)
        # A path spelling alone would miss a replaced/alternate cwd inode.
        expected, current = CUDA_LOADER_EMPTY_DIRECTORY.lstat(), (process / "cwd").stat()
        _require(
            (expected.st_dev, expected.st_ino) == (current.st_dev, current.st_ino),
            "WORKING_DIRECTORY_CHANGED",
        )

    identity()
    observe_runtime_device(device)
    members = validate_native_cuda_executable_mappings(
        read("maps", 2 * 1024**2), inventory=inventory, host=host
    )
    resources = observe_cuda_probe_resources(report, unit=unit, lease_gid=lease_gid)
    identity()
    _require(
        parse_native_executable_mappings(read("maps", 2 * 1024**2)) == members
        and observe_cuda_probe_resources(report, unit=unit, lease_gid=lease_gid) == resources
        and inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE) == before,
        "PROCESS_CHANGED",
    )
    inventory.assert_unchanged()
    host.assert_current()
    digest = sha256_bytes(
        canonical_json_bytes(
            [{"path": str(m.path), "device": m.device, "inode": m.inode} for m in members]
        )
    )
    return NativeCudaProbeProcessObservation(
        report.execution_id,
        phase,
        before.invocation_id,
        report.pid,
        report.start_time_ticks,
        cgroup,
        sha256_bytes(canonical_json_bytes(report)),
        digest,
        members,
        resources,
    )


def _acknowledge_native_cuda_probe(
    observed: NativeCudaProbeProcessObservation,
    report: ProbeReport,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> None:
    """Re-observe, then signal only this fixed unit main; no restart or success rewrite."""
    _require(type(observed) is NativeCudaProbeProcessObservation, "PROCESS_CHANGED")
    _require(
        observe_native_cuda_probe_process(report, inventory=inventory, host=host) == observed,
        "PROCESS_CHANGED",
    )
    unit, _ = _unit(observed.execution_id)
    signal = "SIGUSR1" if observed.phase == "READY" else "SIGUSR2"
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "kill",
            "--kill-whom=main",
            f"--signal={signal}",
            unit,
        ),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    _require(result.returncode == 0, "ACK_UNCERTAIN")


def acknowledge_native_cuda_probe_ready(
    observed: NativeCudaProbeProcessObservation,
    report: NativeCudaProbeLeaseReady,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> None:
    _require(
        type(report) is NativeCudaProbeLeaseReady and observed.phase == "READY", "PHASE_INVALID"
    )
    _acknowledge_native_cuda_probe(observed, report, inventory=inventory, host=host)


def acknowledge_native_cuda_probe_final(
    ready: NativeCudaProbeProcessObservation,
    observed: NativeCudaProbeProcessObservation,
    report: NativeCudaProbeResult,
    *,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> None:
    """Final ACK cannot silently replace the initial observed process/invocation/physical guard."""
    _require(
        type(ready) is NativeCudaProbeProcessObservation
        and type(observed) is NativeCudaProbeProcessObservation
        and type(report) is NativeCudaProbeResult
        and ready.phase == "READY"
        and observed.phase == "FINAL",
        "PHASE_INVALID",
    )
    fields = ("execution_id", "invocation_id", "pid", "start_time_ticks", "cgroup", "resources")
    _require(
        all(getattr(ready, key) == getattr(observed, key) for key in fields), "PROCESS_CHANGED"
    )
    _acknowledge_native_cuda_probe(observed, report, inventory=inventory, host=host)


@dataclass(frozen=True, slots=True)
class NativeCudaProbeTerminalObservation:
    final_observation: NativeCudaProbeProcessObservation
    terminal_unit: CpuUnitObservation
    terminated_at_utc: str
    terminal_probe_gpu_client_count: Literal[0] = 0


def require_native_cuda_probe_empty_cgroup(cgroup: str) -> None:
    """One terminal-cgroup rule shared by successful, failed and retired observations."""
    try:
        _require(native_probe_cgroup_members(cgroup) == (), "TERMINATION_UNCERTAIN")
    except FileNotFoundError:
        # A known terminal cgroup may already have been removed by systemd.
        path = Path("/sys/fs/cgroup") / cgroup.removeprefix("/")
        _require(not path.exists(), "TERMINATION_UNCERTAIN")


def verify_native_cuda_probe_terminal(
    observed: NativeCudaProbeProcessObservation,
    report: NativeCudaProbeResult,
) -> NativeCudaProbeTerminalObservation:
    """Success requires actual unit/cgroup/retained-lock/GPU cleanup, never worker declarations."""
    from datetime import UTC, datetime

    from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients

    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    report = NativeCudaProbeResult.model_validate(report)
    _require(
        type(observed) is NativeCudaProbeProcessObservation and observed.phase == "FINAL",
        "PHASE_INVALID",
    )
    _require(observed.report_sha256 == sha256_bytes(canonical_json_bytes(report)), "REPORT_CHANGED")
    uid, gid, lease_gid = require_native_cuda_probe_unit()
    _require(
        (report.worker_uid, report.worker_gid, report.supplementary_gids)
        == (uid, gid, (lease_gid,)),
        "ACCOUNT_INVALID",
    )
    unit, cgroup = _unit(observed.execution_id)
    before = inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE)

    def terminal() -> None:
        _require(
            before.succeeded
            and before.invocation_id == observed.invocation_id
            and cgroup == observed.cgroup,
            "TERMINATION_UNCERTAIN",
        )
        _require(
            inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE) == before, "TERMINATION_UNCERTAIN"
        )
        require_native_cuda_probe_empty_cgroup(cgroup)

    terminal()
    observe_runtime_device(report.device_capture)
    observe_cuda_probe_retained_resources(observed.resources, unit=unit)
    _require(
        report.pid not in observe_cuda_probe_gpu_clients(report.device_capture),
        "GPU_CLEANUP_UNCERTAIN",
    )
    observe_cuda_probe_retained_resources(observed.resources, unit=unit)
    terminal()
    return NativeCudaProbeTerminalObservation(
        observed,
        before,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


@dataclass(frozen=True, slots=True)
class NativeCudaProbeFailedTerminalObservation:
    """Failure-preserving OS observation, deliberately not an admission/sealing value."""

    ready_observation: NativeCudaProbeProcessObservation
    failed_unit: CpuUnitObservation
    observed_at_utc: str
    terminal_probe_gpu_client_count: Literal[0] = 0


def verify_native_cuda_probe_failed_terminal(
    observed: NativeCudaProbeProcessObservation,
    report: NativeCudaProbeLeaseReady,
) -> NativeCudaProbeFailedTerminalObservation:
    """Verify a failed original invocation has ended without releasing its physical fence."""
    from datetime import UTC, datetime

    from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients

    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(
        type(observed) is NativeCudaProbeProcessObservation
        and observed.phase == "READY"
        and type(report) is NativeCudaProbeLeaseReady,
        "PHASE_INVALID",
    )
    report = NativeCudaProbeLeaseReady.model_validate(report)
    _require(observed.report_sha256 == sha256_bytes(canonical_json_bytes(report)), "REPORT_CHANGED")
    uid, gid, lease_gid = require_native_cuda_probe_unit()
    _require(
        (report.worker_uid, report.worker_gid, report.supplementary_gids)
        == (uid, gid, (lease_gid,)),
        "ACCOUNT_INVALID",
    )
    unit, cgroup = _unit(report.execution_id)
    _require(
        observed.execution_id == report.execution_id
        and observed.pid == report.pid
        and observed.start_time_ticks == report.start_time_ticks
        and observed.cgroup == cgroup,
        "PROCESS_CHANGED",
    )
    before = inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE)

    def terminal() -> None:
        _require(
            before.failed
            and before.invocation_id == observed.invocation_id
            and inspect_cpu_unit(unit, template=CUDA_PROBE_TEMPLATE) == before,
            "TERMINATION_UNCERTAIN",
        )
        _require(not (Path("/proc") / str(observed.pid)).exists(), "TERMINATION_UNCERTAIN")
        require_native_cuda_probe_empty_cgroup(cgroup)

    terminal()
    observe_runtime_device(report.expected_device_capture)
    observe_cuda_probe_retained_resources(observed.resources, unit=unit)
    _require(
        report.pid not in observe_cuda_probe_gpu_clients(report.expected_device_capture),
        "GPU_CLEANUP_UNCERTAIN",
    )
    observe_cuda_probe_retained_resources(observed.resources, unit=unit)
    observe_runtime_device(report.expected_device_capture)
    terminal()
    return NativeCudaProbeFailedTerminalObservation(
        observed,
        before,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )

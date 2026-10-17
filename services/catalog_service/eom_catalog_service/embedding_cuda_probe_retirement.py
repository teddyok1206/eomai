"""Root-only retirement of exact terminal CUDA probes, preserving distinct original outcomes."""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.embedding_native_cuda_probe import (
    NativeCudaProbeLeaseReady,
    NativeCudaProbeResult,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    hold_released_cuda_probe_resources,
)
from eom_catalog_service.embedding_native_cuda_probe_observation import (
    CUDA_PROBE_TEMPLATE,
    NativeCudaProbeFailedTerminalObservation,
    NativeCudaProbeProcessObservation,
    NativeCudaProbeTerminalObservation,
    require_native_cuda_probe_empty_cgroup,
    require_native_cuda_probe_unit,
    verify_native_cuda_probe_failed_terminal,
    verify_native_cuda_probe_terminal,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device

_ROOT = Path("/opt/eom/embedding-probe-retirements")
_PUBLICATION_LOCK = Path("/opt/eom/conda/envs/.embedding-index-CUDA_INDEX_FP32.lock")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "MainPID",
    "NFileDescriptorStore",
    "InvocationID",
    "NeedDaemonReload",
    "FragmentPath",
    "DropInPaths",
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_" + suffix)


@dataclass(frozen=True, slots=True)
class RetiredCudaProbeUnit:
    load_state: str
    invocation_id: str


@dataclass(frozen=True, slots=True)
class NativeCudaProbeRetirementObservation:
    original_failure: NativeCudaProbeFailedTerminalObservation
    retired_unit: RetiredCudaProbeUnit
    observed_at_utc: str


@dataclass(frozen=True, slots=True)
class SuccessfulNativeCudaProbeRetirementObservation:
    original_success: NativeCudaProbeTerminalObservation
    retired_unit: RetiredCudaProbeUnit
    observed_at_utc: str


def _retired_unit(unit: str, invocation: str) -> RetiredCudaProbeUnit:
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", unit, *(f"--property={p}" for p in _PROPERTIES)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_OUTCOME_UNCERTAIN") from None
    _require(
        result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
        "OUTCOME_UNCERTAIN",
    )
    values: dict[str, str] = {}
    try:
        lines = result.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError:
        raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_OUTCOME_UNCERTAIN") from None
    for line in lines:
        key, separator, value = line.partition("=")
        _require(bool(separator) and key in _PROPERTIES and key not in values, "OUTCOME_UNCERTAIN")
        values[key] = value
    _require(set(values) == set(_PROPERTIES), "OUTCOME_UNCERTAIN")
    _require(
        values["LoadState"] in {"loaded", "not-found"}
        and values["ActiveState"] == "inactive"
        and values["SubState"] == "dead"
        and values["MainPID"] == "0"
        and values["NFileDescriptorStore"] == "0"
        and values["InvocationID"] in {"", invocation}
        and values["NeedDaemonReload"] == "no"
        and values["DropInPaths"] == ""
        and values["FragmentPath"]
        == (
            "/etc/systemd/system/" + CUDA_PROBE_TEMPLATE if values["LoadState"] == "loaded" else ""
        ),
        "OUTCOME_UNCERTAIN",
    )
    return RetiredCudaProbeUnit(values["LoadState"], values["InvocationID"])


def observe_retired_native_cuda_probe(
    failed: NativeCudaProbeFailedTerminalObservation,
    report: NativeCudaProbeLeaseReady,
) -> NativeCudaProbeRetirementObservation:
    """Readonly recovery after an uncertain reset; never submit another mutation."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(
        type(failed) is NativeCudaProbeFailedTerminalObservation
        and type(report) is NativeCudaProbeLeaseReady,
        "IDENTITY_INVALID",
    )
    _require(failed.failed_unit.failed, "IDENTITY_INVALID")
    unit, timestamp = _observe_retired_probe(failed.ready_observation, failed.failed_unit, report)
    return NativeCudaProbeRetirementObservation(failed, unit, timestamp)


def observe_retired_successful_native_cuda_probe(
    successful: NativeCudaProbeTerminalObservation,
    report: NativeCudaProbeResult,
) -> SuccessfulNativeCudaProbeRetirementObservation:
    """Observe success cleanup without stopping twice or relabeling a failed probe."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(
        type(successful) is NativeCudaProbeTerminalObservation
        and type(report) is NativeCudaProbeResult,
        "IDENTITY_INVALID",
    )
    _require(successful.terminal_unit.succeeded, "IDENTITY_INVALID")
    unit, timestamp = _observe_retired_probe(
        successful.final_observation, successful.terminal_unit, report
    )
    return SuccessfulNativeCudaProbeRetirementObservation(successful, unit, timestamp)


def _observe_retired_probe(
    observed: NativeCudaProbeProcessObservation,
    terminal_unit: CpuUnitObservation,
    report: NativeCudaProbeLeaseReady | NativeCudaProbeResult,
) -> tuple[RetiredCudaProbeUnit, str]:
    if type(report) is NativeCudaProbeLeaseReady:
        report = NativeCudaProbeLeaseReady.model_validate(report)
        expected_phase = "READY"
        device = report.expected_device_capture
    elif type(report) is NativeCudaProbeResult:
        report = NativeCudaProbeResult.model_validate(report)
        expected_phase = "FINAL"
        device = report.device_capture
    else:
        raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_IDENTITY_INVALID")
    uid, gid, lease_gid = require_native_cuda_probe_unit()
    unit = CUDA_PROBE_TEMPLATE.replace("@.service", f"@{report.execution_id}.service")
    _require(
        terminal_unit.invocation_id == observed.invocation_id
        and observed.phase == expected_phase
        and observed.execution_id == report.execution_id
        and observed.report_sha256 == sha256_bytes(canonical_json_bytes(report))
        and (observed.pid, observed.start_time_ticks) == (report.pid, report.start_time_ticks)
        and observed.cgroup == "/system.slice/" + unit
        and (report.worker_uid, report.worker_gid, report.supplementary_gids)
        == (uid, gid, (lease_gid,)),
        "IDENTITY_INVALID",
    )

    def ended() -> None:
        _require(not (Path("/proc") / str(observed.pid)).exists(), "OUTCOME_UNCERTAIN")
        require_native_cuda_probe_empty_cgroup(observed.cgroup)

    before = _retired_unit(unit, observed.invocation_id)
    ended()
    observe_runtime_device(device)
    with hold_released_cuda_probe_resources(observed.resources):
        _require(
            report.pid not in observe_cuda_probe_gpu_clients(device),
            "OUTCOME_UNCERTAIN",
        )
        ended()
        observe_runtime_device(device)
        _require(_retired_unit(unit, observed.invocation_id) == before, "OUTCOME_UNCERTAIN")
    return before, datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@contextmanager
def _publication_guard() -> Iterator[None]:
    files = NumericalRuntimeFileSnapshots(0)
    files.observe_protected_member_identity(_PUBLICATION_LOCK)
    descriptor = os.open(_PUBLICATION_LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = os.fstat(descriptor)
        _require(
            stat.S_ISREG(value.st_mode)
            and stat.S_IMODE(value.st_mode) == 0o600
            and value.st_uid == 0
            and value.st_nlink == 1
            and value == _PUBLICATION_LOCK.lstat(),
            "PUBLICATION_LOCK_INVALID",
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files.assert_unchanged()
        yield
        files.assert_unchanged()
    finally:
        os.close(descriptor)


def _records(execution: str) -> int:
    for path in (*reversed(_ROOT.parents), _ROOT):
        if path == _ROOT:
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
        value = path.lstat()
        _require(
            stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022,
            "RECORD_DIRECTORY_INVALID",
        )
    parent = os.open(_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        # Atomic no-clobber reservation. Existing intent requires readonly recovery, not replay.
        os.mkdir(execution, mode=0o700, dir_fd=parent)
        os.fsync(parent)
        descriptor = os.open(
            execution, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
        )
        return descriptor
    finally:
        os.close(parent)


def _save_record(
    directory: int,
    name: str,
    event: str,
    observed: (
        NativeCudaProbeFailedTerminalObservation
        | NativeCudaProbeRetirementObservation
        | NativeCudaProbeTerminalObservation
        | SuccessfulNativeCudaProbeRetirementObservation
    ),
) -> None:
    raw = canonical_json_bytes(
        {
            "event": event,
            "observation": TypeAdapter(type(observed)).dump_python(observed, mode="json"),
            "admission_granted": False,
        }
    )
    _require(len(raw) <= 2 * 1024**2 + 65536, "RECORD_TOO_LARGE")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o400,
        dir_fd=directory,
    )
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            _require(0 < count <= len(remaining), "RECORD_WRITE_FAILED")
            remaining = remaining[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


def retire_failed_native_cuda_probe(
    failed: NativeCudaProbeFailedTerminalObservation,
    report: NativeCudaProbeLeaseReady,
) -> NativeCudaProbeRetirementObservation:
    """Preserve failure before one fixed reset; uncertain outcomes never auto-retry."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(type(failed) is NativeCudaProbeFailedTerminalObservation, "IDENTITY_INVALID")
    with _publication_guard():
        fresh = verify_native_cuda_probe_failed_terminal(failed.ready_observation, report)
        _require(fresh.failed_unit == failed.failed_unit, "IDENTITY_CHANGED")
        directory = _records(fresh.ready_observation.execution_id)
        try:
            _save_record(directory, "intent.json", "FAILED_PROBE_RETIREMENT_INTENT", fresh)
            rechecked = verify_native_cuda_probe_failed_terminal(failed.ready_observation, report)
            _require(rechecked.failed_unit == fresh.failed_unit, "IDENTITY_CHANGED")
            unit = CUDA_PROBE_TEMPLATE.replace(
                "@.service", f"@{fresh.ready_observation.execution_id}.service"
            )
            try:
                reset = subprocess.run(
                    ("/usr/bin/systemctl", "--no-ask-password", "reset-failed", unit),
                    capture_output=True,
                    check=False,
                    timeout=10,
                    env=_ENV,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_OUTCOME_UNCERTAIN") from None
            _require(reset.returncode == 0, "OUTCOME_UNCERTAIN")
            result = observe_retired_native_cuda_probe(fresh, report)
            _save_record(directory, "result.json", "FAILED_PROBE_RETIRED_NOT_ADMITTED", result)
            return result
        finally:
            os.close(directory)


def retire_successful_native_cuda_probe(
    successful: NativeCudaProbeTerminalObservation,
    report: NativeCudaProbeResult,
) -> SuccessfulNativeCudaProbeRetirementObservation:
    """After root sealing/readback, stop only this ended success; grant no model authority."""
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(type(successful) is NativeCudaProbeTerminalObservation, "IDENTITY_INVALID")
    with _publication_guard():
        fresh = verify_native_cuda_probe_terminal(successful.final_observation, report)
        _require(fresh.terminal_unit == successful.terminal_unit, "IDENTITY_CHANGED")
        directory = _records(fresh.final_observation.execution_id)
        try:
            _save_record(directory, "intent.json", "SUCCESSFUL_PROBE_RETIREMENT_INTENT", fresh)
            rechecked = verify_native_cuda_probe_terminal(successful.final_observation, report)
            _require(rechecked.terminal_unit == fresh.terminal_unit, "IDENTITY_CHANGED")
            unit = CUDA_PROBE_TEMPLATE.replace(
                "@.service", f"@{fresh.final_observation.execution_id}.service"
            )
            try:
                stopped = subprocess.run(
                    ("/usr/bin/systemctl", "--no-ask-password", "stop", unit),
                    capture_output=True,
                    check=False,
                    timeout=10,
                    env=_ENV,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError("NATIVE_CUDA_PROBE_RETIREMENT_OUTCOME_UNCERTAIN") from None
            _require(stopped.returncode == 0, "OUTCOME_UNCERTAIN")
            result = observe_retired_successful_native_cuda_probe(fresh, report)
            _save_record(directory, "result.json", "SUCCESSFUL_PROBE_RETIRED_NOT_GRANTED", result)
            return result
        finally:
            os.close(directory)

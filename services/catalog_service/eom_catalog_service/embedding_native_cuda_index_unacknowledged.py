"""Root recovery of an original failed INDEX without ACK; never fabricate READY."""

from __future__ import annotations

import os
import re
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cuda_index_ready import (
    MAX_NATIVE_CUDA_INDEX_READY_BYTES,
)
from eom_catalog_contracts.embedding_native_installation_evidence import RootLocalStatEpoch
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    UnacknowledgedNativeCudaIndexGpuResources,
    hold_released_unacknowledged_native_cuda_index_resources,
    observe_unacknowledged_native_cuda_index_gpu_resources,
)
from eom_catalog_service.embedding_native_cuda_index_launch import (
    CUDA_INDEX_TEMPLATE,
    native_cuda_index_launch_environment_bytes,
    native_cuda_index_unit,
)
from eom_catalog_service.embedding_native_cuda_index_lifetime import (
    NATIVE_CUDA_INDEX_LIFETIME_ROOT,
    apply_native_cuda_index_effect,
)
from eom_catalog_service.embedding_native_cuda_index_observation import (
    CapturedNativeCudaIndexLaunchFiles,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.gpu_unit_policy_observation import observe_native_cuda_index_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_failed_gpu_unit_metadata,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    UnitEffectRecordError,
    require_unit_effect_phase_absent,
    reserve_unit_effect_phase,
    write_unit_effect_record,
)


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_INDEX_UNACKNOWLEDGED_" + suffix)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class UnacknowledgedNativeCudaIndexTerminal:
    execution_id: str
    job_id: str
    association_sha256: str
    input_raw_sha256: str
    environment_raw_sha256: str
    ready_raw_sha256: str
    ready_epoch: RootLocalStatEpoch
    terminal_unit: CpuUnitObservation
    terminal_pid: int
    original_outcome: Literal["FAILED"]
    stored_descriptors: Literal[0, 1]
    effective_policy_sha256: str
    device: CudaRuntimeDeviceCapture
    resources: UnacknowledgedNativeCudaIndexGpuResources | None
    observed_at_utc: str


@dataclass(frozen=True, slots=True)
class UnacknowledgedNativeCudaIndexRetirement:
    original_terminal: UnacknowledgedNativeCudaIndexTerminal
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


def _epoch(value: os.stat_result) -> RootLocalStatEpoch:
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


def _identity(captured: CapturedNativeCudaIndexLaunchFiles) -> str:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(captured) is CapturedNativeCudaIndexLaunchFiles, "IDENTITY_INVALID")
    captured.assert_current()
    return native_cuda_index_unit(captured.basis.launch.execution_id)


def _ack_absent(unit: str, invocation: str) -> None:
    require_unit_effect_phase_absent(NATIVE_CUDA_INDEX_LIFETIME_ROOT, unit, invocation, "ack")


def _empty_cgroup(unit: str) -> None:
    try:
        processes = root_owned_unit_processes(unit)
    except FileNotFoundError:
        _require(not (Path("/sys/fs/cgroup/system.slice") / unit).exists(), "TERMINATION_UNCERTAIN")
        processes = ()
    _require(processes == (), "TERMINATION_UNCERTAIN")


def _ready_metadata(captured: CapturedNativeCudaIndexLaunchFiles) -> tuple[str, RootLocalStatEpoch]:
    # The worker is already terminal with an empty cgroup: partial/empty bytes are
    # retained as evidence, never parsed as readiness or used to authorize compute.
    captured.assert_current()
    path = captured.execution / "ready.json"
    before = _epoch(path.lstat())
    _require(before[:6] == captured.ready_identity, "READY_CHANGED")
    files = NumericalRuntimeFileSnapshots(0)
    member = files.observe_protected_member_bytes(path, maximum=MAX_NATIVE_CUDA_INDEX_READY_BYTES)
    _require(_epoch(path.lstat()) == before, "READY_CHANGED")
    files.assert_unchanged()
    captured.assert_current()
    return member.sha256, before


def _basis(
    terminal: UnacknowledgedNativeCudaIndexTerminal, captured: CapturedNativeCudaIndexLaunchFiles
) -> str:
    unit = _identity(captured)
    _require(type(terminal) is UnacknowledgedNativeCudaIndexTerminal, "IDENTITY_INVALID")
    launch = captured.basis.launch
    _require(
        terminal.original_outcome == "FAILED"
        and gpu_unit_terminal_outcome(terminal.terminal_unit) == "FAILED"
        and re.fullmatch(r"[0-9a-f]{32}", terminal.terminal_unit.invocation_id) is not None
        and terminal.terminal_unit.fragment_path == "/etc/systemd/system/" + CUDA_INDEX_TEMPLATE
        and type(terminal.terminal_pid) is int
        and 0 < terminal.terminal_pid <= 2147483647
        and type(terminal.stored_descriptors) is int
        and terminal.stored_descriptors in {0, 1}
        and ((terminal.resources is None) == (terminal.stored_descriptors == 0))
        and (
            terminal.resources is None
            or (
                type(terminal.resources) is UnacknowledgedNativeCudaIndexGpuResources
                and terminal.resources.shared_gpu_lease.holder_pid == terminal.terminal_pid
            )
        )
        and (
            terminal.execution_id,
            terminal.job_id,
            terminal.association_sha256,
            terminal.input_raw_sha256,
            terminal.environment_raw_sha256,
            terminal.device,
        )
        == (
            launch.execution_id,
            launch.job_id,
            launch.association_sha256,
            launch.input_raw_sha256,
            sha256_bytes(native_cuda_index_launch_environment_bytes(launch)),
            captured.device,
        ),
        "IDENTITY_INVALID",
    )
    _ack_absent(unit, terminal.terminal_unit.invocation_id)
    _empty_cgroup(unit)
    _require(
        _ready_metadata(captured) == (terminal.ready_raw_sha256, terminal.ready_epoch)
        and observe_native_cuda_index_unit_policy(unit) == terminal.effective_policy_sha256,
        "PINNED_BASIS_CHANGED",
    )
    return unit


def observe_unacknowledged_native_cuda_index_terminal(
    captured: CapturedNativeCudaIndexLaunchFiles, *, expected_unit: CpuUnitObservation
) -> UnacknowledgedNativeCudaIndexTerminal:
    """Read actual failed unit/PID/store without requiring live owner, deadline or READY."""
    unit = _identity(captured)
    _require(type(expected_unit) is CpuUnitObservation, "IDENTITY_INVALID")
    _require(gpu_unit_terminal_outcome(expected_unit) == "FAILED", "IDENTITY_INVALID")
    policy = observe_native_cuda_index_unit_policy(unit)

    def current() -> tuple[int, Literal[0, 1]]:
        _ack_absent(unit, expected_unit.invocation_id)
        _require(
            inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE) == expected_unit,
            "IDENTITY_CHANGED",
        )
        _empty_cgroup(unit)
        return observe_failed_gpu_unit_metadata(
            unit, template=CUDA_INDEX_TEMPLATE, expected=expected_unit
        )

    pid, store = current()
    ready_hash, ready_epoch = _ready_metadata(captured)
    resources = None
    if store == 1:
        observe_runtime_device(captured.device)
        resources = observe_unacknowledged_native_cuda_index_gpu_resources(
            unit=unit, terminal_pid=pid, lease_gid=captured.lease_gid
        )
        _require(observe_cuda_probe_gpu_clients(captured.device) == (), "GPU_BUSY")
    _require(current() == (pid, store), "IDENTITY_CHANGED")
    launch = captured.basis.launch
    result = UnacknowledgedNativeCudaIndexTerminal(
        launch.execution_id,
        launch.job_id,
        launch.association_sha256,
        launch.input_raw_sha256,
        sha256_bytes(native_cuda_index_launch_environment_bytes(launch)),
        ready_hash,
        ready_epoch,
        expected_unit,
        pid,
        "FAILED",
        store,
        policy,
        captured.device,
        resources,
        _timestamp(),
    )
    _basis(result, captured)
    if resources is not None:
        _require(
            observe_unacknowledged_native_cuda_index_gpu_resources(
                unit=unit, terminal_pid=pid, lease_gid=captured.lease_gid
            )
            == resources,
            "RESOURCE_CHANGED",
        )
        _require(observe_cuda_probe_gpu_clients(captured.device) == (), "GPU_BUSY")
        observe_runtime_device(captured.device)
    _require(current() == (pid, store), "IDENTITY_CHANGED")
    captured.assert_current()
    return result


def observe_retired_unacknowledged_native_cuda_index_unit(
    terminal: UnacknowledgedNativeCudaIndexTerminal, captured: CapturedNativeCudaIndexLaunchFiles
) -> UnacknowledgedNativeCudaIndexRetirement:
    """Read-only reconciliation; store0 never inspects an unrelated physical GPU holder."""
    unit = _basis(terminal, captured)

    def stopped() -> StoppedGpuUnit:
        _basis(terminal, captured)
        observed = observe_stopped_gpu_unit(
            unit, template=CUDA_INDEX_TEMPLATE, invocation=terminal.terminal_unit.invocation_id
        )
        _require(observed.stored_descriptors == 0, "RETIREMENT_UNCERTAIN")
        return observed

    before = stopped()
    scope = (
        nullcontext()
        if terminal.resources is None
        else hold_released_unacknowledged_native_cuda_index_resources(terminal.resources, unit=unit)
    )
    with scope:
        if terminal.resources is not None:
            observe_runtime_device(terminal.device)
            _require(observe_cuda_probe_gpu_clients(terminal.device) == (), "GPU_BUSY")
        _require(stopped() == before, "RETIREMENT_UNCERTAIN")
        captured.assert_current()
        if terminal.resources is not None:
            observe_runtime_device(terminal.device)
        _require(stopped() == before, "RETIREMENT_UNCERTAIN")
    return UnacknowledgedNativeCudaIndexRetirement(terminal, before, _timestamp())


def _save(
    directory: int,
    name: Literal["intent.json", "result.json"],
    event: str,
    value: UnacknowledgedNativeCudaIndexTerminal | UnacknowledgedNativeCudaIndexRetirement,
) -> None:
    try:
        write_unit_effect_record(
            directory,
            name,
            canonical_json_bytes(
                {
                    "event": event,
                    "observation": TypeAdapter(type(value)).dump_python(value, mode="json"),
                    "admission_granted": False,
                }
            ),
        )
    except (OSError, UnitEffectRecordError):
        raise ValueError("NATIVE_CUDA_INDEX_UNACKNOWLEDGED_RECORD_UNCERTAIN") from None


def retire_unacknowledged_native_cuda_index_unit(
    terminal: UnacknowledgedNativeCudaIndexTerminal, captured: CapturedNativeCudaIndexLaunchFiles
) -> UnacknowledgedNativeCudaIndexRetirement:
    """Reserve once, preserve FAILED, reset and clean only this original retained store."""
    unit = _basis(terminal, captured)

    def recheck() -> None:
        fresh = observe_unacknowledged_native_cuda_index_terminal(
            captured, expected_unit=terminal.terminal_unit
        )
        _require(
            replace(fresh, observed_at_utc=terminal.observed_at_utc) == terminal, "IDENTITY_CHANGED"
        )

    recheck()
    try:
        directory = reserve_unit_effect_phase(
            NATIVE_CUDA_INDEX_LIFETIME_ROOT,
            unit,
            terminal.terminal_unit.invocation_id,
            "retirement",
        )
    except FileExistsError:
        raise ValueError("NATIVE_CUDA_INDEX_UNACKNOWLEDGED_EFFECT_ALREADY_RESERVED") from None
    except (OSError, UnitEffectRecordError):
        raise ValueError("NATIVE_CUDA_INDEX_UNACKNOWLEDGED_RECORD_UNCERTAIN") from None
    try:
        _save(
            directory, "intent.json", "NATIVE_CUDA_INDEX_UNACKNOWLEDGED_RETIREMENT_INTENT", terminal
        )
        recheck()
        apply_native_cuda_index_effect("RESET_FAILED", unit)
        stopped = observe_stopped_gpu_unit(
            unit, template=CUDA_INDEX_TEMPLATE, invocation=terminal.terminal_unit.invocation_id
        )
        _require(
            terminal.stored_descriptors == 1 or stopped.stored_descriptors == 0,
            "RETIREMENT_UNCERTAIN",
        )
        if stopped.stored_descriptors == 1:
            _require(terminal.resources is not None, "RETIREMENT_UNCERTAIN")
            _basis(terminal, captured)
            observe_runtime_device(terminal.device)
            _require(
                observe_unacknowledged_native_cuda_index_gpu_resources(
                    unit=unit, terminal_pid=terminal.terminal_pid, lease_gid=captured.lease_gid
                )
                == terminal.resources,
                "RESOURCE_CHANGED",
            )
            _require(observe_cuda_probe_gpu_clients(terminal.device) == (), "GPU_BUSY")
            _require(
                observe_stopped_gpu_unit(
                    unit,
                    template=CUDA_INDEX_TEMPLATE,
                    invocation=terminal.terminal_unit.invocation_id,
                )
                == stopped,
                "RETIREMENT_UNCERTAIN",
            )
            _basis(terminal, captured)
            apply_native_cuda_index_effect("CLEAN_FDSTORE", unit)
        result = observe_retired_unacknowledged_native_cuda_index_unit(terminal, captured)
        _save(directory, "result.json", "NATIVE_CUDA_INDEX_UNACKNOWLEDGED_RETIRED", result)
        return result
    finally:
        try:
            os.close(directory)
        except OSError:
            raise ValueError("NATIVE_CUDA_INDEX_UNACKNOWLEDGED_RECORD_UNCERTAIN") from None

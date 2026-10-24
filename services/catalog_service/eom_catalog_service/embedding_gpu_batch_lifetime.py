"""Original acquired-GPU batch terminal/retirement; no source grant, model replay or publish."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_gpu_control import validate_embedding_gpu_allocation_link
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
    hold_released_embedding_gpu_batch_resources,
    hold_released_ungranted_embedding_gpu_batch_resources,
    observe_embedding_gpu_batch_retained_resources,
    observe_ungranted_embedding_gpu_batch_resources,
)
from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_gpu_batch_observation import (
    CapturedEmbeddingGpuBatchMachine,
    EmbeddingGpuBatchReadyObservation,
)
from eom_catalog_service.embedding_gpu_batch_unit_descriptor import (
    require_embedding_gpu_batch_descriptor,
)
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import native_process_start_ticks
from eom_catalog_service.gpu_unit_policy_observation import observe_embedding_gpu_batch_unit_policy
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_embedding_gpu_batch_terminal_metadata,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    require_unit_effect_phase_absent,
    reserve_unit_effect_phase,
    write_unit_effect_record,
)

GPU_BATCH_LIFETIME_ROOT = Path("/opt/eom/embedding-gpu-batch-lifetimes")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_LIFETIME_INVALID")


def _basis(
    ready: EmbeddingGpuBatchReadyObservation, captured: CapturedEmbeddingGpuBatchMachine
) -> str:
    _require(
        os.getresuid() == (0, 0, 0)
        and type(ready) is EmbeddingGpuBatchReadyObservation
        and type(captured) is CapturedEmbeddingGpuBatchMachine
    )
    validate_embedding_gpu_allocation_link(captured.prepared.request, ready.readiness)
    unit = native_embedding_gpu_batch_unit(captured.prepared.launch.attempt_hex)
    _require(
        ready.cgroup == "/system.slice/" + unit
        and ready.unit.fragment_path == "/etc/systemd/system/" + GPU_BATCH_TEMPLATE
        and ready.unit.main_pid == ready.readiness.pid
        and ready.unit.status.active_state == "activating"
        and ready.unit.status.sub_state == "start"
        and ready.unit.exited_monotonic == 0
        and re.fullmatch(r"[0-9a-f]{32}", ready.unit.invocation_id) is not None
        and ready.unit.status.exec_main_started_monotonic > 0
        and ready.readiness.expected_device_capture == captured.device
        and ready.input_epoch == captured.prepared.input_epoch
        and ready.allocation_epoch == captured.allocation_epoch
        and ready.output_identities == captured.output_identities
        and (
            ready.readiness.worker_uid,
            ready.readiness.worker_gid,
            ready.readiness.supplementary_gids,
        )
        == (captured.worker_uid, captured.worker_gid, (captured.lease_gid,))
        and type(ready.resources) is CudaProbeResourceObservation
        and ready.resources.shared_gpu_lease.holder_pid == ready.readiness.pid
        and ready.resources.shared_gpu_lease.holder_start_time_ticks
        == ready.readiness.start_time_ticks
    )
    captured.assert_current()
    return unit


def require_embedding_gpu_batch_processes_ended(ready: EmbeddingGpuBatchReadyObservation) -> None:
    _require(os.getresuid() == (0, 0, 0) and type(ready) is EmbeddingGpuBatchReadyObservation)
    instance = ready.readiness.allocation_attempt_id.removeprefix("embeddingallocation_")
    unit = native_embedding_gpu_batch_unit(instance)
    _require(ready.cgroup == "/system.slice/" + unit)
    process = Path("/proc") / str(ready.readiness.pid)
    try:
        uid = process.lstat().st_uid
        raw = read_live_runtime_os_file(process / "stat", maximum=65536, owner_uid=uid)
    except FileNotFoundError:
        pass
    else:
        _require(
            native_process_start_ticks(raw, ready.readiness.pid) != ready.readiness.start_time_ticks
        )
    require_embedding_gpu_batch_cgroup_empty(unit)


def require_embedding_gpu_batch_cgroup_empty(unit: str) -> None:
    """Own original batch cgroup only; removal after STOP also means no owned processes."""
    _require(
        os.getresuid() == (0, 0, 0)
        and type(unit) is str
        and re.fullmatch(r"eom-embedding-native-gpu-batch@[0-9a-f]{32}\.service", unit) is not None
    )
    try:
        pids = root_owned_unit_processes(unit)
    except FileNotFoundError:
        try:
            (Path("/sys/fs/cgroup/system.slice") / unit).lstat()
        except FileNotFoundError:
            pids = ()
        else:
            raise ValueError("EMBEDDING_GPU_BATCH_LIFETIME_INVALID") from None
    _require(pids == ())


@dataclass(frozen=True, slots=True)
class EmbeddingGpuBatchTerminalObservation:
    ready: EmbeddingGpuBatchReadyObservation
    terminal_unit: CpuUnitObservation
    original_outcome: Literal["SUCCEEDED", "FAILED"]


def observe_embedding_gpu_batch_terminal(
    ready: EmbeddingGpuBatchReadyObservation, captured: CapturedEmbeddingGpuBatchMachine
) -> EmbeddingGpuBatchTerminalObservation:
    unit = _basis(ready, captured)
    before = inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE)
    _require(
        before.invocation_id == ready.unit.invocation_id
        and before.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic
    )
    outcome = gpu_unit_terminal_outcome(before)
    require_embedding_gpu_batch_processes_ended(ready)
    observe_runtime_device(captured.device)
    observe_embedding_gpu_batch_retained_resources(ready.resources, unit=unit)
    _require(observe_cuda_probe_gpu_clients(captured.device) == ())
    _require(observe_embedding_gpu_batch_unit_policy(unit) == ready.effective_policy_sha256)
    captured.assert_current()
    observe_embedding_gpu_batch_retained_resources(ready.resources, unit=unit)
    require_embedding_gpu_batch_processes_ended(ready)
    _require(inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE) == before)
    return EmbeddingGpuBatchTerminalObservation(ready, before, outcome)


@dataclass(frozen=True, slots=True)
class EmbeddingGpuBatchRetirement:
    original_terminal: EmbeddingGpuBatchTerminalObservation
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


def _terminal_basis(
    terminal: EmbeddingGpuBatchTerminalObservation, captured: CapturedEmbeddingGpuBatchMachine
) -> str:
    _require(type(terminal) is EmbeddingGpuBatchTerminalObservation)
    unit = _basis(terminal.ready, captured)
    _require(
        terminal.terminal_unit.main_pid == 0
        and terminal.terminal_unit.invocation_id == terminal.ready.unit.invocation_id
        and terminal.terminal_unit.status.exec_main_started_monotonic
        == terminal.ready.unit.status.exec_main_started_monotonic
        and terminal.original_outcome == gpu_unit_terminal_outcome(terminal.terminal_unit)
    )
    return unit


def observe_retired_embedding_gpu_batch(
    terminal: EmbeddingGpuBatchTerminalObservation, captured: CapturedEmbeddingGpuBatchMachine
) -> EmbeddingGpuBatchRetirement:
    """Read-only reconciliation; never resubmit work or repeat a cleanup side effect."""
    unit = _terminal_basis(terminal, captured)
    ready = terminal.ready
    before = observe_stopped_gpu_unit(
        unit, template=GPU_BATCH_TEMPLATE, invocation=ready.unit.invocation_id
    )
    _require(before.stored_descriptors == 0)
    require_embedding_gpu_batch_processes_ended(ready)
    observe_runtime_device(captured.device)
    with hold_released_embedding_gpu_batch_resources(ready.resources, unit=unit):
        _require(observe_cuda_probe_gpu_clients(captured.device) == ())
        require_embedding_gpu_batch_processes_ended(ready)
        captured.assert_current()
        _require(
            observe_stopped_gpu_unit(
                unit, template=GPU_BATCH_TEMPLATE, invocation=ready.unit.invocation_id
            )
            == before
        )
    return EmbeddingGpuBatchRetirement(
        terminal,
        before,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def apply_embedding_gpu_batch_effect(
    action: Literal["STOP", "RESET_FAILED", "CLEAN_FDSTORE"], unit: str
) -> None:
    """Closed root-only effects, never an arbitrary service command or compute ACK."""
    _require(
        os.getresuid() == (0, 0, 0)
        and type(unit) is str
        and re.fullmatch(r"eom-embedding-native-gpu-batch@[0-9a-f]{32}\.service", unit) is not None
    )
    _require(type(action) is str and action in {"STOP", "RESET_FAILED", "CLEAN_FDSTORE"})
    arguments = {
        "STOP": ("stop",),
        "RESET_FAILED": ("reset-failed",),
        "CLEAN_FDSTORE": ("clean", "--what=fdstore"),
    }.get(action)
    _require(arguments is not None)
    assert arguments is not None
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "--no-ask-password", *arguments, unit),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("EMBEDDING_GPU_BATCH_EFFECT_UNCERTAIN") from None
    _require(result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384)


def retire_embedding_gpu_batch(
    terminal: EmbeddingGpuBatchTerminalObservation, captured: CapturedEmbeddingGpuBatchMachine
) -> EmbeddingGpuBatchRetirement:
    """Retire only the exact original ended invocation; preserve its success/failure."""
    unit = _terminal_basis(terminal, captured)
    ready = terminal.ready
    _require(observe_embedding_gpu_batch_terminal(ready, captured) == terminal)
    directory = reserve_unit_effect_phase(
        GPU_BATCH_LIFETIME_ROOT, unit, ready.unit.invocation_id, "retirement"
    )
    try:
        write_unit_effect_record(
            directory,
            "intent.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_RETIREMENT_INTENT",
                    "observation": TypeAdapter(EmbeddingGpuBatchTerminalObservation).dump_python(
                        terminal, mode="json"
                    ),
                }
            ),
        )
        _require(observe_embedding_gpu_batch_terminal(ready, captured) == terminal)
        apply_embedding_gpu_batch_effect(
            "STOP" if terminal.original_outcome == "SUCCEEDED" else "RESET_FAILED", unit
        )
        stopped = observe_stopped_gpu_unit(
            unit, template=GPU_BATCH_TEMPLATE, invocation=ready.unit.invocation_id
        )
        if stopped.stored_descriptors == 1:
            require_embedding_gpu_batch_processes_ended(ready)
            observe_runtime_device(captured.device)
            observe_embedding_gpu_batch_retained_resources(ready.resources, unit=unit)
            _require(observe_cuda_probe_gpu_clients(captured.device) == ())
            _require(
                observe_stopped_gpu_unit(
                    unit, template=GPU_BATCH_TEMPLATE, invocation=ready.unit.invocation_id
                )
                == stopped
            )
            captured.assert_current()
            apply_embedding_gpu_batch_effect("CLEAN_FDSTORE", unit)
        result = observe_retired_embedding_gpu_batch(terminal, captured)
        write_unit_effect_record(
            directory,
            "result.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_RETIRED_NOT_PUBLISHED",
                    "observation": TypeAdapter(EmbeddingGpuBatchRetirement).dump_python(
                        result, mode="json"
                    ),
                }
            ),
        )
        return result
    finally:
        os.close(directory)


def retire_failed_ungranted_embedding_gpu_batch(
    captured: CapturedEmbeddingGpuBatchMachine, *, original: CpuUnitObservation
) -> StoppedGpuUnit:
    """Failed-before-GRANT cleanup only, never READY, successful computation or fallback.

    Empty original numeric files and an absent grant/ACK are mandatory. A retained
    descriptor is read independently using actual ExecMainPID, not a claimed birth.
    Zero-store failures do not inspect or interrupt an unrelated image/trainer holder.
    """
    _require(
        os.getresuid() == (0, 0, 0)
        and type(captured) is CapturedEmbeddingGpuBatchMachine
        and type(original) is CpuUnitObservation
    )
    unit = native_embedding_gpu_batch_unit(captured.prepared.launch.attempt_hex)
    terminal = inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE)
    require_embedding_gpu_batch_descriptor(
        captured.prepared.launch.attempt_hex, terminal.drop_in_paths
    )
    _require(
        terminal.invocation_id == original.invocation_id
        and re.fullmatch(r"[0-9a-f]{32}", original.invocation_id) is not None
        and terminal.status.exec_main_started_monotonic
        == original.status.exec_main_started_monotonic
        and original.status.exec_main_started_monotonic > 0
        and terminal.fragment_path == "/etc/systemd/system/" + GPU_BATCH_TEMPLATE
        and not terminal.status.need_daemon_reload
        and gpu_unit_terminal_outcome(terminal) == "FAILED"
    )
    policy = observe_embedding_gpu_batch_unit_policy(unit)
    pid, store = observe_embedding_gpu_batch_terminal_metadata(unit, expected=terminal)
    _require(pid == original.main_pid)

    def pregrant() -> None:
        captured.assert_precompute()
        require_unit_effect_phase_absent(
            GPU_BATCH_LIFETIME_ROOT, unit, original.invocation_id, "ack"
        )
        require_embedding_gpu_batch_cgroup_empty(unit)

    def current() -> None:
        pregrant()
        _require(inspect_cpu_unit(unit, template=GPU_BATCH_TEMPLATE) == terminal)
        _require(
            observe_embedding_gpu_batch_terminal_metadata(unit, expected=terminal) == (pid, store)
        )
        _require(observe_embedding_gpu_batch_unit_policy(unit) == policy)

    current()
    resources = None
    if store == 1:
        resources = observe_ungranted_embedding_gpu_batch_resources(
            unit=unit, terminal_pid=pid, lease_gid=captured.lease_gid
        )
        observe_runtime_device(captured.device)
        _require(observe_cuda_probe_gpu_clients(captured.device) == ())
    current()
    directory = reserve_unit_effect_phase(
        GPU_BATCH_LIFETIME_ROOT, unit, original.invocation_id, "retirement"
    )
    try:
        write_unit_effect_record(
            directory,
            "intent.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_FAILED_BEFORE_GRANT_RETIREMENT_INTENT",
                    "allocation_request_sha256": captured.prepared.request.message_sha256,
                    "original_terminal": TypeAdapter(CpuUnitObservation).dump_python(
                        terminal, mode="json"
                    ),
                    "terminal_pid": pid,
                    "stored_descriptors": store,
                    "resources": TypeAdapter(type(resources)).dump_python(resources, mode="json"),
                    "effective_policy_sha256": policy,
                    "original_outcome": "FAILED",
                }
            ),
        )
        current()
        apply_embedding_gpu_batch_effect("RESET_FAILED", unit)
        stopped = observe_stopped_gpu_unit(
            unit, template=GPU_BATCH_TEMPLATE, invocation=original.invocation_id
        )
        _require(store == 1 or stopped.stored_descriptors == 0)
        if stopped.stored_descriptors == 1:
            _require(resources is not None)
            _require(
                observe_ungranted_embedding_gpu_batch_resources(
                    unit=unit, terminal_pid=pid, lease_gid=captured.lease_gid
                )
                == resources
            )
            pregrant()
            observe_runtime_device(captured.device)
            _require(observe_cuda_probe_gpu_clients(captured.device) == ())
            _require(
                observe_stopped_gpu_unit(
                    unit, template=GPU_BATCH_TEMPLATE, invocation=original.invocation_id
                )
                == stopped
            )
            apply_embedding_gpu_batch_effect("CLEAN_FDSTORE", unit)

        def released() -> StoppedGpuUnit:
            pregrant()
            value = observe_stopped_gpu_unit(
                unit, template=GPU_BATCH_TEMPLATE, invocation=original.invocation_id
            )
            _require(value.stored_descriptors == 0)
            return value

        final = released()
        if resources is not None:
            with hold_released_ungranted_embedding_gpu_batch_resources(resources, unit=unit):
                observe_runtime_device(captured.device)
                _require(observe_cuda_probe_gpu_clients(captured.device) == ())
                _require(released() == final)
        write_unit_effect_record(
            directory,
            "result.json",
            canonical_json_bytes(
                {
                    "event": "EMBEDDING_GPU_BATCH_FAILED_BEFORE_GRANT_RETIRED",
                    "invocation_id": original.invocation_id,
                    "original_outcome": "FAILED",
                    "stored_descriptors": final.stored_descriptors,
                }
            ),
        )
        return final
    finally:
        os.close(directory)

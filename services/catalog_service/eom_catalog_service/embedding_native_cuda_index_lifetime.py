"""Root INDEX ACK/retirement with original-invocation no-replay records, not admission."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_identifiers import canonical_json_bytes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    hold_released_native_cuda_index_resources,
    observe_native_cuda_index_retained_resources,
)
from eom_catalog_service.embedding_native_cuda_index_launch import CUDA_INDEX_TEMPLATE
from eom_catalog_service.embedding_native_cuda_index_observation import (
    CapturedNativeCudaIndexLaunchFiles,
    NativeCudaIndexReadyObservation,
    NativeCudaIndexTerminalObservation,
    observe_native_cuda_index_ready,
    require_native_cuda_index_observation_basis,
    require_native_cuda_index_processes_ended,
    verify_native_cuda_index_terminal,
)
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit,
    gpu_unit_terminal_outcome,
    observe_stopped_gpu_unit,
)
from eom_catalog_service.unit_effect_records import (
    UnitEffectRecordError,
    reserve_unit_effect_phase,
    write_unit_effect_record,
)

NATIVE_CUDA_INDEX_LIFETIME_ROOT = Path("/opt/eom/embedding-native-cuda-index-lifetimes")
_ROOT = NATIVE_CUDA_INDEX_LIFETIME_ROOT
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_" + suffix)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class NativeCudaIndexAcknowledgement:
    ready: NativeCudaIndexReadyObservation
    acknowledged_at_utc: str


@dataclass(frozen=True, slots=True)
class NativeCudaIndexRetirement:
    original_terminal: NativeCudaIndexTerminalObservation
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


def _identity(
    ready: NativeCudaIndexReadyObservation, captured: CapturedNativeCudaIndexLaunchFiles
) -> str:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        type(ready) is NativeCudaIndexReadyObservation
        and type(captured) is CapturedNativeCudaIndexLaunchFiles,
        "IDENTITY_INVALID",
    )
    _require(
        re.fullmatch(r"[0-9a-f]{32}", ready.execution_id) is not None
        and re.fullmatch(r"[0-9a-f]{32}", ready.unit.invocation_id) is not None,
        "IDENTITY_INVALID",
    )
    unit = require_native_cuda_index_observation_basis(ready, captured)
    _require(
        unit == CUDA_INDEX_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")
        and ready.cgroup == "/system.slice/" + unit,
        "IDENTITY_INVALID",
    )
    captured.assert_current()
    return unit


def _terminal_identity(
    terminal: NativeCudaIndexTerminalObservation, captured: CapturedNativeCudaIndexLaunchFiles
) -> str:
    # Before-READY failures have no readiness to borrow; they need a separate future path.
    _require(type(terminal) is NativeCudaIndexTerminalObservation, "IDENTITY_INVALID")
    unit = _identity(terminal.ready, captured)
    _require(
        terminal.original_outcome == gpu_unit_terminal_outcome(terminal.terminal_unit)
        and terminal.terminal_unit.main_pid == 0
        and terminal.terminal_unit.invocation_id == terminal.ready.unit.invocation_id
        and terminal.terminal_unit.status.exec_main_started_monotonic
        == terminal.ready.unit.status.exec_main_started_monotonic,
        "IDENTITY_INVALID",
    )
    return unit


def _reserve(unit: str, invocation: str, phase: Literal["ack", "retirement"]) -> int:
    try:
        return reserve_unit_effect_phase(_ROOT, unit, invocation, phase)
    except FileExistsError:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_EFFECT_ALREADY_RESERVED") from None
    except UnitEffectRecordError as error:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_" + error.code) from None
    except OSError:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_RECORD_UNCERTAIN") from None


def _save(
    directory: int,
    name: Literal["intent.json", "result.json"],
    event: str,
    observation: NativeCudaIndexReadyObservation
    | NativeCudaIndexAcknowledgement
    | NativeCudaIndexTerminalObservation
    | NativeCudaIndexRetirement,
) -> None:
    # Only frozen root metadata, never the input request, text, vectors or credentials.
    raw = canonical_json_bytes(
        {
            "event": event,
            "observation": TypeAdapter(type(observation)).dump_python(observation, mode="json"),
            "admission_granted": False,
        }
    )
    try:
        write_unit_effect_record(directory, name, raw)
    except UnitEffectRecordError as error:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_" + error.code) from None
    except OSError:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_RECORD_UNCERTAIN") from None


def _close_record(directory: int) -> None:
    try:
        os.close(directory)
    except OSError:
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_RECORD_UNCERTAIN") from None


def apply_native_cuda_index_effect(
    action: Literal["ACK", "STOP", "RESET_FAILED", "CLEAN_FDSTORE"], unit: str
) -> None:
    """One closed root-only INDEX effect; caller must own intent and original-unit proof."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        type(unit) is str
        and re.fullmatch(r"eom-embedding-native-cuda-index@[0-9a-f]{32}\.service", unit)
        is not None,
        "IDENTITY_INVALID",
    )
    arguments = {
        "ACK": ("kill", "--kill-whom=main", "--signal=SIGUSR1"),
        "STOP": ("stop",),
        "RESET_FAILED": ("reset-failed",),
        "CLEAN_FDSTORE": ("clean", "--what=fdstore"),
    }[action]
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "--no-ask-password", *arguments, unit),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("NATIVE_CUDA_INDEX_LIFETIME_EFFECT_UNCERTAIN") from None
    _require(
        result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
        "EFFECT_UNCERTAIN",
    )


def acknowledge_native_cuda_index_ready(
    ready: NativeCudaIndexReadyObservation, captured: CapturedNativeCudaIndexLaunchFiles
) -> NativeCudaIndexAcknowledgement:
    """Record and reobserve one original readiness before one root main-PID ACK."""
    unit = _identity(ready, captured)

    def recheck() -> None:
        _require(observe_native_cuda_index_ready(captured) == ready, "IDENTITY_CHANGED")

    recheck()
    directory = _reserve(unit, ready.unit.invocation_id, "ack")
    try:
        _save(directory, "intent.json", "NATIVE_CUDA_INDEX_ACK_INTENT", ready)
        recheck()
        apply_native_cuda_index_effect("ACK", unit)
        result = NativeCudaIndexAcknowledgement(ready, _timestamp())
        _save(directory, "result.json", "NATIVE_CUDA_INDEX_ACK_SENT", result)
        return result
    finally:
        _close_record(directory)


def observe_retired_native_cuda_index_unit(
    terminal: NativeCudaIndexTerminalObservation, captured: CapturedNativeCudaIndexLaunchFiles
) -> NativeCudaIndexRetirement:
    """Read-only uncertainty reconciliation; never re-ACK/reset/clean or reauthorize compute."""
    unit = _terminal_identity(terminal, captured)
    ready = terminal.ready
    before = observe_stopped_gpu_unit(
        unit, template=CUDA_INDEX_TEMPLATE, invocation=ready.unit.invocation_id
    )
    _require(before.stored_descriptors == 0, "RETIREMENT_UNCERTAIN")
    require_native_cuda_index_processes_ended(ready)
    observe_runtime_device(ready.device)
    with hold_released_native_cuda_index_resources(ready.resources, unit=unit):
        _require(observe_cuda_probe_gpu_clients(ready.device) == (), "RETIREMENT_UNCERTAIN")
        require_native_cuda_index_processes_ended(ready)
        observe_runtime_device(ready.device)
        _require(
            observe_stopped_gpu_unit(
                unit, template=CUDA_INDEX_TEMPLATE, invocation=ready.unit.invocation_id
            )
            == before,
            "RETIREMENT_UNCERTAIN",
        )
        captured.assert_current()
    return NativeCudaIndexRetirement(terminal, before, _timestamp())


def retire_native_cuda_index_unit(
    terminal: NativeCudaIndexTerminalObservation, captured: CapturedNativeCudaIndexLaunchFiles
) -> NativeCudaIndexRetirement:
    """Preserve original success/failure and retire only this exact ended INDEX invocation."""
    unit = _terminal_identity(terminal, captured)
    ready = terminal.ready

    def recheck() -> None:
        fresh = verify_native_cuda_index_terminal(ready, captured)
        _require(
            fresh.ready == ready
            and fresh.terminal_unit == terminal.terminal_unit
            and fresh.original_outcome == terminal.original_outcome,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(unit, ready.unit.invocation_id, "retirement")
    try:
        _save(directory, "intent.json", "NATIVE_CUDA_INDEX_RETIREMENT_INTENT", terminal)
        recheck()
        apply_native_cuda_index_effect(
            "STOP" if terminal.original_outcome == "SUCCEEDED" else "RESET_FAILED", unit
        )
        stopped = observe_stopped_gpu_unit(
            unit, template=CUDA_INDEX_TEMPLATE, invocation=ready.unit.invocation_id
        )
        if stopped.stored_descriptors == 1:
            require_native_cuda_index_processes_ended(ready)
            observe_runtime_device(ready.device)
            observe_native_cuda_index_retained_resources(ready.resources, unit=unit)
            _require(observe_cuda_probe_gpu_clients(ready.device) == (), "RETIREMENT_UNCERTAIN")
            _require(
                observe_stopped_gpu_unit(
                    unit, template=CUDA_INDEX_TEMPLATE, invocation=ready.unit.invocation_id
                )
                == stopped,
                "RETIREMENT_UNCERTAIN",
            )
            require_native_cuda_index_processes_ended(ready)
            captured.assert_current()
            apply_native_cuda_index_effect("CLEAN_FDSTORE", unit)
        result = observe_retired_native_cuda_index_unit(terminal, captured)
        _save(directory, "result.json", "NATIVE_CUDA_INDEX_RETIRED_NOT_ADMITTED", result)
        return result
    finally:
        _close_record(directory)

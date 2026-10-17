"""Root benchmark ACK/retirement with original-invocation no-replay records, not admission."""

from __future__ import annotations

import os
import re
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation
from eom_identifiers import canonical_json_bytes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_benchmark_cuda_observation import (
    CUDA_BENCHMARK_TEMPLATE,
    BenchmarkCudaReadyObservation,
    BenchmarkCudaTerminalObservation,
    capture_benchmark_cuda_pinned_files,
    observe_benchmark_cuda_ready,
    require_benchmark_cuda_observation_basis,
    require_benchmark_cuda_processes_ended,
    verify_benchmark_cuda_terminal,
)
from eom_catalog_service.embedding_benchmark_cuda_unacknowledged import (
    UnacknowledgedBenchmarkCudaTerminal,
    capture_unacknowledged_benchmark_files,
    observe_unacknowledged_benchmark_cuda_terminal,
    require_empty_benchmark_cuda_cgroup,
    require_unacknowledged_benchmark_ack_absent,
    require_unacknowledged_benchmark_basis,
)
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_CUDA_LIFETIME_ROOT
from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    hold_released_cuda_probe_resources,
    hold_released_unacknowledged_benchmark_resources,
    observe_benchmark_cuda_retained_resources,
    observe_unacknowledged_benchmark_gpu_resources,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
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

if TYPE_CHECKING:
    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory

_ROOT = BENCHMARK_CUDA_LIFETIME_ROOT
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("BENCHMARK_CUDA_LIFETIME_" + suffix)


@dataclass(frozen=True, slots=True)
class BenchmarkCudaAcknowledgement:
    ready: BenchmarkCudaReadyObservation
    acknowledged_at_utc: str


@dataclass(frozen=True, slots=True)
class BenchmarkCudaRetirement:
    original_terminal: BenchmarkCudaTerminalObservation
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


@dataclass(frozen=True, slots=True)
class UnacknowledgedBenchmarkCudaRetirement:
    original_terminal: UnacknowledgedBenchmarkCudaTerminal
    retired_unit: StoppedGpuUnit
    observed_at_utc: str


def _save(
    directory: int,
    name: Literal["intent.json", "result.json"],
    event: str,
    observation: BenchmarkCudaReadyObservation
    | BenchmarkCudaAcknowledgement
    | BenchmarkCudaTerminalObservation
    | BenchmarkCudaRetirement
    | UnacknowledgedBenchmarkCudaTerminal
    | UnacknowledgedBenchmarkCudaRetirement,
) -> None:
    # The same existing ROOTLOCAL envelope; not a worker/model source receipt.
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
        raise ValueError("BENCHMARK_CUDA_LIFETIME_" + error.code) from None
    except OSError:
        raise ValueError("BENCHMARK_CUDA_LIFETIME_RECORD_UNCERTAIN") from None


def _reserve(ready: BenchmarkCudaReadyObservation, phase: Literal["ack", "retirement"]) -> int:
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")
    return _reserve_original_unit(unit, ready.unit.invocation_id, phase)


def _reserve_original_unit(unit: str, invocation: str, phase: Literal["ack", "retirement"]) -> int:
    try:
        return reserve_unit_effect_phase(_ROOT, unit, invocation, phase)
    except FileExistsError:
        raise ValueError("BENCHMARK_CUDA_LIFETIME_EFFECT_ALREADY_RESERVED") from None
    except UnitEffectRecordError as error:
        raise ValueError("BENCHMARK_CUDA_LIFETIME_" + error.code) from None
    except OSError:
        raise ValueError("BENCHMARK_CUDA_LIFETIME_RECORD_UNCERTAIN") from None


def _effect(action: Literal["ACK", "STOP", "RESET_FAILED", "CLEAN_FDSTORE"], unit: str) -> None:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        re.fullmatch(r"eom-embedding-benchmark-cuda@[0-9a-f]{32}\.service", unit) is not None,
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
        raise ValueError("BENCHMARK_CUDA_LIFETIME_EFFECT_UNCERTAIN") from None
    _require(
        result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384,
        "EFFECT_UNCERTAIN",
    )


def acknowledge_benchmark_cuda_ready(
    ready: BenchmarkCudaReadyObservation,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> BenchmarkCudaAcknowledgement:
    """One physical readiness ACK only; caller retains original Job/source/launch authority.

    Intent or an uncertain result is never permission to send again. The actual
    Orchestrator must already admit the original request; this does not grant data,
    construct a model, seal an installation, publish output or retire GPU ownership.
    """
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(ready) is BenchmarkCudaReadyObservation, "IDENTITY_INVALID")
    _require(
        re.fullmatch(r"[0-9a-f]{32}", ready.execution_id) is not None
        and re.fullmatch(r"[0-9a-f]{32}", ready.unit.invocation_id) is not None,
        "IDENTITY_INVALID",
    )
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")
    _require(ready.cgroup == "/system.slice/" + unit, "IDENTITY_INVALID")

    def recheck() -> None:
        _require(
            observe_benchmark_cuda_ready(
                invocation, environment, backend=backend, inventory=inventory, host=host
            )
            == ready,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(ready, "ack")
    try:
        _save(directory, "intent.json", "BENCHMARK_CUDA_ACK_INTENT", ready)
        recheck()
        _effect("ACK", unit)
        acknowledgement = BenchmarkCudaAcknowledgement(
            ready, datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        _save(directory, "result.json", "BENCHMARK_CUDA_ACK_SENT", acknowledgement)
        return acknowledgement
    finally:
        try:
            os.close(directory)
        except OSError:
            raise ValueError("BENCHMARK_CUDA_LIFETIME_RECORD_UNCERTAIN") from None


def observe_retired_benchmark_cuda_unit(
    terminal: BenchmarkCudaTerminalObservation,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> BenchmarkCudaRetirement:
    """Read-only reconciliation after uncertainty; never repeat a reset/clean or ACK."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is BenchmarkCudaTerminalObservation, "IDENTITY_INVALID")
    ready = terminal.ready
    _require(
        terminal.original_outcome == gpu_unit_terminal_outcome(terminal.terminal_unit)
        and terminal.terminal_unit.invocation_id == ready.unit.invocation_id
        and terminal.terminal_unit.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic,
        "IDENTITY_INVALID",
    )
    captured = capture_benchmark_cuda_pinned_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    unit = require_benchmark_cuda_observation_basis(ready, captured)
    before = observe_stopped_gpu_unit(
        unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=ready.unit.invocation_id
    )
    _require(before.stored_descriptors == 0, "RETIREMENT_UNCERTAIN")
    require_benchmark_cuda_processes_ended(ready)
    observe_runtime_device(ready.device)
    with hold_released_cuda_probe_resources(ready.resources):
        _require(observe_cuda_probe_gpu_clients(ready.device) == (), "RETIREMENT_UNCERTAIN")
        require_benchmark_cuda_processes_ended(ready)
        observe_runtime_device(ready.device)
        _require(
            observe_stopped_gpu_unit(
                unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=ready.unit.invocation_id
            )
            == before,
            "RETIREMENT_UNCERTAIN",
        )
        captured.assert_current()
        inventory.assert_unchanged()
        host.assert_current()
    return BenchmarkCudaRetirement(
        terminal,
        before,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def retire_benchmark_cuda_unit(
    terminal: BenchmarkCudaTerminalObservation,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> BenchmarkCudaRetirement:
    """One outcome-preserving cleanup, after actual terminal/retained-lease/driver proof."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is BenchmarkCudaTerminalObservation, "IDENTITY_INVALID")
    ready = terminal.ready
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{ready.execution_id}.service")

    def recheck() -> None:
        fresh = verify_benchmark_cuda_terminal(
            ready, invocation, environment, backend=backend, inventory=inventory, host=host
        )
        _require(
            fresh.ready == ready
            and fresh.terminal_unit == terminal.terminal_unit
            and fresh.original_outcome == terminal.original_outcome,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(ready, "retirement")
    try:
        _save(directory, "intent.json", "BENCHMARK_CUDA_RETIREMENT_INTENT", terminal)
        recheck()
        _effect("STOP" if terminal.original_outcome == "SUCCEEDED" else "RESET_FAILED", unit)
        stopped = observe_stopped_gpu_unit(
            unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=ready.unit.invocation_id
        )
        if stopped.stored_descriptors == 1:
            observe_runtime_device(ready.device)
            observe_benchmark_cuda_retained_resources(ready.resources, unit=unit)
            _require(observe_cuda_probe_gpu_clients(ready.device) == (), "RETIREMENT_UNCERTAIN")
            _require(
                observe_stopped_gpu_unit(
                    unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=ready.unit.invocation_id
                )
                == stopped,
                "RETIREMENT_UNCERTAIN",
            )
            _effect("CLEAN_FDSTORE", unit)
        result = observe_retired_benchmark_cuda_unit(
            terminal, invocation, environment, backend=backend, inventory=inventory, host=host
        )
        _save(directory, "result.json", "BENCHMARK_CUDA_RETIRED_NOT_ADMITTED", result)
        return result
    finally:
        try:
            os.close(directory)
        except OSError:
            raise ValueError("BENCHMARK_CUDA_LIFETIME_RECORD_UNCERTAIN") from None


def observe_retired_unacknowledged_benchmark_cuda_unit(
    terminal: UnacknowledgedBenchmarkCudaTerminal,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> UnacknowledgedBenchmarkCudaRetirement:
    """Read-only original pre-ACK failure recovery, never a second cleanup command."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is UnacknowledgedBenchmarkCudaTerminal, "IDENTITY_INVALID")
    files = capture_unacknowledged_benchmark_files(
        invocation, environment, backend=backend, inventory=inventory
    )
    unit = require_unacknowledged_benchmark_basis(terminal, files)

    def stopped() -> StoppedGpuUnit:
        require_unacknowledged_benchmark_basis(terminal, files)
        require_empty_benchmark_cuda_cgroup(unit)
        value = observe_stopped_gpu_unit(
            unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=terminal.terminal_unit.invocation_id
        )
        _require(value.stored_descriptors == 0, "RETIREMENT_UNCERTAIN")
        return value

    before = stopped()
    observe_runtime_device(terminal.device)
    # An unleased exit must not open or acquire a competing image/embedding lease.
    guard = (
        nullcontext()
        if terminal.resources is None
        else hold_released_unacknowledged_benchmark_resources(terminal.resources)
    )
    with guard:
        if terminal.resources is not None:
            _require(observe_cuda_probe_gpu_clients(terminal.device) == (), "RETIREMENT_UNCERTAIN")
        _require(stopped() == before, "RETIREMENT_UNCERTAIN")
        files.assert_current()
        inventory.assert_unchanged()
        host.assert_current()
        observe_runtime_device(terminal.device)
        _require(stopped() == before, "RETIREMENT_UNCERTAIN")
    return UnacknowledgedBenchmarkCudaRetirement(
        terminal,
        before,
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def retire_unacknowledged_benchmark_cuda_unit(
    terminal: UnacknowledgedBenchmarkCudaTerminal,
    invocation: BenchmarkWorkerInvocation,
    environment: PreparedBenchmarkEnvironment,
    *,
    backend: NativeEmbeddingBackendPins,
    inventory: PrefixRuntimeInventory,
    host: ProtectedCudaEmbeddingHostClosure,
) -> UnacknowledgedBenchmarkCudaRetirement:
    """One exact-unit cleanup; preserve original pre-ACK FAILED/timeout and absent ACK."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(type(terminal) is UnacknowledgedBenchmarkCudaTerminal, "IDENTITY_INVALID")

    def recheck() -> None:
        fresh = observe_unacknowledged_benchmark_cuda_terminal(
            invocation,
            environment,
            expected_unit=terminal.terminal_unit,
            backend=backend,
            inventory=inventory,
            host=host,
        )
        _require(
            replace(fresh, observed_at_utc=terminal.observed_at_utc) == terminal, "IDENTITY_CHANGED"
        )

    recheck()
    unit = CUDA_BENCHMARK_TEMPLATE.replace("@.service", f"@{terminal.execution_id}.service")
    directory = _reserve_original_unit(unit, terminal.terminal_unit.invocation_id, "retirement")
    try:
        _save(directory, "intent.json", "BENCHMARK_CUDA_UNACKNOWLEDGED_RETIREMENT_INTENT", terminal)
        recheck()
        _effect("RESET_FAILED", unit)
        stopped = observe_stopped_gpu_unit(
            unit, template=CUDA_BENCHMARK_TEMPLATE, invocation=terminal.terminal_unit.invocation_id
        )
        if stopped.stored_descriptors == 1:
            _require(terminal.resources is not None, "RETIREMENT_UNCERTAIN")
            assert terminal.resources is not None
            require_unacknowledged_benchmark_ack_absent(terminal)
            require_empty_benchmark_cuda_cgroup(unit)
            observed = observe_unacknowledged_benchmark_gpu_resources(
                unit=unit,
                terminal_pid=terminal.terminal_pid,
                lease_gid=terminal.resources.shared_gpu_lease.lease_gid,
            )
            _require(observed == terminal.resources, "RETIREMENT_UNCERTAIN")
            _require(observe_cuda_probe_gpu_clients(terminal.device) == (), "RETIREMENT_UNCERTAIN")
            _require(
                observe_stopped_gpu_unit(
                    unit,
                    template=CUDA_BENCHMARK_TEMPLATE,
                    invocation=terminal.terminal_unit.invocation_id,
                )
                == stopped,
                "RETIREMENT_UNCERTAIN",
            )
            require_unacknowledged_benchmark_ack_absent(terminal)
            _effect("CLEAN_FDSTORE", unit)
        result = observe_retired_unacknowledged_benchmark_cuda_unit(
            terminal, invocation, environment, backend=backend, inventory=inventory, host=host
        )
        _save(
            directory, "result.json", "BENCHMARK_CUDA_UNACKNOWLEDGED_RETIRED_NOT_ADMITTED", result
        )
        return result
    finally:
        try:
            os.close(directory)
        except OSError:
            raise ValueError("BENCHMARK_CUDA_LIFETIME_RECORD_UNCERTAIN") from None

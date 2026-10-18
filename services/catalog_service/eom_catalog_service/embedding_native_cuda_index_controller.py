"""One fixed root CUDA INDEX lifetime, never source admission or Artifact publication."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit
from eom_orchestrator.native_embedding_cuda_index_handoff import (
    prepare_native_cuda_index_handoff,
    read_native_cuda_index_owner_binding,
    read_prepared_native_cuda_index,
    require_native_cuda_index_owner_current,
)
from eom_workflow.native_embedding_backend_selection import (
    MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES,
    NativeCudaBackendSelection,
    parse_native_embedding_backend_selection,
)

from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_cuda_index_entry import NativeCudaIndexLaunchPins
from eom_catalog_service.embedding_native_cuda_index_launch import (
    CUDA_INDEX_RUNTIME_ROOT,
    CUDA_INDEX_TEMPLATE,
    native_cuda_index_backend_environment_bytes,
    native_cuda_index_launch_environment_bytes,
    native_cuda_index_unit,
)
from eom_catalog_service.embedding_native_cuda_index_lifetime import (
    NativeCudaIndexRetirement,
    acknowledge_native_cuda_index_ready,
    retire_native_cuda_index_unit,
)
from eom_catalog_service.embedding_native_cuda_index_observation import (
    CapturedNativeCudaIndexLaunchFiles,
    NativeCudaIndexObservationPins,
    NativeCudaIndexReadyObservation,
    capture_native_cuda_index_launch_files,
    observe_native_cuda_index_ready,
    verify_native_cuda_index_terminal,
)
from eom_catalog_service.embedding_native_cuda_index_unacknowledged import (
    UnacknowledgedNativeCudaIndexRetirement,
    observe_unacknowledged_native_cuda_index_terminal,
    retire_unacknowledged_native_cuda_index_unit,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.gpu_unit_terminal_observation import gpu_unit_terminal_outcome

CUDA_INDEX_CONTROLLER_TEMPLATE = "eom-embedding-native-cuda-index-owner@.service"
CUDA_INDEX_BACKEND_FILE = Path("/etc/eom/embedding-native-index-backend.json")
CUDA_INDEX_BACKEND_ENVIRONMENT = Path("/etc/eom/embedding-native-cuda.env")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_COMPUTE_NS = 180 * 10**9
_TERMINAL_GUARD_NS = 10 * 10**9


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_INDEX_CONTROLLER_" + suffix)


@dataclass(frozen=True, slots=True)
class NativeCudaIndexControllerOutcome:
    """Root in-process metadata, not an owner completion/publication receipt."""

    execution_id: str
    job_id: str
    association_sha256: str
    input_raw_sha256: str
    retirement: NativeCudaIndexRetirement | UnacknowledgedNativeCudaIndexRetirement

    @property
    def succeeded(self) -> bool:
        return (
            type(self.retirement) is NativeCudaIndexRetirement
            and self.retirement.original_terminal.original_outcome == "SUCCEEDED"
        )


def _deployment(files: NumericalRuntimeFileSnapshots) -> NativeEmbeddingBackendPins:
    member = files.observe_protected_member_bytes(
        CUDA_INDEX_BACKEND_FILE, maximum=MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES
    )
    selection = parse_native_embedding_backend_selection(member.raw)
    _require(
        selection.purpose == "INDEX" and type(selection.backend) is NativeCudaBackendSelection,
        "BACKEND_INVALID",
    )
    backend = selection.backend
    assert isinstance(backend, NativeCudaBackendSelection)
    configuration = backend.configuration
    pins = NativeEmbeddingBackendPins(
        configuration.configuration_id,
        configuration.configuration_revision_id,
        configuration.configuration_sha256,
        configuration.configuration_raw_sha256,
        backend.receipt_raw_sha256,
    )
    _require(
        files.read(
            CUDA_INDEX_BACKEND_ENVIRONMENT,
            sha256=backend.cuda_environment_raw_sha256,
            maximum=4096,
        )
        == native_cuda_index_backend_environment_bytes(pins),
        "BACKEND_ENVIRONMENT_INVALID",
    )
    files.assert_unchanged()
    return pins


def _write_launch_environment(launch: NativeCudaIndexLaunchPins) -> None:
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        CUDA_INDEX_RUNTIME_ROOT / launch.execution_id,
        owner=owner,
        uid=0,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        create_protected_cpu_handoff_member(
            directory,
            "launch.env",
            native_cuda_index_launch_environment_bytes(launch),
            owner_gid=owner.owner_gid,
            mode=0o600,
        )
        os.fsync(directory)


def _start(unit: str) -> None:
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    _require(
        re.fullmatch(r"eom-embedding-native-cuda-index@[0-9a-f]{32}\.service", unit) is not None,
        "UNIT_INVALID",
    )
    try:
        started = subprocess.run(
            ("/usr/bin/systemctl", "--no-ask-password", "--no-block", "start", unit),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("NATIVE_CUDA_INDEX_CONTROLLER_START_UNCERTAIN") from None
    _require(
        started.returncode == 0 and len(started.stdout) <= 16384 and len(started.stderr) <= 16384,
        "START_UNCERTAIN",
    )


def _pin_invocation(
    observed: CpuUnitObservation, original: CpuUnitObservation | None
) -> CpuUnitObservation | None:
    if observed.fresh:
        _require(original is None, "INVOCATION_CHANGED")
        return None
    if (
        original is None
        and observed.main_pid == observed.exited_monotonic == 0
        and observed.status.exec_main_started_monotonic == 0
        and observed.status.active_state == "activating"
        and observed.status.sub_state == "start"
    ):
        # A queued start is not an actual process birth. It cannot be ACKed or
        # accepted as a failed execution, but may precede the first real snapshot.
        return None
    _require(
        re.fullmatch(r"[0-9a-f]{32}", observed.invocation_id) is not None
        and observed.status.exec_main_started_monotonic > 0,
        "INVOCATION_UNCERTAIN",
    )
    if original is not None:
        _require(
            observed.invocation_id == original.invocation_id
            and observed.status.exec_main_started_monotonic
            == original.status.exec_main_started_monotonic,
            "INVOCATION_CHANGED",
        )
        return original
    return observed


def _is_terminal(observed: CpuUnitObservation) -> bool:
    # A timeout/signal failure is terminal too; CpuUnitObservation.failed excludes timeout.
    if observed.main_pid != 0 or observed.status.active_state not in {"active", "failed"}:
        return False
    if observed.status.sub_state not in {"exited", "failed"}:
        return False
    gpu_unit_terminal_outcome(observed)
    return True


def _run_started(
    captured: CapturedNativeCudaIndexLaunchFiles,
) -> NativeCudaIndexRetirement | UnacknowledgedNativeCudaIndexRetirement:
    launch = captured.basis.launch
    unit = native_cuda_index_unit(launch.execution_id)
    original: CpuUnitObservation | None = None
    ready: NativeCudaIndexReadyObservation | None = None
    while True:
        observed = inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE)
        original = _pin_invocation(observed, original)
        if _is_terminal(observed):
            _require(original is not None, "INVOCATION_UNCERTAIN")
            if ready is None:
                # A successful exit without independently observed ACK is never numerical success.
                _require(gpu_unit_terminal_outcome(observed) == "FAILED", "READY_MISSING")
                terminal = observe_unacknowledged_native_cuda_index_terminal(
                    captured, expected_unit=observed
                )
                return retire_unacknowledged_native_cuda_index_unit(terminal, captured)
            terminal_ready = verify_native_cuda_index_terminal(ready, captured)
            _require(terminal_ready.terminal_unit == observed, "INVOCATION_CHANGED")
            return retire_native_cuda_index_unit(terminal_ready, captured)
        # Only a cheap negative readiness hint. A positive hint still requires
        # the complete protected file/process/resource observation below.
        if (
            ready is None
            and observed.main_pid > 0
            and (captured.execution / "ready.json").lstat().st_size > 0
        ):
            try:
                candidate = observe_native_cuda_index_ready(captured)
            except ValueError as error:
                if str(error) != "NATIVE_CUDA_INDEX_OBSERVATION_NOT_READY":
                    raise
            else:
                _require(
                    original is not None
                    and candidate.unit.invocation_id == original.invocation_id
                    and candidate.unit.status.exec_main_started_monotonic
                    == original.status.exec_main_started_monotonic,
                    "INVOCATION_CHANGED",
                )
                acknowledge_native_cuda_index_ready(candidate, captured)
                ready = candidate
        now = time.monotonic_ns()
        _require(now < launch.expires_ns + _TERMINAL_GUARD_NS, "TERMINATION_UNCERTAIN")
        time.sleep(min(0.1, (launch.expires_ns + _TERMINAL_GUARD_NS - now) / 10**9))


def run_native_cuda_index_controller(execution_id: str) -> NativeCudaIndexControllerOutcome:
    """Consume one fresh original launch; never retry dispatch/ACK/cleanup or publish."""
    _require(os.getresuid() == (0, 0, 0), "ROOT_REQUIRED")
    unit = native_cuda_index_unit(execution_id)
    deployment = NumericalRuntimeFileSnapshots(0)
    backend = _deployment(deployment)
    prepared = read_prepared_native_cuda_index(execution_id)
    binding = read_native_cuda_index_owner_binding(execution_id)
    require_native_cuda_index_owner_current(binding)
    _require(inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE).fresh, "ALREADY_ATTEMPTED")
    prepare_native_cuda_index_handoff(execution_id)
    launch = NativeCudaIndexLaunchPins(
        execution_id,
        prepared.request.job_id,
        prepared.association.association_sha256,
        sha256_bytes(canonical_json_bytes(prepared.request.model_dump(mode="json"))),
        time.monotonic_ns() + _COMPUTE_NS,
        backend.configuration_id,
        backend.configuration_revision_id,
        backend.configuration_sha256,
        backend.configuration_raw_sha256,
        backend.receipt_raw_sha256,
    )
    _write_launch_environment(launch)
    basis = NativeCudaIndexObservationPins(
        launch, prepared.request, binding.owner_pid, binding.owner_start_ticks
    )
    with capture_native_cuda_index_launch_files(basis) as captured:
        deployment.assert_unchanged()
        _require(read_prepared_native_cuda_index(execution_id) == prepared, "INPUT_CHANGED")
        _require(read_native_cuda_index_owner_binding(execution_id) == binding, "OWNER_CHANGED")
        require_native_cuda_index_owner_current(binding)
        captured.assert_current()
        _require(time.monotonic_ns() < launch.expires_ns, "DEADLINE_EXPIRED")
        _require(inspect_cpu_unit(unit, template=CUDA_INDEX_TEMPLATE).fresh, "ALREADY_ATTEMPTED")
        _start(unit)
        result = _run_started(captured)
        deployment.assert_unchanged()
        captured.assert_current()
        return NativeCudaIndexControllerOutcome(
            execution_id, launch.job_id, launch.association_sha256, launch.input_raw_sha256, result
        )


def main() -> int:
    if len(sys.argv) != 2:
        return 1
    try:
        return 0 if run_native_cuda_index_controller(sys.argv[1]).succeeded else 1
    except Exception:
        # No input, tokens, prompt, result or arbitrary diagnostic crosses the root CLI.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

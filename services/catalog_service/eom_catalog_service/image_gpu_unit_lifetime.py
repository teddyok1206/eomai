"""Root image-unit ACK/retirement effects with append-only, no-replay OS evidence.

Not a dispatcher or migration admission: the installer must fence all image GPU
entries before activating a caller. No worker or product Artifact uses this API.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_identifiers import canonical_json_bytes
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes
from pydantic import TypeAdapter

from eom_catalog_service.embedding_cuda_probe_gpu_clients import observe_cuda_probe_gpu_clients
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    hold_released_image_unit_gpu_resources,
    observe_image_unit_gpu_retained_resources,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.gpu_unit_terminal_observation import (
    StoppedGpuUnit as _StoppedImageGpuUnit,
)
from eom_catalog_service.gpu_unit_terminal_observation import observe_stopped_gpu_unit
from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_template
from eom_catalog_service.image_gpu_unit_observation import (
    ImageGpuUnitReadyObservation,
    ImageGpuUnitTerminalObservation,
    ImageGpuUnitUnleasedTerminalObservation,
    image_gpu_unit_terminal_outcome,
    observe_image_gpu_unit_ready,
    observe_unleased_image_gpu_unit_terminal,
    verify_image_gpu_unit_terminal,
)
from eom_catalog_service.unit_effect_records import (
    UnitEffectRecordError,
    reserve_unit_effect_phase,
    write_unit_effect_record,
)

_ROOT = Path("/opt/eom/image-gpu-lifetimes")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("IMAGE_GPU_UNIT_LIFETIME_" + suffix)


def _identity(ready: ImageGpuUnitReadyObservation) -> None:
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(type(ready) is ImageGpuUnitReadyObservation, "IDENTITY_INVALID")
    image_gpu_unit_template(ready.unit_name)
    _require(
        re.fullmatch(r"[0-9a-f]{32}", ready.unit.invocation_id) is not None, "IDENTITY_INVALID"
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _record_identity(
    observed: ImageGpuUnitReadyObservation | ImageGpuUnitUnleasedTerminalObservation,
) -> tuple[str, str]:
    if type(observed) is ImageGpuUnitReadyObservation:
        _identity(observed)
        return observed.unit_name, observed.unit.invocation_id
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    if type(observed) is ImageGpuUnitUnleasedTerminalObservation:
        image_gpu_unit_template(observed.unit_name)
        _require(
            re.fullmatch(r"[0-9a-f]{32}", observed.terminal_unit.invocation_id) is not None
            and observed.original_outcome
            == image_gpu_unit_terminal_outcome(observed.terminal_unit),
            "IDENTITY_INVALID",
        )
        return observed.unit_name, observed.terminal_unit.invocation_id
    raise ValueError("IMAGE_GPU_UNIT_LIFETIME_IDENTITY_INVALID")


def _reserve(
    ready: ImageGpuUnitReadyObservation | ImageGpuUnitUnleasedTerminalObservation,
    phase: Literal["ack", "retirement"],
) -> int:
    """One atomic phase reservation per actual invocation; never retry an old intent."""
    unit_name, invocation = _record_identity(ready)
    try:
        return reserve_unit_effect_phase(_ROOT, unit_name, invocation, phase)
    except UnitEffectRecordError as error:
        raise ValueError("IMAGE_GPU_UNIT_LIFETIME_" + error.code) from None


@dataclass(frozen=True, slots=True)
class ImageGpuUnitAcknowledgement:
    ready: ImageGpuUnitReadyObservation
    acknowledged_at_utc: str


@dataclass(frozen=True, slots=True)
class RetiredImageGpuUnit:
    load_state: str
    invocation_id: str


@dataclass(frozen=True, slots=True)
class ImageGpuUnitRetirement:
    original_terminal: ImageGpuUnitTerminalObservation | ImageGpuUnitUnleasedTerminalObservation
    retired_unit: RetiredImageGpuUnit
    observed_at_utc: str


_RecordObservation = (
    ImageGpuUnitReadyObservation
    | ImageGpuUnitAcknowledgement
    | ImageGpuUnitTerminalObservation
    | ImageGpuUnitUnleasedTerminalObservation
    | ImageGpuUnitRetirement
)


def _save(
    directory: int,
    name: Literal["intent.json", "result.json"],
    event: str,
    observation: _RecordObservation,
) -> None:
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
        raise ValueError("IMAGE_GPU_UNIT_LIFETIME_" + error.code) from None


def _effect(*arguments: str) -> None:
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "--no-ask-password", *arguments),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("IMAGE_GPU_UNIT_LIFETIME_EFFECT_UNCERTAIN") from None
    _require(result.returncode == 0, "EFFECT_UNCERTAIN")


def acknowledge_image_gpu_unit_ready(
    ready: ImageGpuUnitReadyObservation,
) -> ImageGpuUnitAcknowledgement:
    """Persist intent, reobserve, then signal only this original fixed unit main once."""
    _identity(ready)

    def recheck() -> None:
        _require(
            observe_image_gpu_unit_ready(
                ready.unit_name,
                template_sha256=ready.template_sha256,
                bootstrap_sha256=ready.bootstrap_sha256,
                device=ready.device,
            )
            == ready,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(ready, "ack")
    try:
        _save(directory, "intent.json", "IMAGE_GPU_ACK_INTENT", ready)
        recheck()
        _effect("kill", "--kill-whom=main", "--signal=SIGUSR1", ready.unit_name)
        result = ImageGpuUnitAcknowledgement(ready, _timestamp())
        _save(directory, "result.json", "IMAGE_GPU_ACK_SENT", result)
        return result
    finally:
        os.close(directory)


def _stopped_unit(
    observed: ImageGpuUnitReadyObservation | ImageGpuUnitUnleasedTerminalObservation,
) -> _StoppedImageGpuUnit:
    unit_name, invocation = _record_identity(observed)
    template = image_gpu_unit_template(unit_name)
    try:
        return observe_stopped_gpu_unit(unit_name, template=template, invocation=invocation)
    except ValueError:
        raise ValueError("IMAGE_GPU_UNIT_LIFETIME_RETIREMENT_UNCERTAIN") from None


def _retired_unit(
    observed: ImageGpuUnitReadyObservation | ImageGpuUnitUnleasedTerminalObservation,
) -> RetiredImageGpuUnit:
    stopped = _stopped_unit(observed)
    _require(stopped.stored_descriptors == 0, "RETIREMENT_UNCERTAIN")
    return RetiredImageGpuUnit(stopped.load_state, stopped.invocation_id)


def observe_retired_image_gpu_unit(
    terminal: ImageGpuUnitTerminalObservation,
) -> ImageGpuUnitRetirement:
    """Read-only recovery; never repeat stop/reset or reinterpret the original outcome."""
    _require(type(terminal) is ImageGpuUnitTerminalObservation, "IDENTITY_INVALID")
    ready = terminal.ready
    _identity(ready)
    _require(
        terminal.original_outcome == image_gpu_unit_terminal_outcome(terminal.terminal_unit)
        and terminal.terminal_unit.invocation_id == ready.unit.invocation_id
        and terminal.terminal_unit.main_pid == 0
        and terminal.terminal_unit.status.exec_main_started_monotonic
        == ready.unit.status.exec_main_started_monotonic,
        "IDENTITY_INVALID",
    )
    files = NumericalRuntimeFileSnapshots(0)
    files.read(
        Path("/etc/systemd/system") / image_gpu_unit_template(ready.unit_name),
        sha256=ready.template_sha256,
        maximum=65536,
    )
    files.read(
        Path("/usr/local/libexec/eom-image-runtime/run_gpu_unit.py"),
        sha256=ready.bootstrap_sha256,
        maximum=128 * 1024,
    )

    def empty() -> None:
        try:
            members = root_owned_unit_processes(ready.unit_name)
        except FileNotFoundError:
            _require(
                not (Path("/sys/fs/cgroup/system.slice") / ready.unit_name).exists(),
                "RETIREMENT_UNCERTAIN",
            )
            members = ()
        _require(members == (), "RETIREMENT_UNCERTAIN")

    before = _retired_unit(ready)
    empty()
    observe_runtime_device(ready.device)
    with hold_released_image_unit_gpu_resources(ready.resources):
        _require(observe_cuda_probe_gpu_clients(ready.device) == (), "RETIREMENT_UNCERTAIN")
        empty()
        observe_runtime_device(ready.device)
        _require(_retired_unit(ready) == before, "RETIREMENT_UNCERTAIN")
        files.assert_unchanged()
    return ImageGpuUnitRetirement(terminal, before, _timestamp())


def retire_image_gpu_unit(terminal: ImageGpuUnitTerminalObservation) -> ImageGpuUnitRetirement:
    """Preserve exact ended success/failure before one supported, outcome-specific effect."""
    _require(type(terminal) is ImageGpuUnitTerminalObservation, "IDENTITY_INVALID")
    _identity(terminal.ready)

    def recheck() -> None:
        fresh = verify_image_gpu_unit_terminal(terminal.ready)
        # Observation timestamps naturally differ; original identity and outcome must not.
        _require(
            fresh.ready == terminal.ready
            and fresh.terminal_unit == terminal.terminal_unit
            and fresh.original_outcome == terminal.original_outcome,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(terminal.ready, "retirement")
    try:
        _save(directory, "intent.json", "IMAGE_GPU_RETIREMENT_INTENT", terminal)
        recheck()
        _effect(
            "stop" if terminal.original_outcome == "SUCCEEDED" else "reset-failed",
            terminal.ready.unit_name,
        )
        stopped = _stopped_unit(terminal.ready)
        if stopped.stored_descriptors == 1:
            # Preserve=yes survives stop/reset. Release only the same retained
            # physical descriptor after stopped/empty cgroup/device rechecks.
            observe_runtime_device(terminal.ready.device)
            observe_image_unit_gpu_retained_resources(
                terminal.ready.resources, unit=terminal.ready.unit_name
            )
            _require(
                observe_cuda_probe_gpu_clients(terminal.ready.device) == (), "RETIREMENT_UNCERTAIN"
            )
            _require(_stopped_unit(terminal.ready) == stopped, "RETIREMENT_UNCERTAIN")
            _effect("clean", "--what=fdstore", terminal.ready.unit_name)
        result = observe_retired_image_gpu_unit(terminal)
        _save(directory, "result.json", "IMAGE_GPU_RETIRED_NOT_ADMITTED", result)
        return result
    finally:
        os.close(directory)


def observe_retired_unleased_image_gpu_unit(
    terminal: ImageGpuUnitUnleasedTerminalObservation,
) -> ImageGpuUnitRetirement:
    """No-GPU exit recovery checks only its own unit; another holder is not our lease."""
    _require(type(terminal) is ImageGpuUnitUnleasedTerminalObservation, "IDENTITY_INVALID")
    _record_identity(terminal)
    files = NumericalRuntimeFileSnapshots(0)
    files.read(
        Path("/etc/systemd/system") / image_gpu_unit_template(terminal.unit_name),
        sha256=terminal.template_sha256,
        maximum=65536,
    )
    files.read(
        Path("/usr/local/libexec/eom-image-runtime/run_gpu_unit.py"),
        sha256=terminal.bootstrap_sha256,
        maximum=128 * 1024,
    )
    before = _retired_unit(terminal)
    for _ in range(2):
        try:
            members = root_owned_unit_processes(terminal.unit_name)
        except FileNotFoundError:
            _require(
                not (Path("/sys/fs/cgroup/system.slice") / terminal.unit_name).exists(),
                "RETIREMENT_UNCERTAIN",
            )
            members = ()
        _require(members == () and _retired_unit(terminal) == before, "RETIREMENT_UNCERTAIN")
    files.assert_unchanged()
    return ImageGpuUnitRetirement(terminal, before, _timestamp())


def retire_unleased_image_gpu_unit(
    terminal: ImageGpuUnitUnleasedTerminalObservation,
) -> ImageGpuUnitRetirement:
    """Cache/input/busy exits preserve their own outcome without claiming a physical lease."""
    _require(type(terminal) is ImageGpuUnitUnleasedTerminalObservation, "IDENTITY_INVALID")
    _record_identity(terminal)

    def recheck() -> None:
        fresh = observe_unleased_image_gpu_unit_terminal(
            terminal.unit_name,
            template_sha256=terminal.template_sha256,
            bootstrap_sha256=terminal.bootstrap_sha256,
            expected_unit=terminal.terminal_unit,
        )
        _require(
            fresh.terminal_unit == terminal.terminal_unit
            and fresh.effective_policy_sha256 == terminal.effective_policy_sha256
            and fresh.original_outcome == terminal.original_outcome,
            "IDENTITY_CHANGED",
        )

    recheck()
    directory = _reserve(terminal, "retirement")
    try:
        _save(directory, "intent.json", "IMAGE_GPU_UNLEASED_RETIREMENT_INTENT", terminal)
        recheck()
        _effect(
            "stop" if terminal.original_outcome == "SUCCEEDED" else "reset-failed",
            terminal.unit_name,
        )
        result = observe_retired_unleased_image_gpu_unit(terminal)
        _save(directory, "result.json", "IMAGE_GPU_UNLEASED_RETIRED_NOT_ADMITTED", result)
        return result
    finally:
        os.close(directory)

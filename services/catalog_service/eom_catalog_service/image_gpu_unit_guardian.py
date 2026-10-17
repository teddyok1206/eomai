"""Bounded root observation of one image invocation using the existing lifecycle owner.

Installation pins are internal root-composition values, not a worker message or
proof of a legacy drain. This adapter does not launch/restart a worker or model.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.models import Sha256
from eom_orchestrator.inference_transfer_cpu_systemd import inspect_cpu_unit
from pydantic import TypeAdapter

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.image_gpu_unit_identity import (
    image_gpu_unit_template,
    image_gpu_unit_templates,
)
from eom_catalog_service.image_gpu_unit_lifetime import (
    ImageGpuUnitRetirement,
    acknowledge_image_gpu_unit_ready,
    retire_image_gpu_unit,
    retire_unleased_image_gpu_unit,
)
from eom_catalog_service.image_gpu_unit_observation import (
    ImageGpuUnitReadyObservation,
    image_gpu_unit_arguments,
    image_gpu_unit_descriptor_count,
    observe_image_gpu_unit_ready,
    observe_unleased_image_gpu_unit_terminal,
    verify_image_gpu_unit_terminal,
)

GUARDIAN_TEMPLATE = "eom-image-gpu-lifetime@.service"
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool, suffix: str) -> None:
    if not condition:
        raise ValueError("IMAGE_GPU_GUARDIAN_" + suffix)


@dataclass(frozen=True, slots=True)
class ImageGpuInstallationPins:
    templates: tuple[tuple[str, str], ...]
    bootstrap_sha256: str
    device: CudaRuntimeDeviceCapture

    def __post_init__(self) -> None:
        _require(
            type(self.templates) is tuple
            and all(type(row) is tuple and len(row) == 2 for row in self.templates),
            "INSTALLATION_PINS_INVALID",
        )
        _require(
            tuple(name for name, _ in self.templates) == image_gpu_unit_templates(),
            "INSTALLATION_PINS_INVALID",
        )
        adapter = TypeAdapter(Sha256)
        for _, digest in self.templates:
            adapter.validate_python(digest, strict=True)
        adapter.validate_python(self.bootstrap_sha256, strict=True)
        _require(type(self.device) is CudaRuntimeDeviceCapture, "INSTALLATION_PINS_INVALID")


def _timeout(raw: bytes) -> int:
    values = {}
    for line in raw.decode("utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"TimeoutStartSec", "TimeoutStopSec"}:
            _require(
                key not in values and re.fullmatch(r"[1-9][0-9]{0,5}", value) is not None,
                "TIMEOUT_INVALID",
            )
            values[key] = int(value)
    _require(
        set(values) == {"TimeoutStartSec", "TimeoutStopSec"}
        and 0 < values["TimeoutStartSec"] <= 86400
        and values["TimeoutStopSec"] <= 300,
        "TIMEOUT_INVALID",
    )
    return values["TimeoutStartSec"] + values["TimeoutStopSec"] + 30


def start_image_gpu_unit_guardian(unit: str, *, guardian_template_sha256: str) -> str:
    """Root pre-entry dispatch to one fresh fixed guardian; never restart after uncertainty.

    The caller is the protected installation composition, not an image worker.
    The guardian itself must capture the full installation before any ACK.
    """
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    image_gpu_unit_template(unit)
    digest = TypeAdapter(Sha256).validate_python(guardian_template_sha256, strict=True)
    files = NumericalRuntimeFileSnapshots(0)
    files.read(Path("/etc/systemd/system") / GUARDIAN_TEMPLATE, sha256=digest, maximum=65536)
    files.observe_protected_member_identity(Path("/usr/bin/systemd-escape"))
    try:
        escaped = subprocess.run(
            ("/usr/bin/systemd-escape", "--template=" + GUARDIAN_TEMPLATE, unit),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("IMAGE_GPU_GUARDIAN_IDENTITY_UNAVAILABLE") from None
    _require(
        escaped.returncode == 0 and len(escaped.stdout) <= 256 and len(escaped.stderr) <= 16384,
        "IDENTITY_UNAVAILABLE",
    )
    _require(
        re.fullmatch(
            rb"eom-image-gpu-lifetime@(?:[A-Za-z0-9_.]|\\x[0-9a-f]{2})+\.service\n", escaped.stdout
        )
        is not None,
        "IDENTITY_UNAVAILABLE",
    )
    guardian_unit = escaped.stdout[:-1].decode("ascii")
    _require(
        inspect_cpu_unit(guardian_unit, template=GUARDIAN_TEMPLATE).fresh, "GUARDIAN_NOT_FRESH"
    )
    files.assert_unchanged()
    try:
        submitted = subprocess.run(
            ("/usr/bin/systemctl", "--no-ask-password", "--no-block", "start", guardian_unit),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("IMAGE_GPU_GUARDIAN_SUBMISSION_UNCERTAIN") from None
    _require(submitted.returncode == 0, "SUBMISSION_UNCERTAIN")
    files.assert_unchanged()
    return guardian_unit


def manage_image_gpu_unit_lifetime(
    unit: str,
    *,
    installation: ImageGpuInstallationPins,
) -> ImageGpuUnitRetirement:
    """Observe one invocation; exactly one ACK and one outcome-specific retirement.

    An unobserved retained pre-ACK crash stays fenced for explicit recovery. It
    never manufactures READY/PID/start facts or resets an uncertain unit.
    """
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(type(installation) is ImageGpuInstallationPins, "INSTALLATION_PINS_INVALID")
    template = image_gpu_unit_template(unit)
    pins = dict(installation.templates)
    files = NumericalRuntimeFileSnapshots(0)
    current_raw = b""
    for name, digest in installation.templates:
        raw = files.read(Path("/etc/systemd/system") / name, sha256=digest, maximum=65536)
        # Pure command validation uses the actual requested instance, not a fabricated OS run.
        image_gpu_unit_arguments(raw, name.replace("@.service", "@" + unit.partition("@")[2]))
        if name == template:
            current_raw = raw
    files.read(
        Path("/usr/local/libexec/eom-image-runtime/run_gpu_unit.py"),
        sha256=installation.bootstrap_sha256,
        maximum=128 * 1024,
    )
    deadline = time.monotonic() + _timeout(current_raw)
    invocation: str | None = None
    started: int | None = None
    ready: ImageGpuUnitReadyObservation | None = None
    while time.monotonic() < deadline:
        files.assert_unchanged()
        actual = inspect_cpu_unit(unit, template=template)
        _require(
            re.fullmatch(r"[0-9a-f]{32}", actual.invocation_id) is not None,
            "INVOCATION_UNAVAILABLE",
        )
        if invocation is None:
            invocation = actual.invocation_id
        _require(actual.invocation_id == invocation, "INVOCATION_CHANGED")
        if actual.status.exec_main_started_monotonic:
            if started is None:
                started = actual.status.exec_main_started_monotonic
            _require(actual.status.exec_main_started_monotonic == started, "INVOCATION_CHANGED")
        _require(
            actual.status.active_state in {"activating", "active", "failed"}, "UNIT_STATE_UNCERTAIN"
        )
        if ready is not None:
            if actual.main_pid == 0:
                terminal = verify_image_gpu_unit_terminal(ready)
                files.assert_unchanged()
                return retire_image_gpu_unit(terminal)
        else:
            descriptors = image_gpu_unit_descriptor_count(unit)
            if actual.main_pid > 0 and descriptors == 1:
                ready = observe_image_gpu_unit_ready(
                    unit,
                    template_sha256=pins[template],
                    bootstrap_sha256=installation.bootstrap_sha256,
                    device=installation.device,
                )
                _require(ready.unit == actual, "INVOCATION_CHANGED")
                files.assert_unchanged()
                acknowledge_image_gpu_unit_ready(ready)
            elif actual.main_pid == 0 and actual.status.active_state in {"active", "failed"}:
                _require(descriptors == 0, "UNOBSERVED_RETAINED_EXIT")
                terminal_unleased = observe_unleased_image_gpu_unit_terminal(
                    unit,
                    template_sha256=pins[template],
                    bootstrap_sha256=installation.bootstrap_sha256,
                    expected_unit=actual,
                )
                files.assert_unchanged()
                return retire_unleased_image_gpu_unit(terminal_unleased)
        # This is the bounded runtime handshake, not conversational corpus polling.
        # Fast only during the 30-second ACK handshake. A running model needs
        # bounded cleanup latency, not five systemctl processes per second.
        time.sleep(0.2 if ready is None else 1.0)
    raise ValueError("IMAGE_GPU_GUARDIAN_OBSERVATION_EXPIRED")

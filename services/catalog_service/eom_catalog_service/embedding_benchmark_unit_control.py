"""Fixed root CPU/CUDA unit operations; no source grant or GPU retirement protocol."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkDevice,
    BenchmarkExecutionPolicy,
)
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_cpu_unit

from eom_catalog_service.embedding_benchmark_unit_policy import (
    BenchmarkUnitFamily as BenchmarkUnitFamily,
)
from eom_catalog_service.embedding_benchmark_unit_policy import (
    benchmark_unit_family as benchmark_unit_family,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_CPU_FAMILY = benchmark_unit_family("CPU")
_CUDA_FAMILY = benchmark_unit_family("CUDA")
CPU_BENCHMARK_TEMPLATE = _CPU_FAMILY.service_template
CPU_BENCHMARK_SOCKET = _CPU_FAMILY.socket_template
CPU_BENCHMARK_TEMPLATE_SHA256 = _CPU_FAMILY.service_sha256
CPU_BENCHMARK_SOCKET_SHA256 = _CPU_FAMILY.socket_sha256
CUDA_BENCHMARK_TEMPLATE = _CUDA_FAMILY.service_template
CUDA_BENCHMARK_SOCKET = _CUDA_FAMILY.socket_template
CUDA_BENCHMARK_TEMPLATE_SHA256 = _CUDA_FAMILY.service_sha256
CUDA_BENCHMARK_SOCKET_SHA256 = _CUDA_FAMILY.socket_sha256
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_SOCKET_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "NeedDaemonReload",
    "FragmentPath",
    "DropInPaths",
    "Job",
)


def require_root_benchmark_control() -> None:
    if os.getresuid() != (0, 0, 0) or os.getresgid() != (0, 0, 0):
        raise ValueError("BENCHMARK_UNIT_ROOT_REQUIRED")


@dataclass(frozen=True, slots=True)
class FixedRootBenchmarkUnits:
    """Two reviewed families, not arbitrary units/commands or an execution permit."""

    device: BenchmarkDevice
    execution_id: str
    policy: BenchmarkExecutionPolicy | None = None

    def __post_init__(self) -> None:
        require_root_benchmark_control()
        if (
            type(self.device) is not str
            or self.device not in {"CPU", "CUDA"}
            or type(self.execution_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", self.execution_id, re.ASCII) is None
        ):
            raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
        benchmark_unit_family(self.device, self.policy)

    @property
    def family(self) -> BenchmarkUnitFamily:
        return benchmark_unit_family(self.device, self.policy)

    @property
    def template(self) -> str:
        return self.family.service_template

    @property
    def socket_template(self) -> str:
        return self.family.socket_template

    @property
    def service(self) -> str:
        return self.template.replace("@.service", f"@{self.execution_id}.service")

    @property
    def socket(self) -> str:
        return self.socket_template.replace("@.socket", f"@{self.execution_id}.socket")

    def capture_installed(self) -> NumericalRuntimeFileSnapshots:
        require_root_benchmark_control()
        files = NumericalRuntimeFileSnapshots(0)
        family = self.family
        service, listener, service_sha, socket_sha = (
            family.service_template,
            family.socket_template,
            family.service_sha256,
            family.socket_sha256,
        )
        for name, digest in ((service, service_sha), (listener, socket_sha)):
            files.read(Path("/etc/systemd/system") / name, sha256=digest, maximum=65536)
        files.assert_unchanged()
        return files

    def observe(self) -> CpuUnitObservation:
        require_root_benchmark_control()
        return inspect_cpu_unit(self.service, template=self.template)

    def _run(self, arguments: tuple[str, ...]) -> bytes:
        require_root_benchmark_control()
        try:
            result = subprocess.run(
                ("/usr/bin/systemctl", *arguments),
                capture_output=True,
                check=False,
                timeout=10,
                env=_ENV,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("BENCHMARK_UNIT_EFFECT_UNCERTAIN") from None
        if result.returncode != 0 or len(result.stdout) > 16384 or len(result.stderr) > 16384:
            raise ValueError("BENCHMARK_UNIT_EFFECT_UNCERTAIN")
        return result.stdout

    def require_socket_state(self, *, active: bool) -> None:
        raw = self._run(("show", self.socket, *("--property=" + key for key in _SOCKET_PROPERTIES)))
        fields: dict[str, str] = {}
        for line in raw.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in _SOCKET_PROPERTIES or key in fields:
                raise ValueError("BENCHMARK_UNIT_SOCKET_STATE_UNCERTAIN")
            fields[key] = value
        if not (
            set(fields) == set(_SOCKET_PROPERTIES)
            and fields["LoadState"] == "loaded"
            and fields["ActiveState"] == ("active" if active else "inactive")
            and fields["SubState"] in ({"listening", "running"} if active else {"dead"})
            and fields["NeedDaemonReload"] == "no"
            and fields["FragmentPath"] == "/etc/systemd/system/" + self.socket_template
            and fields["DropInPaths"] == ""
            and fields["Job"] in {"", "0"}
        ):
            raise ValueError("BENCHMARK_UNIT_SOCKET_STATE_UNCERTAIN")

    def start_socket(self) -> None:
        self._run(("start", self.socket))

    def start_service(self) -> None:
        self._run(("--no-block", "start", self.service))

    def stop_socket(self) -> None:
        # Late cleanup is not a new compute admission and has no compute-deadline fence.
        self._run(("stop", self.socket))

    def retire_cpu_service(self, outcome: Literal["SUCCEEDED", "FAILED"]) -> None:
        if self.device != "CPU" or outcome not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("BENCHMARK_UNIT_CPU_RETIREMENT_REQUIRED")
        # CUDA must use its actual retained-FD/physical-lease lifetime owner instead.
        self._run(("stop" if outcome == "SUCCEEDED" else "reset-failed", self.service))

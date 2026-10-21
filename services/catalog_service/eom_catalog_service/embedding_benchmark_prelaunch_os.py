"""Read-only PID1/proc and protected supervisor observations; no failure/compute authority."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    BenchmarkFailedControllerPin,
)

from eom_catalog_service.embedding_benchmark_unit_control import (
    CPU_BENCHMARK_SOCKET,
    CPU_BENCHMARK_SOCKET_SHA256,
    CPU_BENCHMARK_TEMPLATE,
    CPU_BENCHMARK_TEMPLATE_SHA256,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_COMMON = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "InvocationID",
    "FragmentPath",
    "DropInPaths",
    "NeedDaemonReload",
    "Job",
    "ControlGroup",
    "ControlPID",
    "ActiveEnterTimestampMonotonic",
    "ActiveExitTimestampMonotonic",
    "InactiveExitTimestampMonotonic",
)
_SERVICE = (
    "MainPID",
    "ExecMainStartTimestampMonotonic",
    "ExecMainExitTimestampMonotonic",
    "NFileDescriptorStore",
    "Restart",
    "NRestarts",
    "Result",
)
_CONTROLLER = ("ExecStart", "ExecMainStatus")
_PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
_BOOT = Path("/proc/sys/kernel/random/boot_id")


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE")


def _unit(name: str, properties: tuple[str, ...]) -> dict[str, str]:
    """Only callers' fixed validated units/properties; no shell or state-changing operation."""
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", name, *("--property=" + key for key in properties)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
        _require(result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= 16384)
        values: dict[str, str] = {}
        for line in result.stdout.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            _require(bool(separator) and key in properties and key not in values)
            values[key] = value
        _require(set(values) == set(properties))
        return values
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ValueError("BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE") from None


def _quiescent(value: dict[str, str], *, name: str, fragment: str, controller: bool) -> None:
    _require(
        value["Id"] == name
        and value["LoadState"] == "loaded"
        and value["ActiveState"] == ("failed" if controller else "inactive")
        and value["SubState"] == ("failed" if controller else "dead")
        and value["FragmentPath"] == fragment
        and value["DropInPaths"] == ""
        and value["NeedDaemonReload"] == "no"
        and value["Job"] in {"", "0"}
        and value["ControlGroup"] == ""
        and value["ControlPID"] == "0"
    )


def _positive(value: str) -> int:
    _require(re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None)
    return int(value)


@dataclass(frozen=True, slots=True)
class BenchmarkPrelaunchMachineObservation:
    boot_id: str
    controller: tuple[tuple[str, str], ...]
    native_service: tuple[tuple[str, str], ...]
    native_socket: tuple[tuple[str, str], ...]
    supervisor_epoch: tuple[int, ...]

    def snapshot_value(self) -> dict[str, object]:
        return {
            "boot_id": self.boot_id,
            "controller": dict(self.controller),
            "native_service": dict(self.native_service),
            "native_socket": dict(self.native_socket),
            "supervisor_epoch": self.supervisor_epoch,
        }


class CapturedBenchmarkPrelaunchMachine:
    """One fixed original controller/CPU stage; unchanged code epochs plus fresh OS reads."""

    def __init__(
        self,
        controller: BenchmarkFailedControllerPin,
        *,
        execution_id: str,
        owner_pid: int,
        expires_ns: int,
    ) -> None:
        self.controller = BenchmarkFailedControllerPin.model_validate(
            controller.model_dump(mode="json")
        )
        _require(
            type(execution_id) is str and re.fullmatch(r"[0-9a-f]{32}", execution_id) is not None
        )
        _require(type(owner_pid) is int and 0 < owner_pid <= 2**31 - 1)
        _require(type(expires_ns) is int and 0 < expires_ns < 2**63)
        self.execution_id, self.owner_pid, self.expires_ns = execution_id, owner_pid, expires_ns
        self._supervisor = (
            Path("/var/lib")
            / self.controller.unit.removesuffix(".service")
            / "benchmark_goal_supervisor.py"
        )
        self._files = NumericalRuntimeFileSnapshots(0)
        protected_paths = (
            self._supervisor,
            Path("/etc/systemd/system") / CPU_BENCHMARK_TEMPLATE,
            Path("/etc/systemd/system") / CPU_BENCHMARK_SOCKET,
        )
        self._acl_paths = tuple(
            sorted({part for path in protected_paths for part in (path, *path.parents)})
        )
        self._assert_no_acl()
        raw = self._files.read(
            self._supervisor, sha256=self.controller.supervisor_raw_sha256, maximum=128 * 1024
        )
        try:
            tree = ast.parse(raw.decode("utf-8"))
            source_values = [
                node.value.value
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "SOURCE"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
            ]
            _require(source_values == [self.controller.source_commit])
        except (SyntaxError, UnicodeError):
            raise ValueError("BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE") from None
        for name, sha in (
            (CPU_BENCHMARK_TEMPLATE, CPU_BENCHMARK_TEMPLATE_SHA256),
            (CPU_BENCHMARK_SOCKET, CPU_BENCHMARK_SOCKET_SHA256),
        ):
            self._files.read(Path("/etc/systemd/system") / name, sha256=sha, maximum=65536)
        self._files.assert_unchanged()

    def _assert_no_acl(self) -> None:
        try:
            for path in self._acl_paths:
                _require(
                    not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
                        os.listxattr(path, follow_symlinks=False)
                    )
                )
        except OSError:
            raise ValueError("BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE") from None

    def observe(self) -> BenchmarkPrelaunchMachineObservation:
        self._files.assert_unchanged()
        self._assert_no_acl()
        _require(time.monotonic_ns() > self.expires_ns)
        try:
            # A reused/live PID is deliberately unavailable, not treated as proof of an old death.
            os.stat(Path("/proc") / str(self.owner_pid), follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("BENCHMARK_PRELAUNCH_OWNER_STILL_PRESENT")
        try:
            with _BOOT.open("rb") as stream:
                boot_raw = stream.read(128)
            _require(len(boot_raw) == 37 and boot_raw.endswith(b"\n"))
            boot_id = boot_raw[:-1].decode("ascii")
        except (OSError, UnicodeError):
            raise ValueError("BENCHMARK_PRELAUNCH_MACHINE_UNAVAILABLE") from None
        _require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id) is not None)
        controller = _unit(self.controller.unit, _COMMON + _SERVICE + _CONTROLLER)
        _quiescent(
            controller,
            name=self.controller.unit,
            fragment="/run/systemd/transient/" + self.controller.unit,
            controller=True,
        )
        _require(
            controller["InvocationID"] == self.controller.invocation_id
            and controller["MainPID"] == "0"
            and controller["ControlPID"] == "0"
            and controller["NFileDescriptorStore"] == "0"
            and controller["Restart"] == "no"
            and controller["NRestarts"] == "0"
            and controller["Result"] == "exit-code"
            and controller["ExecMainStatus"] == "1"
            and _positive(controller["ExecMainExitTimestampMonotonic"])
            >= _positive(controller["ExecMainStartTimestampMonotonic"])
        )
        command = re.findall(r"argv\[\]=([^;]+) ;", controller["ExecStart"])
        _require(
            len(command) == 1 and command[0].split() == [_PYTHON, "-I", "-B", str(self._supervisor)]
        )
        service_name = CPU_BENCHMARK_TEMPLATE.replace(
            "@.service", "@" + self.execution_id + ".service"
        )
        socket_name = CPU_BENCHMARK_SOCKET.replace("@.socket", "@" + self.execution_id + ".socket")
        service = _unit(service_name, _COMMON + _SERVICE)
        socket = _unit(socket_name, _COMMON)
        _quiescent(
            service,
            name=service_name,
            fragment="/etc/systemd/system/" + CPU_BENCHMARK_TEMPLATE,
            controller=False,
        )
        _quiescent(
            socket,
            name=socket_name,
            fragment="/etc/systemd/system/" + CPU_BENCHMARK_SOCKET,
            controller=False,
        )
        _require(
            service["InvocationID"] == socket["InvocationID"] == ""
            and all(
                service[key] == "0"
                for key in (
                    "MainPID",
                    "ControlPID",
                    "ExecMainStartTimestampMonotonic",
                    "ExecMainExitTimestampMonotonic",
                    "NFileDescriptorStore",
                    "NRestarts",
                )
            )
            and service["Restart"] == "no"
            and service["Result"] == "success"
            and all(
                unit[key] == "0"
                for unit in (service, socket)
                for key in (
                    "ActiveEnterTimestampMonotonic",
                    "ActiveExitTimestampMonotonic",
                    "InactiveExitTimestampMonotonic",
                )
            )
        )
        self._files.assert_unchanged()
        self._assert_no_acl()
        value = self._supervisor.stat(follow_symlinks=False)
        epoch = (
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
        return BenchmarkPrelaunchMachineObservation(
            boot_id,
            tuple(sorted(controller.items())),
            tuple(sorted(service.items())),
            tuple(sorted(socket.items())),
            epoch,
        )

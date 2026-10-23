"""Current PID1 facts for the retired budget600 CPU timeout; no recovery side effects."""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import BenchmarkFailedControllerPin
from eom_orchestrator.native_embedding_cpu_execution import require_empty_native_cpu_cgroup

from eom_catalog_service.embedding_benchmark_budget600_window_evidence import (
    CONTROLLER_UNIT,
    CapturedBudget600Window,
)
from eom_catalog_service.embedding_benchmark_poststart_os import (
    _COMMON,
    _CONTROLLER,
    _SERVICE,
    BenchmarkPoststartMachineObservation,
    CapturedBenchmarkPoststartRetirement,
    _no_acl,
    _unit,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_SUPERVISOR = Path(
    "/var/lib/eom-gpu-benchmark-budget600-20261022-a7a80a1c/benchmark_budget600_supervisor_v4.py"
)
_BOOT = Path("/proc/sys/kernel/random/boot_id")
_PREFIX = "eom-embedding-benchmark-cpu-budget600@"


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("BENCHMARK_BUDGET600_MACHINE_UNAVAILABLE")


def _retired(value: dict[str, str], *, name: str, service: bool) -> None:
    _require(
        value["Id"] == name
        and value["LoadState"] == "not-found"
        and value["ActiveState"] == "inactive"
        and value["SubState"] == "dead"
        and value["FragmentPath"] == ""
        and value["DropInPaths"] == ""
        and value["NeedDaemonReload"] == "no"
        and value["Job"] in {"", "0"}
        and value["ControlGroup"] == ""
        and value["ControlPID"] == "0"
    )
    if service:
        _require(
            value["MainPID"] == "0"
            and value["NFileDescriptorStore"] == "0"
            and value["NRestarts"] == "0"
            and value["Restart"] == "no"
        )


class CapturedBudget600PoststartMachine:
    """Tie the original failed controller to absent retired units and preserved root pins.

    The owner may observe current PID1 and the readable controller source, but
    cannot reread root-private retirement/window bytes. Mint checks those first.
    """

    def __init__(
        self,
        controller: BenchmarkFailedControllerPin,
        *,
        execution_id: str,
        native_invocation_id: str,
        owner_pid: int,
        expires_ns: int,
        window: CapturedBudget600Window | None = None,
        retirement: CapturedBenchmarkPoststartRetirement | None = None,
    ) -> None:
        self.controller = BenchmarkFailedControllerPin.model_validate(controller)
        _require(
            self.controller.unit == CONTROLLER_UNIT
            and re.fullmatch(r"[0-9a-f]{32}", execution_id) is not None
            and re.fullmatch(r"[0-9a-f]{32}", native_invocation_id) is not None
            and type(owner_pid) is int
            and 0 < owner_pid <= 2**31 - 1
            and type(expires_ns) is int
            and 0 < expires_ns < 2**63
            and ((window is None) == (retirement is None))
        )
        self.execution_id = execution_id
        self.native_invocation_id = native_invocation_id
        self.owner_pid = owner_pid
        self.expires_ns = expires_ns
        self.window = window
        self.retirement = retirement
        self._files = NumericalRuntimeFileSnapshots(0)
        self._protected = (_SUPERVISOR, *_SUPERVISOR.parents)
        _no_acl(self._protected)
        raw = self._files.read(
            _SUPERVISOR, sha256=self.controller.supervisor_raw_sha256, maximum=128 * 1024
        )
        try:
            tree = ast.parse(raw.decode("utf-8"))
        except (UnicodeError, SyntaxError):
            raise ValueError("BENCHMARK_BUDGET600_MACHINE_UNAVAILABLE") from None
        source = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SOURCE" for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        _require(source == [self.controller.source_commit])
        self.observe()

    def observe(self) -> BenchmarkPoststartMachineObservation:
        self._files.assert_unchanged()
        _no_acl(self._protected)
        if self.window is not None:
            self.window.assert_current()
        if self.retirement is not None:
            self.retirement.assert_current()
            _require(self.retirement.native_invocation_id == self.native_invocation_id)
        _require(time.monotonic_ns() > self.expires_ns)
        try:
            os.stat(Path("/proc") / str(self.owner_pid), follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("BENCHMARK_BUDGET600_OWNER_STILL_PRESENT")
        raw = _BOOT.read_bytes()
        _require(len(raw) == 37 and raw.endswith(b"\n"))
        boot = raw[:-1].decode("ascii")
        _require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot) is not None)
        controller = _unit(self.controller.unit, _COMMON + _SERVICE + _CONTROLLER)
        commands = re.findall(r"argv\[\]=([^;]+) ;", controller["ExecStart"])
        _require(
            controller["Id"] == self.controller.unit
            and controller["LoadState"] == "loaded"
            and (controller["ActiveState"], controller["SubState"]) == ("failed", "failed")
            and controller["FragmentPath"] == "/run/systemd/transient/" + self.controller.unit
            and controller["DropInPaths"] == ""
            and controller["NeedDaemonReload"] == "no"
            and controller["Job"] in {"", "0"}
            and controller["ControlGroup"] == ""
            and controller["MainPID"] == controller["ControlPID"] == "0"
            and controller["NFileDescriptorStore"] == controller["NRestarts"] == "0"
            and controller["Restart"] == "no"
            and controller["Result"] == "exit-code"
            and controller["ExecMainStatus"] == "1"
            and controller["InvocationID"] == self.controller.invocation_id
            and len(commands) == 1
            and commands[0].split()
            == ["/srv/eom/conda/envs/eom-api/bin/python", "-I", "-B", str(_SUPERVISOR)]
        )
        service_name = _PREFIX + self.execution_id + ".service"
        socket_name = _PREFIX + self.execution_id + ".socket"
        service = _unit(service_name, _COMMON + _SERVICE)
        socket = _unit(socket_name, _COMMON)
        _retired(service, name=service_name, service=True)
        _retired(socket, name=socket_name, service=False)
        require_empty_native_cpu_cgroup(service_name)
        self._files.assert_unchanged()
        return BenchmarkPoststartMachineObservation(
            boot,
            tuple(sorted(controller.items())),
            tuple(sorted(service.items())),
            tuple(sorted(socket.items())),
        )

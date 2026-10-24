"""Shared bounded terminal/stopped GPU-unit observations, never effects or admission."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "MainPID",
    "NFileDescriptorStore",
    "InvocationID",
    "NeedDaemonReload",
    "FragmentPath",
    "DropInPaths",
    "Job",
    "ControlGroup",
)


def gpu_unit_terminal_outcome(terminal: CpuUnitObservation) -> Literal["SUCCEEDED", "FAILED"]:
    if type(terminal) is not CpuUnitObservation:
        raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
    if terminal.succeeded:
        return "SUCCEEDED"
    if (
        terminal.main_pid == 0
        and terminal.status.active_state == "failed"
        and terminal.status.sub_state == "failed"
        and terminal.status.process_started
        and terminal.status.exec_main_code in {1, 2, 3}
        and terminal.status.result
        in {
            "exit-code",
            "signal",
            "core-dump",
            "timeout",
            "watchdog",
            "oom-kill",
            "resources",
            "protocol",
        }
        and terminal.exited_monotonic >= terminal.status.exec_main_started_monotonic
    ):
        return "FAILED"
    raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")


@dataclass(frozen=True, slots=True)
class StoppedGpuUnit:
    load_state: str
    invocation_id: str
    stored_descriptors: Literal[0, 1]


def observe_failed_gpu_unit_metadata(
    unit: str, *, template: str, expected: CpuUnitObservation
) -> tuple[int, Literal[0, 1]]:
    """Read actual dead main PID/store, without inventing a missing process birth."""
    if (
        os.getresuid() != (0, 0, 0)
        or type(unit) is not str
        or type(template) is not str
        or re.fullmatch(r"eom-[a-z0-9-]+@\.service", template) is None
        or re.fullmatch(re.escape(template).replace("@", r"@[0-9a-f]{32}"), unit) is None
        or type(expected) is not CpuUnitObservation
        or re.fullmatch(r"[0-9a-f]{32}", expected.invocation_id) is None
        or expected.fragment_path != "/etc/systemd/system/" + template
        or gpu_unit_terminal_outcome(expected) != "FAILED"
    ):
        raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
    return _observe_original_terminal_process(unit, expected)


def observe_embedding_gpu_batch_terminal_metadata(
    unit: str, *, expected: CpuUnitObservation
) -> tuple[int, Literal[0, 1]]:
    """Batch-only actual exited PID/store, including a successful pre-compute BUSY exit.

    The caller must still prove original allocation linkage, absent compute grant,
    unchanged empty numerical files and safe retirement before selecting CPU. This
    observation alone is neither BUSY proof nor permission to retry or fall back.
    """
    template = "eom-embedding-native-gpu-batch@.service"
    if (
        os.getresuid() != (0, 0, 0)
        or type(unit) is not str
        or re.fullmatch(r"eom-embedding-native-gpu-batch@[0-9a-f]{32}\.service", unit) is None
        or type(expected) is not CpuUnitObservation
        or re.fullmatch(r"[0-9a-f]{32}", expected.invocation_id) is None
        or expected.fragment_path != "/etc/systemd/system/" + template
        or expected.drop_in_paths
        or expected.status.need_daemon_reload
    ):
        raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
    gpu_unit_terminal_outcome(expected)  # Real terminal success/failure, not a fresh/running unit.
    return _observe_original_terminal_process(unit, expected)


def _observe_original_terminal_process(
    unit: str, expected: CpuUnitObservation
) -> tuple[int, Literal[0, 1]]:
    """Shared bounded projection after each purpose/outcome-specific root guard."""
    properties = (
        "ExecMainPID",
        "NFileDescriptorStore",
        "InvocationID",
        "ExecMainStartTimestampMonotonic",
    )
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", unit, *("--property=" + key for key in properties)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
        if result.returncode != 0 or len(result.stdout) > 16384 or len(result.stderr) > 16384:
            raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
        fields: dict[str, str] = {}
        for line in result.stdout.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in properties or key in fields:
                raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
            fields[key] = value
        if not (
            set(fields) == set(properties)
            and fields["InvocationID"] == expected.invocation_id
            and fields["ExecMainStartTimestampMonotonic"]
            == str(expected.status.exec_main_started_monotonic)
            and fields["NFileDescriptorStore"] in {"0", "1"}
            and re.fullmatch(r"[1-9][0-9]{0,9}", fields["ExecMainPID"]) is not None
            and int(fields["ExecMainPID"]) <= 2147483647
        ):
            raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN")
        return int(fields["ExecMainPID"]), 1 if fields["NFileDescriptorStore"] == "1" else 0
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ValueError("GPU_UNIT_TERMINATION_UNCERTAIN") from None


def observe_stopped_gpu_unit(unit: str, *, template: str, invocation: str) -> StoppedGpuUnit:
    """Only read actual post-effect state; caller owns the concrete fixed unit family."""
    if (
        os.getresuid() != (0, 0, 0)
        or type(unit) is not str
        or type(template) is not str
        or re.fullmatch(r"eom-[a-z0-9-]+@\.service", template) is None
        or not unit.startswith(template.removesuffix("@.service") + "@")
        or not unit.endswith(".service")
        or any(char in unit for char in ("/", "\0", "\n", "\r"))
        or type(invocation) is not str
        or re.fullmatch(r"[0-9a-f]{32}", invocation) is None
    ):
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
    try:
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", unit, *("--property=" + key for key in _PROPERTIES)),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN") from None
    if result.returncode != 0 or len(result.stdout) > 16384 or len(result.stderr) > 16384:
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
    values: dict[str, str] = {}
    try:
        lines = result.stdout.decode("ascii").splitlines()
    except UnicodeError:
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN") from None
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key not in _PROPERTIES or key in values:
            raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
        values[key] = value
    if set(values) != set(_PROPERTIES):
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
    loaded = values["LoadState"] == "loaded"
    if not (
        values["LoadState"] in {"loaded", "not-found"}
        and values["ActiveState"] == "inactive"
        and (
            values["SubState"] == "dead"
            or (
                values["SubState"] == "dead-resources-pinned"
                and loaded
                and values["NFileDescriptorStore"] == "1"
            )
        )
        and values["MainPID"] == "0"
        and values["NFileDescriptorStore"] in {"0", "1"}
        and (loaded or values["NFileDescriptorStore"] == "0")
        and values["InvocationID"] in {"", invocation}
        and values["NeedDaemonReload"] == "no"
        and values["DropInPaths"] == ""
        and values["Job"] in {"", "0"}
        and values["ControlGroup"] == ""
        and values["FragmentPath"] == ("/etc/systemd/system/" + template if loaded else "")
    ):
        raise ValueError("GPU_UNIT_RETIREMENT_UNCERTAIN")
    return StoppedGpuUnit(
        values["LoadState"],
        values["InvocationID"],
        0 if values["NFileDescriptorStore"] == "0" else 1,
    )

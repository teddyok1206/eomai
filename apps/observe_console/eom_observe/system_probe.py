"""Allow-listed, best-effort host probes; no process environment or journal access."""

from __future__ import annotations

import pwd
import subprocess
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SYSTEMD_PROPERTIES = (
    "ActiveState",
    "SubState",
    "MainPID",
    "ExecMainStatus",
    "ActiveEnterTimestamp",
    "InactiveEnterTimestamp",
)


@dataclass(frozen=True)
class ProbeResult:
    fresh: bool
    load_average: str | None
    memory_available_kib: int | None
    users_present: dict[str, bool]
    units: dict[str, dict[str, str]]


def _read_load() -> str | None:
    try:
        return Path("/proc/loadavg").read_text(encoding="ascii").split()[0]
    except (OSError, IndexError):
        return None


def _read_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _unit_properties(unit: str) -> dict[str, str]:
    argv = ["systemctl", "show", unit]
    for prop in ALLOWED_SYSTEMD_PROPERTIES:
        argv.extend(["--property", prop])
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=1, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    return {
        key: value
        for line in result.stdout.splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
        if key in ALLOWED_SYSTEMD_PROPERTIES
    }


def probe_system() -> ProbeResult:
    users: dict[str, bool] = {}
    for number in range(1, 7):
        name = f"eom-cdx-{number:02d}"
        try:
            pwd.getpwnam(name)
            users[name] = True
        except KeyError:
            users[name] = False
    units = {
        name: _unit_properties(name)
        for name in ("eom-observe.service", "eom-workflow-runner.service")
    }
    load = _read_load()
    memory = _read_memory()
    return ProbeResult(
        fresh=load is not None and memory is not None,
        load_average=load,
        memory_available_kib=memory,
        users_present=users,
        units=units,
    )

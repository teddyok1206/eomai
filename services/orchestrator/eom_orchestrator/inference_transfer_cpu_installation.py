"""Privileged fixed no-forward CPU verification; never accepts arbitrary units/commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from eom_orchestrator.inference_transfer_cpu_systemd import (
    CPU_TEMPLATE,
    PREPARE_TEMPLATE,
    inspect_cpu_unit,
    require_cpu_runtime,
)

SYSTEMCTL = "/usr/bin/systemctl"
PROBE = "eom-embedding-experiment-probe.service"
PROBE_SHA256 = "310fdb4e8d49dd89c19edcb3db08a352f6facf405ddb9a4fc7d59db430ae1dfb"
POLKIT = Path("/etc/polkit-1/rules.d/50-eom-worker-units.rules")
POLKIT_SHA256 = "fc63581550983bdfe9742556d8f1331ac51925ffa962302c9b3c38ffed72b08a"
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_INSTANCE = "embeddingexecution_" + "0" * 32
_SANDBOX = (
    "User",
    "Group",
    "SupplementaryGroups",
    "NoNewPrivileges",
    "PrivateTmp",
    "PrivateNetwork",
    "PrivateDevices",
    "ProtectSystem",
    "ProtectHome",
    "ProtectKernelTunables",
    "ProtectKernelModules",
    "ProtectKernelLogs",
    "ProtectControlGroups",
    "ProtectClock",
    "ProtectHostname",
    "RestrictSUIDSGID",
    "LockPersonality",
    "RestrictRealtime",
    "CapabilityBoundingSet",
    "AmbientCapabilities",
    "RestrictAddressFamilies",
    "SystemCallArchitectures",
    "ReadOnlyPaths",
    "InaccessiblePaths",
    "UMask",
    "MemoryMax",
    "TasksMax",
    "LimitFSIZE",
    "LimitCORE",
    "KillMode",
    "Restart",
    "RootDirectory",
    "RootImage",
    "ExecStartPre",
    "ExecStartPost",
    "BindPaths",
    "BindReadOnlyPaths",
    "TemporaryFileSystem",
    "ReadWritePaths",
    "FragmentPath",
    "DropInPaths",
    "NeedDaemonReload",
)


def _checked_file(path: Path, expected: str) -> None:
    # No repository import: pinned installed bytes, protected ancestors and FD identity.
    import hashlib
    import stat

    for member in (path, *path.parents):
        value = member.lstat()
        if value.st_uid != 0 or stat.S_ISLNK(value.st_mode) or value.st_mode & 0o022:
            raise ValueError("INFERENCE_CPU_PROBE_INSTALLED_FILE_INVALID")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = os.fstat(descriptor)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or not 0 < value.st_size < 128 * 1024
        ):
            raise ValueError("INFERENCE_CPU_PROBE_INSTALLED_FILE_INVALID")
        raw = os.read(descriptor, value.st_size + 1)

        def epoch(info: os.stat_result) -> tuple[int, ...]:
            return (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        if (
            epoch(value) != epoch(os.fstat(descriptor))
            or epoch(value) != epoch(path.lstat())
            or len(raw) != value.st_size
            or hashlib.sha256(raw).hexdigest() != expected
        ):
            raise ValueError("INFERENCE_CPU_PROBE_INSTALLED_FILE_INVALID")
    finally:
        os.close(descriptor)


def _properties(unit: str) -> dict[str, str]:
    response = subprocess.run(
        (SYSTEMCTL, "--no-pager", "show", unit, *(f"--property={key}" for key in _SANDBOX)),
        capture_output=True,
        timeout=15,
        check=False,
        env=_ENV,
    )
    if response.returncode or len(response.stdout) > 64 * 1024 or len(response.stderr) > 16 * 1024:
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_UNAVAILABLE")
    result: dict[str, str] = {}
    for line in response.stdout.decode("utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in result or key not in _SANDBOX:
            raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
        result[key] = value
    if set(result) != set(_SANDBOX):
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
    return result


def validate_effective_policies(
    main: dict[str, str], probe: dict[str, str], prepare: dict[str, str]
) -> None:
    for values, template in ((main, CPU_TEMPLATE), (probe, PROBE), (prepare, PREPARE_TEMPLATE)):
        if (
            set(values) != set(_SANDBOX)
            or values["FragmentPath"] != "/etc/systemd/system/" + template
            or values["DropInPaths"]
            or values["NeedDaemonReload"] != "no"
        ):
            raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
    for key in set(_SANDBOX) - {"FragmentPath"}:
        if main[key] != probe[key]:
            raise ValueError("INFERENCE_CPU_PROBE_POLICY_MISMATCH")
    if (
        main["User"] != "eom-embedding-experiment"
        or main["Group"] != "eom-embedding-experiment"
        or main["SupplementaryGroups"]
        or main["CapabilityBoundingSet"]
        or main["AmbientCapabilities"]
        or main["NoNewPrivileges"] != "yes"
        or main["PrivateNetwork"] != "yes"
        or main["PrivateDevices"] != "yes"
        or main["ProtectSystem"] != "strict"
        or main["RestrictAddressFamilies"] != "AF_UNIX"
    ):
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
    if (
        prepare["User"] != "root"
        or prepare["Group"] != "root"
        or prepare["SupplementaryGroups"]
        or set(prepare["CapabilityBoundingSet"].split()) != {"cap_dac_read_search", "cap_chown"}
        or prepare["AmbientCapabilities"]
        or prepare["NoNewPrivileges"] != "yes"
        or prepare["PrivateNetwork"] != "yes"
        or prepare["PrivateDevices"] != "yes"
        or prepare["ReadWritePaths"] != "/run/eom-embedding-experiments"
    ):
        raise ValueError("INFERENCE_CPU_PREPARE_POLICY_INVALID")


def verify_polkit_scope() -> None:
    allowed_unit = "eom-embedding-experiment@" + _INSTANCE + ".service"
    cases = (
        ("eom-workflow-runner", allowed_unit, "start", True),
        (
            "eom-workflow-runner",
            "eom-embedding-experiment-prepare@" + _INSTANCE + ".service",
            "start",
            False,
        ),
        ("eom-workflow-runner", PROBE, "start", False),
        ("eom-workflow-runner", allowed_unit, "restart", False),
        ("eom-workflow-runner", "eom-embedding-experiment@invalid.service", "start", False),
        ("eom-embedding-experiment", allowed_unit, "start", False),
    )
    for user, unit, verb, expected in cases:
        # $$ is the actual subject process; no unit starts and no caller authority fields.
        command = (
            "exec /usr/bin/pkcheck --action-id org.freedesktop.systemd1.manage-units "
            '--process "$$" --detail unit "$1" --detail verb "$2"'
        )
        result = subprocess.run(
            ("/usr/sbin/runuser", "-u", user, "--", "/bin/sh", "-c", command, "probe", unit, verb),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            env=_ENV,
        )
        if result.returncode != (0 if expected else 1):
            raise ValueError("INFERENCE_CPU_PROBE_POLKIT_SCOPE_INVALID")


def verify_fixed_cpu_installation() -> None:
    if os.geteuid() != 0:
        raise ValueError("INFERENCE_CPU_PROBE_ROOT_REQUIRED")
    require_cpu_runtime()
    _checked_file(Path("/etc/systemd/system") / PROBE, PROBE_SHA256)
    _checked_file(POLKIT, POLKIT_SHA256)
    main = "eom-embedding-experiment@" + _INSTANCE + ".service"
    prepare = "eom-embedding-experiment-prepare@" + _INSTANCE + ".service"
    validate_effective_policies(_properties(main), _properties(PROBE), _properties(prepare))
    verify_polkit_scope()
    before = inspect_cpu_unit(PROBE, template=PROBE)
    if not before.fresh:
        raise ValueError("INFERENCE_CPU_PROBE_HISTORY_REQUIRES_REVIEW")
    result = subprocess.run(
        (SYSTEMCTL, "--no-ask-password", "start", PROBE),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=1830,
        check=False,
        env=_ENV,
    )
    after = inspect_cpu_unit(PROBE, template=PROBE)
    if result.returncode or not after.succeeded or inspect_cpu_unit(PROBE, template=PROBE) != after:
        raise ValueError("INFERENCE_CPU_PROBE_UNCERTAIN_OR_FAILED")
    validate_effective_policies(_properties(main), _properties(PROBE), _properties(prepare))


def main() -> int:
    try:
        verify_fixed_cpu_installation()
        print("CPU_ISOLATION_PROBE=PASS MODEL_FORWARD_COUNT=0")
        return 0
    except Exception:
        print("CPU_ISOLATION_PROBE=REJECTED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

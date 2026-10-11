"""Privileged fixed no-forward CPU verification; never accepts arbitrary units/commands."""

from __future__ import annotations

import os
import pwd
import re
import selectors
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from eom_orchestrator.inference_transfer_cpu_systemd import (
    BGE_CPU_TEMPLATE,
    CPU_TEMPLATE,
    PREPARE_TEMPLATE,
    CpuResourceProfile,
    cpu_resource_limits,
    cpu_unit_names,
    inspect_cpu_unit,
    require_cpu_runtime,
)

SYSTEMCTL = "/usr/bin/systemctl"
PROBE = "eom-embedding-experiment-probe.service"
PROBE_SHA256 = "310fdb4e8d49dd89c19edcb3db08a352f6facf405ddb9a4fc7d59db430ae1dfb"
POLKIT = Path("/etc/polkit-1/rules.d/50-eom-worker-units.rules")
POLKIT_SHA256 = "589f0c9258bacf17e4d3cefe3aba49c313c6733299dde196aaccf1662c7f985c"
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_INSTANCE = "embeddingexecution_" + "0" * 32
_OMITTED_EMPTY_EXEC = frozenset({"ExecStartPre", "ExecStartPost"})
_SAFE_FAILURE_CODES = frozenset(
    {
        "INFERENCE_CPU_PROBE_INSTALLED_FILE_INVALID",
        "INFERENCE_CPU_PROBE_POLICY_UNAVAILABLE",
        "INFERENCE_CPU_PROBE_POLICY_INVALID",
        "INFERENCE_CPU_PROBE_POLICY_MISMATCH",
        "INFERENCE_CPU_PREPARE_POLICY_INVALID",
        "INFERENCE_CPU_PROBE_SUBJECT_UNAVAILABLE",
        "INFERENCE_CPU_PROBE_SUBJECT_INVALID",
        "INFERENCE_CPU_PROBE_SUBJECT_CHANGED",
        "INFERENCE_CPU_PROBE_POLKIT_SCOPE_INVALID",
        "INFERENCE_CPU_PROBE_ROOT_REQUIRED",
        "INFERENCE_CPU_PROBE_HISTORY_REQUIRES_REVIEW",
        "INFERENCE_CPU_PROBE_UNCERTAIN_OR_FAILED",
        "INFERENCE_CPU_INSTALLED_PATH_INVALID",
        "INFERENCE_CPU_TEMPLATE_INVALID",
        "INFERENCE_CPU_INTERPRETER_INVALID",
        "INFERENCE_CPU_STATUS_UNAVAILABLE",
        "INFERENCE_CPU_STATUS_INVALID",
        "INFERENCE_CPU_OWNER_IDENTITY_INVALID",
    }
)
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
    "TimeoutStartUSec",
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
    templates = {
        "eom-embedding-experiment@" + _INSTANCE + ".service": CPU_TEMPLATE,
        "eom-embedding-experiment-bge@" + _INSTANCE + ".service": BGE_CPU_TEMPLATE,
        PROBE: PROBE,
        "eom-embedding-experiment-prepare@" + _INSTANCE + ".service": PREPARE_TEMPLATE,
    }
    if unit not in templates:
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
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
    missing = set(_SANDBOX) - result.keys()
    # The caller verifies pinned installed template bytes before this read. systemctl show omits
    # empty structured Exec arrays; only these two may be normalized, with no effective override.
    if missing and (
        missing - _OMITTED_EMPTY_EXEC
        or result.get("FragmentPath") != "/etc/systemd/system/" + templates[unit]
        or result.get("DropInPaths") != ""
        or result.get("NeedDaemonReload") != "no"
    ):
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
    for key in missing:
        result[key] = ""
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
        or main["TimeoutStartUSec"] != "30min"
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
        or prepare["TimeoutStartUSec"] != "30s"
    ):
        raise ValueError("INFERENCE_CPU_PREPARE_POLICY_INVALID")


def validate_bge_effective_policies(
    main: dict[str, str],
    bge: dict[str, str],
    probe: dict[str, str],
    prepare: dict[str, str],
) -> None:
    """The fixed BGE resource change is not permission to change the existing CPU sandbox."""
    validate_effective_policies(main, probe, prepare)
    if (
        set(bge) != set(_SANDBOX)
        or bge["FragmentPath"] != "/etc/systemd/system/" + BGE_CPU_TEMPLATE
        or bge["DropInPaths"]
        or bge["NeedDaemonReload"] != "no"
        or main["MemoryMax"] != str(cpu_resource_limits().memory_max_bytes)
        or bge["MemoryMax"] != str(cpu_resource_limits(CpuResourceProfile.BGE).memory_max_bytes)
        or bge["TimeoutStartUSec"] != "1h 30min"
    ):
        raise ValueError("INFERENCE_CPU_PROBE_POLICY_INVALID")
    for key in set(_SANDBOX) - {"FragmentPath", "MemoryMax", "TimeoutStartUSec"}:
        if bge[key] != main[key]:
            raise ValueError("INFERENCE_CPU_PROBE_POLICY_MISMATCH")


@dataclass(frozen=True, slots=True)
class PolkitSubject:
    pid: int
    start_time: int
    uid: int
    parent_pid: int

    @property
    def process_argument(self) -> str:
        return f"{self.pid},{self.start_time},{self.uid}"


def _read_subject_pid(stream: int) -> int:
    deadline = monotonic() + 5
    payload = bytearray()
    with selectors.DefaultSelector() as ready:
        ready.register(stream, selectors.EVENT_READ)
        while b"\n" not in payload:
            remaining = deadline - monotonic()
            if remaining <= 0 or not ready.select(remaining):
                raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_UNAVAILABLE")
            chunk = os.read(stream, 65 - len(payload))
            if not chunk or len(payload) + len(chunk) > 64:
                raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
            payload.extend(chunk)
    if re.fullmatch(rb"[1-9][0-9]{0,9}\n", payload) is None:
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
    return int(payload)


def _kernel_subject(pid: int, *, uid: int, parent_pid: int) -> PolkitSubject:
    if min(pid, uid, parent_pid) <= 0 or max(pid, parent_pid) > 2**31 - 1:
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
    stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    status_text = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    if len(stat_text) > 4096 or len(status_text) > 16 * 1024:
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
    opening, separator, rest = stat_text.rpartition(")")
    fields = rest.split()
    uid_rows = [
        line.partition(":")[2].split()
        for line in status_text.splitlines()
        if line.startswith("Uid:")
    ]
    try:
        observed_pid = int(opening.split("(", 1)[0].strip())
        observed_parent = int(fields[1])
        start_time = int(fields[19])
        observed_uids = tuple(int(value) for value in uid_rows[0])
    except (IndexError, ValueError) as exc:
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID") from exc
    if (
        not separator
        or observed_pid != pid
        or observed_parent != parent_pid
        or start_time <= 0
        or len(uid_rows) != 1
        or observed_uids != (uid, uid, uid, uid)
    ):
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
    return PolkitSubject(pid, start_time, uid, parent_pid)


def _close_owned_subject(process: subprocess.Popen[bytes]) -> None:
    # EOF terminates the fixed cat. Only the Popen-owned wrapper may be killed on cleanup timeout;
    # never send a signal to a PID reported over stdout or to an arbitrary process group.
    if process.stdin is not None and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.stdout is not None:
            process.stdout.close()


@contextmanager
def _temporary_polkit_subject(user: str) -> Iterator[PolkitSubject]:
    if os.geteuid() != 0 or user not in {"eom-workflow-runner", "eom-embedding-experiment"}:
        raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
    uid = pwd.getpwnam(user).pw_uid
    process = subprocess.Popen(
        (
            "/usr/sbin/runuser",
            "-u",
            user,
            "--",
            "/bin/sh",
            "-c",
            'printf "%s\\n" "$$"; exec /bin/cat',
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_ENV,
    )
    try:
        if process.stdout is None:
            raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_INVALID")
        pid = _read_subject_pid(process.stdout.fileno())
        before = _kernel_subject(pid, uid=uid, parent_pid=process.pid)
        if process.poll() is not None:
            raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_UNAVAILABLE")
        yield before
        if (
            process.poll() is not None
            or _kernel_subject(pid, uid=uid, parent_pid=process.pid) != before
        ):
            raise ValueError("INFERENCE_CPU_PROBE_SUBJECT_CHANGED")
    finally:
        _close_owned_subject(process)


def verify_polkit_scope(*, profile: CpuResourceProfile = CpuResourceProfile.E5) -> None:
    if os.geteuid() != 0:
        raise ValueError("INFERENCE_CPU_PROBE_ROOT_REQUIRED")
    allowed_unit = cpu_unit_names(_INSTANCE, profile=profile)[1]
    invalid_unit = cpu_resource_limits(profile).template.replace("@.service", "@invalid.service")
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
        ("eom-workflow-runner", invalid_unit, "start", False),
        ("eom-embedding-experiment", allowed_unit, "start", False),
    )
    for user, unit, verb, expected in cases:
        # Action details require a trusted root caller. Authority is evaluated for the separately
        # kernel-validated target UID/PID/starttime, never for the root caller or a supplied actor.
        with _temporary_polkit_subject(user) as subject:
            result = subprocess.run(
                (
                    "/usr/bin/pkcheck",
                    "--action-id",
                    "org.freedesktop.systemd1.manage-units",
                    "--process",
                    subject.process_argument,
                    "--detail",
                    "unit",
                    unit,
                    "--detail",
                    "verb",
                    verb,
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
                env=_ENV,
            )
            if result.returncode != (0 if expected else 1):
                raise ValueError("INFERENCE_CPU_PROBE_POLKIT_SCOPE_INVALID")


def verify_bge_cpu_resource_profile() -> None:
    """Read installed BGE policy/authority only; this does not run a model or a probe unit."""
    if os.geteuid() != 0:
        raise ValueError("INFERENCE_CPU_PROBE_ROOT_REQUIRED")
    require_cpu_runtime()
    require_cpu_runtime(profile=CpuResourceProfile.BGE)
    _checked_file(Path("/etc/systemd/system") / PROBE, PROBE_SHA256)
    _checked_file(POLKIT, POLKIT_SHA256)
    prepare, main = cpu_unit_names(_INSTANCE)
    bge = cpu_unit_names(_INSTANCE, profile=CpuResourceProfile.BGE)[1]
    validate_bge_effective_policies(
        _properties(main), _properties(bge), _properties(PROBE), _properties(prepare)
    )
    verify_polkit_scope(profile=CpuResourceProfile.BGE)


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
    except Exception as exc:
        code = "INFERENCE_CPU_PROBE_UNEXPECTED_FAILURE"
        if (
            isinstance(exc, ValueError)
            and len(exc.args) == 1
            and isinstance(exc.args[0], str)
            and exc.args[0] in _SAFE_FAILURE_CODES
        ):
            code = exc.args[0]
        elif isinstance(exc, subprocess.TimeoutExpired):
            code = "INFERENCE_CPU_PROBE_SUBPROCESS_TIMEOUT"
        elif isinstance(exc, OSError):
            code = "INFERENCE_CPU_PROBE_OS_UNAVAILABLE"
        print(f"CPU_ISOLATION_PROBE=REJECTED ERROR_CODE={code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Fixed-template systemd worker launch and readiness contract."""

from __future__ import annotations

import hashlib
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from eom_protocol import ErrorCode

from eom_orchestrator.errors import PlatformError
from eom_orchestrator.worker_registry import WorkerSlot

SYSTEMCTL = Path("/usr/bin/systemctl")
SYSTEMD_UNIT_ROOT = Path("/etc/systemd/system")
WORKER_EXECUTABLE = Path("/usr/local/libexec/eom-worker-exec")
WORKER_AUTH_EXECUTABLE = Path("/usr/local/libexec/eom-worker-auth-status")
SYSTEMCTL_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
JOB_ID_PATTERN = re.compile(r"\Ajob_[0-9a-f]{32}\Z", re.ASCII)
PROBE_ID_PATTERN = re.compile(r"\Aprobe_[0-9a-f]{32}\Z", re.ASCII)
SLOT_IDS = frozenset({"01", "02", "03", "04", "05"})
ACTIVE_STATES = frozenset({"activating", "active", "deactivating", "reloading"})
NON_ACTIVE_SYSTEMCTL_EXIT_CODES = frozenset({3, 4})
AUTHORIZATION_DENIED_MARKERS = (
    b"access denied",
    b"authentication is required",
    b"interactive authentication required",
    b"not authorized",
    b"permission denied",
)
FIXED_WORKER_TIMEOUT_SECONDS = 1800
FIXED_ANALYSIS_WORKER_TIMEOUT_SECONDS = 7200
FIXED_WORKER_CLIENT_GUARD_SECONDS = 30


def fixed_worker_timeout_seconds(slot: WorkerSlot) -> int:
    """Return the reviewed execution ceiling for one fixed worker identity."""

    return (
        FIXED_ANALYSIS_WORKER_TIMEOUT_SECONDS
        if validate_slot(slot) == "05"
        else FIXED_WORKER_TIMEOUT_SECONDS
    )


# These hashes are the installed contract. Tests compare them with the canonical repository
# sources, and runtime readiness compares them with root-owned installed artifacts.
WORKER_TEMPLATE_SHA256 = {
    "01": "3c0f2b5b19852714a38739f20a73ade9f003832ae521711b5f08a83dd7238437",
    "02": "08590fce316a9d6e3e3d57680204b3030d1b5672429fa32d9a91253cb85d62e8",
    "03": "e261fdc7e5c5af7c260107a9594da605aa37d6edc0d14ea1733e5489ecae0f2f",
    "04": "328fce8d9099d71925658552626d38e0702550b8da3d451f5f017fec32460a17",
    "05": "b992622ee6c718a60ca3d9601ac56646213ab59703e6670a7b6edbf3484b4672",
}
PROBE_TEMPLATE_SHA256 = {
    "01": "6d74599b84b8ac243656fb1cef1ffb459261ff23195428cd47be4da86134d4e4",
    "02": "66fd5e603821b3c21c76d06cc96cf29aaba30c5c90f99e2a0c08ee347dff555c",
    "03": "b6851bf9e087ea6c0a2cbabe61e03abc06dd862bbe5edf69e2e4e7e2f445b8a5",
    "04": "83eccd46ee0b058ede1824b1f137b9f35803a9da5d91ae14ec1961651d34a69a",
    "05": "86c19aa495b44be6f38441b6fe63308e408cf12310d5d562207a128ef354768c",
}
AUTH_TEMPLATE_SHA256 = {
    "01": "4ca00325bea635d32b192ae3cc6300fc887d13f861d38aeb2bbc2639945e1ae4",
    "02": "312b0ce43e70bd005bac19f4659b0e1120b55bd2d8de338ac41a6a70b07226cd",
    "03": "cf1686cb8bab136017148e9ede376362ff217bcc7a69a14c87fcde0c1fa90f5f",
    "04": "a46f8d4c4b5f7b2bfdf1993e0cb7694bef348e85d56fcb858471d8ba8bbcf142",
    "05": "98dbc3e1b1907912a71b8f2b7b2c7a7c224cd19b927084bfde2de5037ead29e3",
}
WORKER_EXECUTABLE_SHA256 = "aab4b92a04caffd7a6864db0a703093c98e50b27ed084a122479b69c64e6b038"
WORKER_AUTH_EXECUTABLE_SHA256 = "a4d0cb8655507d69c85ba7f12b8674f4b0ffef123af68190c36b95b67ea18b42"
AUTH_REQUIRED_EXIT = 20
AUTH_PROBE_INVALID_EXIT = 21
AUTH_PROBE_TIMEOUT_EXIT = 22


@dataclass(frozen=True)
class FixedUnitStatus:
    load_state: str
    active_state: str
    sub_state: str
    result: str
    exec_main_code: int
    exec_main_status: int
    exec_main_started_monotonic: int
    need_daemon_reload: bool

    @property
    def process_started(self) -> bool:
        return self.exec_main_started_monotonic > 0 or self.exec_main_code != 0

    @property
    def process_lingering(self) -> bool:
        return self.active_state in ACTIVE_STATES

    @property
    def exit_code(self) -> int:
        if self.exec_main_code == 1:
            return self.exec_main_status
        if self.exec_main_code > 1:
            return 128 + self.exec_main_status
        return self.exec_main_status


@dataclass(frozen=True)
class FixedUnitRun:
    unit_name: str
    exit_code: int
    command_stdout: bytes
    command_stderr: bytes
    status: FixedUnitStatus | None
    active_returncode: int


@dataclass(frozen=True)
class WorkerSystemdReadiness:
    ready: bool
    code: str
    detail: str


@dataclass(frozen=True)
class WorkerAuthSystemdObservation:
    state: str
    reason_code: str | None
    unit_name: str


@dataclass(frozen=True)
class WorkerUnitActivity:
    state: str
    unit_name: str
    exit_code: int | None


def validate_slot(slot: WorkerSlot) -> str:
    if slot.slot_id not in SLOT_IDS or slot.linux_user != f"eom-cdx-{slot.slot_id}":
        raise ValueError("worker slot does not match a fixed systemd identity")
    return slot.slot_id


def validate_job_id(job_id: str) -> str:
    if JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise ValueError("invalid canonical EOM job ID")
    return job_id


def worker_unit_name(slot: WorkerSlot, job_id: str) -> str:
    slot_id = validate_slot(slot)
    return f"eom-worker-{slot_id}@{validate_job_id(job_id)}.service"


def probe_unit_name(slot: WorkerSlot, probe_id: str | None = None) -> str:
    slot_id = validate_slot(slot)
    actual_probe_id = probe_id or f"probe_{uuid4().hex}"
    if PROBE_ID_PATTERN.fullmatch(actual_probe_id) is None:
        raise ValueError("invalid worker authorization probe identity")
    return f"eom-worker-probe-{slot_id}@{actual_probe_id}.service"


def auth_unit_name(slot: WorkerSlot) -> str:
    return f"eom-worker-auth-{validate_slot(slot)}.service"


def systemctl_start_argv(unit_name: str) -> tuple[str, ...]:
    return (
        str(SYSTEMCTL),
        "--no-ask-password",
        "--wait",
        "start",
        unit_name,
    )


def systemctl_show_argv(unit_name: str) -> tuple[str, ...]:
    return (
        str(SYSTEMCTL),
        "show",
        "--no-pager",
        "--property=LoadState",
        "--property=ActiveState",
        "--property=SubState",
        "--property=Result",
        "--property=ExecMainCode",
        "--property=ExecMainStatus",
        "--property=ExecMainStartTimestampMonotonic",
        "--property=NeedDaemonReload",
        unit_name,
    )


def systemctl_is_active_argv(unit_name: str) -> tuple[str, ...]:
    return (str(SYSTEMCTL), "is-active", "--quiet", unit_name)


def _run_unit_start(unit_name: str, *, timeout_seconds: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        systemctl_start_argv(unit_name),
        capture_output=True,
        check=False,
        env=SYSTEMCTL_ENV,
        timeout=timeout_seconds,
    )


def _read_unit_active_returncode(unit_name: str) -> int:
    try:
        completed = subprocess.run(
            systemctl_is_active_argv(unit_name),
            capture_output=True,
            check=False,
            env=SYSTEMCTL_ENV,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("fixed worker unit activity is unavailable") from exc
    return completed.returncode


def _unit_is_lingering(active_returncode: int) -> bool:
    if active_returncode == 0:
        return True
    if active_returncode in NON_ACTIVE_SYSTEMCTL_EXIT_CODES:
        return False
    raise ValueError("fixed worker unit activity is unexpected")


def parse_unit_status(output: str) -> FixedUnitStatus:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    try:
        return FixedUnitStatus(
            load_state=values["LoadState"],
            active_state=values["ActiveState"],
            sub_state=values["SubState"],
            result=values["Result"],
            exec_main_code=int(values["ExecMainCode"]),
            exec_main_status=int(values["ExecMainStatus"]),
            exec_main_started_monotonic=int(values["ExecMainStartTimestampMonotonic"] or "0"),
            need_daemon_reload=values["NeedDaemonReload"] == "yes",
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("systemd unit status is incomplete") from exc


def _read_unit_status(unit_name: str) -> FixedUnitStatus:
    completed = subprocess.run(
        systemctl_show_argv(unit_name),
        capture_output=True,
        check=False,
        env=SYSTEMCTL_ENV,
        timeout=15,
    )
    if completed.returncode != 0:
        raise OSError("fixed worker unit status is unavailable")
    return parse_unit_status(completed.stdout.decode("utf-8", errors="replace"))


def _start_unit(unit_name: str, *, timeout_seconds: int) -> FixedUnitRun:
    completed = _run_unit_start(unit_name, timeout_seconds=timeout_seconds)
    active_returncode = _read_unit_active_returncode(unit_name)
    try:
        status = _read_unit_status(unit_name)
    except (OSError, ValueError):
        status = None
    return FixedUnitRun(
        unit_name=unit_name,
        exit_code=completed.returncode,
        command_stdout=completed.stdout,
        command_stderr=completed.stderr,
        status=status,
        active_returncode=active_returncode,
    )


def launch_worker_unit(slot: WorkerSlot, job_id: str, *, timeout_seconds: int) -> FixedUnitRun:
    if timeout_seconds != fixed_worker_timeout_seconds(slot):
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "worker timeout does not match fixed unit contract"
        )
    unit_name = worker_unit_name(slot, job_id)
    try:
        run = _start_unit(
            unit_name,
            timeout_seconds=timeout_seconds + FIXED_WORKER_CLIENT_GUARD_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PlatformError(ErrorCode.WORKER_TIMEOUT, "fixed worker unit timed out") from exc
    except (OSError, ValueError) as exc:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit status is unavailable"
        ) from exc
    status = run.status
    try:
        lingering = _unit_is_lingering(run.active_returncode)
    except ValueError as exc:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit activity is unexpected"
        ) from exc
    if status is not None and status.need_daemon_reload:
        raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit is stale")
    if lingering or (status is not None and status.process_lingering):
        raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit did not stop")
    if status is not None and status.result == "timeout":
        raise PlatformError(ErrorCode.WORKER_TIMEOUT, "fixed worker unit timed out")
    if run.exit_code == 0:
        return FixedUnitRun(
            unit_name=run.unit_name,
            exit_code=0,
            command_stdout=run.command_stdout,
            command_stderr=run.command_stderr,
            status=status,
            active_returncode=run.active_returncode,
        )
    if status is None or not status.process_started or status.exit_code == 0:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit start was denied or unavailable"
        )
    return FixedUnitRun(
        unit_name=run.unit_name,
        exit_code=status.exit_code,
        command_stdout=run.command_stdout,
        command_stderr=run.command_stderr,
        status=status,
        active_returncode=run.active_returncode,
    )


def inspect_worker_systemd_contract(slot: WorkerSlot) -> WorkerSystemdReadiness:
    try:
        slot_id = validate_slot(slot)
        _validate_root_owned_artifact(
            SYSTEMD_UNIT_ROOT / f"eom-worker-{slot_id}@.service",
            expected_mode=0o644,
            expected_sha256=WORKER_TEMPLATE_SHA256[slot_id],
        )
        _validate_root_owned_artifact(
            SYSTEMD_UNIT_ROOT / f"eom-worker-probe-{slot_id}@.service",
            expected_mode=0o644,
            expected_sha256=PROBE_TEMPLATE_SHA256[slot_id],
        )
        _validate_root_owned_artifact(
            WORKER_EXECUTABLE,
            expected_mode=0o755,
            expected_sha256=WORKER_EXECUTABLE_SHA256,
        )
        _validate_root_owned_artifact(
            SYSTEMD_UNIT_ROOT / f"eom-worker-auth-{slot_id}.service",
            expected_mode=0o644,
            expected_sha256=AUTH_TEMPLATE_SHA256[slot_id],
        )
        _validate_root_owned_artifact(
            WORKER_AUTH_EXECUTABLE,
            expected_mode=0o755,
            expected_sha256=WORKER_AUTH_EXECUTABLE_SHA256,
        )
    except (KeyError, OSError, ValueError):
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_TEMPLATE_INVALID", f"slot {slot.slot_id}"
        )
    return WorkerSystemdReadiness(True, "READY", f"slot {slot_id} contract v1")


def observe_worker_auth_systemd(slot: WorkerSlot) -> WorkerAuthSystemdObservation:
    """Run the fixed non-generating probe and return only its allowlisted classification."""

    unit_name = auth_unit_name(slot)
    try:
        run = _start_unit(unit_name, timeout_seconds=60)
        lingering = _unit_is_lingering(run.active_returncode)
    except subprocess.TimeoutExpired:
        return WorkerAuthSystemdObservation("DEGRADED", "AUTH_PROBE_TIMEOUT", unit_name)
    except (OSError, ValueError):
        return WorkerAuthSystemdObservation("DEGRADED", "AUTH_PROBE_UNAVAILABLE", unit_name)
    if lingering or (run.status is not None and run.status.process_lingering):
        return WorkerAuthSystemdObservation("DEGRADED", "AUTH_PROBE_LINGERING", unit_name)
    status = run.status
    if status is not None and status.need_daemon_reload:
        return WorkerAuthSystemdObservation("DEGRADED", "AUTH_PROBE_STALE", unit_name)
    if run.exit_code == 0 and (status is None or status.exit_code == 0):
        return WorkerAuthSystemdObservation("READY", None, unit_name)
    if status is None or not status.process_started:
        return WorkerAuthSystemdObservation("DEGRADED", "AUTH_PROBE_START_DENIED", unit_name)
    reason_by_exit = {
        AUTH_REQUIRED_EXIT: ("AUTH_REQUIRED", "CODEX_LOGIN_REQUIRED"),
        AUTH_PROBE_INVALID_EXIT: ("DEGRADED", "AUTH_PROBE_INVALID"),
        AUTH_PROBE_TIMEOUT_EXIT: ("DEGRADED", "AUTH_PROBE_TIMEOUT"),
    }
    state, reason = reason_by_exit.get(status.exit_code, ("DEGRADED", "AUTH_PROBE_FAILED"))
    return WorkerAuthSystemdObservation(state, reason, unit_name)


def inspect_worker_unit_activity(slot: WorkerSlot, job_id: str) -> WorkerUnitActivity:
    """Inspect one exact fixed worker instance without starting, stopping, or resetting it."""

    unit_name = worker_unit_name(slot, job_id)
    try:
        active_returncode = _read_unit_active_returncode(unit_name)
        active = _unit_is_lingering(active_returncode)
        status = _read_unit_status(unit_name)
    except (OSError, ValueError):
        return WorkerUnitActivity("UNKNOWN", unit_name, None)
    if status.need_daemon_reload:
        return WorkerUnitActivity("UNKNOWN", unit_name, None)
    if active or status.process_lingering:
        return WorkerUnitActivity("RUNNING", unit_name, None)
    return WorkerUnitActivity(
        "ABSENT",
        unit_name,
        status.exit_code if status.process_started else None,
    )


def probe_worker_systemd_authorization(slot: WorkerSlot) -> WorkerSystemdReadiness:
    unit_name = probe_unit_name(slot)
    try:
        started = _run_unit_start(unit_name, timeout_seconds=30)
    except subprocess.TimeoutExpired:
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_PROBE_TIMEOUT", f"slot {slot.slot_id} probe timed out"
        )
    except OSError:
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_PROBE_UNAVAILABLE", f"slot {slot.slot_id} probe unavailable"
        )
    if started.returncode != 0:
        diagnostics = (started.stdout + b"\n" + started.stderr).lower()
        denied = any(marker in diagnostics for marker in AUTHORIZATION_DENIED_MARKERS)
        return WorkerSystemdReadiness(
            False,
            "WORKER_SYSTEMD_AUTHORIZATION_DENIED" if denied else "WORKER_SYSTEMD_PROBE_FAILED",
            f"slot {slot.slot_id} probe start failed",
        )

    # CollectMode may unload the completed oneshot before a subsequent `show`, which can then
    # rehydrate the template without its execution metadata. The successful blocking StartUnit
    # result is authoritative; is-active is used only to reject a lingering process.
    try:
        active_returncode = _read_unit_active_returncode(unit_name)
        lingering = _unit_is_lingering(active_returncode)
    except (OSError, ValueError):
        return WorkerSystemdReadiness(
            False,
            "WORKER_SYSTEMD_STATUS_UNEXPECTED",
            f"slot {slot.slot_id} probe status unavailable",
        )
    if lingering:
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_PROBE_LINGERING", f"slot {slot.slot_id} probe remained active"
        )
    return WorkerSystemdReadiness(True, "READY", f"slot {slot.slot_id} probe passed")


def _validate_root_owned_artifact(path: Path, *, expected_mode: int, expected_sha256: str) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise ValueError("installed worker artifact ownership is invalid")
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("installed worker artifact hash is invalid")

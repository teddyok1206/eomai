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
SYSTEMCTL_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
JOB_ID_PATTERN = re.compile(r"\Ajob_[0-9a-f]{32}\Z", re.ASCII)
PROBE_ID_PATTERN = re.compile(r"\Aprobe_[0-9a-f]{32}\Z", re.ASCII)
SLOT_IDS = frozenset({"01", "02", "03", "04", "05"})
ACTIVE_STATES = frozenset({"activating", "active", "deactivating", "reloading"})
FIXED_WORKER_TIMEOUT_SECONDS = 600

# These hashes are the installed contract. Tests compare them with the canonical repository
# sources, and runtime readiness compares them with root-owned installed artifacts.
WORKER_TEMPLATE_SHA256 = {
    "01": "0ef8e0e7b10febf252f58eaa113b58f48ffc34b1983e3aead799460e6b586b38",
    "02": "f939ea2c0fca407209996f4b191796ae349d0c56b716eca8f9f4b5a47c91f174",
    "03": "6ffe68dd2f919a9249649237ef18bf0423d7abfd3f27360d228340a9a2d98092",
    "04": "bf1c098eec35327bfa9713ce7fdb1bab2b530209265b64aa4982b818a02abd21",
    "05": "7bbf49cb966ad2cc673d34c99f1a3f7301a18b021d28d3f9ef07faf3046e566b",
}
PROBE_TEMPLATE_SHA256 = {
    "01": "8c039d8ce80a161dfc093ce803a80d455a9c73f757687b5831b35821f62a7f0f",
    "02": "e28d25ce9dd609046e483de6638f9f9c316766f193e884ea32ee5e6a97e94207",
    "03": "c6356db32e605a8a67a4c0a892678c7006361a3a675e1b2db1507b12e164f4bf",
    "04": "3b4cd10ecc74823599ccfbb1a99fc985724dec0125c0ee1eb6f263ecb772a337",
    "05": "23815f4365697b32f5d5fa3b296c666b5a7dafdc2cbf9477fb0ffb529c64ed88",
}
WORKER_EXECUTABLE_SHA256 = "3a98648520e7274591e1b3b36faba38d521bb6f467b526e6176949ba4d321d58"


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
    status: FixedUnitStatus


@dataclass(frozen=True)
class WorkerSystemdReadiness:
    ready: bool
    code: str
    detail: str


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
    completed = subprocess.run(
        systemctl_start_argv(unit_name),
        capture_output=True,
        check=False,
        env=SYSTEMCTL_ENV,
        timeout=timeout_seconds,
    )
    status = _read_unit_status(unit_name)
    return FixedUnitRun(
        unit_name=unit_name,
        exit_code=completed.returncode,
        command_stdout=completed.stdout,
        command_stderr=completed.stderr,
        status=status,
    )


def launch_worker_unit(slot: WorkerSlot, job_id: str, *, timeout_seconds: int) -> FixedUnitRun:
    if timeout_seconds != FIXED_WORKER_TIMEOUT_SECONDS:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "worker timeout does not match fixed unit contract"
        )
    unit_name = worker_unit_name(slot, job_id)
    try:
        run = _start_unit(unit_name, timeout_seconds=timeout_seconds + 30)
    except subprocess.TimeoutExpired as exc:
        raise PlatformError(ErrorCode.WORKER_TIMEOUT, "fixed worker unit timed out") from exc
    except (OSError, ValueError) as exc:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit status is unavailable"
        ) from exc
    if run.status.need_daemon_reload:
        raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit is stale")
    if run.status.process_lingering:
        raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit did not stop")
    if run.status.result == "timeout":
        raise PlatformError(ErrorCode.WORKER_TIMEOUT, "fixed worker unit timed out")
    if not run.status.process_started:
        raise PlatformError(
            ErrorCode.WORKER_UNAVAILABLE, "fixed worker unit start was denied or unavailable"
        )
    return FixedUnitRun(
        unit_name=run.unit_name,
        exit_code=run.status.exit_code,
        command_stdout=run.command_stdout,
        command_stderr=run.command_stderr,
        status=run.status,
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
    except (KeyError, OSError, ValueError):
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_TEMPLATE_INVALID", f"slot {slot.slot_id}"
        )
    return WorkerSystemdReadiness(True, "READY", f"slot {slot_id} contract v1")


def probe_worker_systemd_authorization(slot: WorkerSlot) -> WorkerSystemdReadiness:
    unit_name = probe_unit_name(slot)
    try:
        run = _start_unit(unit_name, timeout_seconds=30)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_AUTHORIZATION_DENIED", f"slot {slot.slot_id}"
        )
    status = run.status
    completed_before_collection = (
        status.load_state == "loaded"
        and status.result == "success"
        and status.process_started
        and status.exit_code == 0
    )
    collected_after_success = status.load_state == "not-found"
    ready = (
        run.exit_code == 0
        and (completed_before_collection or collected_after_success)
        and not status.process_lingering
        and not status.need_daemon_reload
    )
    return WorkerSystemdReadiness(
        ready,
        "READY" if ready else "WORKER_SYSTEMD_AUTHORIZATION_DENIED",
        f"slot {slot.slot_id} probe {'passed' if ready else 'failed'}",
    )


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

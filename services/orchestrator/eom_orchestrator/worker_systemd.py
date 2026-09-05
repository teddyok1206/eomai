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
WORKER_DEVICE_LOGIN_EXECUTABLE = Path("/usr/local/libexec/eom-worker-device-login")
WORKER_USAGE_EXECUTABLE = Path("/usr/local/libexec/eom-worker-codex-usage")
SYSTEMCTL_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
JOB_ID_PATTERN = re.compile(r"\Ajob_[0-9a-f]{32}\Z", re.ASCII)
PROBE_ID_PATTERN = re.compile(r"\Aprobe_[0-9a-f]{32}\Z", re.ASCII)
AUTH_ENROLLMENT_ID_PATTERN = re.compile(r"\Aauthflow_[0-9a-f]{32}\Z", re.ASCII)
USAGE_INSTANCE_PATTERN = re.compile(r"\Acodexcmd_[0-9a-f]{32}-authbinding_[0-9a-f]{32}\Z", re.ASCII)
SLOT_IDS = frozenset({"01", "02", "03", "04", "05", "06"})
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
        if validate_slot(slot) in {"05", "06"}
        else FIXED_WORKER_TIMEOUT_SECONDS
    )


# These hashes are the installed contract. Tests compare them with the canonical repository
# sources, and runtime readiness compares them with root-owned installed artifacts.
WORKER_TEMPLATE_SHA256 = {
    "01": "9fd450e28e5d5dcec105ff67613e30479623714dacf97bd83f9ff3f4d81d1610",
    "02": "4f161c30c11b9d1a77905caafdb2357cad9ff210babaf18e23fb9387cf4839de",
    "03": "c2f2254c142a4929fed20924881870f155fae3c05d1e6096858d6237bf4a441d",
    "04": "598519eb0f35d0d6869d7bed72c30c5ae10f17207ec3816093d096f74e97519c",
    "05": "15216cdcd8b397520b7125f719db8f62142f625456fe6ed9b2a058a5bba36a79",
    "06": "4fd257b45cc10c4b181a6c75572ff5b786d30d6a374e4d76d62c2cdf552abfd3",
}
PROBE_TEMPLATE_SHA256 = {
    "01": "6d74599b84b8ac243656fb1cef1ffb459261ff23195428cd47be4da86134d4e4",
    "02": "66fd5e603821b3c21c76d06cc96cf29aaba30c5c90f99e2a0c08ee347dff555c",
    "03": "b6851bf9e087ea6c0a2cbabe61e03abc06dd862bbe5edf69e2e4e7e2f445b8a5",
    "04": "83eccd46ee0b058ede1824b1f137b9f35803a9da5d91ae14ec1961651d34a69a",
    "05": "86c19aa495b44be6f38441b6fe63308e408cf12310d5d562207a128ef354768c",
    "06": "f14b35970a292fa6ccd6d319880578e4243f047e73bc9d3dfe215a7b3cb8f87e",
}
AUTH_TEMPLATE_SHA256 = {
    "01": "4ca00325bea635d32b192ae3cc6300fc887d13f861d38aeb2bbc2639945e1ae4",
    "02": "312b0ce43e70bd005bac19f4659b0e1120b55bd2d8de338ac41a6a70b07226cd",
    "03": "cf1686cb8bab136017148e9ede376362ff217bcc7a69a14c87fcde0c1fa90f5f",
    "04": "a46f8d4c4b5f7b2bfdf1993e0cb7694bef348e85d56fcb858471d8ba8bbcf142",
    "05": "98dbc3e1b1907912a71b8f2b7b2c7a7c224cd19b927084bfde2de5037ead29e3",
    "06": "695e4742b2e4e624439712e16cc48245301b8cd42a4df86ee99d33bee80f84db",
}
LOGIN_TEMPLATE_SHA256 = {
    "01": "1a1599089916ae6c51cf1fab6e65078f5fe83a07f2f9c517ec71830e7b5de5ce",
    "02": "4f36d89147bfdf7e227d2c67265c3ea2c2d26fb875265ec664d2d1f5e578fbde",
    "03": "d4ba2743d78ac02e196147f8b9c8e7d532572db648e0c0a698315ff87e0d92cf",
    "04": "6ec5adadc3a2d3e9af89430a91094930ff36fe5e1f70720682add7f45daeafb4",
    "05": "5036d11960c3b45cbf9c199df1c6be995e7e6de7e2d41f6504f6aa0157aacfa1",
    "06": "6df179d670a1b299116bb59180d36b0bbbef7ec690b095d86add8b968850ea13",
}
USAGE_TEMPLATE_SHA256 = {
    "01": "effffebe0d152c425a64f5fa703d028311394b6a0c3cea7a79d1c8b5544f5416",
    "02": "ea6c7302fa2f56f931ceb1ea2951191ec894c11d2197d63f3eea9a71d8cb88a2",
    "03": "ea1d3a01bf9a25f31be2cdd32e2312f86bd3259da01681abcfda57f51efbc19a",
    "04": "089cb15b83afb430ec41f1c14c6a2e874013f938ca743218d35a08b474ac93d1",
    "05": "1f6111362c44782f348148d14c26d212320f2c1c1ec342b6a2667ded65a70daa",
    "06": "d0cb86d101fb7f6227d3e9c693581639d5753dcecf02adda6e410b82f4cb240a",
}
WORKER_EXECUTABLE_SHA256 = "2e012614b9aa2464e45aa99a588da3efbf8fd76d32d85833e4c065fc87e0d4f9"
WORKER_AUTH_EXECUTABLE_SHA256 = "42951e21b4c54574d6402fc61139792ec8abf2b549d30867e792df7977f6b7e7"
WORKER_DEVICE_LOGIN_EXECUTABLE_SHA256 = (
    "47ca1fb12d88d1f02ac4402b2e260e96d4ae78b3ceefdeedbee9da392650feec"
)
WORKER_USAGE_EXECUTABLE_SHA256 = "ad9e8c827985d2eef739af0323a3e31696590262e69f2a31273abd266ae3d33b"
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


@dataclass(frozen=True)
class WorkerDeviceLoginActivity:
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


def device_login_unit_name(slot: WorkerSlot, enrollment_id: str) -> str:
    slot_id = validate_slot(slot)
    if AUTH_ENROLLMENT_ID_PATTERN.fullmatch(enrollment_id) is None:
        raise ValueError("invalid Codex auth enrollment identity")
    return f"eom-worker-login-{slot_id}@{enrollment_id}.service"


def usage_unit_name(slot: WorkerSlot, command_id: str, binding_id: str) -> str:
    slot_id = validate_slot(slot)
    instance = f"{command_id}-{binding_id}"
    if USAGE_INSTANCE_PATTERN.fullmatch(instance) is None:
        raise ValueError("invalid Codex usage observation identity")
    return f"eom-worker-usage-{slot_id}@{instance}.service"


def systemctl_start_argv(unit_name: str) -> tuple[str, ...]:
    return (
        str(SYSTEMCTL),
        "--no-ask-password",
        "--wait",
        "start",
        unit_name,
    )


def systemctl_start_async_argv(unit_name: str) -> tuple[str, ...]:
    return (str(SYSTEMCTL), "--no-ask-password", "--no-block", "start", unit_name)


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
        _validate_root_owned_artifact(
            SYSTEMD_UNIT_ROOT / f"eom-worker-login-{slot_id}@.service",
            expected_mode=0o644,
            expected_sha256=LOGIN_TEMPLATE_SHA256[slot_id],
        )
        _validate_root_owned_artifact(
            WORKER_DEVICE_LOGIN_EXECUTABLE,
            expected_mode=0o755,
            expected_sha256=WORKER_DEVICE_LOGIN_EXECUTABLE_SHA256,
        )
        _validate_root_owned_artifact(
            SYSTEMD_UNIT_ROOT / f"eom-worker-usage-{slot_id}@.service",
            expected_mode=0o644,
            expected_sha256=USAGE_TEMPLATE_SHA256[slot_id],
        )
        _validate_root_owned_artifact(
            WORKER_USAGE_EXECUTABLE,
            expected_mode=0o755,
            expected_sha256=WORKER_USAGE_EXECUTABLE_SHA256,
        )
    except (KeyError, OSError, ValueError):
        return WorkerSystemdReadiness(
            False, "WORKER_SYSTEMD_TEMPLATE_INVALID", f"slot {slot.slot_id}"
        )
    contract_version = "v2" if slot_id == "06" else "v1"
    return WorkerSystemdReadiness(True, "READY", f"slot {slot_id} contract {contract_version}")


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


def launch_worker_usage_unit(slot: WorkerSlot, command_id: str, binding_id: str) -> FixedUnitRun:
    """Run one fixed non-generating App Server usage observation instance."""

    unit_name = usage_unit_name(slot, command_id, binding_id)
    try:
        run = _start_unit(unit_name, timeout_seconds=90)
        lingering = _unit_is_lingering(run.active_returncode)
    except subprocess.TimeoutExpired as exc:
        raise OSError("Codex usage observation timed out") from exc
    if lingering or (run.status is not None and run.status.process_lingering):
        raise OSError("Codex usage observation unit is lingering")
    if run.status is not None and run.status.need_daemon_reload:
        raise OSError("Codex usage observation unit is stale")
    if run.exit_code == 0 and (run.status is None or run.status.exit_code == 0):
        return run
    if run.status is None or not run.status.process_started:
        raise OSError("Codex usage observation unit did not start")
    return FixedUnitRun(
        unit_name=run.unit_name,
        exit_code=run.status.exit_code,
        command_stdout=run.command_stdout,
        command_stderr=run.command_stderr,
        status=run.status,
        active_returncode=run.active_returncode,
    )


def launch_device_login_unit(slot: WorkerSlot, enrollment_id: str) -> WorkerDeviceLoginActivity:
    """Start exactly one fixed device-login unit without waiting for user interaction."""

    unit_name = device_login_unit_name(slot, enrollment_id)
    try:
        completed = subprocess.run(
            systemctl_start_async_argv(unit_name),
            capture_output=True,
            check=False,
            env=SYSTEMCTL_ENV,
            timeout=15,
        )
        status = _read_unit_status(unit_name)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return WorkerDeviceLoginActivity("UNAVAILABLE", unit_name, None)
    if completed.returncode != 0 or status.need_daemon_reload:
        return WorkerDeviceLoginActivity("UNAVAILABLE", unit_name, None)
    if status.process_lingering:
        return WorkerDeviceLoginActivity("RUNNING", unit_name, None)
    if not status.process_started:
        return WorkerDeviceLoginActivity("UNAVAILABLE", unit_name, None)
    return WorkerDeviceLoginActivity("TERMINAL", unit_name, status.exit_code)


def inspect_device_login_unit(slot: WorkerSlot, enrollment_id: str) -> WorkerDeviceLoginActivity:
    """Read one exact login unit without changing it."""

    unit_name = device_login_unit_name(slot, enrollment_id)
    try:
        status = _read_unit_status(unit_name)
    except (OSError, ValueError):
        return WorkerDeviceLoginActivity("UNAVAILABLE", unit_name, None)
    if status.need_daemon_reload:
        return WorkerDeviceLoginActivity("UNAVAILABLE", unit_name, None)
    if status.process_lingering:
        return WorkerDeviceLoginActivity("RUNNING", unit_name, None)
    return WorkerDeviceLoginActivity(
        "TERMINAL" if status.process_started else "ABSENT",
        unit_name,
        status.exit_code if status.process_started else None,
    )


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

"""One fixed browser unit; actual cgroup closure is required before profile takeover."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_kakao_archive_contracts import canonical_bytes
from eom_kakao_archive_contracts.kakao_remote import ProfileFence, validate_remote_contract

from . import kakao_runtime_os as runtime_os
from .native_exam_preparation import require_native_exam_runtime_python

UNIT = "eom-kakao-browser.service"
TEMPLATE = Path("/etc/systemd/system") / UNIT
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-browser/bin/python")
DRIVER = PYTHON.parent / "eom-kakao-browser-driver"
ENVIRONMENT = Path("/etc/eom/kakao-browser.env")
REQUEST = Path("/var/lib/eom-kakao-runtime/browser/request.json")
CONTROL_LOCK = REQUEST.parent / "control.lock"
HISTORY_MARKER = "initialized.json"
CGROUP = "/system.slice/" + UNIT
CGROUP_ROOT = Path("/sys/fs/cgroup")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
PROPERTIES = (
    "LoadState",
    "FragmentPath",
    "DropInPaths",
    "NeedDaemonReload",
    "User",
    "Group",
    "Type",
    "NotifyAccess",
    "KillMode",
    "Restart",
    "Job",
    "ActiveState",
    "SubState",
    "MainPID",
    "ControlPID",
    "ExecMainPID",
    "ExecMainStartTimestampMonotonic",
    "InvocationID",
    "ControlGroup",
    "StatusText",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
)


class KakaoBrowserRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BrowserRunHandle:
    """Persist privately with the claimed run; never accepted from UI or worker output."""

    fence: ProfileFence
    command_sha256: str
    boot_id: str
    invocation_id: str
    main_pid: int
    started_monotonic_us: int
    cgroup: str


@dataclass(frozen=True, slots=True)
class StoppedBrowserRun:
    run: BrowserRunHandle
    observed_at: datetime
    cgroup_state: Literal["ABSENT", "EMPTY"]
    unit_result: str
    main_exit_code: int
    main_exit_status: int


@dataclass(frozen=True, slots=True)
class ClosedBrowserDispatch:
    """An unconfirmed dispatch is physically closed, not a successful run/flush receipt."""

    fence: ProfileFence
    command_sha256: str
    dispatched_boot_id: str
    observed_boot_id: str
    observed_at: datetime
    cgroup_state: Literal["ABSENT", "EMPTY"]
    reason: Literal["START_NOT_CONFIRMED", "REBOOT_UNCLEAN"]
    invocation_id: str
    started_monotonic_us: int
    unit_result: str
    main_exit_code: int
    main_exit_status: int


@contextmanager
def _directory(path: Path, *, owners: frozenset[int], protected: bool = True) -> Iterator[int]:
    try:
        with runtime_os.protected_directory(path, owners=owners, protected=protected) as directory:
            yield directory
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _read(path: Path, *, uid: int, maximum: int, owners: frozenset[int]) -> bytes:
    try:
        return runtime_os.read_protected(path, uid=uid, maximum=maximum, owners=owners)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _has_history() -> bool:
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    with _directory(REQUEST.parent, owners=frozenset({0, owner})) as directory:
        for name in (REQUEST.name, HISTORY_MARKER):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            return True
    return False


def _stage(fence: ProfileFence, *, first: bool) -> str:
    """Caller holds control.lock and has confirmed closure. Preserve every prior input."""
    raw = canonical_bytes(fence.model_dump(mode="json"))
    validate_remote_contract("profile", json.loads(raw))
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    with _directory(REQUEST.parent, owners=frozenset({0, owner})) as directory:

        def write_new(name: str) -> None:
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o640,
                    dir_fd=directory,
                )
            except FileExistsError:
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_RUN_ALREADY_STAGED") from None
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)

        if first:
            write_new(HISTORY_MARKER)
        write_new(f"{fence.browser_run_id}.json")
        pending = f"{fence.browser_run_id}.next"
        write_new(pending)
        os.rename(pending, REQUEST.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    return _digest(raw)


@contextmanager
def _control_lock() -> Iterator[None]:
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    if os.geteuid() != owner or owner == 0:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_OWNER_INVALID")
    with _directory(CONTROL_LOCK.parent, owners=frozenset({0, owner})) as directory:
        fd = os.open(
            CONTROL_LOCK.name,
            os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != owner
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size
            ):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CONTROL_LOCK_UNTRUSTED")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CONTROL_BUSY") from None
            linked = os.stat(CONTROL_LOCK.name, dir_fd=directory, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CONTROL_LOCK_UNTRUSTED")
            yield
        finally:
            os.close(fd)


def _boot_id() -> str:
    try:
        return runtime_os.boot_identity(BOOT_ID)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _parse_show(raw: bytes) -> dict[str, str]:
    try:
        return runtime_os.parse_unit_observation(raw, PROPERTIES)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _show() -> dict[str, str]:
    try:
        return runtime_os.show_unit(UNIT, PROPERTIES)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _trusted_unit(values: dict[str, str]) -> None:
    expected = {
        "LoadState": "loaded",
        "FragmentPath": str(TEMPLATE),
        "DropInPaths": "",
        "NeedDaemonReload": "no",
        "User": "eom-kakao",
        "Group": "eom-kakao",
        "Type": "notify",
        "NotifyAccess": "main",
        "KillMode": "mixed",
        "Restart": "no",
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_UNIT_UNTRUSTED")


def _cgroup_closed() -> Literal["ABSENT", "EMPTY"]:
    try:
        return runtime_os.cgroup_closed(
            CGROUP_ROOT, UNIT, open_directory=lambda path: _directory(path, owners=frozenset({0}))
        )
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_" + exc.reason) from None


def _same_execution(run: BrowserRunHandle, values: dict[str, str]) -> None:
    _trusted_unit(values)
    if (
        run.cgroup != CGROUP
        or _boot_id() != run.boot_id
        or values["InvocationID"] not in {run.invocation_id, ""}
        or (
            values["ActiveState"] not in {"inactive", "failed"}
            and values["InvocationID"] != run.invocation_id
        )
        or int(values["ExecMainPID"]) != run.main_pid
        or int(values["ExecMainStartTimestampMonotonic"]) != run.started_monotonic_us
        or values["ControlGroup"] not in {run.cgroup, ""}
        or values["StatusText"] != "KAKAO_BROWSER_STARTED:" + run.command_sha256
    ):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_RUN_MISMATCH")


def _stopped(run: BrowserRunHandle, values: dict[str, str]) -> StoppedBrowserRun:
    _same_execution(run, values)
    if (
        values["ActiveState"] not in {"inactive", "failed"}
        or values["SubState"] not in {"dead", "failed"}
        or values["MainPID"] != "0"
        or values["ControlPID"] != "0"
        or values["Job"] != ""
    ):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_STOP_UNCONFIRMED")
    return StoppedBrowserRun(
        run,
        datetime.now(UTC),
        _cgroup_closed(),
        values["Result"],
        int(values["ExecMainCode"]),
        int(values["ExecMainStatus"]),
    )


@dataclass(frozen=True, slots=True)
class FixedKakaoBrowserRuntime:
    template_sha256: str
    driver_sha256: str

    def _installed(self) -> None:
        try:
            for digest in (self.template_sha256, self.driver_sha256):
                if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
                    raise ValueError
            require_native_exam_runtime_python(PYTHON)
            for path, digest, maximum in (
                (TEMPLATE, self.template_sha256, 16384),
                (DRIVER, self.driver_sha256, 1024 * 1024),
            ):
                if _digest(_read(path, uid=0, maximum=maximum, owners=frozenset({0}))) != digest:
                    raise ValueError
            if not os.access(DRIVER, os.X_OK):
                raise ValueError
            if _read(ENVIRONMENT, uid=0, maximum=256, owners=frozenset({0})) != (
                f"EOM_KAKAO_BROWSER_DRIVER_SHA256={self.driver_sha256}\n".encode()
            ):
                raise ValueError
        except (OSError, ValueError, KeyError):
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_RUNTIME_UNAVAILABLE") from None

    def _request(self, fence: ProfileFence) -> str:
        owner = pwd.getpwnam("eom-catalog-manager").pw_uid
        raw = _read(REQUEST, uid=owner, maximum=4096, owners=frozenset({0, owner}))
        try:
            value = json.loads(raw)
            validate_remote_contract("profile", value)
            if ProfileFence.model_validate(value) != fence:
                raise ValueError
        except ValueError:
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FENCE_MISMATCH") from None
        return _digest(raw)

    def observe_run(self, fence: ProfileFence) -> BrowserRunHandle:
        """Recover the original uncertain start by observation, never start again."""
        with _control_lock():
            self._installed()
            return self._running(fence, self._request(fence), _show())

    def boot_identity(self) -> str:
        """The owner records this with its dispatch intent before calling start."""
        return _boot_id()

    def observe_idle(self) -> runtime_os.IdleRuntimeObservation:
        """First-install probe only; a prior dispatch still needs exact recovery evidence."""
        with _control_lock():
            self._installed()
            values = _show()
            _trusted_unit(values)
            if (
                values["Job"]
                or values["ActiveState"] != "inactive"
                or values["SubState"] != "dead"
                or values["MainPID"] != "0"
                or values["ControlPID"] != "0"
                or values["ControlGroup"] not in {"", CGROUP}
            ):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_IDLE_UNCONFIRMED")
            closed = _cgroup_closed()
            never_dispatched = (
                not _has_history()
                and values["ExecMainStartTimestampMonotonic"] == "0"
                and values["ExecMainPID"] == "0"
                and not values["InvocationID"]
                and not values["StatusText"]
            )
            return runtime_os.IdleRuntimeObservation(
                UNIT, _boot_id(), datetime.now(UTC), closed, never_dispatched
            )

    def observe_dispatch(
        self, fence: ProfileFence, *, command_sha256: str, dispatched_boot_id: str
    ) -> BrowserRunHandle | ClosedBrowserDispatch:
        """Read-only recovery for an exact staged start, including failure before READY.

        Called only with the owner's stored intent. A closed result does not authorize
        a new claim, prove profile flush, or replace the separate gateway stop check.
        Missing/partial staging stays UNKNOWN; this never creates/deletes input files.
        """
        with _control_lock():
            self._installed()
            return self._dispatch_observation(
                fence,
                command_sha256=command_sha256,
                dispatched_boot_id=dispatched_boot_id,
                values=_show(),
            )

    def _dispatch_observation(
        self,
        fence: ProfileFence,
        *,
        command_sha256: str,
        dispatched_boot_id: str,
        values: dict[str, str],
    ) -> BrowserRunHandle | ClosedBrowserDispatch:
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", command_sha256) is None
            or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", dispatched_boot_id)
            is None
            or self._request(fence) != command_sha256
        ):
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FENCE_MISMATCH")
        _trusted_unit(values)
        current_boot = _boot_id()
        if values["ActiveState"] == "active":
            if current_boot != dispatched_boot_id:
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_RUN_MISMATCH")
            return self._running(fence, command_sha256, values)
        if (
            values["ActiveState"] not in {"inactive", "failed"}
            or values["SubState"] not in {"dead", "failed"}
            or values["MainPID"] != "0"
            or values["ControlPID"] != "0"
            or values["Job"] != ""
            or values["ControlGroup"] not in {"", CGROUP}
            or (
                values["InvocationID"]
                and re.fullmatch(r"[0-9a-f]{32}", values["InvocationID"]) is None
            )
        ):
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_STOP_UNCONFIRMED")
        # Before READY, systemd may still show the previous invocation's status.
        # We assert only closure of this fixed unit, not successful execution of
        # the staged command or association of that previous outcome to this run.
        return ClosedBrowserDispatch(
            fence=fence,
            command_sha256=command_sha256,
            dispatched_boot_id=dispatched_boot_id,
            observed_boot_id=current_boot,
            observed_at=datetime.now(UTC),
            cgroup_state=_cgroup_closed(),
            reason="START_NOT_CONFIRMED"
            if current_boot == dispatched_boot_id
            else "REBOOT_UNCLEAN",
            invocation_id=values["InvocationID"],
            started_monotonic_us=int(values["ExecMainStartTimestampMonotonic"]),
            unit_result=values["Result"],
            main_exit_code=int(values["ExecMainCode"]),
            main_exit_status=int(values["ExecMainStatus"]),
        )

    def _running(
        self, fence: ProfileFence, digest: str, values: dict[str, str]
    ) -> BrowserRunHandle:
        _trusted_unit(values)
        if (
            values["ActiveState"] != "active"
            or values["SubState"] != "running"
            or values["MainPID"] == "0"
            or values["ControlPID"] != "0"
            or values["Job"] != ""
            or values["MainPID"] != values["ExecMainPID"]
            or values["ExecMainStartTimestampMonotonic"] == "0"
            or re.fullmatch(r"[0-9a-f]{32}", values["InvocationID"]) is None
            or values["ControlGroup"] != CGROUP
            or values["StatusText"] != "KAKAO_BROWSER_STARTED:" + digest
        ):
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_START_UNCONFIRMED")
        return BrowserRunHandle(
            fence,
            digest,
            _boot_id(),
            values["InvocationID"],
            int(values["MainPID"]),
            int(values["ExecMainStartTimestampMonotonic"]),
            CGROUP,
        )

    def start(
        self,
        fence: ProfileFence,
        *,
        prior: BrowserRunHandle | ClosedBrowserDispatch | None,
        assert_current: Callable[[ProfileFence], None],
    ) -> BrowserRunHandle:
        with _control_lock():
            self._installed()
            if fence.mode not in {"AUTO", "MANUAL"}:
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_MODE_NOT_STARTABLE")
            values = _show()
            _trusted_unit(values)
            if prior is None:
                if (
                    values["ActiveState"] != "inactive"
                    or values["MainPID"] != "0"
                    or values["ControlPID"] != "0"
                    or values["Job"] != ""
                    or values["ExecMainStartTimestampMonotonic"] != "0"
                    or _has_history()
                ):
                    raise KakaoBrowserRuntimeError("KAKAO_BROWSER_PRIOR_RUN_REQUIRED")
                _cgroup_closed()
            else:
                if isinstance(prior, ClosedBrowserDispatch):
                    closed = self._dispatch_observation(
                        prior.fence,
                        command_sha256=prior.command_sha256,
                        dispatched_boot_id=prior.dispatched_boot_id,
                        values=values,
                    )
                    if not isinstance(closed, ClosedBrowserDispatch):
                        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_STOP_UNCONFIRMED")
                    prior = closed
                else:
                    _stopped(prior, values)
                if (
                    fence.profile_id != prior.fence.profile_id
                    or fence.browser_run_id == prior.fence.browser_run_id
                    or fence.fence_epoch <= prior.fence.fence_epoch
                ):
                    raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FENCE_MISMATCH")
                if self._request(prior.fence) != prior.command_sha256:
                    raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FENCE_MISMATCH")
            assert_current(fence)
            digest = _stage(fence, first=prior is None)
            try:
                result = subprocess.run(
                    ["/usr/bin/systemctl", "--no-ask-password", "start", UNIT],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=20,
                )
                if result.returncode:
                    raise ValueError
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_START_UNCERTAIN") from None
            started = self._running(fence, digest, _show())
            if prior is not None and (
                started.invocation_id == prior.invocation_id
                or started.started_monotonic_us <= prior.started_monotonic_us
            ):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_START_UNCONFIRMED")
            return started

    def observe_stopped(self, run: BrowserRunHandle) -> StoppedBrowserRun:
        with _control_lock():
            self._installed()
            return _stopped(run, _show())

    def stop(self, run: BrowserRunHandle) -> StoppedBrowserRun:
        with _control_lock():
            self._installed()
            values = _show()
            _same_execution(run, values)
            if values["ActiveState"] in {"inactive", "failed"}:
                return _stopped(run, values)
            # Timeout neither proves failure nor allows takeover: observe actual closure.
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["/usr/bin/systemctl", "--no-ask-password", "stop", UNIT],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=35,
                )
            return _stopped(run, _show())

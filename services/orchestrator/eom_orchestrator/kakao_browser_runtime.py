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

from .native_exam_preparation import require_native_exam_runtime_python

UNIT = "eom-kakao-browser.service"
TEMPLATE = Path("/etc/systemd/system") / UNIT
PYTHON = Path("/srv/eom/conda/envs/eom-kakao-browser/bin/python")
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


@contextmanager
def _directory(path: Path, *, owners: frozenset[int], protected: bool = True) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if protected and (info.st_uid not in owners or info.st_mode & 0o022):
                raise KakaoBrowserRuntimeError("KAKAO_BROWSER_DIRECTORY_UNTRUSTED")
        yield fd
    finally:
        os.close(fd)


def _read(path: Path, *, uid: int, maximum: int, owners: frozenset[int]) -> bytes:
    with _directory(path.parent, owners=owners) as directory:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != uid
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or not 0 < before.st_size <= maximum
        ):
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FILE_UNTRUSTED")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(raw) != before.st_size:
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_FILE_CHANGED")
    return raw


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
    # Kernel-owned, no user path or process-list scan.
    with BOOT_ID.open("r", encoding="ascii") as stream:
        value = stream.read(64).strip()
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is None:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_BOOT_UNKNOWN")
    return value


def _parse_show(raw: bytes) -> dict[str, str]:
    try:
        if len(raw) > 16384:
            raise ValueError
        values: dict[str, str] = {}
        for line in raw.decode("utf-8").splitlines():
            key, value = line.split("=", 1)
            if key not in PROPERTIES or key in values:
                raise ValueError
            values[key] = value
        if set(values) != set(PROPERTIES):
            raise ValueError
        for key in (
            "MainPID",
            "ControlPID",
            "ExecMainPID",
            "ExecMainStartTimestampMonotonic",
            "ExecMainCode",
            "ExecMainStatus",
        ):
            if re.fullmatch(r"0|[1-9][0-9]{0,19}", values[key]) is None:
                raise ValueError
        if values["Result"] not in {
            "success",
            "exit-code",
            "signal",
            "core-dump",
            "watchdog",
            "timeout",
            "start-limit-hit",
            "resources",
            "protocol",
            "oom-kill",
        }:
            raise ValueError
        return values
    except (ValueError, UnicodeError):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_OBSERVATION_INVALID") from None


def _show() -> dict[str, str]:
    try:
        completed = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                UNIT,
                "--no-pager",
                "--property=" + ",".join(PROPERTIES),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if completed.returncode:
            raise ValueError
        return _parse_show(completed.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_OBSERVATION_UNAVAILABLE") from None


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
    # The only accepted cgroup path is fixed by the installed unit, never supplied by a worker.
    path = CGROUP_ROOT / CGROUP.lstrip("/")
    try:
        with _directory(path, owners=frozenset({0})) as directory:
            fd = os.open(
                "cgroup.events", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
            )
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(1025)
    except FileNotFoundError:
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CGROUP_UNKNOWN") from None
        # Missing mount/controller is not a removed service cgroup.
        with _directory(CGROUP_ROOT / "system.slice", owners=frozenset({0})):
            pass
        return "ABSENT"
    if len(raw) > 1024:
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CGROUP_UNKNOWN")
    try:
        values: dict[str, str] = {}
        for line in raw.decode("ascii").splitlines():
            key, value = line.split()
            if key in values or key not in {"populated", "frozen"} or value not in {"0", "1"}:
                raise ValueError
            values[key] = value
        if values.get("populated") != "0":
            raise ValueError
    except (ValueError, UnicodeError):
        raise KakaoBrowserRuntimeError("KAKAO_BROWSER_CGROUP_NOT_CLOSED") from None
    return "EMPTY"


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

    def _running(
        self, fence: ProfileFence, digest: str, values: dict[str, str]
    ) -> BrowserRunHandle:
        _trusted_unit(values)
        if (
            values["ActiveState"] != "active"
            or values["SubState"] != "running"
            or values["MainPID"] == "0"
            or values["ControlPID"] != "0"
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
        prior: BrowserRunHandle | None,
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
                    or values["ExecMainStartTimestampMonotonic"] != "0"
                    or _has_history()
                ):
                    raise KakaoBrowserRuntimeError("KAKAO_BROWSER_PRIOR_RUN_REQUIRED")
                _cgroup_closed()
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

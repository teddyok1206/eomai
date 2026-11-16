"""Catalog-owned fixed gateway handoff; authorization and durable lease stay with its owner."""

from __future__ import annotations

import fcntl
import grp
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
from eom_kakao_archive_contracts.kakao_remote import (
    GatewayLeaseGrant,
    GatewayRevocation,
    ProfileFence,
    gateway_execution_digest,
    validate_remote_contract,
)

from . import kakao_runtime_os as runtime_os
from .kakao_browser_runtime import BrowserRunHandle
from .native_exam_preparation import require_native_exam_runtime_python

UNIT = "eom-kakao-remote.service"
CGROUP = "/system.slice/" + UNIT
BROWSER_CGROUP = "/system.slice/eom-kakao-browser.service"
TEMPLATE = Path("/etc/systemd/system") / UNIT
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-remote/bin/python")
SUPERVISOR = (
    PYTHON.parent.parent / "lib/python3.12/site-packages/eom_kakao_archive_gateway/supervisor.py"
)
GRANT = Path("/var/lib/eom-kakao-runtime/remote/grant.json")
CONTROL_LOCK = GRANT.parent / "control.lock"
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


class KakaoGatewayRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class GatewayRunHandle:
    grant: GatewayLeaseGrant
    boot_id: str
    invocation_id: str
    main_pid: int
    started_monotonic_us: int
    cgroup: str


@dataclass(frozen=True, slots=True)
class ClosedGatewayDispatch:
    """Physical closure only, never a successful session or browser-flush receipt."""

    grant: GatewayLeaseGrant
    dispatched_boot_id: str
    observed_boot_id: str
    observed_at: datetime
    cgroup_state: Literal["ABSENT", "EMPTY"]
    invocation_id: str
    started_monotonic_us: int
    unit_result: str
    main_exit_code: int
    main_exit_status: int


@contextmanager
def _directory(path: Path, *, owners: frozenset[int]) -> Iterator[int]:
    try:
        with runtime_os.protected_directory(path, owners=owners) as fd:
            yield fd
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_" + exc.reason) from None


def _read(path: Path, *, uid: int, maximum: int, owners: frozenset[int]) -> bytes:
    try:
        return runtime_os.read_protected(path, uid=uid, maximum=maximum, owners=owners)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_" + exc.reason) from None


def _show() -> dict[str, str]:
    try:
        return runtime_os.show_unit(UNIT, PROPERTIES)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_" + exc.reason) from None


def _boot_id() -> str:
    try:
        return runtime_os.boot_identity(BOOT_ID)
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_" + exc.reason) from None


def _cgroup_closed() -> Literal["ABSENT", "EMPTY"]:
    try:
        return runtime_os.cgroup_closed(
            CGROUP_ROOT, UNIT, open_directory=lambda path: _directory(path, owners=frozenset({0}))
        )
    except runtime_os.KakaoRuntimeOsError as exc:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_" + exc.reason) from None


@contextmanager
def _control_lock() -> Iterator[None]:
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    if os.geteuid() != owner or owner == 0:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_OWNER_INVALID")
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
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_CONTROL_LOCK_UNTRUSTED")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_CONTROL_BUSY") from None
            linked = os.stat(CONTROL_LOCK.name, dir_fd=directory, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_CONTROL_LOCK_UNTRUSTED")
            yield
        finally:
            os.close(fd)


def _current() -> GatewayLeaseGrant | GatewayRevocation:
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    raw = _read(GRANT, uid=owner, maximum=4096, owners=frozenset({0, owner}))
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_INVALID")
    if value.get("schema_version") == "kakao-remote-gateway-revocation/1.0":
        validate_remote_contract("revocation", value)
        result: GatewayLeaseGrant | GatewayRevocation = GatewayRevocation.model_validate(value)
    else:
        validate_remote_contract("grant", value)
        result = GatewayLeaseGrant.model_validate(value)
    if canonical_bytes(result.model_dump(mode="json")) != raw:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_INVALID")
    return result


def _has_grant_history() -> bool:
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    with (
        _directory(GRANT.parent, owners=frozenset({0, owner})) as directory,
        os.scandir(directory) as entries,
    ):
        # An interrupted .next or unknown entry is history, not a reason to reset first use.
        return any(entry.name != CONTROL_LOCK.name for entry in entries)


def _matches(value: GatewayLeaseGrant | GatewayRevocation, grant: GatewayLeaseGrant) -> None:
    if isinstance(value, GatewayLeaseGrant):
        good = (
            gateway_execution_digest(value) == gateway_execution_digest(grant)
            and value.grant_revision >= grant.grant_revision
        )
    else:
        good = (value.lease_id, value.fence_epoch, value.gateway_epoch) == (
            grant.lease_id,
            grant.fence_epoch,
            grant.gateway_epoch,
        )
    if not good:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_FENCE_MISMATCH")


def _publish(
    value: GatewayLeaseGrant | GatewayRevocation,
    *,
    expected: GatewayLeaseGrant | GatewayRevocation | None,
) -> None:
    """Under control.lock: compare exact old value, stage once, atomic replace and fsync."""
    try:
        current = _current()
    except FileNotFoundError:
        current = None
    if current == value:
        return
    if current != expected:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_STALE")
    raw = canonical_bytes(value.model_dump(mode="json"))
    validate_remote_contract(
        "grant" if isinstance(value, GatewayLeaseGrant) else "revocation", json.loads(raw)
    )
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    read_gid = grp.getgrnam("eom-kakao-grant").gr_gid
    pending = "grant-" + hashlib.sha256(raw).hexdigest() + ".next"
    with _directory(GRANT.parent, owners=frozenset({0, owner})) as directory:
        info = os.fstat(directory)
        if info.st_uid != owner or info.st_gid != read_gid or stat.S_IMODE(info.st_mode) != 0o2750:
            raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_DIRECTORY_UNTRUSTED")
        try:
            fd = os.open(
                pending,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o640,
                dir_fd=directory,
            )
        except FileExistsError:
            if (
                _read(GRANT.parent / pending, uid=owner, maximum=4096, owners=frozenset({0, owner}))
                != raw
            ):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_PUBLICATION_UNCERTAIN") from None
        else:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o640)
                if os.fstat(stream.fileno()).st_gid != read_gid:
                    raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_GROUP_INVALID")
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(pending, GRANT.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)


def _trusted(values: dict[str, str]) -> None:
    expected = {
        "LoadState": "loaded",
        "FragmentPath": str(TEMPLATE),
        "DropInPaths": "",
        "NeedDaemonReload": "no",
        "User": "eom-kakao-remote",
        "Group": "eom-kakao-proxy",
        "Type": "notify",
        "NotifyAccess": "main",
        "KillMode": "control-group",
        "Restart": "no",
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_UNIT_UNTRUSTED")


def _running(grant: GatewayLeaseGrant, values: dict[str, str]) -> GatewayRunHandle:
    _trusted(values)
    if (
        values["Job"]
        or values["ActiveState"] != "active"
        or values["SubState"] != "running"
        or values["MainPID"] == "0"
        or values["ControlPID"] != "0"
        or values["MainPID"] != values["ExecMainPID"]
        or values["ExecMainStartTimestampMonotonic"] == "0"
        or re.fullmatch(r"[0-9a-f]{32}", values["InvocationID"]) is None
        or values["ControlGroup"] != CGROUP
        or values["StatusText"] != "KAKAO_GATEWAY_STARTED:" + gateway_execution_digest(grant)
    ):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_START_UNCONFIRMED")
    return GatewayRunHandle(
        grant,
        _boot_id(),
        values["InvocationID"],
        int(values["MainPID"]),
        int(values["ExecMainStartTimestampMonotonic"]),
        CGROUP,
    )


def _same_execution(run: GatewayRunHandle, values: dict[str, str]) -> None:
    _trusted(values)
    if (
        run.cgroup != CGROUP
        or run.boot_id != _boot_id()
        or values["InvocationID"] not in {run.invocation_id, ""}
        or (
            values["ActiveState"] not in {"inactive", "failed"}
            and values["InvocationID"] != run.invocation_id
        )
        or int(values["ExecMainPID"]) != run.main_pid
        or int(values["ExecMainStartTimestampMonotonic"]) != run.started_monotonic_us
        or values["ControlGroup"] not in {CGROUP, ""}
        or values["StatusText"] != "KAKAO_GATEWAY_STARTED:" + gateway_execution_digest(run.grant)
    ):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_RUN_MISMATCH")


def _closed(
    grant: GatewayLeaseGrant, dispatched_boot_id: str, values: dict[str, str]
) -> ClosedGatewayDispatch:
    _trusted(values)
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", dispatched_boot_id) is None:
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_BOOT_UNKNOWN")
    if (
        values["Job"]
        or values["ActiveState"] not in {"inactive", "failed"}
        or values["SubState"] not in {"dead", "failed"}
        or values["MainPID"] != "0"
        or values["ControlPID"] != "0"
        or values["ControlGroup"] not in {"", CGROUP}
        or (
            values["InvocationID"] and re.fullmatch(r"[0-9a-f]{32}", values["InvocationID"]) is None
        )
    ):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_STOP_UNCONFIRMED")
    return ClosedGatewayDispatch(
        grant,
        dispatched_boot_id,
        _boot_id(),
        datetime.now(UTC),
        _cgroup_closed(),
        values["InvocationID"],
        int(values["ExecMainStartTimestampMonotonic"]),
        values["Result"],
        int(values["ExecMainCode"]),
        int(values["ExecMainStatus"]),
    )


def _browser_ready(
    grant: GatewayLeaseGrant,
    browser: BrowserRunHandle,
    observe_browser: Callable[[ProfileFence], BrowserRunHandle],
) -> None:
    if (
        browser.fence.mode != "MANUAL"
        or browser.fence.profile_id != grant.profile_id
        or browser.fence.fence_epoch != grant.fence_epoch
        or browser.cgroup != BROWSER_CGROUP
        or observe_browser(browser.fence) != browser
    ):
        raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_BROWSER_MISMATCH")
    # Only the gateway UID can connect to VNC. Its notify readiness also checks the
    # actual VNC peer UID and fixed browser cgroup; Catalog does not gain that access.


@dataclass(frozen=True, slots=True)
class FixedKakaoGatewayRuntime:
    template_sha256: str
    supervisor_sha256: str

    def _installed(self) -> None:
        try:
            require_native_exam_runtime_python(PYTHON)
            for path, digest, maximum in (
                (TEMPLATE, self.template_sha256, 16384),
                (SUPERVISOR, self.supervisor_sha256, 65536),
            ):
                if (
                    re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                    or "sha256:"
                    + hashlib.sha256(
                        _read(path, uid=0, maximum=maximum, owners=frozenset({0}))
                    ).hexdigest()
                    != digest
                ):
                    raise ValueError
        except (OSError, ValueError, KeyError):
            raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_RUNTIME_UNAVAILABLE") from None

    def boot_identity(self) -> str:
        return _boot_id()

    def observe_idle(self) -> runtime_os.IdleRuntimeObservation:
        """No grant/run required for initial inventory; never authorizes a start by itself."""
        with _control_lock():
            self._installed()
            values = _show()
            _trusted(values)
            if (
                values["Job"]
                or values["ActiveState"] != "inactive"
                or values["SubState"] != "dead"
                or values["MainPID"] != "0"
                or values["ControlPID"] != "0"
                or values["ControlGroup"] not in {"", CGROUP}
            ):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_IDLE_UNCONFIRMED")
            closed = _cgroup_closed()
            never_dispatched = (
                not _has_grant_history()
                and values["ExecMainStartTimestampMonotonic"] == "0"
                and values["ExecMainPID"] == "0"
                and not values["InvocationID"]
                and not values["StatusText"]
            )
            return runtime_os.IdleRuntimeObservation(
                UNIT, _boot_id(), datetime.now(UTC), closed, never_dispatched
            )

    def observe_dispatch(
        self, grant: GatewayLeaseGrant, *, dispatched_boot_id: str
    ) -> GatewayRunHandle | ClosedGatewayDispatch:
        with _control_lock():
            self._installed()
            current = _current()
            _matches(current, grant)
            values = _show()
            if values["ActiveState"] == "active":
                if _boot_id() != dispatched_boot_id or not isinstance(current, GatewayLeaseGrant):
                    raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_RUN_MISMATCH")
                return _running(current, values)
            return _closed(grant, dispatched_boot_id, values)

    def start(
        self,
        grant: GatewayLeaseGrant,
        browser: BrowserRunHandle,
        *,
        prior: ClosedGatewayDispatch | None,
        assert_current: Callable[[GatewayLeaseGrant], None],
        observe_browser: Callable[[ProfileFence], BrowserRunHandle],
    ) -> GatewayRunHandle:
        with _control_lock():
            self._installed()
            values = _show()
            if prior is None:
                _closed(grant, _boot_id(), values)
                try:
                    _current()
                except FileNotFoundError:
                    pass
                else:
                    raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_PRIOR_REQUIRED")
                if _has_grant_history() or values["ExecMainStartTimestampMonotonic"] != "0":
                    raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_PRIOR_REQUIRED")
                expected = None
            else:
                expected = _current()
                _matches(expected, prior.grant)
                prior = _closed(prior.grant, prior.dispatched_boot_id, values)
                if (
                    grant.profile_id != prior.grant.profile_id
                    or grant.lease_id == prior.grant.lease_id
                    or grant.gateway_epoch <= prior.grant.gateway_epoch
                    or grant.fence_epoch < prior.grant.fence_epoch
                ):
                    raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_FENCE_MISMATCH")
            _browser_ready(grant, browser, observe_browser)
            assert_current(grant)
            if not grant.authorized_at <= datetime.now(UTC) < grant.expires_at:
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_EXPIRED")
            _publish(grant, expected=expected)
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
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_START_UNCERTAIN") from None
            started = _running(grant, _show())
            if prior is not None and (
                started.invocation_id == prior.invocation_id
                or started.started_monotonic_us <= prior.started_monotonic_us
            ):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_START_UNCONFIRMED")
            return started

    def renew(
        self,
        run: GatewayRunHandle,
        grant: GatewayLeaseGrant,
        browser: BrowserRunHandle,
        *,
        assert_current: Callable[[GatewayLeaseGrant], None],
        observe_browser: Callable[[ProfileFence], BrowserRunHandle],
    ) -> None:
        with _control_lock():
            self._installed()
            values = _show()
            _same_execution(run, values)
            _running(run.grant, values)
            current = _current()
            _matches(current, run.grant)
            _matches(grant, run.grant)
            if not isinstance(current, GatewayLeaseGrant):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_REVOKED")
            now = datetime.now(UTC)
            if (
                not current.authorized_at <= now < current.expires_at
                or not grant.authorized_at <= now < grant.expires_at
                or (
                    grant != current
                    and (
                        grant.grant_revision <= current.grant_revision
                        or grant.authorized_at < current.authorized_at
                        or grant.expires_at < current.expires_at
                    )
                )
            ):
                raise KakaoGatewayRuntimeError("KAKAO_GATEWAY_GRANT_STALE")
            _browser_ready(grant, browser, observe_browser)
            assert_current(grant)
            _publish(grant, expected=current)

    def stop(self, run: GatewayRunHandle, revocation: GatewayRevocation) -> ClosedGatewayDispatch:
        with _control_lock():
            self._installed()
            values = _show()
            _same_execution(run, values)
            _matches(revocation, run.grant)
            current = _current()
            _matches(current, run.grant)
            _publish(revocation, expected=current)
            if values["ActiveState"] not in {"inactive", "failed"} or values["Job"]:
                with suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run(
                        ["/usr/bin/systemctl", "--no-ask-password", "stop", UNIT],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=5,
                    )
                values = _show()
                _same_execution(run, values)
            return _closed(run.grant, run.boot_id, values)

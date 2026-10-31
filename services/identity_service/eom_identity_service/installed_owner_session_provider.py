"""Actual fixed API process/config/key-metadata observation; never a capture or grant."""

from __future__ import annotations

import fcntl
import hashlib
import os
import pwd
import re
import socket
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_operator_identity.owner_session_capture_v11 import OwnerSessionCaptureRequestV11

from eom_identity_service.authenticated_session_fence import AuthenticatedOperatorSession
from eom_identity_service.owner_session_transport import (
    FixedIdentityProviderPin,
    OwnerSessionTransportError,
    _api_unix_socket_epoch,
    _observe_owner_session_transport,
    import_owner_session_capture,
)

_API_PREFIX = Path("/srv/eom/conda/envs/eom-api/lib/python3.12/site-packages")
_CONFIG = Path("/etc/eom-api/api.yaml")
_SECRET = Path("/etc/eom/secrets/api.env")
_CODE_MEMBERS = frozenset(
    {
        "eom_api/routers/owner_session_capture.py",
        "eom_api/lifespan.py",
        "eom_api/settings.py",
        "eom_api/dependencies.py",
        "eom_api/request_context.py",
        "eom_api/services/reference_query_prepare_client.py",
        "eom_identity_service/tokens.py",
        "eom_identity_service/auth_service.py",
        "eom_identity_service/authenticated_session_fence.py",
        "eom_identity_service/owner_session_transport.py",
        "eom_operator_identity/owner_session_capture.py",
        "eom_operator_identity/owner_session_capture_v11.py",
    }
)
_UNIT_PROPERTIES = frozenset(
    {
        "MainPID",
        "InvocationID",
        "User",
        "ActiveState",
        "FragmentPath",
        "DropInPaths",
        "ExecMainStartTimestamp",
    }
)
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}


def _failure() -> OwnerSessionTransportError:
    return OwnerSessionTransportError("OWNER_SESSION_PROVIDER_UNAVAILABLE")


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _raw(descriptor: int, maximum: int) -> bytes:
    """Only bounded pread; secret O_PATH descriptors are never passed here."""
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
        raise _failure()
    raw = os.pread(descriptor, maximum + 1, 0)
    if len(raw) > maximum or _epoch(os.fstat(descriptor)) != _epoch(before):
        raise _failure()
    return raw


@dataclass(frozen=True, slots=True)
class HeldIdentityProviderFile:
    """Fixed local file witness, not independent identity/lifecycle or permission."""

    path: Path
    descriptor: int
    parent_descriptor: int
    epoch: tuple[int, ...]
    parent_epoch: tuple[int, ...]
    sha256: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise _failure()
        if any(type(fd) is not int or fd < 3 for fd in (self.descriptor, self.parent_descriptor)):
            raise _failure()
        for epoch in (self.epoch, self.parent_epoch):
            if len(epoch) != 9 or any(type(value) is not int or value < 0 for value in epoch):
                raise _failure()
        if self.sha256 is not None and (
            type(self.sha256) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.sha256) is None
        ):
            raise _failure()


@dataclass(frozen=True, slots=True)
class InstalledIdentityProviderObservation:
    """Trusted composition values only; these data cannot mint session authority."""

    pin: FixedIdentityProviderPin
    pid: int
    start_ticks: int
    invocation_id: str
    process_descriptor: int
    configuration: HeldIdentityProviderFile
    key_metadata: HeldIdentityProviderFile
    code: tuple[HeldIdentityProviderFile, ...]

    def __post_init__(self) -> None:
        if (
            type(self.pin) is not FixedIdentityProviderPin
            or type(self.pid) is not int
            or self.pid < 2
            or type(self.start_ticks) is not int
            or self.start_ticks < 1
            or type(self.process_descriptor) is not int
            or self.process_descriptor < 3
            or type(self.invocation_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", self.invocation_id) is None
            or self.configuration.path != _CONFIG
            or self.configuration.sha256 != self.pin.configuration_sha256
            or self.key_metadata.path != _SECRET
            or self.key_metadata.sha256 is not None
            or {value.path for value in self.code} != {_API_PREFIX / name for name in _CODE_MEMBERS}
            or len(self.code) != len(_CODE_MEMBERS)
        ):
            raise _failure()
        self.pin.__post_init__()
        values = (self.configuration, self.key_metadata, *self.code)
        descriptors = (self.process_descriptor, *(v.descriptor for v in values))
        if len(set(descriptors)) != len(descriptors):
            raise _failure()
        for value in values:
            if type(value) is not HeldIdentityProviderFile:
                raise _failure()
            value.__post_init__()
        if any(value.sha256 is None for value in self.code):
            raise _failure()


def _unit() -> dict[str, str]:
    response = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-pager",
            "show",
            "eom-api.service",
            *("--property=" + name for name in sorted(_UNIT_PROPERTIES)),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=2,
        env=_ENV,
    )
    if response.returncode or response.stderr or len(response.stdout) > 8192:
        raise _failure()
    result: dict[str, str] = {}
    for line in response.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in _UNIT_PROPERTIES or key in result:
            raise _failure()
        result[key] = value
    if set(result) != _UNIT_PROPERTIES:
        raise _failure()
    return result


class ProtectedInstalledIdentityProviderAdmission:
    """No root/key access or provider default. Recheck actual owned handles and peer lifetime."""

    def __init__(self, observation: InstalledIdentityProviderObservation) -> None:
        if type(observation) is not InstalledIdentityProviderObservation:
            raise _failure()
        observation.__post_init__()
        self.observation = observation

    def _assert_catalog_api_peer(self, connection: socket.socket) -> None:
        """Physical binding; the shared transport has just fenced current provider bytes."""
        observed = self.observation
        try:
            epoch = _api_unix_socket_epoch(connection)
            api = pwd.getpwnam("eom-api")
            if epoch[-3:] != (observed.pid, api.pw_uid, api.pw_gid):
                raise _failure()
        except Exception:
            raise _failure() from None

    def capture_catalog_request(
        self,
        *,
        request: OwnerSessionCaptureRequestV11,
        response_raw: bytes,
        connection: socket.socket,
        started_at: datetime,
        deadline: float,
    ) -> AuthenticatedOperatorSession:
        """Consume a current installed peer's exact QUERY capture; never a DTO-only mint."""
        try:
            checked = OwnerSessionCaptureRequestV11.model_validate(request)
            if checked.purpose != "REFERENCE_QUERY":
                raise _failure()
            observation = _observe_owner_session_transport(
                request=checked,
                response_raw=response_raw,
                connection=connection,
                pin=self.observation.pin,
                admission=self,
                verify_peer=self._assert_catalog_api_peer,
                started_at=started_at,
                deadline=deadline,
                epoch_reader=_api_unix_socket_epoch,
            )
            return import_owner_session_capture(observation)
        except OwnerSessionTransportError:
            raise
        except Exception:
            raise _failure() from None

    def assert_current(
        self, *, source_commit: str, wheel_sha256: str, configuration_sha256: str
    ) -> None:
        try:
            observed = self.observation
            observed.__post_init__()
            if (source_commit, wheel_sha256, configuration_sha256) != (
                observed.pin.source_commit,
                observed.pin.wheel_sha256,
                observed.pin.configuration_sha256,
            ):
                raise _failure()
            api = pwd.getpwnam("eom-api")
            current = _unit()
            properties = dict(current)
            started = datetime.strptime(
                properties.pop("ExecMainStartTimestamp"), "%a %Y-%m-%d %H:%M:%S UTC"
            ).replace(tzinfo=UTC)
            # systemd display is second-resolution; changes at/after that second
            # cannot establish bytes/config loaded by the earlier API process.
            started_ns = int(started.timestamp()) * 1_000_000_000
            if properties != {
                "MainPID": str(observed.pid),
                "InvocationID": observed.invocation_id,
                "User": "eom-api",
                "ActiveState": "active",
                "FragmentPath": "/etc/systemd/system/eom-api.service",
                "DropInPaths": "",
            }:
                raise _failure()
            if any(
                value.epoch[7] >= started_ns or value.epoch[8] >= started_ns
                for value in (observed.configuration, observed.key_metadata, *observed.code)
            ):
                raise _failure()
            process = observed.process_descriptor
            if (
                os.readlink(f"/proc/self/fd/{process}") != f"/proc/{observed.pid}/stat"
                or os.fstat(process).st_uid != api.pw_uid
                or fcntl.fcntl(process, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
            ):
                raise _failure()
            raw = _raw(process, 4096).decode("ascii")
            fields = raw[raw.rindex(")") + 2 :].split()
            if raw.split(" ", 1)[0] != str(observed.pid) or int(fields[19]) != observed.start_ticks:
                raise _failure()
            self._file(observed.configuration, api.pw_gid, kind="CONFIGURATION")
            self._file(observed.key_metadata, api.pw_gid, kind="KEY_METADATA")
            for value in observed.code:
                self._file(value, api.pw_gid, kind="CODE")
            if _unit() != current:
                raise _failure()
        except Exception:
            raise _failure() from None

    @staticmethod
    def _file(
        value: HeldIdentityProviderFile,
        api_gid: int,
        *,
        kind: Literal["CONFIGURATION", "KEY_METADATA", "CODE"],
    ) -> None:
        before = os.fstat(value.descriptor)
        parent = os.fstat(value.parent_descriptor)
        flags = fcntl.fcntl(value.descriptor, fcntl.F_GETFL)
        if (
            _epoch(before) != value.epoch
            # Folder timestamps/size describe siblings, not this pinned member.
            # Keep named + held directory identity, ownership and permissions;
            # the member itself retains its full epoch and byte hash below.
            or _epoch(parent)[:5] != value.parent_epoch[:5]
            or _epoch(value.path.parent.lstat())[:5] != value.parent_epoch[:5]
            or _epoch(value.path.lstat()) != value.epoch
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or not stat.S_ISDIR(parent.st_mode)
            or parent.st_mode & 0o022
            or os.readlink(f"/proc/self/fd/{value.descriptor}") != str(value.path)
            or os.readlink(f"/proc/self/fd/{value.parent_descriptor}") != str(value.path.parent)
        ):
            raise _failure()
        if kind == "KEY_METADATA":
            if (
                not flags & os.O_PATH
                or value.sha256 is not None
                or before.st_uid != 0
                or parent.st_uid != 0
                or before.st_gid != api_gid
                or stat.S_IMODE(before.st_mode) not in (0o600, 0o640)
            ):
                raise _failure()
            return
        if flags & os.O_PATH or flags & os.O_ACCMODE != os.O_RDONLY:
            raise _failure()
        owners = {0, pwd.getpwnam("eom").pw_uid} if kind == "CODE" else {0}
        modes = (0o644,) if kind == "CODE" else (0o640, 0o644)
        if (
            before.st_uid not in owners
            or parent.st_uid not in owners
            or stat.S_IMODE(before.st_mode) not in modes
            or (kind == "CONFIGURATION" and before.st_gid != api_gid)
        ):
            raise _failure()
        raw = _raw(value.descriptor, 1024 * 1024)
        if value.sha256 != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise _failure()


@contextmanager
def open_installed_identity_provider_observation(
    pin: FixedIdentityProviderPin,
    *,
    code_sha256: tuple[tuple[str, str], ...],
) -> Iterator[InstalledIdentityProviderObservation]:
    """Trusted root composition opens fixed read-only/O_PATH handles, never key bytes.

    Caller passes independently reviewed wheel-member pins, not self-hashed
    installed code. The root parent retains this scope until its controller
    operation exits. No worker/model input or serializable authority is accepted.
    """
    descriptors: list[int] = []
    entered = False
    try:
        if (
            os.geteuid() != 0
            or type(pin) is not FixedIdentityProviderPin
            or not isinstance(code_sha256, tuple)
            or len(code_sha256) != len(_CODE_MEMBERS)
        ):
            raise _failure()
        pin.__post_init__()
        pins = dict(code_sha256)
        if set(pins) != _CODE_MEMBERS or len(pins) != len(code_sha256):
            raise _failure()
        current = _unit()
        pid = int(current["MainPID"])
        if pid < 2:
            raise _failure()

        def hold(path: Path, expected: str | None) -> HeldIdentityProviderFile:
            parent = os.open(path.parent, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            descriptors.append(parent)
            descriptor = os.open(
                path,
                (os.O_PATH if expected is None else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            descriptors.append(descriptor)
            return HeldIdentityProviderFile(
                path,
                descriptor,
                parent,
                _epoch(os.fstat(descriptor)),
                _epoch(os.fstat(parent)),
                expected,
            )

        process = os.open(f"/proc/{pid}/stat", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(process)
        raw = _raw(process, 4096).decode("ascii")
        ticks = int(raw[raw.rindex(")") + 2 :].split()[19])
        observation = InstalledIdentityProviderObservation(
            pin,
            pid,
            ticks,
            current["InvocationID"],
            process,
            hold(_CONFIG, pin.configuration_sha256),
            hold(_SECRET, None),
            tuple(hold(_API_PREFIX / name, pins[name]) for name in sorted(pins)),
        )
        ProtectedInstalledIdentityProviderAdmission(observation).assert_current(
            source_commit=pin.source_commit,
            wheel_sha256=pin.wheel_sha256,
            configuration_sha256=pin.configuration_sha256,
        )
        entered = True
        yield observation
    except OwnerSessionTransportError:
        raise
    except Exception:
        # The consumer owns authentication/source/execution failures after entry;
        # do not relabel them as provider-installation failure during cleanup.
        if entered:
            raise
        raise _failure() from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def identity_provider_code_members() -> tuple[str, ...]:
    """Fixed review inventory for trusted wheel materialization, not request selection."""
    return tuple(sorted(_CODE_MEMBERS))

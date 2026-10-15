"""Observe one actual root-managed indexing owner; metadata/UID alone never admit it.

This adapter reads no credential and launches/installs nothing. The fixed entrypoint
and service must already exist in an independently approved immutable owner release.
"""

from __future__ import annotations

import hashlib
import io
import os
import pwd
import re
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eom_operator_identity import (
    LocalIndexingRuntimeConfiguration,
    LocalIndexingServiceReference,
    local_indexing_service_bytes,
    parse_local_indexing_runtime_configuration,
    parse_local_indexing_service_reference,
)

_UNIT_NAME = "eom-embedding-index-owner.service"
_UNIT_PATH = Path("/etc/systemd/system") / _UNIT_NAME
_CONFIG_PATH = Path("/etc/eom/local-indexing-runtime.json")
_OWNER_SELECTION_PATH = Path("/etc/eom/local-indexing-owner.json")
_RELEASES = Path("/opt/eom/embedding-owner-releases")
_PREFIX = Path("/opt/eom/conda/envs/eom-embedding-experiment")
_ENTRY = "eom_workflow_runner/local_indexing_service_entry.py"
_ROOT_UID = 0
_RUNTIME_USER = "eom-workflow-runner"
_PROPERTIES = frozenset(
    {
        "MainPID",
        "ExecMainPID",
        "InvocationID",
        "User",
        "ActiveState",
        "FragmentPath",
        "DropInPaths",
        "ControlGroup",
        "ExecMainStartTimestamp",
    }
)
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C", "TZ": "UTC"}
_SEAL = object()


class IndexingRuntimeAdmissionError(ValueError):
    def __init__(
        self, code: Literal["LOCAL_INDEXING_RUNTIME_UNAVAILABLE", "LOCAL_INDEXING_RUNTIME_CHANGED"]
    ) -> None:
        self.code = code
        super().__init__(code)


def _unavailable() -> IndexingRuntimeAdmissionError:
    return IndexingRuntimeAdmissionError("LOCAL_INDEXING_RUNTIME_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class LocalIndexingRuntimePin:
    """Independently selected released-control pointers, not model-supplied authority."""

    service: LocalIndexingServiceReference
    runtime_source_commit: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        checked = parse_local_indexing_service_reference(local_indexing_service_bytes(self.service))
        if (
            type(self.runtime_source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.runtime_source_commit) is None
            or type(self.configuration_sha256) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.configuration_sha256) is None
        ):
            raise _unavailable()
        object.__setattr__(self, "service", checked)


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


class _ProtectedFiles:
    """One-capture bounded materialization and immutable file/directory epochs."""

    def __init__(self, started_ns: int) -> None:
        self.started_ns = started_ns
        self.epochs: dict[Path, tuple[int, ...]] = {}

    def observe(self, path: Path, *, directory: bool = False) -> os.stat_result:
        value = path.lstat()
        if (
            path.is_symlink()
            or value.st_uid != _ROOT_UID
            or value.st_mode & 0o022
            or (not stat.S_ISDIR(value.st_mode) if directory else not stat.S_ISREG(value.st_mode))
            or (not directory and value.st_nlink != 1)
            or max(value.st_mtime_ns, value.st_ctime_ns) > self.started_ns
        ):
            raise _unavailable()
        current = _epoch(value)
        if path in self.epochs and self.epochs[path] != current:
            raise _unavailable()
        self.epochs[path] = current
        return value

    def ancestors(self, path: Path) -> None:
        self.ancestors_many((path,))

    def ancestors_many(self, paths: tuple[Path, ...]) -> None:
        # Deduplicate path names only within this observation, never filesystem
        # attributes or authority across fences. Shared parents remain rechecked.
        parents: dict[Path, None] = {}
        for path in paths:
            if not path.is_absolute() or ".." in path.parts:
                raise _unavailable()
            for parent in reversed(path.parents):
                parents[parent] = None
        for parent in parents:
            # Ancestor directory contents need not be immutable: /etc and /opt
            # can receive unrelated releases. Their ownership/mode still must be safe.
            value = parent.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or parent.is_symlink()
                or (value.st_uid != _ROOT_UID or value.st_mode & 0o022)
            ):
                raise _unavailable()

    def read(self, path: Path, *, maximum: int, expected_sha256: str | None = None) -> bytes:
        self.ancestors(path)
        before = self.observe(path)
        if not 0 <= before.st_size <= maximum:
            raise _unavailable()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            if _epoch(os.fstat(descriptor)) != _epoch(before):
                raise _unavailable()
            raw = os.pread(descriptor, maximum + 1, 0)
            if len(raw) != before.st_size or _epoch(os.fstat(descriptor)) != _epoch(before):
                raise _unavailable()
        finally:
            os.close(descriptor)
        self.observe(path)
        if (
            expected_sha256 is not None
            and "sha256:" + hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise _unavailable()
        return raw

    def assert_current(self) -> None:
        captured = tuple(self.epochs.items())
        self.ancestors_many(tuple(path for path, _expected in captured))
        for path, expected in captured:
            if _epoch(path.lstat()) != expected:
                raise _unavailable()


def _unit() -> dict[str, str]:
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "--no-pager",
            "show",
            _UNIT_NAME,
            *("--property=" + name for name in sorted(_PROPERTIES)),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=2,
        env=_ENV,
    )
    if result.returncode or result.stderr or len(result.stdout) > 8192:
        raise _unavailable()
    values: dict[str, str] = {}
    for line in result.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in _PROPERTIES or key in values:
            raise _unavailable()
        values[key] = value
    if set(values) != _PROPERTIES:
        raise _unavailable()
    return values


def _live(path: Path, maximum: int) -> str:
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise _unavailable()
    return raw.decode("ascii").strip()


def _executable() -> Path:
    return Path("/proc/self/exe").resolve(strict=True)


def _self_unit() -> tuple[dict[str, str], int]:
    user = pwd.getpwnam(_RUNTIME_USER)
    if (
        os.getuid() != user.pw_uid
        or os.geteuid() != user.pw_uid
        or (not sys.flags.isolated or not sys.dont_write_bytecode)
    ):
        raise _unavailable()
    current = _unit()
    if (
        current["User"] != _RUNTIME_USER
        or current["ActiveState"] != "active"
        or current["MainPID"] != str(os.getpid())
        or current["ExecMainPID"] != str(os.getpid())
        or current["FragmentPath"] != str(_UNIT_PATH)
        or current["DropInPaths"]
        or current["ControlGroup"] != "/system.slice/" + _UNIT_NAME
        or re.fullmatch(r"[0-9a-f]{32}", current["InvocationID"]) is None
        or _live(Path("/proc/self/cgroup"), 8192) != "0::" + current["ControlGroup"]
    ):
        raise _unavailable()
    started = datetime.strptime(
        current["ExecMainStartTimestamp"], "%a %Y-%m-%d %H:%M:%S UTC"
    ).replace(tzinfo=UTC)
    return current, int(started.timestamp()) * 1_000_000_000


def _wheel_members(
    files: _ProtectedFiles, wheel: Path, sha256: str, site: Path, seen: set[str]
) -> tuple[set[str], set[str]]:
    raw = files.read(wheel, maximum=64 * 1024**2, expected_sha256=sha256)
    members: set[str] = set()
    roots: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= 20_000 or sum(info.file_size for info in infos) > 128 * 1024**2:
            raise _unavailable()
        names: set[str] = set()
        for info in infos:
            name, parts = info.filename, info.filename.split("/")
            if (
                name in names
                or name.startswith("/")
                or any(p in ("", ".", "..") for p in parts)
                or "\\" in name
                or any(ord(char) < 32 for char in name)
                or info.is_dir()
                or ((info.external_attr >> 16) and not stat.S_ISREG(info.external_attr >> 16))
                or info.flag_bits & 1
                or info.file_size > 64 * 1024**2
            ):
                raise _unavailable()
            names.add(name)
            # pip's dist-info installation records have a separate lifecycle.
            # All executable EOM namespaces/resources remain closed and byte-exact.
            if not parts[0].startswith("eom_") or ".dist-info" in parts[0]:
                continue
            if name in seen:
                raise _unavailable()
            seen.add(name)
            target = site / name
            if files.read(target, maximum=64 * 1024**2) != archive.read(info):
                raise _unavailable()
            members.add(name)
            roots.add(parts[0])
    return members, roots


def _closed_namespaces(
    files: _ProtectedFiles, site: Path, roots: set[str], expected: set[str]
) -> None:
    actual: set[str] = set()
    for root in sorted(roots):
        directory = site / root
        files.observe(directory, directory=True)
        for path in directory.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                files.observe(path, directory=True)
            else:
                files.observe(path)
                actual.add(path.relative_to(site).as_posix())
    if actual != expected:
        raise _unavailable()


def _loaded_code(files: _ProtectedFiles, site: Path, members: set[str]) -> None:
    external: dict[Path, None] = {}
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        source = getattr(module, "__file__", None)
        if not isinstance(source, str):
            if name.startswith("eom_"):
                raise _unavailable()
            continue
        path = Path(source)
        if path.is_relative_to(site) and path.relative_to(site).as_posix() in members:
            continue
        if (
            name.startswith("eom_")
            and name != "eom_gpu_lease"
            and not name.startswith("eom_gpu_lease.")
        ):
            raise _unavailable()
        if not path.is_relative_to(_PREFIX):
            raise _unavailable()
        external[path] = None
    files.ancestors_many(tuple(external))
    for path in external:
        files.observe(path)


class AuthenticatedLocalIndexingRuntime:
    """Current same-process installed-unit capture, never serializable data authority.

    A DB fence and the separately released Catalog grant remain mandatory.
    """

    __slots__ = (
        "_boot",
        "_closed",
        "_config",
        "_files",
        "_members",
        "_pid",
        "_pin",
        "_site",
        "_unit",
    )

    def __init__(
        self,
        seal: object,
        pin: LocalIndexingRuntimePin,
        config: LocalIndexingRuntimeConfiguration,
        files: _ProtectedFiles,
        unit: dict[str, str],
        boot: str,
        site: Path,
        members: set[str],
    ) -> None:
        if seal is not _SEAL:
            raise _unavailable()
        self._pin, self._config, self._files, self._unit = pin, config, files, unit
        self._boot, self._pid, self._site = boot, os.getpid(), site
        self._members, self._closed = frozenset(members), False

    def __reduce__(self) -> Any:
        raise TypeError("indexing runtime capture cannot be serialized or transferred")

    def close(self) -> None:
        self._closed = True

    def read_owner_configuration(self) -> bytes:
        """Bind one fixed non-secret root selection to this actual process epoch.

        This is neither an arbitrary-file reader nor data authority. The Catalog
        grant pins the separate runtime configuration; owner selections are kept
        outside that hash cycle and every request records their exact control pins.
        """
        try:
            pin = self._pin
            self.assert_current(
                service=pin.service,
                runtime_source_commit=pin.runtime_source_commit,
                configuration_sha256=pin.configuration_sha256,
            )
            raw = self._files.read(_OWNER_SELECTION_PATH, maximum=64 * 1024)
            self.assert_current(
                service=pin.service,
                runtime_source_commit=pin.runtime_source_commit,
                configuration_sha256=pin.configuration_sha256,
            )
            return raw
        except Exception:
            raise IndexingRuntimeAdmissionError("LOCAL_INDEXING_RUNTIME_CHANGED") from None

    def assert_current(
        self,
        *,
        service: LocalIndexingServiceReference,
        runtime_source_commit: str,
        configuration_sha256: str,
    ) -> None:
        try:
            expected = LocalIndexingRuntimePin(service, runtime_source_commit, configuration_sha256)
            current, _started = _self_unit()
            if (
                self._closed
                or os.getpid() != self._pid
                or expected != self._pin
                or current != self._unit
            ):
                raise _unavailable()
            if _live(Path("/proc/sys/kernel/random/boot_id"), 64) != self._boot:
                raise _unavailable()
            self._files.assert_current()
            _loaded_code(self._files, self._site, set(self._members))
            self._files.assert_current()
        except Exception:
            raise IndexingRuntimeAdmissionError("LOCAL_INDEXING_RUNTIME_CHANGED") from None


def capture_local_indexing_runtime(
    pin: LocalIndexingRuntimePin,
) -> AuthenticatedLocalIndexingRuntime:
    """Actual OS/unit/root-release checks; no descriptor, observation or flag input."""
    try:
        if type(pin) is not LocalIndexingRuntimePin:
            raise _unavailable()
        pin.__post_init__()
        unit, started_ns = _self_unit()
        files = _ProtectedFiles(started_ns)
        config = parse_local_indexing_runtime_configuration(
            files.read(_CONFIG_PATH, maximum=4096, expected_sha256=pin.configuration_sha256)
        )
        if (
            config.service != pin.service
            or config.runtime_source_commit != pin.runtime_source_commit
        ):
            raise _unavailable()
        files.read(_UNIT_PATH, maximum=64 * 1024, expected_sha256=config.unit_sha256)
        executable = _PREFIX / "bin/python3.12"
        if sys.executable not in (str(executable), str(_PREFIX / "bin/python")) or (
            _executable() != executable
        ):
            raise _unavailable()
        files.read(executable, maximum=64 * 1024**2, expected_sha256=config.interpreter_sha256)
        release = _RELEASES / pin.runtime_source_commit
        site = release / "site-packages"
        main = getattr(sys.modules.get("__main__"), "__file__", None)
        if main != str(site / _ENTRY) or sys.argv != [str(site / _ENTRY)]:
            raise _unavailable()
        seen: set[str] = set()
        roots: set[str] = set()
        for filename, expected in (
            ("eom_platform-0.1.0-py3-none-any.whl", config.platform_wheel_sha256),
            ("eom_api_contracts-0.1.0-py3-none-any.whl", config.api_contracts_wheel_sha256),
        ):
            _members, namespaces = _wheel_members(files, release / filename, expected, site, seen)
            roots.update(namespaces)
        if _ENTRY not in seen:
            raise _unavailable()
        _closed_namespaces(files, site, roots, seen)
        _loaded_code(files, site, seen)
        boot = _live(Path("/proc/sys/kernel/random/boot_id"), 64)
        if re.fullmatch(r"[0-9a-f-]{36}", boot) is None:
            raise _unavailable()
        capture = AuthenticatedLocalIndexingRuntime(
            _SEAL, pin, config, files, unit, boot, site, seen
        )
        capture.assert_current(
            service=pin.service,
            runtime_source_commit=pin.runtime_source_commit,
            configuration_sha256=pin.configuration_sha256,
        )
        return capture
    except Exception:
        raise _unavailable() from None

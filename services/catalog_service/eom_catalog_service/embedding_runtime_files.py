"""Protected numerical-runtime file snapshots: bounded initial bytes, then identity checks."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True, slots=True)
class FixedNativeEmbeddingProfile:
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"]
    prefix: Path
    worker_user: str
    supplementary_group: str | None


NATIVE_EMBEDDING_PROFILES = MappingProxyType(
    {
        "CPU_INDEX_FP32": FixedNativeEmbeddingProfile(
            "CPU_INDEX_FP32",
            Path("/opt/eom/conda/envs/eom-embedding-index-cpu"),
            "eom-embedding-index-cpu",
            None,
        ),
        "CUDA_INDEX_FP32": FixedNativeEmbeddingProfile(
            "CUDA_INDEX_FP32",
            Path("/opt/eom/conda/envs/eom-embedding-cuda"),
            "eom-embedding-cuda",
            "eom-gpu-lease",
        ),
    }
)


def fixed_native_embedding_profile(profile: str) -> FixedNativeEmbeddingProfile:
    """One stdlib-only closed installation/identity mapping; no availability selector."""
    if type(profile) is not str or profile not in NATIVE_EMBEDDING_PROFILES:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PROFILE_INVALID")
    return NATIVE_EMBEDDING_PROFILES[profile]


class InstalledRuntimeProofError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_runtime_proof(condition: bool, code: str) -> None:
    if not condition:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_" + code)


_require = require_runtime_proof


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


@dataclass(frozen=True, slots=True)
class RuntimeFileEpoch:
    path: Path
    identity: tuple[int, ...]
    ancestors: tuple[tuple[Path, tuple[int, ...]], ...]
    sha256: str

    def assert_unchanged(self) -> None:
        try:
            for path, initial in self.ancestors:
                _require(_directory_identity(path.lstat()) == initial, "ANCESTOR_CHANGED")
            _require(_identity(self.path.lstat()) == self.identity, "FILE_CHANGED")
        except OSError as exc:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_CHANGED") from exc


@dataclass(frozen=True, slots=True)
class ObservedRuntimeMemberBytes:
    """Actual bounded immutable bytes; not an expected pin or installation grant."""

    sha256: str
    size_bytes: int
    raw: bytes


@contextmanager
def _protected_open(
    path: Path, owner_uid: int
) -> Iterator[tuple[int, tuple[tuple[Path, tuple[int, ...]], ...]]]:
    _require(path.is_absolute() and ".." not in path.parts, "PATH_INVALID")
    descriptors: list[tuple[int, int | None, str, Path, tuple[int, ...]]] = []
    leaf = -1
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        for component in path.parent.parts:
            parent = descriptors[-1][0] if descriptors else None
            named = descriptors[-1][3] / component if descriptors else Path(component)
            descriptor = os.open(component, flags, dir_fd=parent)
            value = os.fstat(descriptor)
            descriptors.append((descriptor, parent, component, named, _directory_identity(value)))
            # Test surrogates use a non-root owner beneath sticky /tmp; production owner=0
            # has no writable-ancestor exception and all roots are fixed below /opt.
            test_sticky = (
                owner_uid != 0
                and named == Path("/tmp")
                and value.st_uid == 0
                and bool(value.st_mode & stat.S_ISVTX)
            )
            _require(
                value.st_uid in {0, owner_uid} and (not value.st_mode & 0o022 or test_sticky),
                "ANCESTOR_UNPROTECTED",
            )
        leaf = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=descriptors[-1][0],
        )
        value = os.fstat(leaf)
        _require(
            stat.S_ISREG(value.st_mode)
            and value.st_uid == owner_uid
            and value.st_nlink == 1
            and not value.st_mode & 0o6022,
            "FILE_UNPROTECTED",
        )
        ancestors = tuple((named, initial) for _fd, _parent, _name, named, initial in descriptors)
        yield leaf, ancestors
        _require(
            _identity(os.fstat(leaf))
            == _identity(os.stat(path.name, dir_fd=descriptors[-1][0], follow_symlinks=False)),
            "FILE_CHANGED",
        )
        for fd, parent, name, _named, initial in descriptors:
            _require(
                _directory_identity(os.fstat(fd)) == initial
                and _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                == initial,
                "ANCESTOR_CHANGED",
            )
    except OSError as exc:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_FILE_UNAVAILABLE") from exc
    finally:
        if leaf >= 0:
            os.close(leaf)
        for descriptor, *_rest in reversed(descriptors):
            os.close(descriptor)


class NumericalRuntimeFileSnapshots:
    """One admitted immutable runtime; deduplicate equal member references by exact path/SHA."""

    def __init__(self, owner_uid: int = 0) -> None:
        self.owner_uid = owner_uid
        self._epochs: dict[Path, RuntimeFileEpoch] = {}
        self._namespace_directories: dict[Path, tuple[int, ...]] = {}
        self._observations: dict[Path, ObservedRuntimeMemberBytes] = {}
        self._observation_bytes = 0

    def observe_protected_interpreter(self, path: Path) -> None:
        """Protect actual executable identity; full interpreter bytes belong to launch audit."""
        self.observe_protected_member_identity(path)

    def observe_protected_member_identity(self, path: Path) -> None:
        """Retain protected file/ancestor epochs without claiming or repeating a byte hash."""
        if path in self._epochs:
            self._epochs[path].assert_unchanged()
            return
        with _protected_open(path, self.owner_uid) as (descriptor, ancestors):
            epoch = RuntimeFileEpoch(path, _identity(os.fstat(descriptor)), ancestors, "")
        epoch.assert_unchanged()
        self._epochs[path] = epoch

    def observe_protected_member_bytes(
        self, path: Path, *, maximum: int
    ) -> ObservedRuntimeMemberBytes:
        """Capture small metadata once, retaining byte identity for one expected read."""
        _require(type(maximum) is int and 0 < maximum <= 8 * 1024**2, "OBSERVATION_INVALID")
        previous = self._epochs.get(path)
        if previous is not None:
            _require(previous.sha256 == "", "REPEATED_BYTE_READ")
            previous.assert_unchanged()
        with _protected_open(path, self.owner_uid) as (descriptor, ancestors):
            initial = os.fstat(descriptor)
            _require(
                0 <= initial.st_size <= maximum
                and self._observation_bytes + initial.st_size <= 16 * 1024**2,
                "FILE_SIZE_INVALID",
            )
            if previous is not None:
                _require(_identity(initial) == previous.identity, "FILE_CHANGED")
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            count = 0
            while chunk := os.pread(descriptor, min(65536, maximum + 1 - count), count):
                count += len(chunk)
                _require(count <= initial.st_size, "FILE_SIZE_INVALID")
                digest.update(chunk)
                chunks.append(chunk)
            _require(count == initial.st_size, "FILE_SIZE_INVALID")
            observed = ObservedRuntimeMemberBytes(
                "sha256:" + digest.hexdigest(), count, b"".join(chunks)
            )
            epoch = RuntimeFileEpoch(path, _identity(initial), ancestors, observed.sha256)
            _require(_identity(os.fstat(descriptor)) == epoch.identity, "FILE_CHANGED")
        epoch.assert_unchanged()
        self._epochs[path] = epoch
        self._observations[path] = observed
        self._observation_bytes += observed.size_bytes
        return observed

    def require_closed_namespaces(self, roots: set[Path], expected: set[Path]) -> None:
        observed: set[Path] = set()
        for root in roots:
            for parent, directories, names in os.walk(root, followlinks=False):
                directory = Path(parent)
                value = directory.lstat()
                _require(
                    stat.S_ISDIR(value.st_mode)
                    and value.st_uid == self.owner_uid
                    and not value.st_mode & 0o022,
                    "NAMESPACE_UNPROTECTED",
                )
                self._namespace_directories[directory] = _identity(value)
                for name in directories:
                    _require(not (directory / name).is_symlink(), "NAMESPACE_LINK")
                observed.update(directory / name for name in names)
        _require(observed == expected, "NAMESPACE_SET_MISMATCH")

    @contextmanager
    def verified_open(
        self,
        path: Path,
        *,
        sha256: str,
        maximum: int,
        size: int | None = None,
        retain_bytes: bool = False,
    ) -> Iterator[tuple[int, bytes]]:
        if path in self._observations:
            observed = self._observations[path]
            epoch = self._epochs[path]
            _require(
                observed.sha256 == sha256
                and 0 <= observed.size_bytes <= maximum
                and (size is None or observed.size_bytes == size),
                "DUPLICATE_REFERENCE_MISMATCH",
            )
            epoch.assert_unchanged()
            with _protected_open(path, self.owner_uid) as (descriptor, _ancestors):
                _require(_identity(os.fstat(descriptor)) == epoch.identity, "FILE_CHANGED")
                yield descriptor, observed.raw if retain_bytes else b""
                _require(_identity(os.fstat(descriptor)) == epoch.identity, "FILE_CHANGED")
            epoch.assert_unchanged()
            self._observation_bytes -= observed.size_bytes
            del self._observations[path]
            return
        _require(path not in self._epochs, "REPEATED_BYTE_READ")
        with _protected_open(path, self.owner_uid) as (descriptor, ancestors):
            initial = os.fstat(descriptor)
            _require(
                0 <= initial.st_size <= maximum and (size is None or initial.st_size == size),
                "FILE_SIZE_INVALID",
            )
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            count = 0
            while chunk := os.pread(descriptor, min(1024**2, maximum + 1 - count), count):
                count += len(chunk)
                _require(count <= maximum, "FILE_SIZE_INVALID")
                digest.update(chunk)
                if retain_bytes:
                    chunks.append(chunk)
            _require(
                count == initial.st_size and "sha256:" + digest.hexdigest() == sha256,
                "FILE_HASH_MISMATCH",
            )
            epoch = RuntimeFileEpoch(path, _identity(initial), ancestors, sha256)
            yield descriptor, b"".join(chunks)
            _require(_identity(os.fstat(descriptor)) == epoch.identity, "FILE_CHANGED")
        epoch.assert_unchanged()
        self._epochs[path] = epoch

    def verify(self, path: Path, *, sha256: str, size: int, maximum: int) -> None:
        if path in self._epochs:
            epoch = self._epochs[path]
            _require(
                epoch.sha256 == sha256 and epoch.identity[6] == size, "DUPLICATE_REFERENCE_MISMATCH"
            )
            epoch.assert_unchanged()
            return
        with self.verified_open(path, sha256=sha256, size=size, maximum=maximum):
            pass

    def read(self, path: Path, *, sha256: str, maximum: int, size: int | None = None) -> bytes:
        with self.verified_open(
            path, sha256=sha256, size=size, maximum=maximum, retain_bytes=True
        ) as (_descriptor, raw):
            return raw

    def assert_unchanged(self) -> None:
        for epoch in self._epochs.values():
            epoch.assert_unchanged()
        for path, initial in self._namespace_directories.items():
            _require(_identity(path.lstat()) == initial, "NAMESPACE_CHANGED")


def read_live_runtime_os_file(path: Path, *, maximum: int, owner_uid: int = 0) -> bytes:
    """Fixed kernel/proc observation: st_size may be zero; live bytes are never cached."""
    with _protected_open(path, owner_uid) as (descriptor, _ancestors):
        chunks: list[bytes] = []
        count = 0
        while chunk := os.read(descriptor, min(65536, maximum + 1 - count)):
            count += len(chunk)
            _require(count <= maximum, "OS_OBSERVATION_TOO_LARGE")
            chunks.append(chunk)
        _require(count > 0, "OS_OBSERVATION_EMPTY")
        return b"".join(chunks)

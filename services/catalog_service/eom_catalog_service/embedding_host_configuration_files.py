"""Resolve one owner-pinned immutable OS snapshot; never install, mount or grant it."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.embedding_host_configuration import (
    MAX_HOST_CONFIGURATION_BYTES,
    MAX_LOADER_CACHE_BYTES,
    EmbeddingHostConfigurationPointer,
    EmbeddingHostConfigurationSnapshot,
    parse_host_configuration_pointer,
    parse_host_configuration_snapshot_bytes,
    validate_host_configuration_pointer,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_host_closure import (
    FIXED_EMBEDDING_HOST_SEED_SHA256,
    embedding_host_configuration_seed,
    validate_embedding_loader_cache,
)

_ROOT = Path("/opt/eom/embedding-host-configurations")
_CACHE = Path("/etc/ld.so.cache")


class HostConfigurationSnapshotError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(value: bool, code: str) -> None:
    if not value:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_" + code)


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


def _read_only_member(path: Path, owner_uid: int) -> tuple[int, ...]:
    value = path.lstat()
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == owner_uid
        and stat.S_IMODE(value.st_mode) == 0o444
        and value.st_nlink == 1,
        "PERMISSION_INVALID",
    )
    _require(
        not {"system.posix_acl_access", "system.posix_acl_default"}.intersection(
            os.listxattr(path, follow_symlinks=False)
        ),
        "PERMISSION_INVALID",
    )
    return _identity(value)


def _file_error(error: InstalledRuntimeProofError) -> HostConfigurationSnapshotError:
    suffix = {
        "INSTALLED_RUNTIME_FILE_HASH_MISMATCH": "HASH_MISMATCH",
        "INSTALLED_RUNTIME_FILE_CHANGED": "CHANGED",
        "INSTALLED_RUNTIME_ANCESTOR_CHANGED": "CHANGED",
        "INSTALLED_RUNTIME_NAMESPACE_CHANGED": "CHANGED",
        "INSTALLED_RUNTIME_FILE_UNPROTECTED": "PERMISSION_INVALID",
        "INSTALLED_RUNTIME_ANCESTOR_UNPROTECTED": "PERMISSION_INVALID",
    }.get(error.code, "UNAVAILABLE")
    return HostConfigurationSnapshotError("HOST_CONFIGURATION_" + suffix)


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingHostConfiguration:
    pointer: EmbeddingHostConfigurationPointer
    snapshot: EmbeddingHostConfigurationSnapshot
    cache_path: Path
    cache_identity: tuple[int, ...]
    files: NumericalRuntimeFileSnapshots = field(repr=False, compare=False)

    def assert_unchanged(self) -> None:
        try:
            self.files.assert_unchanged()
            _require(
                _read_only_member(self.cache_path, self.files.owner_uid) == self.cache_identity,
                "CHANGED",
            )
        except InstalledRuntimeProofError as error:
            raise _file_error(error) from None
        except OSError:
            raise HostConfigurationSnapshotError("HOST_CONFIGURATION_UNAVAILABLE") from None


def resolve_host_configuration_snapshot(
    pointer: EmbeddingHostConfigurationPointer,
) -> ResolvedEmbeddingHostConfiguration:
    """Read at a fixed installation boundary; no live-cache fallback or source authority."""
    try:
        pointer = parse_host_configuration_pointer(pointer)
        root = _ROOT / pointer.configuration_id / pointer.configuration_revision_id
        files = NumericalRuntimeFileSnapshots(0)
        manifest = root / "snapshot.json"
        _read_only_member(manifest, files.owner_uid)
        raw = files.read(
            manifest,
            sha256=pointer.manifest_raw_sha256,
            size=pointer.manifest_byte_count,
            maximum=MAX_HOST_CONFIGURATION_BYTES,
        )
        snapshot = parse_host_configuration_snapshot_bytes(raw)
        validate_host_configuration_pointer(pointer, snapshot, raw)
        _require(
            snapshot.baseline_host_seed_sha256 == FIXED_EMBEDDING_HOST_SEED_SHA256
            and snapshot.host_seed_sha256
            == embedding_host_configuration_seed(
                cache_byte_count=snapshot.loader_cache.byte_count,
                cache_sha256=snapshot.loader_cache.sha256,
            ),
            "SEED_PIN_INVALID",
        )
        cache_path = root / snapshot.loader_cache.member_name
        cache_identity = _read_only_member(cache_path, files.owner_uid)
        cache = files.read(
            cache_path,
            sha256=snapshot.loader_cache.sha256,
            size=snapshot.loader_cache.byte_count,
            maximum=MAX_LOADER_CACHE_BYTES,
        )
        validate_embedding_loader_cache(cache)
        resolved = ResolvedEmbeddingHostConfiguration(
            pointer, snapshot, cache_path, cache_identity, files
        )
        resolved.assert_unchanged()
        return resolved
    except HostConfigurationSnapshotError:
        raise
    except InstalledRuntimeProofError as error:
        raise _file_error(error) from None
    except (ValueError, SchemaError, TypeError):
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_POINTER_INVALID") from None
    except FileNotFoundError:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_MISSING") from None
    except OSError:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_UNAVAILABLE") from None


def _mount_record(raw: bytes) -> tuple[int, int]:
    _require(type(raw) is bytes and 0 < len(raw) <= 1024**2, "MOUNT_INVALID")
    found: list[tuple[int, int]] = []
    for line in raw.decode("ascii", errors="strict").splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if len(fields) < 6 or fields[4] != str(_CACHE):
            continue
        _require(
            bool(separator)
            and len(after.split()) >= 3
            and fields[0].isdigit()
            and len(fields[0]) <= 10
            and fields[1].isdigit()
            and len(fields[1]) <= 10,
            "MOUNT_INVALID",
        )
        options = fields[5].split(",")
        _require("ro" in options and "rw" not in options, "MOUNT_INVALID")
        found.append((int(fields[0]), int(fields[1])))
    _require(len(found) == 1 and 0 < min(found[0]) <= max(found[0]) < 2**32, "MOUNT_INVALID")
    return found[0]


def _mount_namespace_identity() -> tuple[int, int]:
    current = os.stat("/proc/self/ns/mnt")
    return current.st_dev, current.st_ino


def _read_only_target_mount_id(resolved: ResolvedEmbeddingHostConfiguration) -> int:
    """Bounded own-FD kernel witness avoids reparsing all mounts on each recheck."""
    descriptor = os.open(_CACHE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        _require(_identity(os.fstat(descriptor)) == resolved.cache_identity, "MOUNT_INVALID")
        _require(bool(os.fstatvfs(descriptor).f_flag & os.ST_RDONLY), "MOUNT_INVALID")
        raw = read_live_runtime_os_file(
            Path("/proc") / str(os.getpid()) / "fdinfo" / str(descriptor),
            maximum=4096,
            owner_uid=os.geteuid(),
        )
        ids = [
            line.split(":", 1)[1].strip()
            for line in raw.decode("ascii").splitlines()
            if line.startswith("mnt_id:")
        ]
        _require(len(ids) == 1 and ids[0].isdigit() and len(ids[0]) <= 10, "MOUNT_INVALID")
        mount_id = int(ids[0])
        _require(0 < mount_id < 2**32, "MOUNT_INVALID")
        _require(
            _identity(os.fstat(descriptor)) == _identity(_CACHE.lstat()) == resolved.cache_identity,
            "MOUNT_CHANGED",
        )
        return mount_id
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class EmbeddingHostSnapshotMount:
    """Local kernel observation, not a serializable grant, lifecycle or mutable registry."""

    configuration: ResolvedEmbeddingHostConfiguration
    mount_id: int
    parent_mount_id: int
    namespace_identity: tuple[int, int]

    def assert_unchanged(self) -> None:
        try:
            self.configuration.assert_unchanged()
            _require(_mount_namespace_identity() == self.namespace_identity, "MOUNT_CHANGED")
            _require(
                _read_only_target_mount_id(self.configuration) == self.mount_id, "MOUNT_CHANGED"
            )
        except HostConfigurationSnapshotError:
            raise
        except (OSError, ValueError):
            raise HostConfigurationSnapshotError("HOST_CONFIGURATION_MOUNT_INVALID") from None


def require_host_configuration_snapshot_mount(
    resolved: ResolvedEmbeddingHostConfiguration,
) -> EmbeddingHostSnapshotMount:
    """Observe the exact pre-exec read-only binding; this function never creates a mount."""
    try:
        _require(type(resolved) is ResolvedEmbeddingHostConfiguration, "POINTER_INVALID")
        resolved.assert_unchanged()
        namespace = _mount_namespace_identity()
        actual_mount = _read_only_target_mount_id(resolved)
        raw = read_live_runtime_os_file(
            Path("/proc") / str(os.getpid()) / "mountinfo", maximum=1024**2, owner_uid=os.geteuid()
        )
        mount_id, parent = _mount_record(raw)
        _require(actual_mount == mount_id, "MOUNT_INVALID")
        resolved.files.observe_protected_member_identity(_CACHE)
        evidence = EmbeddingHostSnapshotMount(resolved, mount_id, parent, namespace)
        evidence.assert_unchanged()
        return evidence
    except HostConfigurationSnapshotError:
        raise
    except (OSError, ValueError):
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_MOUNT_INVALID") from None


def capture_snapshot_embedding_host(
    *,
    expected_seed_sha256: str,
    files: NumericalRuntimeFileSnapshots,
    snapshot_mount: EmbeddingHostSnapshotMount,
) -> host.ProtectedEmbeddingHostClosure:
    """Read exact mounted configuration through the same fixed-host capture implementation."""
    _require(type(snapshot_mount) is EmbeddingHostSnapshotMount, "MOUNT_INVALID")
    snapshot_mount.assert_unchanged()
    snapshot = snapshot_mount.configuration.snapshot
    _require(
        type(expected_seed_sha256) is str
        and snapshot.baseline_host_seed_sha256 == host.FIXED_EMBEDDING_HOST_SEED_SHA256
        and expected_seed_sha256
        == snapshot.host_seed_sha256
        == embedding_host_configuration_seed(
            cache_byte_count=snapshot.loader_cache.byte_count,
            cache_sha256=snapshot.loader_cache.sha256,
        ),
        "SEED_PIN_INVALID",
    )
    return host._capture_embedding_host(
        expected_seed_sha256=expected_seed_sha256,
        files=files,
        fixed_files=host._files_with_loader_cache(
            cache_byte_count=snapshot.loader_cache.byte_count,
            cache_sha256=snapshot.loader_cache.sha256,
        ),
        assert_mount_current=snapshot_mount.assert_unchanged,
    )

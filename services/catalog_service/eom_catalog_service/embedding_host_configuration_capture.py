"""Stdlib-only protected host configuration capture, shared by bootstrap and runtime.

This observes fixed installation files and kernel mounts; never installs or grants.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    read_live_runtime_os_file,
)

_ROOT = Path("/opt/eom/embedding-host-configurations")
_CACHE = Path("/etc/ld.so.cache")
_MAX_MANIFEST = 8192
_MAX_CACHE = 128 * 1024
_SELECTION_FIELDS = frozenset(
    {
        "schema_ref",
        "configuration_id",
        "configuration_revision_id",
        "manifest_byte_count",
        "manifest_raw_sha256",
        "snapshot_sha256",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "configuration_id",
        "configuration_revision_id",
        "captured_at",
        "baseline_host_seed_sha256",
        "host_seed_sha256",
        "loader_cache",
        "snapshot_sha256",
    }
)


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


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _reviewed_seed(*, baseline: str, cache_byte_count: int, cache_sha256: str) -> str:
    try:
        return host.reviewed_embedding_host_configuration_seed(
            baseline_host_seed_sha256=baseline,
            cache_byte_count=cache_byte_count,
            cache_sha256=cache_sha256,
        )
    except InstalledRuntimeProofError:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_SEED_PIN_INVALID") from None


@dataclass(frozen=True, slots=True)
class HostConfigurationSnapshotPin:
    """The existing six-field pointer before third-party packages can be trusted."""

    schema_ref: str
    configuration_id: str
    configuration_revision_id: str
    manifest_byte_count: int
    manifest_raw_sha256: str
    snapshot_sha256: str

    def __post_init__(self) -> None:
        _require(
            type(self.schema_ref) is str
            and self.schema_ref
            == "eom://schemas/knowledge/embedding-host-configuration-snapshot/1.0#/$defs/snapshot"
            and type(self.configuration_id) is str
            and re.fullmatch(r"embeddinghostconfig_[0-9a-f]{32}", self.configuration_id) is not None
            and type(self.configuration_revision_id) is str
            and re.fullmatch(r"embeddinghostconfigrev_[0-9a-f]{32}", self.configuration_revision_id)
            is not None
            and type(self.manifest_byte_count) is int
            and 0 < self.manifest_byte_count <= _MAX_MANIFEST
            and _sha(self.manifest_raw_sha256)
            and _sha(self.snapshot_sha256),
            "POINTER_INVALID",
        )


def parse_host_configuration_snapshot_pin(value: object) -> HostConfigurationSnapshotPin:
    _require(type(value) is dict and set(value) == _SELECTION_FIELDS, "POINTER_INVALID")
    assert isinstance(value, dict)
    return HostConfigurationSnapshotPin(**value)


class HostConfigurationFiles(Protocol):
    @property
    def cache_path(self) -> Path: ...
    @property
    def cache_identity(self) -> tuple[int, ...]: ...
    @property
    def files(self) -> NumericalRuntimeFileSnapshots: ...
    @property
    def host_seed_sha256(self) -> str: ...
    @property
    def baseline_host_seed_sha256(self) -> str: ...
    @property
    def cache_byte_count(self) -> int: ...
    @property
    def cache_sha256(self) -> str: ...
    def assert_unchanged(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CapturedHostConfiguration:
    selection: HostConfigurationSnapshotPin
    snapshot_raw: bytes = field(repr=False)
    baseline_host_seed_sha256: str
    host_seed_sha256: str
    cache_byte_count: int
    cache_sha256: str
    cache_path: Path
    cache_identity: tuple[int, ...]
    files: NumericalRuntimeFileSnapshots = field(repr=False, compare=False)

    def assert_unchanged(self) -> None:
        assert_host_configuration_files_current(self)


def assert_host_configuration_files_current(configuration: HostConfigurationFiles) -> None:
    try:
        configuration.files.assert_unchanged()
        _require(
            _read_only_member(configuration.cache_path, configuration.files.owner_uid)
            == configuration.cache_identity,
            "CHANGED",
        )
    except InstalledRuntimeProofError as error:
        raise _file_error(error) from None
    except OSError:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_UNAVAILABLE") from None


def _manifest_values(raw: bytes, pin: HostConfigurationSnapshotPin) -> tuple[str, str, int, str]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, value in pairs:
            _require(name not in values and len(values) < 8, "POINTER_INVALID")
            values[name] = value
        return values

    def reject(_value: str) -> Any:
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_POINTER_INVALID")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_float=reject, parse_constant=reject)
        _require(type(value) is dict and set(value) == _MANIFEST_FIELDS, "POINTER_INVALID")
        cache = value["loader_cache"]
        _require(
            type(cache) is dict
            and set(cache) == {"role", "member_name", "byte_count", "sha256"}
            and cache["role"] == "LD_SO_CACHE"
            and cache["member_name"] == "ld.so.cache"
            and type(cache["byte_count"]) is int
            and 48 <= cache["byte_count"] <= _MAX_CACHE
            and _sha(cache["sha256"]),
            "POINTER_INVALID",
        )
        stamp = value["captured_at"]
        _require(
            type(stamp) is str and 20 <= len(stamp) <= 27 and stamp.endswith("Z"), "POINTER_INVALID"
        )
        current = datetime.fromisoformat(stamp)
        _require(
            current.tzinfo is not None
            and current.utcoffset() == UTC.utcoffset(current)
            and current.isoformat().replace("+00:00", "Z") == stamp,
            "POINTER_INVALID",
        )
        baseline, seed = value["baseline_host_seed_sha256"], value["host_seed_sha256"]
        _require(
            value["schema_version"] == "embedding-host-configuration-snapshot/1.0"
            and value["configuration_id"] == pin.configuration_id
            and value["configuration_revision_id"] == pin.configuration_revision_id
            and _sha(baseline)
            and _sha(seed)
            and value["snapshot_sha256"] == pin.snapshot_sha256
            and _hash(
                _canonical({key: item for key, item in value.items() if key != "snapshot_sha256"})
            )
            == pin.snapshot_sha256
            and raw == _canonical(value),
            "POINTER_INVALID",
        )
        _require(
            seed
            == _reviewed_seed(
                baseline=baseline,
                cache_byte_count=cache["byte_count"],
                cache_sha256=cache["sha256"],
            ),
            "SEED_PIN_INVALID",
        )
        return baseline, seed, cache["byte_count"], cache["sha256"]
    except HostConfigurationSnapshotError:
        raise
    except (ValueError, TypeError, RecursionError, KeyError, AttributeError):
        raise HostConfigurationSnapshotError("HOST_CONFIGURATION_POINTER_INVALID") from None


def resolve_host_configuration_snapshot(
    pin: HostConfigurationSnapshotPin,
) -> CapturedHostConfiguration:
    """One fixed-path stdlib capture; ordinary values never establish installation authority."""
    try:
        _require(type(pin) is HostConfigurationSnapshotPin, "POINTER_INVALID")
        pin.__post_init__()
        root = _ROOT / pin.configuration_id / pin.configuration_revision_id
        files = NumericalRuntimeFileSnapshots(0)
        manifest = root / "snapshot.json"
        _read_only_member(manifest, files.owner_uid)
        raw = files.read(
            manifest,
            sha256=pin.manifest_raw_sha256,
            size=pin.manifest_byte_count,
            maximum=_MAX_MANIFEST,
        )
        baseline, seed, size, sha = _manifest_values(raw, pin)
        path = root / "ld.so.cache"
        identity = _read_only_member(path, files.owner_uid)
        cache = files.read(path, sha256=sha, size=size, maximum=_MAX_CACHE)
        host.validate_embedding_loader_cache(cache)
        captured = CapturedHostConfiguration(
            pin, raw, baseline, seed, size, sha, path, identity, files
        )
        captured.assert_unchanged()
        return captured
    except HostConfigurationSnapshotError:
        raise
    except InstalledRuntimeProofError as error:
        raise _file_error(error) from None
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


def _read_only_target_mount_id(resolved: HostConfigurationFiles) -> int:
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
class EmbeddingHostSnapshotMount[Configuration: HostConfigurationFiles]:
    """Local kernel observation, not a serializable grant, lifecycle or mutable registry."""

    configuration: Configuration
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


def require_host_configuration_snapshot_mount[Configuration: HostConfigurationFiles](
    resolved: Configuration,
) -> EmbeddingHostSnapshotMount[Configuration]:
    """Observe the exact pre-exec read-only binding; this function never creates a mount."""
    try:
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


def capture_snapshot_embedding_host[Configuration: HostConfigurationFiles](
    *,
    expected_seed_sha256: str,
    files: NumericalRuntimeFileSnapshots,
    snapshot_mount: EmbeddingHostSnapshotMount[Configuration],
) -> host.ProtectedEmbeddingHostClosure:
    """Both bootstrap and runtime use this same fixed host and actual kernel witness."""
    _require(type(snapshot_mount) is EmbeddingHostSnapshotMount, "MOUNT_INVALID")
    snapshot_mount.assert_unchanged()
    configuration = snapshot_mount.configuration
    _require(
        type(expected_seed_sha256) is str
        and expected_seed_sha256
        == configuration.host_seed_sha256
        == _reviewed_seed(
            baseline=configuration.baseline_host_seed_sha256,
            cache_byte_count=configuration.cache_byte_count,
            cache_sha256=configuration.cache_sha256,
        ),
        "SEED_PIN_INVALID",
    )
    return host._capture_embedding_host(
        expected_seed_sha256=expected_seed_sha256,
        files=files,
        fixed_files=host.reviewed_embedding_host_files(
            baseline_host_seed_sha256=configuration.baseline_host_seed_sha256,
            cache_byte_count=configuration.cache_byte_count,
            cache_sha256=configuration.cache_sha256,
        ),
        assert_mount_current=snapshot_mount.assert_unchanged,
    )

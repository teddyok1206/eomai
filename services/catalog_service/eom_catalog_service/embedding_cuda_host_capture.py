"""Stdlib-only fixed root CUDA extension file capture, not native/GPU admission."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_host_closure import (
    embedding_host_loader_cache_routes,
    read_embedding_loader_cache_entries,
)

_ROOT = Path("/opt/eom/embedding-cuda-host-extensions")
_MAX_MANIFEST = 8192
_MAX_CACHE = 128 * 1024
_LIBRARIES = (
    ("CUDA_DRIVER", "libcuda.so.1", 128 * 1024 * 1024),
    ("RDMACM", "librdmacm.so.1", 8 * 1024 * 1024),
    ("IBVERBS", "libibverbs.so.1", 8 * 1024 * 1024),
    ("MLX5", "libmlx5.so.1", 8 * 1024 * 1024),
    ("NL_CORE", "libnl-3.so.200", 8 * 1024 * 1024),
    ("NL_ROUTE", "libnl-route-3.so.200", 8 * 1024 * 1024),
)
CUDA_HOST_SCHEMA_REF = "eom://schemas/knowledge/embedding-cuda-host-extension/1.0#/$defs/snapshot"
CUDA_HOST_NVML_SCHEMA_REF = (
    "eom://schemas/knowledge/embedding-cuda-host-extension/1.1#/$defs/snapshot"
)


@dataclass(frozen=True, slots=True)
class CudaHostLibraryRecipe:
    schema_version: str
    libraries: tuple[tuple[str, str, int], ...]


_RECIPES = MappingProxyType(
    {
        CUDA_HOST_SCHEMA_REF: CudaHostLibraryRecipe(
            "embedding-cuda-host-extension/1.0", _LIBRARIES
        ),
        CUDA_HOST_NVML_SCHEMA_REF: CudaHostLibraryRecipe(
            "embedding-cuda-host-extension/1.1",
            (*_LIBRARIES, ("CUDA_NVML", "libnvidia-ml.so.1", 8 * 1024 * 1024)),
        ),
    }
)


class CudaHostExtensionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(value: bool, code: str) -> None:
    if not value:
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_" + code)


def cuda_host_library_recipe(schema_ref: str) -> CudaHostLibraryRecipe:
    """Two explicit immutable formats; an unknown pointer never selects latest."""
    _require(type(schema_ref) is str and schema_ref in _RECIPES, "POINTER_INVALID")
    return _RECIPES[schema_ref]


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_cuda_host_configuration_identity(
    configuration_id: object, configuration_revision_id: object
) -> None:
    _require(
        type(configuration_id) is str
        and re.fullmatch(r"embeddingcudahost_[0-9a-f]{32}", configuration_id) is not None
        and type(configuration_revision_id) is str
        and re.fullmatch(r"embeddingcudahostrev_[0-9a-f]{32}", configuration_revision_id)
        is not None,
        "POINTER_INVALID",
    )


@dataclass(frozen=True, slots=True)
class CudaHostExtensionPin:
    schema_ref: str
    configuration_id: str
    configuration_revision_id: str
    manifest_byte_count: int
    manifest_raw_sha256: str
    snapshot_sha256: str

    def __post_init__(self) -> None:
        validate_cuda_host_configuration_identity(
            self.configuration_id, self.configuration_revision_id
        )
        _require(
            type(self.schema_ref) is str
            and self.schema_ref in _RECIPES
            and type(self.manifest_byte_count) is int
            and 0 < self.manifest_byte_count <= _MAX_MANIFEST
            and _sha(self.manifest_raw_sha256)
            and _sha(self.snapshot_sha256),
            "POINTER_INVALID",
        )


def parse_cuda_host_extension_pin(
    value: object, *, expected_schema_ref: str = CUDA_HOST_SCHEMA_REF
) -> CudaHostExtensionPin:
    cuda_host_library_recipe(expected_schema_ref)
    _require(
        type(value) is dict
        and set(value)
        == {
            "schema_ref",
            "configuration_id",
            "configuration_revision_id",
            "manifest_byte_count",
            "manifest_raw_sha256",
            "snapshot_sha256",
        },
        "POINTER_INVALID",
    )
    assert isinstance(value, dict)
    pin = CudaHostExtensionPin(**value)
    _require(pin.schema_ref == expected_schema_ref, "POINTER_INVALID")
    return pin


@dataclass(frozen=True, slots=True)
class CudaHostLibraryPin:
    role: str
    member_name: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _Manifest:
    base_pin: base_capture.HostConfigurationSnapshotPin
    base_seed: str
    driver_release: str
    libraries: tuple[CudaHostLibraryPin, ...]
    cache_byte_count: int
    cache_sha256: str
    host_seed_sha256: str


def _manifest(raw: bytes, pin: CudaHostExtensionPin) -> _Manifest:
    recipe = cuda_host_library_recipe(pin.schema_ref)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            _require(name not in result and len(result) < 12, "MANIFEST_INVALID")
            result[name] = value
        return result

    def reject(_value: str) -> Any:
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_MANIFEST_INVALID")

    try:
        _require(type(raw) is bytes and 0 < len(raw) <= _MAX_MANIFEST, "MANIFEST_INVALID")
        document = json.loads(
            raw, object_pairs_hook=unique, parse_float=reject, parse_constant=reject
        )
        _require(
            type(document) is dict
            and set(document)
            == {
                "schema_version",
                "configuration_id",
                "configuration_revision_id",
                "captured_at",
                "base_configuration",
                "base_host_seed_sha256",
                "driver_release",
                "libraries",
                "loader_cache",
                "host_seed_sha256",
                "snapshot_sha256",
            },
            "MANIFEST_INVALID",
        )
        _require(
            document["schema_version"] == recipe.schema_version
            and document["configuration_id"] == pin.configuration_id
            and document["configuration_revision_id"] == pin.configuration_revision_id
            and raw == _canonical(document)
            and len(raw) == pin.manifest_byte_count
            and _hash(raw) == pin.manifest_raw_sha256,
            "POINTER_INVALID",
        )
        stamp = document["captured_at"]
        _require(type(stamp) is str and 20 <= len(stamp) <= 27, "MANIFEST_INVALID")
        captured_at = datetime.fromisoformat(stamp)
        _require(
            captured_at.tzinfo is not None
            and captured_at.utcoffset() == UTC.utcoffset(captured_at)
            and captured_at.isoformat().replace("+00:00", "Z") == stamp,
            "MANIFEST_INVALID",
        )
        driver = document["driver_release"]
        _require(
            type(driver) is str
            and re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", driver) is not None
            and _sha(document["base_host_seed_sha256"]),
            "MANIFEST_INVALID",
        )
        rows = document["libraries"]
        _require(type(rows) is list and len(rows) == len(recipe.libraries), "MEMBER_SET_INVALID")
        libraries = []
        for row, (role, name, maximum) in zip(rows, recipe.libraries, strict=True):
            _require(
                type(row) is dict
                and set(row) == {"role", "member_name", "byte_count", "sha256"}
                and row["role"] == role
                and row["member_name"] == name
                and type(row["byte_count"]) is int
                and 0 < row["byte_count"] <= maximum
                and _sha(row["sha256"]),
                "MEMBER_SET_INVALID",
            )
            libraries.append(CudaHostLibraryPin(**row))
        cache = document["loader_cache"]
        _require(
            type(cache) is dict
            and set(cache) == {"role", "member_name", "byte_count", "sha256"}
            and cache["role"] == "LD_SO_CACHE"
            and cache["member_name"] == "ld.so.cache"
            and type(cache["byte_count"]) is int
            and 48 <= cache["byte_count"] <= _MAX_CACHE
            and _sha(cache["sha256"]),
            "MANIFEST_INVALID",
        )
        seed = {
            name: document[name]
            for name in ("base_host_seed_sha256", "driver_release", "libraries", "loader_cache")
        }
        _require(
            document["host_seed_sha256"] == _hash(_canonical(seed))
            and document["snapshot_sha256"] == pin.snapshot_sha256
            and pin.snapshot_sha256
            == _hash(
                _canonical(
                    {name: value for name, value in document.items() if name != "snapshot_sha256"}
                )
            ),
            "HASH_MISMATCH",
        )
        return _Manifest(
            base_capture.parse_host_configuration_snapshot_pin(document["base_configuration"]),
            document["base_host_seed_sha256"],
            driver,
            tuple(libraries),
            cache["byte_count"],
            cache["sha256"],
            document["host_seed_sha256"],
        )
    except CudaHostExtensionError:
        raise
    except (ValueError, TypeError, RecursionError, KeyError, AttributeError):
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_MANIFEST_INVALID") from None


def _read_only(path: Path, owner_uid: int) -> tuple[int, ...]:
    value = path.lstat()
    _require(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == owner_uid
        and stat.S_IMODE(value.st_mode) == 0o444
        and value.st_nlink == 1
        and not {
            "system.posix_acl_access",
            "system.posix_acl_default",
            "security.capability",
        }.intersection(os.listxattr(path, follow_symlinks=False)),
        "PERMISSION_INVALID",
    )
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


def validate_cuda_host_loader_cache(
    raw: bytes, root: Path, *, schema_ref: str = CUDA_HOST_SCHEMA_REF
) -> None:
    """Exact base and explicitly selected private routes, never wildcard host permission."""
    recipe = cuda_host_library_recipe(schema_ref)
    expected = dict(embedding_host_loader_cache_routes())
    expected.update((name, str(root / name)) for _role, name, _maximum in recipe.libraries)
    seen: set[str] = set()
    try:
        entries = read_embedding_loader_cache_entries(raw)
    except (InstalledRuntimeProofError, UnicodeError, ValueError):
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_CACHE_INVALID") from None
    for entry in entries:
        _require(
            entry.name not in seen
            and entry.name in expected
            and entry.path == expected[entry.name]
            and entry.abi == 0x303
            and entry.osversion == 0
            and entry.hardware == 0,
            "CACHE_ROUTE_INVALID",
        )
        seen.add(entry.name)
    _require(seen == set(expected), "CACHE_SET_INVALID")


def _closed_members(root: Path, expected: set[Path]) -> None:
    observed: set[Path] = set()
    with os.scandir(root) as entries:
        for entry in entries:
            member = root / entry.name
            _require(member in expected and len(observed) < len(expected), "MEMBER_SET_INVALID")
            _require(entry.is_file(follow_symlinks=False), "MEMBER_SET_INVALID")
            observed.add(member)
    _require(observed == expected, "MEMBER_SET_INVALID")


@dataclass(frozen=True, slots=True)
class CapturedCudaHostExtension:
    selection: CudaHostExtensionPin
    snapshot_raw: bytes = field(repr=False)
    base_configuration: base_capture.CapturedHostConfiguration
    host_seed_sha256: str
    driver_release: str
    libraries: tuple[CudaHostLibraryPin, ...]
    cache_byte_count: int
    cache_sha256: str
    cache_path: Path
    cache_identity: tuple[int, ...]
    files: NumericalRuntimeFileSnapshots = field(repr=False, compare=False)

    @property
    def baseline_host_seed_sha256(self) -> str:
        return self.base_configuration.baseline_host_seed_sha256

    def assert_unchanged(self) -> None:
        try:
            self.base_configuration.assert_unchanged()
            self.files.assert_unchanged()
            _require(
                _read_only(self.cache_path, self.files.owner_uid) == self.cache_identity, "CHANGED"
            )
        except CudaHostExtensionError:
            raise
        except (OSError, InstalledRuntimeProofError, base_capture.HostConfigurationSnapshotError):
            raise CudaHostExtensionError("CUDA_HOST_EXTENSION_CHANGED") from None


def resolve_cuda_host_extension(pin: CudaHostExtensionPin) -> CapturedCudaHostExtension:
    """Verify fixed protected file bytes once; do not load an ELF or grant execution."""
    try:
        _require(type(pin) is CudaHostExtensionPin, "POINTER_INVALID")
        pin.__post_init__()
        root = _ROOT / pin.configuration_id / pin.configuration_revision_id
        files = NumericalRuntimeFileSnapshots(0)
        path = root / "snapshot.json"
        manifest_identity = _read_only(path, files.owner_uid)
        raw = files.read(
            path,
            sha256=pin.manifest_raw_sha256,
            size=pin.manifest_byte_count,
            maximum=_MAX_MANIFEST,
        )
        _require(_read_only(path, files.owner_uid) == manifest_identity, "CHANGED")
        manifest = _manifest(raw, pin)
        recipe = cuda_host_library_recipe(pin.schema_ref)
        base = base_capture.resolve_host_configuration_snapshot(manifest.base_pin)
        _require(manifest.base_seed == base.host_seed_sha256, "BASE_SEED_INVALID")
        expected = {path, root / "ld.so.cache"}
        for library, (_role, _name, maximum) in zip(
            manifest.libraries, recipe.libraries, strict=True
        ):
            member = root / library.member_name
            initial = _read_only(member, files.owner_uid)
            files.verify(member, sha256=library.sha256, size=library.byte_count, maximum=maximum)
            _require(_read_only(member, files.owner_uid) == initial, "CHANGED")
            expected.add(member)
        cache_path = root / "ld.so.cache"
        identity = _read_only(cache_path, files.owner_uid)
        cache = files.read(
            cache_path,
            sha256=manifest.cache_sha256,
            size=manifest.cache_byte_count,
            maximum=_MAX_CACHE,
        )
        validate_cuda_host_loader_cache(cache, root, schema_ref=pin.schema_ref)
        _closed_members(root, expected)
        files.require_closed_namespaces({root}, expected)
        _closed_members(root, expected)
        result = CapturedCudaHostExtension(
            pin,
            raw,
            base,
            manifest.host_seed_sha256,
            manifest.driver_release,
            manifest.libraries,
            manifest.cache_byte_count,
            manifest.cache_sha256,
            cache_path,
            identity,
            files,
        )
        result.assert_unchanged()
        return result
    except CudaHostExtensionError:
        raise
    except FileNotFoundError:
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_MISSING") from None
    except InstalledRuntimeProofError as error:
        suffix = {
            "INSTALLED_RUNTIME_FILE_HASH_MISMATCH": "HASH_MISMATCH",
            "INSTALLED_RUNTIME_FILE_CHANGED": "CHANGED",
            "INSTALLED_RUNTIME_FILE_UNPROTECTED": "PERMISSION_INVALID",
            "INSTALLED_RUNTIME_NAMESPACE_SET_MISMATCH": "MEMBER_SET_INVALID",
        }.get(error.code, "UNAVAILABLE")
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_" + suffix) from None
    except base_capture.HostConfigurationSnapshotError:
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_BASE_INVALID") from None
    except OSError:
        raise CudaHostExtensionError("CUDA_HOST_EXTENSION_UNAVAILABLE") from None

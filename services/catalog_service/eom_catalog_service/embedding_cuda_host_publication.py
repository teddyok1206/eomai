"""Local administrative CUDA host publication, never NAS/model/device authority.

Only the reviewed installed owner invokes this module as root with the admitted
OLD interpreter. Source hashes are a closed host recipe, not caller self-attestation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    _protected_open,
)

_ROOT_UID = 0
_ROOT = Path("/opt/eom/embedding-cuda-host-extensions")
_LOCK = Path("/opt/eom/conda/envs/.embedding-index-CUDA_INDEX_FP32.lock")
_UNIT = "eom-cuda-host-cache-builder.service"
_OWNER_RELEASES = Path("/opt/eom/embedding-owner-releases")
_DRIVER = "580.126.09"
_SYSTEM_LIBRARIES = Path("/usr/lib/x86_64-linux-gnu")
_TOOL = (
    Path("/usr/sbin/ldconfig.real"),
    1051280,
    "d879c9a8a41240aeb7fd0f3221116fc4cf41cc6c64c24e10541d1bafbe537ab1",
)
# Independent reviewed source recipe; paths are locations, SHA/size identify bytes.
_SOURCES = MappingProxyType(
    {
        "CUDA_DRIVER": (
            "libcuda.so.580.126.09",
            96284520,
            "e8e541166449da5a1278f40b27a28d072174b31f2941b101a9609b6d1d3aed32",
        ),
        "RDMACM": (
            "librdmacm.so.1.3.50.0",
            122144,
            "18609553ba84c9206739d0a6d62ae5371d4713058ed4b68c665e627d967df648",
        ),
        "IBVERBS": (
            "libibverbs.so.1.14.50.0",
            138032,
            "249242c3ba29d72b7a9be560b768bf43fc5924c8a166f4e3bbb224bd81ade3ab",
        ),
        "MLX5": (
            "libmlx5.so.1.24.50.0",
            545464,
            "61afce27090a889326a3a7eb5df44e003712503dbf31eb876fd3666578d2cfe6",
        ),
        "NL_CORE": (
            "libnl-3.so.200.26.0",
            133944,
            "afcb69e2ef0b46c2ce7b7483848332fa9462776d33163f64209acf01f86eddd7",
        ),
        "NL_ROUTE": (
            "libnl-route-3.so.200.26.0",
            575344,
            "088b0021d638306f5541e7baab06a0182b07db0a280e19b3b40c746f729b3773",
        ),
        "CUDA_NVML": (
            "libnvidia-ml.so.580.126.09",
            2283608,
            "7cf5b9e876f8a082616b5b632f426fdf2ac6fb2e04bfa90c5a3f4eebafe90910",
        ),
    }
)


class CudaHostPublicationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CudaHostPublicationError("CUDA_HOST_PUBLICATION_" + code)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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


@dataclass(frozen=True, slots=True)
class CudaHostPublicationRequest:
    configuration_id: str
    configuration_revision_id: str
    base_configuration: base_capture.HostConfigurationSnapshotPin
    rdmacm_source: Path
    schema_ref: str = capture.CUDA_HOST_SCHEMA_REF

    def __post_init__(self) -> None:
        capture.validate_cuda_host_configuration_identity(
            self.configuration_id, self.configuration_revision_id
        )
        capture.cuda_host_library_recipe(self.schema_ref)
        _require(
            type(self.base_configuration) is base_capture.HostConfigurationSnapshotPin,
            "INPUT_INVALID",
        )
        self.base_configuration.__post_init__()
        _require(
            isinstance(self.rdmacm_source, Path)
            and self.rdmacm_source.is_absolute()
            and ".." not in self.rdmacm_source.parts,
            "INPUT_INVALID",
        )
        _require(
            self.rdmacm_source.is_relative_to("/tmp")
            and self.rdmacm_source.name == _SOURCES["RDMACM"][0],
            "INPUT_INVALID",
        )


@dataclass(frozen=True, slots=True)
class CudaHostPublicationResult:
    pointer: capture.CudaHostExtensionPin
    disposition: Literal["CREATED", "REUSED"]


def _directory(path: Path) -> None:
    for member in reversed((path, *path.parents)):
        value = member.lstat()
        synthetic_tmp = (
            _ROOT_UID != 0
            and member == Path("/tmp")
            and value.st_uid == 0
            and bool(value.st_mode & stat.S_ISVTX)
        )
        _require(
            stat.S_ISDIR(value.st_mode)
            and value.st_uid in {0, _ROOT_UID}
            and (not value.st_mode & 0o022 or synthetic_tmp),
            "DIRECTORY_INVALID",
        )


def _mkdir(path: Path, *, mode: int = 0o755) -> None:
    _directory(path.parent)
    if not path.exists():
        path.mkdir(mode=mode)
        # Root's0077 umask may narrow a requested0755 directory. Correct only
        # this fresh owned inode; never repair an existing incomplete directory.
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            created = os.fstat(descriptor)
            _require(created.st_uid == _ROOT_UID, "DIRECTORY_INVALID")
            _require(_identity(created) == _identity(path.lstat()), "DIRECTORY_CHANGED")
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
    _directory(path)
    _require(stat.S_IMODE(path.lstat().st_mode) in {mode, 0o555}, "DIRECTORY_MODE_INVALID")


def _private_parents(workspace: Path, target: Path) -> None:
    _require(target.is_relative_to(workspace) and ".." not in target.parts, "BUILD_PATH_INVALID")
    current = workspace
    for component in target.relative_to(workspace).parts:
        current /= component
        _mkdir(current, mode=0o700)


@contextmanager
def _lock() -> Iterator[None]:
    _directory(_LOCK.parent)
    fd = os.open(
        _LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600
    )
    try:
        initial = os.fstat(fd)
        _require(
            stat.S_ISREG(initial.st_mode)
            and initial.st_uid == _ROOT_UID
            and stat.S_IMODE(initial.st_mode) == 0o600
            and initial.st_nlink == 1
            and initial.st_size == 0
            and _identity(initial) == _identity(_LOCK.lstat()),
            "LOCK_INVALID",
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CudaHostPublicationError("CUDA_HOST_PUBLICATION_BUSY") from None
        yield
        _require(
            _identity(os.fstat(fd)) == _identity(_LOCK.lstat()) == _identity(initial),
            "LOCK_CHANGED",
        )
    finally:
        os.close(fd)


def _write(path: Path, raw: bytes, *, mode: int = 0o444) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(os.dup(fd), "wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _materialize(
    source: Path,
    target: Path,
    *,
    owner_uid: int,
    size: int,
    sha: str,
    maximum: int,
    mode: int = 0o444,
) -> None:
    _require(type(size) is int and 0 < size <= maximum, "SOURCE_INVALID")
    with _protected_open(source, owner_uid) as (source_fd, _ancestors):
        initial = os.fstat(source_fd)
        _require(initial.st_size == size, "SOURCE_SIZE_INVALID")
        destination = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        try:
            digest = hashlib.sha256()
            offset = 0
            with os.fdopen(os.dup(destination), "wb") as output:
                while raw := os.pread(source_fd, min(1024**2, size + 1 - offset), offset):
                    offset += len(raw)
                    _require(offset <= size, "SOURCE_SIZE_INVALID")
                    digest.update(raw)
                    output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            _require(offset == size and digest.hexdigest() == sha, "SOURCE_HASH_MISMATCH")
            _require(_identity(os.fstat(source_fd)) == _identity(initial), "SOURCE_CHANGED")
            os.fchmod(destination, mode)
        finally:
            os.close(destination)


def _prepare_cache_command(
    workspace: Path, final: Path, bindings: tuple[tuple[Path, Path], ...]
) -> tuple[str, ...]:
    build = workspace / "build"
    command = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--unit=" + _UNIT,
        "--property=Type=exec",
        "--property=User=root",
        "--property=Group=root",
        "--property=UMask=0077",
        "--property=NoNewPrivileges=yes",
        "--property=PrivateMounts=yes",
        "--property=PrivateNetwork=yes",
        "--property=PrivateDevices=yes",
        "--property=ProtectSystem=strict",
        "--property=ProtectHome=yes",
        "--property=ProtectControlGroups=yes",
        "--property=InaccessiblePaths=-/mnt/nas -/etc/eom -/var/lib/eom-workers -/var/lib/eom-api",
        "--property=CapabilityBoundingSet=CAP_SYS_CHROOT",
        "--property=RestrictNamespaces=yes",
        "--property=RestrictAddressFamilies=AF_UNIX",
        "--property=TasksMax=16",
        "--property=MemoryMax=268435456",
        "--property=LimitFSIZE=131072",
        "--property=CPUQuota=100%",
        "--property=RuntimeMaxSec=30",
        "--property=WorkingDirectory=/",
        "--property=ReadWritePaths=" + str(build / "etc") + " " + str(build / "var/cache/ldconfig"),
        "--setenv=PATH=/usr/bin:/bin",
        "--setenv=LC_ALL=C",
        "--setenv=TZ=UTC",
    ]
    readonly = []
    for source, target in bindings:
        destination = build / target.relative_to("/")
        _private_parents(workspace, destination.parent)
        _write(destination, b"", mode=0o444)
        readonly.append(str(source) + ":" + str(destination))
    command.append("--property=BindReadOnlyPaths=" + " ".join(readonly))
    command.extend(
        (
            str(workspace / "ldconfig.real"),
            "-r",
            str(build),
            "-C",
            "/etc/ld.so.cache",
            "-f",
            "/etc/ld.so.conf",
            "-X",
            "-i",
            "-c",
            "new",
        )
    )
    return tuple(command)


def _generate_cache(
    workspace: Path,
    final: Path,
    stage: Path,
    cpu_files: NumericalRuntimeFileSnapshots,
    *,
    base_configuration: base_capture.CapturedHostConfiguration,
    schema_ref: str = capture.CUDA_HOST_SCHEMA_REF,
) -> bytes:
    recipe = capture.cuda_host_library_recipe(schema_ref)
    base_configuration.assert_unchanged()
    # The cache must describe the exact reviewed base selected by this request,
    # not reinterpret a successor through the immutable legacy host table.
    fixed = {
        path: (size, sha)
        for path, size, sha in host.reviewed_embedding_host_files(
            baseline_host_seed_sha256=base_configuration.baseline_host_seed_sha256,
            cache_byte_count=base_configuration.cache_byte_count,
            cache_sha256=base_configuration.cache_sha256,
        )
    }
    build = workspace / "build"
    for relative in ("etc", "var/cache/ldconfig", "lib", "usr/lib"):
        _private_parents(workspace, build / relative)
    _write(build / "etc/ld.so.conf", ("/lib/x86_64-linux-gnu\n" + str(final) + "\n").encode())
    bindings = []
    for name, route in host.embedding_host_loader_cache_routes():
        source = host._SONAMES[name]
        size, sha = fixed[source]
        cpu_files.verify(source, sha256="sha256:" + sha, size=size, maximum=8 * 1024**2)
        bindings.append((source, Path(route)))
    bindings.extend((stage / name, final / name) for _role, name, _maximum in recipe.libraries)
    command = _prepare_cache_command(workspace, final, tuple(bindings))
    _write(workspace / "unit-name", (_UNIT + "\n").encode(), mode=0o600)
    diagnostic_fd = os.open(
        workspace / "cache-unit.stderr",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(diagnostic_fd, "wb") as diagnostic:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=diagnostic,
                check=False,
                timeout=45,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
            )
    except subprocess.TimeoutExpired:
        _write(
            workspace / "cache-unit-outcome.json",
            _canonical(
                {
                    "unit": _UNIT,
                    "scope": "CACHE_ONLY_NOT_NATIVE_ADMISSION",
                    "state": "OUTCOME_UNKNOWN",
                }
            ),
            mode=0o600,
        )
        raise CudaHostPublicationError("CUDA_HOST_PUBLICATION_UNIT_OUTCOME_UNKNOWN") from None
    _write(
        workspace / "cache-unit-outcome.json",
        _canonical(
            {
                "unit": _UNIT,
                "scope": "CACHE_ONLY_NOT_NATIVE_ADMISSION",
                "returncode": result.returncode,
                "state": "SUCCEEDED" if result.returncode == 0 else "FAILED",
            }
        ),
        mode=0o600,
    )
    _require(result.returncode == 0, "CACHE_UNIT_FAILED")
    cpu_files.assert_unchanged()
    base_configuration.assert_unchanged()
    observed = NumericalRuntimeFileSnapshots(_ROOT_UID).observe_protected_member_bytes(
        build / "etc/ld.so.cache", maximum=128 * 1024
    )
    capture.validate_cuda_host_loader_cache(observed.raw, final, schema_ref=schema_ref)
    return observed.raw


def _require_cache_unit_quiescent() -> None:
    try:
        result = subprocess.run(
            (
                "/usr/bin/systemctl",
                "show",
                _UNIT,
                "-p",
                "LoadState",
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
                "-p",
                "ControlPID",
                "--no-pager",
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
        )
    except subprocess.TimeoutExpired:
        raise CudaHostPublicationError("CUDA_HOST_PUBLICATION_UNIT_STATE_UNKNOWN") from None
    _require(
        result.returncode == 0 and len(result.stdout) <= 4096 and not result.stderr,
        "UNIT_STATE_UNKNOWN",
    )
    lines = result.stdout.splitlines()
    _require(len(lines) == 4 and all(line.count("=") == 1 for line in lines), "UNIT_STATE_UNKNOWN")
    values = dict(line.split("=", 1) for line in lines)
    _require(len(values) == 4, "UNIT_STATE_UNKNOWN")
    _require(
        values
        == {"LoadState": "not-found", "ActiveState": "inactive", "MainPID": "0", "ControlPID": "0"},
        "UNIT_NOT_QUIESCENT",
    )


def _pointer_from_raw(
    request: CudaHostPublicationRequest, raw: bytes
) -> capture.CudaHostExtensionPin:
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= 8192, "MANIFEST_INVALID")
        value = json.loads(raw)
    except (ValueError, RecursionError):
        raise CudaHostPublicationError("CUDA_HOST_PUBLICATION_MANIFEST_INVALID") from None
    _require(
        type(value) is dict and isinstance(value.get("snapshot_sha256"), str), "MANIFEST_INVALID"
    )
    return capture.CudaHostExtensionPin(
        request.schema_ref,
        request.configuration_id,
        request.configuration_revision_id,
        len(raw),
        _hash(raw),
        value["snapshot_sha256"],
    )


def _reused(request: CudaHostPublicationRequest, final: Path) -> capture.CudaHostExtensionPin:
    _require(
        stat.S_ISDIR(final.lstat().st_mode) and stat.S_IMODE(final.lstat().st_mode) == 0o555,
        "EXISTING_REVISION_INCOMPLETE",
    )
    files = NumericalRuntimeFileSnapshots(_ROOT_UID)
    observed = files.observe_protected_member_bytes(final / "snapshot.json", maximum=8192)
    pointer = _pointer_from_raw(request, observed.raw)
    selected = capture.resolve_cuda_host_extension(pointer)
    _require(
        selected.base_configuration.selection == request.base_configuration
        and selected.driver_release == _DRIVER,
        "EXISTING_REVISION_CONFLICT",
    )
    for member in selected.libraries:
        _name, size, sha = _SOURCES[member.role]
        _require(
            member.byte_count == size and member.sha256 == "sha256:" + sha,
            "EXISTING_REVISION_CONFLICT",
        )
    return pointer


def _retained_stat(path: Path, mode: int, *, kind: Literal["FILE", "DIRECTORY"]) -> os.stat_result:
    value = path.lstat()
    _require(
        (stat.S_ISREG(value.st_mode) if kind == "FILE" else stat.S_ISDIR(value.st_mode))
        and value.st_uid == _ROOT_UID
        and stat.S_IMODE(value.st_mode) == mode
        and (kind == "DIRECTORY" or value.st_nlink == 1)
        and not {
            "system.posix_acl_access",
            "system.posix_acl_default",
            "security.capability",
        }.intersection(os.listxattr(path, follow_symlinks=False)),
        "RETAINED_PERMISSION_INVALID",
    )
    return value


def _capture_retained_publication(
    request: CudaHostPublicationRequest,
    pointer: capture.CudaHostExtensionPin,
    base: base_capture.CapturedHostConfiguration,
    workspace: Path,
    final: Path,
) -> NumericalRuntimeFileSnapshots:
    """Verify only the existing fixed builder tree; never rebuild or read source libraries."""
    recipe = capture.cuda_host_library_recipe(request.schema_ref)
    stage = workspace / "revision"
    files = NumericalRuntimeFileSnapshots(_ROOT_UID)
    _retained_stat(stage / "snapshot.json", 0o444, kind="FILE")
    raw = files.read(
        stage / "snapshot.json",
        sha256=pointer.manifest_raw_sha256,
        size=pointer.manifest_byte_count,
        maximum=8192,
    )
    manifest = capture._manifest(raw, pointer)
    _require(
        manifest.base_pin == request.base_configuration
        and manifest.base_seed == base.host_seed_sha256
        and manifest.driver_release == _DRIVER,
        "RETAINED_REVISION_CONFLICT",
    )
    modes = {stage / "snapshot.json": 0o444, stage / "ld.so.cache": 0o444}
    for library, (_role, name, maximum) in zip(manifest.libraries, recipe.libraries, strict=True):
        _physical, size, sha = _SOURCES[library.role]
        _require(
            library.byte_count == size and library.sha256 == "sha256:" + sha,
            "RETAINED_REVISION_CONFLICT",
        )
        path = stage / name
        modes[path] = 0o444
        _retained_stat(path, 0o444, kind="FILE")
        files.verify(path, sha256="sha256:" + sha, size=size, maximum=maximum)
    _retained_stat(stage / "ld.so.cache", 0o444, kind="FILE")
    cache = files.read(
        stage / "ld.so.cache",
        sha256=manifest.cache_sha256,
        size=manifest.cache_byte_count,
        maximum=128 * 1024,
    )
    capture.validate_cuda_host_loader_cache(cache, final, schema_ref=request.schema_ref)

    build = workspace / "build"
    placeholders = {
        build / Path(route).relative_to("/")
        for _name, route in host.embedding_host_loader_cache_routes()
    }
    placeholders.update(
        build / (final / name).relative_to("/") for _role, name, _maximum in recipe.libraries
    )
    modes.update(dict.fromkeys(placeholders, 0o444))
    modes.update(
        {
            workspace / "ldconfig.real": 0o500,
            workspace / "unit-name": 0o600,
            workspace / "cache-unit-outcome.json": 0o600,
            workspace / "cache-unit.stderr": 0o600,
            build / "etc/ld.so.conf": 0o444,
            build / "etc/ld.so.cache": 0o644,
            build / "var/cache/ldconfig/aux-cache": 0o600,
        }
    )
    directories = {workspace, stage, build / "lib", build / "usr/lib"}
    for member in modes.keys() | directories:
        parent = member.parent
        while parent.is_relative_to(workspace):
            directories.add(parent)
            if parent == workspace:
                break
            parent = parent.parent
    children: dict[Path, set[Path]] = {path: set() for path in directories}
    for member in modes.keys() | directories:
        if member != workspace:
            children[member.parent].add(member)
    initial_directories = {}
    for directory, expected in children.items():
        initial_directories[directory] = _identity(
            _retained_stat(directory, 0o700, kind="DIRECTORY")
        )
        observed: set[Path] = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                member = directory / entry.name
                _require(member in expected and len(observed) < len(expected), "MEMBER_SET_INVALID")
                observed.add(member)
        _require(observed == expected, "MEMBER_SET_INVALID")
    initial_members = {
        path: _identity(_retained_stat(path, mode, kind="FILE")) for path, mode in modes.items()
    }
    for path in placeholders:
        files.read(path, sha256=_hash(b""), size=0, maximum=1)
    _tool, size, sha = _TOOL
    files.verify(
        workspace / "ldconfig.real", sha256="sha256:" + sha, size=size, maximum=8 * 1024**2
    )
    metadata = {
        workspace / "unit-name": (_UNIT + "\n").encode(),
        workspace / "cache-unit-outcome.json": _canonical(
            {
                "unit": _UNIT,
                "scope": "CACHE_ONLY_NOT_NATIVE_ADMISSION",
                "returncode": 0,
                "state": "SUCCEEDED",
            }
        ),
        build / "etc/ld.so.conf": ("/lib/x86_64-linux-gnu\n" + str(final) + "\n").encode(),
        build / "etc/ld.so.cache": cache,
    }
    for path, expected_raw in metadata.items():
        files.verify(path, sha256=_hash(expected_raw), size=len(expected_raw), maximum=128 * 1024)
    # Diagnostics and the unused auxiliary cache are bounded retained evidence,
    # not publication authority. Neither is interpreted or rewritten here.
    for path in (workspace / "cache-unit.stderr", build / "var/cache/ldconfig/aux-cache"):
        _require(path.lstat().st_size <= 128 * 1024, "RETAINED_EVIDENCE_SIZE_INVALID")
        files.observe_protected_member_identity(path)
    files.require_closed_namespaces({workspace}, set(modes))
    for path, initial in initial_directories.items() | initial_members.items():
        _require(_identity(path.lstat()) == initial, "RETAINED_CHANGED")
    files.assert_unchanged()
    return files


def _commit_revision(stage: Path, final: Path) -> None:
    os.rename(stage, final)
    # Cross-parent rename needs write access to its '..' update until the move.
    final.chmod(0o555)
    for directory in (final, stage.parent, final.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def complete_cuda_host_extension_publication(
    request: CudaHostPublicationRequest, expected_pointer: capture.CudaHostExtensionPin
) -> CudaHostPublicationResult:
    """Commit an exact retained complete stage, without rerunning its failed process."""
    _require(os.geteuid() == _ROOT_UID, "OWNER_REQUIRED")
    _require(
        type(request) is CudaHostPublicationRequest
        and type(expected_pointer) is capture.CudaHostExtensionPin,
        "INPUT_INVALID",
    )
    request.__post_init__()
    expected_pointer.__post_init__()
    _require(
        (
            expected_pointer.schema_ref,
            expected_pointer.configuration_id,
            expected_pointer.configuration_revision_id,
        )
        == (request.schema_ref, request.configuration_id, request.configuration_revision_id),
        "INPUT_INVALID",
    )
    with _lock():
        _directory(_ROOT)
        logical = _ROOT / request.configuration_id
        final = logical / request.configuration_revision_id
        _require_cache_unit_quiescent()
        base = base_capture.resolve_host_configuration_snapshot(request.base_configuration)
        if final.exists() or final.is_symlink():
            pointer = _reused(request, final)
            _require(pointer == expected_pointer, "EXISTING_REVISION_CONFLICT")
            base.assert_unchanged()
            return CudaHostPublicationResult(pointer, "REUSED")
        publication = _ROOT / ".publication"
        private_logical = publication / request.configuration_id
        workspace = private_logical / request.configuration_revision_id
        boundaries = {
            path: _identity(_retained_stat(path, mode, kind="DIRECTORY"))
            for path, mode in (
                (_ROOT, 0o755),
                (logical, 0o755),
                (publication, 0o700),
                (private_logical, 0o700),
            )
        }
        files = _capture_retained_publication(request, expected_pointer, base, workspace, final)
        _require_cache_unit_quiescent()
        base.assert_unchanged()
        files.assert_unchanged()
        for path, initial in boundaries.items():
            _require(_identity(path.lstat()) == initial, "DIRECTORY_CHANGED")
        _require(not final.exists() and not final.is_symlink(), "EXISTING_REVISION_CONFLICT")
        _commit_revision(workspace / "revision", final)
        # Stage-path epochs necessarily changed at the commit boundary. Resolve
        # the immutable final namespace afresh instead of laundering those epochs.
        capture.resolve_cuda_host_extension(expected_pointer).assert_unchanged()
        return CudaHostPublicationResult(expected_pointer, "CREATED")


def publish_cuda_host_extension(
    request: CudaHostPublicationRequest,
) -> CudaHostPublicationResult:
    """Explicit root filesystem materialization; this never selects a runtime or grants CUDA."""
    _require(os.geteuid() == _ROOT_UID, "OWNER_REQUIRED")
    _require(type(request) is CudaHostPublicationRequest, "INPUT_INVALID")
    request.__post_init__()
    recipe = capture.cuda_host_library_recipe(request.schema_ref)
    base = base_capture.resolve_host_configuration_snapshot(request.base_configuration)
    with _lock():
        _mkdir(_ROOT)
        logical = _ROOT / request.configuration_id
        _mkdir(logical)
        final = logical / request.configuration_revision_id
        if final.exists() or final.is_symlink():
            return CudaHostPublicationResult(_reused(request, final), "REUSED")
        _require_cache_unit_quiescent()
        _mkdir(_ROOT / ".publication", mode=0o700)
        _mkdir(_ROOT / ".publication" / request.configuration_id, mode=0o700)
        workspace = (
            _ROOT / ".publication" / request.configuration_id / request.configuration_revision_id
        )
        _require(
            not workspace.exists() and not workspace.is_symlink(),
            "PREVIOUS_OPERATION_REQUIRES_RECONCILIATION",
        )
        workspace.mkdir(mode=0o700)
        stage = workspace / "revision"
        stage.mkdir(mode=0o700)
        libraries = []
        for role, name, maximum in recipe.libraries:
            physical, size, sha = _SOURCES[role]
            source = request.rdmacm_source if role == "RDMACM" else _SYSTEM_LIBRARIES / physical
            owner = pwd.getpwnam("eom").pw_uid if role == "RDMACM" else _ROOT_UID
            _materialize(source, stage / name, owner_uid=owner, size=size, sha=sha, maximum=maximum)
            libraries.append(
                {"role": role, "member_name": name, "byte_count": size, "sha256": "sha256:" + sha}
            )
        tool, size, sha = _TOOL
        _materialize(
            tool,
            workspace / "ldconfig.real",
            owner_uid=_ROOT_UID,
            size=size,
            sha=sha,
            maximum=8 * 1024**2,
            mode=0o500,
        )
        cache = _generate_cache(
            workspace,
            final,
            stage,
            NumericalRuntimeFileSnapshots(_ROOT_UID),
            base_configuration=base,
            schema_ref=request.schema_ref,
        )
        _write(stage / "ld.so.cache", cache)
        body = {
            "schema_version": recipe.schema_version,
            "configuration_id": request.configuration_id,
            "configuration_revision_id": request.configuration_revision_id,
            "captured_at": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "base_configuration": asdict(request.base_configuration),
            "base_host_seed_sha256": base.host_seed_sha256,
            "driver_release": _DRIVER,
            "libraries": libraries,
            "loader_cache": {
                "role": "LD_SO_CACHE",
                "member_name": "ld.so.cache",
                "byte_count": len(cache),
                "sha256": _hash(cache),
            },
        }
        body["host_seed_sha256"] = _hash(
            _canonical(
                {
                    name: body[name]
                    for name in (
                        "base_host_seed_sha256",
                        "driver_release",
                        "libraries",
                        "loader_cache",
                    )
                }
            )
        )
        body["snapshot_sha256"] = _hash(_canonical(body))
        raw = _canonical(body)
        pointer = _pointer_from_raw(request, raw)
        capture._manifest(raw, pointer)
        _write(stage / "snapshot.json", raw)
        base.assert_unchanged()
        _require(len(tuple(stage.iterdir())) == len(recipe.libraries) + 2, "MEMBER_SET_INVALID")
        _commit_revision(stage, final)
        capture.resolve_cuda_host_extension(pointer).assert_unchanged()
        return CudaHostPublicationResult(pointer, "CREATED")


def main(argv: list[str] | None = None) -> int:
    """Protected OLD owner entry; output is small pointer metadata, not a native receipt."""
    import argparse
    import sys

    if (
        os.geteuid() != 0
        or Path(sys.prefix) != Path("/opt/eom/conda/envs/eom-embedding-experiment")
        or sys.version_info[:3] != (3, 12, 13)
        or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode)
    ):
        print("CUDA_HOST_PUBLICATION_PROTECTED_OWNER_REQUIRED", file=sys.stderr)
        return 1
    source = Path(__file__)
    relative = (
        source.relative_to(_OWNER_RELEASES) if source.is_relative_to(_OWNER_RELEASES) else None
    )
    if (
        relative is None
        or len(relative.parts) != 4
        or re.fullmatch(r"[0-9a-f]{40}", relative.parts[0]) is None
        or relative.parts[1:]
        != ("site-packages", "eom_catalog_service", "embedding_cuda_host_publication.py")
    ):
        print("CUDA_HOST_PUBLICATION_INSTALLED_OWNER_REQUIRED", file=sys.stderr)
        return 1
    try:
        NumericalRuntimeFileSnapshots(0).observe_protected_member_identity(source)
    except ValueError:
        print("CUDA_HOST_PUBLICATION_INSTALLED_OWNER_REQUIRED", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--configuration-id", required=True)
    parser.add_argument("--configuration-revision-id", required=True)
    parser.add_argument("--base-pointer-json", required=True)
    parser.add_argument("--rdmacm-source", type=Path, required=True)
    parser.add_argument(
        "--schema-ref",
        choices=(capture.CUDA_HOST_SCHEMA_REF, capture.CUDA_HOST_NVML_SCHEMA_REF),
        default=capture.CUDA_HOST_SCHEMA_REF,
    )
    args = parser.parse_args(argv)

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in pairs:
            _require(name not in result and len(result) < 6, "INPUT_INVALID")
            result[name] = value
        return result

    try:
        _require(len(args.base_pointer_json.encode()) <= 8192, "INPUT_INVALID")
        base = base_capture.parse_host_configuration_snapshot_pin(
            json.loads(args.base_pointer_json, object_pairs_hook=unique)
        )
        result = publish_cuda_host_extension(
            CudaHostPublicationRequest(
                args.configuration_id,
                args.configuration_revision_id,
                base,
                args.rdmacm_source,
                args.schema_ref,
            )
        )
        print(
            json.dumps(
                {
                    "event": "CUDA_HOST_PUBLICATION",
                    "state": "ROOTLOCAL_AVAILABLE_NOT_NATIVE_ADMITTED",
                    "result": asdict(result),
                },
                sort_keys=True,
            )
        )
        return 0
    except (ValueError, OSError, TypeError, RecursionError) as error:
        print(
            json.dumps(
                {
                    "event": "CUDA_HOST_PUBLICATION",
                    "state": "FAILED_NOT_ADMITTED",
                    "code": getattr(error, "code", "CUDA_HOST_PUBLICATION_INVALID"),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

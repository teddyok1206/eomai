"""Read-only fixed native prefix composition; no publication or installation grant."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import tarfile
import time
import tomllib
import types
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from eom_catalog_service.embedding_conda_runtime_closure import (
    CondaRuntimeArchivePin,
    CondaRuntimeAuditPlan,
    audit_installed_conda31,
)
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    RuntimeFileEpoch,
    capture_cuda_loader_directory,
    fixed_native_embedding_profile,
    require_runtime_proof,
)
from eom_catalog_service.embedding_runtime_host_closure import (
    MAX_READELF_OUTPUT_BYTES,
    ProtectedEmbeddingHostClosure,
    capture_protected_embedding_host,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelMemberPin,
    observe_runtime_wheel_installation,
    verify_installed_runtime_wheel,
)

if TYPE_CHECKING:
    from eom_catalog_service.embedding_host_configuration_capture import (
        HostConfigurationSnapshotPin,
    )

_COUNTS = {"CPU_INDEX_FP32": 55, "CUDA_INDEX_FP32": 70}
_LOCKS = (
    ("infra/conda", "eom-embedding-protected-runtime.requirements.proposal.lock"),
    ("infra/conda", "eom-embedding-index-cpu.requirements.proposal.lock"),
    ("infra/conda", "eom-embedding-cuda.requirements.proposal.lock"),
    ("scripts/embedding", "common-numeric-runtime-wheels.lock"),
    ("scripts/embedding", "cuda-runtime-wheels.lock"),
)
_ROOTS = frozenset(
    {
        "packages/protocol",
        "packages/identifiers",
        "services/orchestrator",
        "apps/eomctl",
        "tools/dev_reporter",
        "tools/textbook_analysis",
        "packages/workflow",
        "services/workflow_runner",
        "packages/hwpx_contracts",
        "services/hwpx_manager",
        "packages/content_intake",
        "packages/content_pack",
        "packages/item_registry",
        "packages/operator_identity",
        "services/identity_service",
        "packages/catalog_contracts",
        "packages/image_contracts",
        "services/catalog_service",
    }
)
_BOOTSTRAP = frozenset(
    {
        "__init__.py",
        "embedding_runtime_files.py",
        "embedding_runtime_wheel_closure.py",
        "embedding_runtime_host_closure.py",
        "embedding_conda_runtime_closure.py",
        "embedding_runtime_prefix_closure.py",
    }
)
_SNAPSHOT_BOOTSTRAP = _BOOTSTRAP | {"embedding_host_configuration_capture.py"}
_MAX_MEMBERS = 100000
_MAX_BYTES = 16 * 1024**3


def _require(condition: bool, code: str = "INVALID") -> None:
    require_runtime_proof(condition, "PREFIX_" + code)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    return _hash(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def _relative(value: object) -> str:
    _require(
        type(value) is str
        and 0 < len(value.encode()) <= 512
        and not value.startswith("/")
        and "\\" not in value
        and all(ord(c) >= 32 for c in value)
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        "PATH_INVALID",
    )
    return str(value)


@dataclass(frozen=True, slots=True)
class PrefixSourceArchivePin:
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require(
            type(self.sha256) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.sha256) is not None
            and type(self.size_bytes) is int
            and 0 < self.size_bytes <= 64 * 1024**2
        )


@dataclass(frozen=True, slots=True)
class PrefixSourceWheelPin:
    name: str
    archive: RuntimeWheelArchivePin
    source_commit: str
    source_archive: PrefixSourceArchivePin

    def __post_init__(self) -> None:
        _require(
            type(self.name) is str
            and self.name in {"eom-platform", "eom-gpu-lease"}
            and type(self.archive) is RuntimeWheelArchivePin
            and type(self.source_commit) is str
            and re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is not None
            and type(self.source_archive) is PrefixSourceArchivePin
        )
        self.archive.__post_init__()
        self.source_archive.__post_init__()
        _require(
            self.archive.wheel_filename == self.name.replace("-", "_") + "-0.1.0-py3-none-any.whl"
        )


@dataclass(frozen=True, slots=True)
class PrefixRuntimeAuditPlan:
    conda: CondaRuntimeAuditPlan
    public_archives: tuple[RuntimeWheelArchivePin, ...]
    private_archives: tuple[PrefixSourceWheelPin, ...]
    created_at: RuntimeWheelMemberPin
    history: RuntimeWheelMemberPin
    helper: RuntimeWheelMemberPin

    def __post_init__(self) -> None:
        _require(type(self.conda) is CondaRuntimeAuditPlan)
        self.conda.__post_init__()
        _require(
            type(self.public_archives) is tuple
            and len(self.public_archives) == _COUNTS[self.conda.profile]
            and type(self.private_archives) is tuple
            and len(self.private_archives) == (1 if self.conda.profile == "CPU_INDEX_FP32" else 2)
        )
        for archive in self.public_archives:
            _require(type(archive) is RuntimeWheelArchivePin)
            archive.__post_init__()
        _require(
            tuple(pin.wheel_filename for pin in self.public_archives)
            == tuple(sorted({pin.wheel_filename for pin in self.public_archives}))
        )
        for private in self.private_archives:
            _require(type(private) is PrefixSourceWheelPin)
            private.__post_init__()
        _require(
            tuple(pin.name for pin in self.private_archives)
            == (
                ("eom-platform",)
                if self.conda.profile == "CPU_INDEX_FP32"
                else ("eom-platform", "eom-gpu-lease")
            )
        )
        for pin in (self.created_at, self.history, self.helper):
            _require(type(pin) is RuntimeWheelMemberPin)
            pin.__post_init__()
            _require(pin.size_bytes <= 1024**2)


@dataclass(frozen=True, slots=True)
class PrefixRuntimeInventoryEntry:
    """One observed member value; constructible Python data, never an admission grant."""

    relative_member: str
    epoch: tuple[int, ...]
    sha256: str | None
    symlink_target: str | None

    def __post_init__(self) -> None:
        _relative(self.relative_member)
        _inventory_epoch(self.epoch, 9)
        mode = self.epoch[4]
        _require(
            stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode),
            "INVENTORY_INVALID",
        )
        if stat.S_ISREG(mode):
            _require(
                type(self.sha256) is str
                and len(self.sha256) == 71
                and re.fullmatch(r"sha256:[0-9a-f]{64}", self.sha256) is not None
                and self.symlink_target is None
                and self.epoch[5] == 1
                and not mode & 0o6022,
                "INVENTORY_INVALID",
            )
        elif stat.S_ISLNK(mode):
            _require(
                self.sha256 is None
                and type(self.symlink_target) is str
                and 0 < len(self.symlink_target.encode()) <= 512
                and not self.symlink_target.startswith("/")
                and "\\" not in self.symlink_target
                and all(ord(value) >= 32 for value in self.symlink_target)
                and self.epoch[5] == 1,
                "INVENTORY_INVALID",
            )
        else:
            _require(
                self.sha256 is None and self.symlink_target is None and not mode & 0o022,
                "INVENTORY_INVALID",
            )


@dataclass(frozen=True, slots=True)
class PrefixRuntimeInventory:
    """Same-audit metadata closure; no serializer, byte rehash or origin/privilege grant."""

    prefix: Path
    owner_uid: int
    root_epoch: tuple[int, ...]
    ancestor_epochs: tuple[tuple[Path, tuple[int, ...]], ...]
    entries: tuple[PrefixRuntimeInventoryEntry, ...]

    def __post_init__(self) -> None:
        _require(
            isinstance(self.prefix, Path)
            and self.prefix.is_absolute()
            and ".." not in self.prefix.parts
            and type(self.owner_uid) is int
            and 0 <= self.owner_uid <= 4294967294
            and type(self.ancestor_epochs) is tuple
            and type(self.entries) is tuple
            and 0 < len(self.entries) <= _MAX_MEMBERS,
            "INVENTORY_INVALID",
        )
        _inventory_epoch(self.root_epoch, 9)
        _require(
            self.root_epoch[2] == self.owner_uid
            and stat.S_ISDIR(self.root_epoch[4])
            and not self.root_epoch[4] & 0o022,
            "INVENTORY_INVALID",
        )
        _require(
            len(self.ancestor_epochs) == len(self.prefix.parents)
            and all(type(value) is tuple and len(value) == 2 for value in self.ancestor_epochs),
            "INVENTORY_INVALID",
        )
        _require(
            tuple(path for path, _epoch in self.ancestor_epochs)
            == tuple(reversed(self.prefix.parents)),
            "INVENTORY_INVALID",
        )
        for path, epoch in self.ancestor_epochs:
            _inventory_epoch(epoch, 5)
            _require(
                stat.S_ISDIR(epoch[4]) and epoch[2] in {0, self.owner_uid},
                "INVENTORY_INVALID",
            )
            test_sticky = (
                self.owner_uid != 0 and path == Path("/tmp") and bool(epoch[4] & stat.S_ISVTX)
            )
            _require(not epoch[4] & 0o022 or test_sticky, "INVENTORY_INVALID")
        previous_name: str | None = None
        directories: set[str] = set()
        required_directories: set[str] = set()
        size = 0
        for entry in self.entries:
            _require(type(entry) is PrefixRuntimeInventoryEntry, "INVENTORY_INVALID")
            entry.__post_init__()
            _require(entry.epoch[2] == self.owner_uid, "INVENTORY_INVALID")
            _require(
                previous_name is None or previous_name < entry.relative_member,
                "INVENTORY_INVALID",
            )
            previous_name = entry.relative_member
            if stat.S_ISDIR(entry.epoch[4]):
                directories.add(entry.relative_member)
            else:
                parent = entry.relative_member.rpartition("/")[0]
                while parent:
                    required_directories.add(parent)
                    parent = parent.rpartition("/")[0]
            if stat.S_ISREG(entry.epoch[4]):
                size += entry.epoch[6]
                _require(size <= _MAX_BYTES, "INVENTORY_INVALID")
        _require(
            directories == required_directories,
            "INVENTORY_INVALID",
        )

    def assert_unchanged(self) -> None:
        """Metadata/link checks only; a caller-created value does not attest audited bytes."""
        self.__post_init__()
        try:
            _require(
                all(
                    _ancestor_identity(path.lstat()) == epoch
                    for path, epoch in self.ancestor_epochs
                )
                and _identity(self.prefix.lstat()) == self.root_epoch,
                "INVENTORY_CHANGED",
            )
            for entry in self.entries:
                path = self.prefix / entry.relative_member
                _require(_identity(path.lstat()) == entry.epoch, "INVENTORY_CHANGED")
                if entry.symlink_target is not None:
                    _require(os.readlink(path) == entry.symlink_target, "INVENTORY_CHANGED")
        except OSError:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PREFIX_INVENTORY_CHANGED") from None


def _inventory_epoch(epoch: tuple[int, ...], length: int) -> None:
    _require(
        type(epoch) is tuple
        and len(epoch) == length
        and all(type(value) is int and 0 <= value <= 18446744073709551615 for value in epoch)
        and epoch[1] > 0
        and epoch[2] <= 4294967294
        and epoch[3] <= 4294967294
        and epoch[4] <= 65535,
        "INVENTORY_INVALID",
    )
    if length == 9:
        _require(0 < epoch[5] <= _MAX_MEMBERS and epoch[6] <= _MAX_BYTES, "INVENTORY_INVALID")


@dataclass(frozen=True, slots=True)
class PrefixRuntimeByteAudit:
    profile: str
    source_closure_sha256: str
    member_inventory_sha256: str
    byte_closure_sha256: str
    elf_closure_sha256: str
    regular_members: int
    link_members: int
    size_bytes: int
    elf_members: int
    inventory: PrefixRuntimeInventory


def parse_embedding_prefix_audit_input(
    raw: bytes,
) -> tuple[PrefixRuntimeAuditPlan, str, tuple[tuple[str, str, int], ...]]:
    """One bounded closed owner-value parser; fields confer no root/native authority."""
    selected = _parse_prefix_installation_input(
        raw, expected_version="embedding-prefix-audit-input/1.0"
    )
    return selected.plan, selected.host_seed_sha256, selected.bootstrap


@dataclass(frozen=True, slots=True)
class ConfiguredPrefixRuntimeAuditInput:
    plan: PrefixRuntimeAuditPlan
    host_seed_sha256: str
    bootstrap: tuple[tuple[str, str, int], ...]
    host_configuration: HostConfigurationSnapshotPin | None


def parse_installed_embedding_prefix_audit_input(raw: bytes) -> ConfiguredPrefixRuntimeAuditInput:
    """Explicit installation-family reader, never a grant or an implicit version upgrade."""
    return _parse_prefix_installation_input(raw, expected_version=None)


def capture_prefix_audit_host(
    selected: ConfiguredPrefixRuntimeAuditInput, *, files: NumericalRuntimeFileSnapshots
) -> ProtectedEmbeddingHostClosure:
    """Existing protected audit owner; do not import the seventh module for strict1.0."""
    _require(type(selected) is ConfiguredPrefixRuntimeAuditInput, "INPUT_INVALID")
    if selected.host_configuration is None:
        return capture_protected_embedding_host(
            expected_seed_sha256=selected.host_seed_sha256, files=files
        )
    from eom_catalog_service.embedding_host_configuration_capture import (
        capture_snapshot_embedding_host,
        require_host_configuration_snapshot_mount,
        resolve_host_configuration_snapshot,
    )

    captured = resolve_host_configuration_snapshot(selected.host_configuration)
    return capture_snapshot_embedding_host(
        expected_seed_sha256=selected.host_seed_sha256,
        files=files,
        snapshot_mount=require_host_configuration_snapshot_mount(captured),
    )


def _parse_prefix_installation_input(
    raw: bytes, *, expected_version: str | None
) -> ConfiguredPrefixRuntimeAuditInput:
    _require(type(raw) is bytes and 0 < len(raw) <= 128 * 1024, "INPUT_INVALID")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, "INPUT_INVALID")
            result[key] = value
        return result

    def reject(_value: str) -> Any:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PREFIX_INPUT_INVALID")

    def closed(value: object, keys: set[str]) -> dict[str, Any]:
        _require(type(value) is dict and set(cast(dict[str, Any], value)) == keys, "INPUT_INVALID")
        return cast(dict[str, Any], value)

    def member(value: object) -> RuntimeWheelMemberPin:
        item = closed(value, {"sha256", "size_bytes"})
        return RuntimeWheelMemberPin(item["sha256"], item["size_bytes"])

    def archive(value: object) -> RuntimeWheelArchivePin:
        item = closed(value, {"filename", "sha256", "size_bytes"})
        return RuntimeWheelArchivePin(item["filename"], item["sha256"], item["size_bytes"])

    try:
        document: object = json.loads(
            raw, object_pairs_hook=unique, parse_constant=reject, parse_float=reject
        )
        _require(type(document) is dict, "INPUT_INVALID")
        assert isinstance(document, dict)
        version = document.get("schema_version")
        _require(
            type(version) is str
            and version in {"embedding-prefix-audit-input/1.0", "embedding-prefix-audit-input/1.1"}
            and (expected_version is None or version == expected_version),
            "INPUT_INVALID",
        )
        selected_bootstrap = (
            _SNAPSHOT_BOOTSTRAP if version == "embedding-prefix-audit-input/1.1" else _BOOTSTRAP
        )
        item = closed(
            document,
            {
                "schema_version",
                "profile",
                "host_seed_sha256",
                "conda_source",
                "conda_archives",
                "public_archives",
                "private_archives",
                "created_at",
                "history",
                "helper",
                "bootstrap",
            }
            | ({"host_configuration"} if version == "embedding-prefix-audit-input/1.1" else set()),
        )
        _require(
            type(item["profile"]) is str
            and item["profile"] in _COUNTS
            and type(item["host_seed_sha256"]) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["host_seed_sha256"]) is not None,
            "INPUT_INVALID",
        )
        for name, count in (
            ("conda_archives", 31),
            ("public_archives", _COUNTS[item["profile"]]),
            ("private_archives", 1 if item["profile"] == "CPU_INDEX_FP32" else 2),
            ("bootstrap", len(selected_bootstrap)),
        ):
            _require(type(item[name]) is list and len(item[name]) == count, "INPUT_INVALID")
        public = tuple(archive(value) for value in item["public_archives"])
        overlays = tuple(
            sorted(
                (
                    pin
                    for pin in public
                    if pin.wheel_filename.split("-", 1)[0]
                    in {"pip", "wheel", "setuptools", "packaging"}
                ),
                key=lambda pin: pin.wheel_filename,
            )
        )
        source = member(item["conda_source"])
        conda_pins = []
        for value in item["conda_archives"]:
            row = closed(value, {"filename", "sha256", "size_bytes"})
            conda_pins.append(
                CondaRuntimeArchivePin(row["filename"], row["sha256"], row["size_bytes"])
            )
        private_pins = []
        for value in item["private_archives"]:
            row = closed(value, {"name", "archive", "source_commit", "source_archive"})
            source_row = closed(row["source_archive"], {"sha256", "size_bytes"})
            private_pins.append(
                PrefixSourceWheelPin(
                    row["name"],
                    archive(row["archive"]),
                    row["source_commit"],
                    PrefixSourceArchivePin(source_row["sha256"], source_row["size_bytes"]),
                )
            )
        bootstrap = []
        for value in item["bootstrap"]:
            row = closed(value, {"filename", "sha256", "size_bytes"})
            _require(
                type(row["filename"]) is str
                and row["filename"] in selected_bootstrap
                and type(row["size_bytes"]) is int
                and 0 <= row["size_bytes"] <= 1024**2
                and type(row["sha256"]) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", row["sha256"]) is not None,
                "INPUT_INVALID",
            )
            bootstrap.append((row["filename"], row["sha256"], row["size_bytes"]))
        _require(
            tuple(row[0] for row in bootstrap) == tuple(sorted(selected_bootstrap)), "INPUT_INVALID"
        )
        snapshot = None
        if version == "embedding-prefix-audit-input/1.1":
            from eom_catalog_service.embedding_host_configuration_capture import (
                parse_host_configuration_snapshot_pin,
            )

            snapshot = parse_host_configuration_snapshot_pin(item["host_configuration"])
        plan = PrefixRuntimeAuditPlan(
            CondaRuntimeAuditPlan(
                item["profile"], source.sha256, source.size_bytes, tuple(conda_pins), overlays
            ),
            public,
            tuple(private_pins),
            member(item["created_at"]),
            member(item["history"]),
            member(item["helper"]),
        )
        return ConfiguredPrefixRuntimeAuditInput(
            plan, item["host_seed_sha256"], tuple(bootstrap), snapshot
        )
    except InstalledRuntimeProofError:
        raise
    except Exception:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PREFIX_INPUT_INVALID") from None


@dataclass(frozen=True, slots=True)
class _Source:
    pins: dict[str, tuple[str, int]]
    documents: dict[str, bytes]


def _git_source(descriptor: int, size: int, commit: str) -> _Source:
    """Fixed plain Git tar, bounded before TarInfo/PAX allocation; never extraction."""
    pins: dict[str, tuple[str, int]] = {}
    documents: dict[str, bytes] = {}
    offset = count = 0
    comment = False
    prefix: str | None = None
    zeros = 0
    while offset < size:
        header = os.pread(descriptor, 512, offset)
        _require(len(header) == 512, "SOURCE_INVALID")
        offset += 512
        if header == bytes(512):
            zeros += 1
            if zeros == 2:
                while offset < size:
                    tail = os.pread(descriptor, min(65536, size - offset), offset)
                    _require(bool(tail) and tail == bytes(len(tail)), "SOURCE_INVALID")
                    offset += len(tail)
                break
            continue
        _require(zeros == 0 and count < 20000, "SOURCE_INVALID")
        info = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        count += 1
        _require(
            0 <= info.size <= 64 * 1024**2 and offset + ((info.size + 511) // 512) * 512 <= size,
            "SOURCE_INVALID",
        )
        if info.type == tarfile.XGLTYPE:
            expected = f"comment={commit}\n".encode()
            length = len(expected) + 3
            while len(str(length).encode()) + 1 + len(expected) != length:
                length = len(str(length).encode()) + 1 + len(expected)
            _require(
                not comment
                and count == 1
                and info.size == length
                and os.pread(descriptor, info.size, offset)
                == str(length).encode() + b" " + expected,
                "SOURCE_COMMIT_INVALID",
            )
            comment = True
        else:
            if prefix is None:
                prefix = commit + "/" if info.name.rstrip("/") == commit else ""
            _require(
                not prefix or info.name == commit or info.name.startswith(prefix),
                "SOURCE_PREFIX_INVALID",
            )
            name = info.name[len(prefix) :] if prefix and info.name != commit else info.name
            if info.isdir():
                if name not in {"", commit}:
                    _relative(name.removesuffix("/"))
                _require(info.size == 0, "SOURCE_INVALID")
                offset += ((info.size + 511) // 512) * 512
                continue
            path = _relative(name)
            _require(info.isreg() and path not in pins and comment, "SOURCE_INVALID")
            digest = hashlib.sha256()
            retain = path in {"pyproject.toml", "packages/gpu_lease/pyproject.toml"}
            _require(not retain or info.size <= 64 * 1024, "SOURCE_INVALID")
            chunks: list[bytes] = []
            read = 0
            while read < info.size:
                raw = os.pread(descriptor, min(65536, info.size - read), offset + read)
                _require(bool(raw), "SOURCE_INVALID")
                digest.update(raw)
                if retain:
                    chunks.append(raw)
                read += len(raw)
            pins[path] = "sha256:" + digest.hexdigest(), info.size
            if retain:
                documents[path] = b"".join(chunks)
        offset += ((info.size + 511) // 512) * 512
    _require(comment and zeros == 2 and "pyproject.toml" in documents, "SOURCE_INVALID")
    return _Source(pins, documents)


def _source_payload(source: _Source, package: str) -> dict[str, tuple[str, int]]:
    project_path = (
        "pyproject.toml" if package == "eom-platform" else "packages/gpu_lease/pyproject.toml"
    )
    _require(project_path in source.documents, "SOURCE_PROJECT_MISSING")
    project = tomllib.loads(source.documents[project_path].decode("utf-8", "strict"))
    _require(
        project["project"]["name"] == package and project["project"]["version"] == "0.1.0",
        "SOURCE_PROJECT_INVALID",
    )
    root = project["tool"]["setuptools"]["packages"]["find"]["where"]
    _require(
        type(root) is list and all(type(value) is str for value in root), "SOURCE_PROJECT_INVALID"
    )
    if package == "eom-platform":
        _require(len(root) == len(_ROOTS) and set(root) == _ROOTS, "SOURCE_PROJECT_INVALID")
        roots = tuple(root)
    else:
        _require(
            root == ["."]
            and project["tool"]["setuptools"]["packages"]["find"]["include"] == ["eom_gpu_lease*"],
            "SOURCE_PROJECT_INVALID",
        )
        roots = ("packages/gpu_lease",)
    patterns = project["tool"]["setuptools"].get("package-data", {})
    _require(type(patterns) is dict and len(patterns) <= 32, "SOURCE_PROJECT_INVALID")
    literals: set[str] = set()
    for namespace, values in patterns.items():
        _require(
            re.fullmatch(r"eom_[a-z0-9_]{1,64}", namespace) is not None
            and type(values) is list
            and len(values) <= 64
            and all(
                type(value) is str
                and len(value) <= 512
                and (
                    re.fullmatch(r"[A-Za-z0-9_/-]+/\*\.json", value)
                    or re.fullmatch(r"[A-Za-z0-9_/-]+/[A-Za-z0-9_.-]+\.json", value)
                )
                and not value.startswith("/")
                and all(part not in {"", ".", ".."} for part in value.split("/"))
                for value in values
            ),
            "SOURCE_PROJECT_INVALID",
        )
        literals.update(namespace + "/" + value for value in values if "*" not in value)
    result: dict[str, tuple[str, int]] = {}
    for path, pin in source.pins.items():
        for base in roots:
            if not path.startswith(base + "/"):
                continue
            target = path[len(base) + 1 :]
            namespace, separator, member = target.partition("/")
            if not separator or not (namespace == "eomctl" or namespace.startswith("eom_")):
                continue
            wanted = member.endswith(".py") or any(
                (member == pattern if "*" not in pattern else fnmatch.fnmatchcase(member, pattern))
                and member.count("/") == pattern.count("/")
                for pattern in patterns.get(namespace, [])
            )
            if wanted:
                _require(target not in result, "SOURCE_DUPLICATE_TARGET")
                result[target] = pin
    _require(bool(result), "SOURCE_PAYLOAD_MISSING")
    _require(literals <= set(result), "SOURCE_LITERAL_RESOURCE_MISSING")
    return result


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


def _ancestor_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _tree(
    prefix: Path, expected: set[Path], links: dict[Path, str], owner_uid: int
) -> tuple[dict[Path, tuple[int, ...]], int, int]:
    epochs: dict[Path, tuple[int, ...]] = {}
    observed: set[Path] = set()
    size = regular = 0
    for parent, directories, names in os.walk(prefix, followlinks=False):
        directory = Path(parent)
        value = directory.lstat()
        _require(len(epochs) < _MAX_MEMBERS, "TREE_TOO_LARGE")
        _require(
            stat.S_ISDIR(value.st_mode) and value.st_uid == owner_uid and not value.st_mode & 0o022,
            "TREE_UNPROTECTED",
        )
        epochs[directory] = _identity(value)
        for name in (*directories, *names):
            path = directory / name
            value = path.lstat()
            if stat.S_ISDIR(value.st_mode):
                continue
            _require(
                path in expected
                and value.st_uid == owner_uid
                and value.st_nlink == 1
                and (stat.S_ISLNK(value.st_mode) or not value.st_mode & 0o6022),
                "TREE_MEMBER_INVALID",
            )
            _require(len(observed) < _MAX_MEMBERS, "TREE_TOO_LARGE")
            observed.add(path)
            epochs[path] = _identity(value)
            if stat.S_ISLNK(value.st_mode):
                _require(path in links and os.readlink(path) == links[path], "TREE_LINK_INVALID")
            else:
                _require(stat.S_ISREG(value.st_mode) and path not in links, "TREE_MEMBER_INVALID")
                size += value.st_size
                regular += 1
                _require(size <= _MAX_BYTES, "TREE_TOO_LARGE")
            if path.suffix == ".pth":
                _require(
                    path == prefix / "lib/python3.12/site-packages/distutils-precedence.pth",
                    "HOOK_FORBIDDEN",
                )
            _require(
                path.suffix not in {".pyo", ".egg-link"}
                and not any(part.endswith(".egg-info") for part in path.parts),
                "HOOK_FORBIDDEN",
            )
    _require(observed == expected, "TREE_SET_MISMATCH")
    ancestors = {
        parent for path in expected for parent in path.parents if parent.is_relative_to(prefix)
    }
    _require(set(epochs) - observed == ancestors, "TREE_DIRECTORY_SET_MISMATCH")
    return epochs, size, regular


@dataclass(frozen=True, slots=True)
class _Elf:
    path: Path
    needed: tuple[str, ...]
    soname: str | None
    rpath: tuple[str, ...]
    runpath: tuple[str, ...]
    definitions: frozenset[str]
    requirements: tuple[tuple[str, frozenset[str]], ...]


def _readelf(path: Path, raw: bytes) -> _Elf:
    _require(0 < len(raw) <= MAX_READELF_OUTPUT_BYTES, "ELF_INVALID")
    text = raw.decode("ascii", "strict")
    _require(
        re.search(r"^\s*Class:\s+ELF64\s*$", text, re.M) is not None
        and re.search(r"^\s*Data:\s+2's complement, little endian\s*$", text, re.M) is not None
        and re.search(r"^\s*Machine:\s+Advanced Micro Devices X86-64\s*$", text, re.M) is not None,
        "ELF_FOREIGN",
    )
    interpreters = re.findall(r"\[Requesting program interpreter: ([^\]]+)\]", text)
    _require(interpreters in ([], ["/lib64/ld-linux-x86-64.so.2"]), "ELF_LOADER_INVALID")
    needed = tuple(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", text))
    _require(
        len(needed) <= 64
        and len(needed) == text.count("(NEEDED)")
        and len(set(needed)) == len(needed)
        and all(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", value) for value in needed),
        "ELF_INVALID",
    )
    sonames = re.findall(r"\(SONAME\)\s+Library soname: \[([^\]]+)\]", text)
    _require(
        len(sonames) <= 1
        and len(sonames) == text.count("(SONAME)")
        and all(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", value) for value in sonames),
        "ELF_INVALID",
    )
    routes = []
    for tag in ("RPATH", "RUNPATH"):
        values = re.findall(r"\(" + tag + r"\)\s+Library (?:rpath|runpath): \[([^\]]*)\]", text)
        _require(len(values) <= 1 and len(values) == text.count(f"({tag})"), "ELF_ROUTE_INVALID")
        routes.append(tuple(values[0].split(":")) if values else ())
    _require(
        not re.search(r"\((?:AUDIT|DEPAUDIT|FILTER|AUXILIARY|TEXTREL)\)", text), "ELF_FLAGS_INVALID"
    )
    for tag, allowed in (
        ("FLAGS", {"SYMBOLIC", "BIND_NOW", "STATIC_TLS", "ORIGIN"}),
        ("FLAGS_1", {"NOW", "NODELETE", "PIE", "ORIGIN"}),
    ):
        flags = re.findall(r"\(" + tag + r"\)[ \t]+(?:Flags:[ \t]*)?([^\n]*)", text)
        _require(
            len(flags) <= 1
            and len(flags) == text.count(f"({tag})")
            and all(set(value.split()) <= allowed for value in flags),
            "ELF_FLAGS_INVALID",
        )
    definitions: set[str] = set()
    base_definition: str | None = None
    requirements: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    current: str | None = None
    section: str | None = None
    definition_count: int | None = None
    requirement_count: int | None = None
    for line in text.splitlines():
        if line.startswith("Version definition section "):
            match = re.search(r"contains ([0-9]+) entr(?:y|ies):$", line)
            _require(match is not None and definition_count is None, "ELF_VERSION_INVALID")
            assert match is not None
            definition_count = int(match[1])
            _require(0 < definition_count <= 4096, "ELF_VERSION_INVALID")
            section, current = "definition", None
        elif line.startswith("Version needs section "):
            match = re.search(r"contains ([0-9]+) entr(?:y|ies):$", line)
            _require(match is not None and requirement_count is None, "ELF_VERSION_INVALID")
            assert match is not None
            requirement_count = int(match[1])
            _require(0 < requirement_count <= 64, "ELF_VERSION_INVALID")
            section, current = "needs", None
        elif line.startswith("Version symbols section "):
            section, current = None, None
        elif section == "definition":
            # BASE identifies the build object, not an exported version or a loader path.
            base = re.search(
                r"\bFlags:\s+BASE\s+Index:\s+1\s+Cnt:\s+1\s+"
                r"Name: ([A-Za-z0-9_./+-]{1,512})\s*$",
                line,
            )
            if base:
                _require(base_definition is None, "ELF_VERSION_INVALID")
                base_definition = base[1]
            else:
                _require(not re.search(r"\bFlags:\s+BASE\b", line), "ELF_VERSION_INVALID")
                match = re.search(r"\bName: ([A-Za-z0-9_.+-]{1,128})\s*$", line)
                if match:
                    _require(match[1] not in definitions, "ELF_VERSION_INVALID")
                    definitions.add(match[1])
        elif section == "needs":
            file = re.search(r"\bFile: ([A-Za-z0-9_.+-]{1,128})\s+Cnt: ([0-9]+)\s*$", line)
            if file:
                _require(file[1] in needed and file[1] not in requirements, "ELF_VERSION_INVALID")
                current = file[1]
                requirements[current] = set()
                counts[current] = int(file[2])
                _require(0 < counts[current] <= 4096, "ELF_VERSION_INVALID")
            elif current is not None:
                match = re.search(r"\bName: ([A-Za-z0-9_.+-]{1,128})\s+Flags:", line)
                if match:
                    _require(match[1] not in requirements[current], "ELF_VERSION_INVALID")
                    requirements[current].add(match[1])
    _require(
        (
            definition_count is None
            or definition_count == len(definitions) + (base_definition is not None)
        )
        and (requirement_count is None or requirement_count == len(requirements))
        and all(len(requirements[name]) == count for name, count in counts.items()),
        "ELF_VERSION_INVALID",
    )
    return _Elf(
        path,
        needed,
        sonames[0] if sonames else None,
        routes[0],
        routes[1],
        frozenset(definitions),
        tuple((name, frozenset(values)) for name, values in requirements.items()),
    )


def _routes(
    elf: _Elf,
    prefix: Path,
    directories: set[Path],
    *,
    links: dict[Path, str],
    host: ProtectedEmbeddingHostClosure,
    empty_directory: RuntimeFileEpoch | None = None,
) -> tuple[Path, ...]:
    values = elf.runpath or elf.rpath
    result: list[Path] = []
    for value in values:
        if value == "":
            _require(empty_directory is not None, "ELF_ROUTE_INVALID")
            assert empty_directory is not None
            empty_directory.assert_unchanged()
            # ld.so really searches cwd. A captured empty immutable namespace
            # proves no candidate there; it is not an ignored arbitrary route.
            continue
        if value.startswith("/"):
            host.assert_absent_search_route(value)
            continue
        _require(
            value == "$ORIGIN"
            or value.startswith("$ORIGIN/")
            or value == "${ORIGIN}"
            or value.startswith("${ORIGIN}/"),
            "ELF_ROUTE_INVALID",
        )
        suffix = (
            value.removeprefix("${ORIGIN}")
            if value.startswith("${ORIGIN}")
            else value.removeprefix("$ORIGIN")
        )
        _require("$" not in suffix and "\\" not in suffix, "ELF_ROUTE_INVALID")
        path = Path(os.path.normpath(str(elf.path.parent) + suffix))
        _require(path.is_relative_to(prefix), "ELF_ROUTE_INVALID")
        path = _resolve_alias(path, prefix, links)
        # The complete immutable tree proves this directory is absent, just as ld.so observes.
        if path in directories:
            result.append(path)
    return tuple(result)


def _resolve_alias(candidate: Path, prefix: Path, links: dict[Path, str]) -> Path:
    visits: set[Path] = set()
    while True:
        _require(candidate.is_relative_to(prefix), "ELF_ROUTE_INVALID")
        relative = candidate.relative_to(prefix)
        partial = prefix
        for index, component in enumerate(relative.parts):
            partial /= component
            if partial in links:
                _require(partial not in visits and len(visits) < 64, "ELF_ROUTE_INVALID")
                visits.add(partial)
                candidate = Path(
                    os.path.normpath(
                        partial.parent / links[partial] / Path(*relative.parts[index + 1 :])
                    )
                )
                break
        else:
            return candidate


def _elf_closure(
    prefix: Path,
    inventory: set[Path],
    links: dict[Path, str],
    files: NumericalRuntimeFileSnapshots,
    host: ProtectedEmbeddingHostClosure,
    deadline: float,
) -> tuple[str, int]:
    objects: dict[Path, _Elf] = {}
    for path in sorted(inventory - set(links)):
        with files.open_verified_member(path) as (descriptor, _sha):
            if os.pread(descriptor, 4, 0) == b"\x7fELF":
                _require(len(objects) < 1024 and time.monotonic() < deadline, "ELF_LIMIT")
                objects[path] = _readelf(
                    path,
                    host.inspect_elf(descriptor, deadline=min(deadline, time.monotonic() + 90.0)),
                )
    host.fixed_loader_path()
    empty_directory = None
    if any("" in (elf.runpath or elf.rpath) for elf in objects.values()):
        _require(
            prefix == fixed_native_embedding_profile("CUDA_INDEX_FP32").prefix,
            "ELF_ROUTE_INVALID",
        )
        empty_directory = capture_cuda_loader_directory(files)
    directories = {
        parent for member in inventory for parent in member.parents if parent.is_relative_to(prefix)
    }
    directories.update(path for path in links if _resolve_alias(path, prefix, links) in directories)
    edge_count = 0
    result = []
    # One fixed Python process. RPATH is transitive; RUNPATH is direct-only.
    main = objects.get(prefix / "bin/python3.12")
    main_routes = (
        _routes(main, prefix, directories, links=links, host=host, empty_directory=empty_directory)
        if main is not None and not main.runpath
        else ()
    )
    needed_names = {name for elf in objects.values() for name in elf.needed}
    entry_paths = {
        path
        for path, elf in objects.items()
        if path == prefix / "bin/python3.12" or elf.soname is None or elf.soname not in needed_names
    }
    pending: list[tuple[Path, tuple[Path, ...]]] = [
        (path, () if path == prefix / "bin/python3.12" else main_routes)
        for path in sorted(entry_paths, reverse=True)
    ]
    # Dependencies inherit their loader's context, not an invented standalone Python parent.
    # Unvisited alternatives and disconnected components still receive complete inspection.
    remaining = sorted(objects.keys() - entry_paths, reverse=True)
    visited: set[Path] = set()
    seen: set[tuple[Path, tuple[Path, ...]]] = set()
    resolutions: dict[tuple[Path, str], Path | str] = {}
    while pending or remaining:
        if not pending:
            fallback = remaining.pop()
            if fallback in visited:
                continue
            pending.append((fallback, main_routes))
        path, inherited = pending.pop()
        if (path, inherited) in seen:
            continue
        seen.add((path, inherited))
        visited.add(path)
        elf = objects[path]
        own = _routes(
            elf, prefix, directories, links=links, host=host, empty_directory=empty_directory
        )
        search = own if elf.runpath else own + inherited
        for name in elf.needed:
            edge_count += 1
            _require(edge_count <= 8192, "ELF_LIMIT")
            selected: Path | None = None
            for root in search:
                candidate = _resolve_alias(root / name, prefix, links)
                if candidate in inventory:
                    _require(candidate in objects, "ELF_TARGET_INVALID")
                    selected = candidate
                    break
            required = dict(elf.requirements).get(name, frozenset())
            if selected is not None:
                target = selected
                _require(
                    objects[target].soname in {None, name}
                    and required <= objects[target].definitions,
                    "ELF_VERSION_UNAVAILABLE",
                )
                next_routes = inherited if elf.runpath else own + inherited
                _require(len(next_routes) <= 32, "ELF_ROUTE_INVALID")
                pending.append((target, tuple(dict.fromkeys(next_routes))))
                _require(resolutions.get((path, name), target) == target, "ELF_AMBIGUOUS")
                resolutions[path, name] = target
                result.append(
                    (
                        str(path.relative_to(prefix)),
                        name,
                        str(target.relative_to(prefix)),
                        sorted(required),
                    )
                )
            else:
                _require(required <= host.fixed_soname_versions(name), "ELF_VERSION_UNAVAILABLE")
                _require(
                    resolutions.get((path, name), "FIXED_HOST") == "FIXED_HOST", "ELF_AMBIGUOUS"
                )
                resolutions[path, name] = "FIXED_HOST"
                result.append((str(path.relative_to(prefix)), name, "FIXED_HOST", sorted(required)))
    if empty_directory is not None:
        empty_directory.assert_unchanged()
        return _digest(
            {
                "edges": sorted(result),
                "empty_cuda_loader_directory": {
                    "path": str(empty_directory.path),
                    "identity": empty_directory.identity,
                    "ancestors": tuple(
                        (str(path), identity) for path, identity in empty_directory.ancestors
                    ),
                },
            }
        ), len(objects)
    # Preserve the historical CPU digest when no empty search component was used.
    return _digest(sorted(result)), len(objects)


def audit_installed_embedding_prefix(
    plan: PrefixRuntimeAuditPlan,
    *,
    prefix: Path,
    archive_root: Path,
    helper_path: Path,
    lock_directory: Path,
    files: NumericalRuntimeFileSnapshots,
    host: ProtectedEmbeddingHostClosure,
) -> PrefixRuntimeByteAudit:
    """Actual fixed whole-prefix bytes/ELF closure only; never execute NEW or grant IAM."""
    try:
        _require(type(plan) is PrefixRuntimeAuditPlan)
        plan.__post_init__()
        _require(
            prefix == fixed_native_embedding_profile(plan.conda.profile).prefix
            and all(
                isinstance(path, Path) and path.is_absolute() and ".." not in path.parts
                for path in (prefix, archive_root, helper_path, lock_directory)
            )
        )
        _require(
            type(host) is ProtectedEmbeddingHostClosure
            and type(files) is NumericalRuntimeFileSnapshots
        )
        host.assert_current()
        ancestor_epochs = tuple(
            (path, _ancestor_identity(path.lstat())) for path in reversed(prefix.parents)
        )
        deadline = time.monotonic() + 900.0
        sources: dict[str, _Source] = {}
        sources_by_name: dict[str, _Source] = {}
        with ExitStack() as stack:
            for pin in plan.private_archives:
                key = pin.source_archive.sha256
                if key not in sources:
                    path = archive_root / key[7:] / f"source-{pin.source_commit}.tar"
                    descriptor, _raw = stack.enter_context(
                        files.verified_open(
                            path,
                            sha256=key,
                            size=pin.source_archive.size_bytes,
                            maximum=64 * 1024**2,
                        )
                    )
                    sources[key] = _git_source(
                        descriptor, pin.source_archive.size_bytes, pin.source_commit
                    )
                else:
                    _require(
                        sources_by_name["eom-platform"] is sources[key]
                        and pin.source_commit == plan.private_archives[0].source_commit
                        and pin.source_archive == plan.private_archives[0].source_archive,
                        "SOURCE_CONFLICT",
                    )
                sources_by_name[pin.name] = sources[key]
            source = sources_by_name["eom-platform"]
            _require(
                source.pins.get("scripts/embedding/_install_experiment_snapshot.py")
                == (plan.helper.sha256, plan.helper.size_bytes),
                "HELPER_SOURCE_MISMATCH",
            )
            files.observe_protected_member_bytes(helper_path, maximum=1024**2)
            _fd, helper_raw = stack.enter_context(
                files.verified_open(
                    helper_path,
                    sha256=plan.helper.sha256,
                    size=plan.helper.size_bytes,
                    maximum=1024**2,
                    retain_bytes=True,
                )
            )
            module = types.ModuleType("_eom_embedding_index_snapshot")
            module.__file__ = str(helper_path)
            files.assert_unchanged()
            exec(compile(helper_raw, str(helper_path), "exec"), module.__dict__)
            for parent, name in _LOCKS:
                lock_pin = source.pins.get(parent + "/" + name)
                _require(lock_pin is not None, "LOCK_SOURCE_MISSING")
                assert lock_pin is not None
                files.verify(
                    lock_directory / name, sha256=lock_pin[0], size=lock_pin[1], maximum=128 * 1024
                )
            reader = cast(Callable[[Path, str], object], module.index_runtime_locks)
            expected = reader(lock_directory, plan.conda.profile)
            files.assert_unchanged()
            _require(
                type(expected) is dict and len(expected) == _COUNTS[plan.conda.profile],
                "LOCK_CLOSURE_INVALID",
            )
            rows = cast(dict[str, tuple[str, str, str]], expected)
            _require(
                all(
                    type(name) is str
                    and type(row) is tuple
                    and len(row) == 3
                    and all(type(value) is str for value in row)
                    for name, row in rows.items()
                ),
                "LOCK_CLOSURE_INVALID",
            )
            public = {pin.wheel_filename: pin for pin in plan.public_archives}
            _require(
                set(public) == {row[1] for row in rows.values()}
                and all(public[row[1]].sha256 == "sha256:" + row[2] for row in rows.values()),
                "LOCK_CLOSURE_INVALID",
            )
            conda = audit_installed_conda31(
                plan.conda,
                prefix=prefix,
                archive_root=archive_root,
                files=files,
                tool_admission=host,
            )
            expected_members = set(conda.installed_members)
            links = dict(conda.installed_links)
            ownership: dict[Path, str] = {}
            overlays = {wheel.name: wheel for wheel in conda.overlay_wheels}
            for name, (version, filename, _sha) in sorted(rows.items()):
                archive = public[filename]
                if name in overlays:
                    verified = overlays[name]
                    _require(
                        verified.archive_sha256 == archive.sha256 and verified.version == version,
                        "OVERLAY_CONFLICT",
                    )
                else:
                    observed = observe_runtime_wheel_installation(
                        archive, name, version, prefix=prefix, files=files
                    )
                    verified = verify_installed_runtime_wheel(
                        observed, prefix=prefix, archive_root=archive_root, files=files
                    )
                for path in verified.all_installed_members:
                    _require(
                        path not in ownership
                        or path == prefix / "lib/python3.12/site-packages/nvidia/__init__.py",
                        "WHEEL_OWNERSHIP_CONFLICT",
                    )
                    ownership[path] = name
                expected_members.update(verified.all_installed_members)
            for private in plan.private_archives:
                observed = observe_runtime_wheel_installation(
                    private.archive, private.name, "0.1.0", prefix=prefix, files=files
                )
                verified = verify_installed_runtime_wheel(
                    observed, prefix=prefix, archive_root=archive_root, files=files
                )
                payload = _source_payload(sources_by_name[private.name], private.name)
                site = prefix / "lib/python3.12/site-packages"
                archive_payload = {
                    path
                    for path in verified.archive_payload_members
                    if not path.relative_to(site).parts[0].endswith(".dist-info")
                }
                _require(
                    archive_payload == {site / path for path in payload},
                    "PRIVATE_SOURCE_SET_MISMATCH",
                )
                for relative, (sha, member_size) in payload.items():
                    files.verify(site / relative, sha256=sha, size=member_size, maximum=2 * 1024**3)
                _require(
                    not set(verified.all_installed_members).intersection(ownership),
                    "WHEEL_OWNERSHIP_CONFLICT",
                )
                ownership.update((path, private.name) for path in verified.all_installed_members)
                expected_members.update(verified.all_installed_members)
            for name, metadata_pin in (("created_at", plan.created_at), ("history", plan.history)):
                path = prefix / "conda-meta" / name
                files.verify(
                    path, sha256=metadata_pin.sha256, size=metadata_pin.size_bytes, maximum=1024**2
                )
                expected_members.add(path)
            epochs, size, regular = _tree(prefix, expected_members, links, files.owner_uid)
            elf_hash, elf_count = _elf_closure(
                prefix, expected_members, links, files, host, deadline
            )
            member_values = []
            member_hashes: dict[Path, str] = {}
            for path in sorted(expected_members):
                mode = stat.S_IMODE(path.lstat().st_mode)
                if path in links:
                    member_values.append((str(path.relative_to(prefix)), mode, links[path]))
                else:
                    with files.open_verified_member(path) as (_descriptor, sha):
                        member_values.append((str(path.relative_to(prefix)), mode, sha))
                        member_hashes[path] = sha
            files.assert_unchanged()
            host.assert_current()
            _require(
                time.monotonic() < deadline
                and all(_identity(path.lstat()) == initial for path, initial in epochs.items())
                and all(
                    _ancestor_identity(path.lstat()) == initial for path, initial in ancestor_epochs
                ),
                "TREE_CHANGED",
            )
            _require(0 < len(epochs) - 1 <= _MAX_MEMBERS, "INVENTORY_INVALID")
            inventory = PrefixRuntimeInventory(
                prefix,
                files.owner_uid,
                epochs[prefix],
                ancestor_epochs,
                tuple(
                    PrefixRuntimeInventoryEntry(
                        str(path.relative_to(prefix)),
                        epochs[path],
                        member_hashes.get(path),
                        links.get(path),
                    )
                    for path in sorted(
                        set(epochs) - {prefix}, key=lambda member: str(member.relative_to(prefix))
                    )
                ),
            )
            _require(
                len(member_hashes) == regular
                and set(member_hashes) | set(links) == expected_members,
                "INVENTORY_INVALID",
            )
            return PrefixRuntimeByteAudit(
                plan.conda.profile,
                _digest(
                    [
                        (pin.name, pin.source_commit, pin.source_archive.sha256)
                        for pin in plan.private_archives
                    ]
                ),
                _digest([str(path.relative_to(prefix)) for path in sorted(expected_members)]),
                _digest(member_values),
                elf_hash,
                regular,
                len(links),
                size,
                elf_count,
                inventory,
            )
    except InstalledRuntimeProofError:
        raise
    except Exception:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PREFIX_INVALID") from None

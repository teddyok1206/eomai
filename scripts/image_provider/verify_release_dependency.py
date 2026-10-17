"""Closed image/standalone-lease release admission; never install or import ML packages."""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import re
import selectors
import stat
import struct
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name, parse_wheel_filename

MAX_WHEEL_BYTES = 256 * 1024**2
MAX_MEMBER_BYTES = 256 * 1024**2
MAX_EXPANDED_BYTES = 512 * 1024**2
MAX_METADATA_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 64 * 1024**2
MAX_RECORD_BYTES = 8 * 1024**2
MAX_CENTRAL_BYTES = 16 * 1024**2
MAX_WHEEL_MEMBERS = 20000
RUNTIME_METADATA_TIMEOUT_SECONDS = 15.0
ROLE_INFO = MappingProxyType(
    {
        "CONTRACT": (
            "eom-image-contracts",
            "0.1.0",
            "eom_image_contracts",
            "packages/image_contracts",
        ),
        "PROVIDER": (
            "eom-local-image-provider",
            "0.1.0",
            "eom_image_provider",
            "services/image_provider",
        ),
        "TRAINER": (
            "eom-local-image-trainer",
            "0.1.0",
            "eom_image_trainer",
            "services/image_trainer",
        ),
        "GPU_LEASE": ("eom-gpu-lease", "0.1.0", "eom_gpu_lease", "packages/gpu_lease"),
        "PEFT": ("peft", "0.17.1", "peft", None),
        "BITSANDBYTES": ("bitsandbytes", "0.47.0", "bitsandbytes", None),
    }
)
PREFIXES = MappingProxyType(
    {
        "provider": Path("/srv/eom/conda/envs/eom-image"),
        "trainer": Path("/srv/eom/conda/envs/eom-image-trainer"),
    }
)


class ImageReleaseError(ValueError):
    """Only content-free static error labels leave this admission boundary."""


class _EntryPointsParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True)
class WheelPin:
    role: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class VerifiedWheel:
    pin: WheelPin
    distribution: str
    version: str
    requirements: tuple[str, ...]
    python_requirement: str
    namespace_hashes: tuple[tuple[str, str], ...]
    tags: tuple[str, ...]


def _require(value: bool, code: str) -> None:
    if not value:
        raise ImageReleaseError("IMAGE_RELEASE_" + code)


def _epoch(value: os.stat_result) -> tuple[int, ...]:
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


def _safe_name(name: str) -> None:
    _require(
        bool(name) and not name.startswith("/") and "\\" not in name and "\x00" not in name,
        "MEMBER_PATH_INVALID",
    )
    _require(all(part not in {"", ".", ".."} for part in name.split("/")), "MEMBER_PATH_INVALID")
    _require(PurePosixPath(name).as_posix() == name, "MEMBER_PATH_INVALID")


def _protected(path: Path, *, private: bool = False) -> None:
    _require(path.is_absolute() and ".." not in path.parts, "PATH_INVALID")
    for member in (path, *path.parents):
        value = member.lstat()
        sticky_root = (
            stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
        )
        _require(not stat.S_ISLNK(value.st_mode), "PATH_INVALID")
        _require(value.st_uid in {0, os.geteuid()}, "PATH_OWNER_INVALID")
        _require(not value.st_mode & 0o022 or sticky_root, "PATH_MODE_INVALID")
    if private:
        _require(stat.S_IMODE(path.stat().st_mode) == 0o700, "QUARANTINE_MODE_INVALID")


def _read_file(path: Path, *, maximum: int, single_link: bool = True) -> bytes:
    _protected(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        initial = os.fstat(descriptor)
        _require(
            stat.S_ISREG(initial.st_mode)
            and (initial.st_nlink == 1 if single_link else initial.st_nlink >= 1),
            "FILE_INVALID",
        )
        _require(0 <= initial.st_size <= maximum, "FILE_SIZE_INVALID")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024**2, maximum + 1 - total)):
            total += len(chunk)
            _require(total <= maximum, "FILE_SIZE_INVALID")
            chunks.append(chunk)
        _require(
            total == initial.st_size and _epoch(initial) == _epoch(os.fstat(descriptor)),
            "FILE_CHANGED",
        )
        _require(_epoch(initial) == _epoch(path.lstat()), "FILE_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _namespace_source(source_root: Path, project: str, namespace: str) -> dict[str, str]:
    root = source_root / project / namespace
    _protected(root)
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), "SOURCE_LINK_INVALID")
        if path.is_dir():
            continue
        _require(
            "__pycache__" not in path.parts and path.suffix != ".pyc", "SOURCE_GENERATED_INVALID"
        )
        _require(
            path.suffix in {".py", ".json", ".txt"} or path.name == "py.typed",
            "SOURCE_MEMBER_INVALID",
        )
        result[path.relative_to(root.parent).as_posix()] = _digest(
            _read_file(path, maximum=8 * 1024**2)
        )
    return result


def _source_requirements(source_root: Path, project: str) -> tuple[str, str, tuple[str, ...], str]:
    metadata = tomllib.loads(
        _read_file(source_root / project / "pyproject.toml", maximum=MAX_METADATA_BYTES).decode()
    )["project"]
    requirements = [str(Requirement(value)) for value in metadata.get("dependencies", [])]
    for extra, values in metadata.get("optional-dependencies", {}).items():
        for value in values:
            requirements.append(str(Requirement(value + f'; extra == "{extra}"')))
    return (
        canonicalize_name(metadata["name"]),
        metadata["version"],
        tuple(sorted(requirements)),
        str(SpecifierSet(metadata["requires-python"])),
    )


def _wheel_central_directory(descriptor: int, size: int) -> int:
    """Bound actual ZIP32 central headers before ZipFile allocates its member list."""
    tail_size = min(size, 22 + 65535)
    tail = os.pread(descriptor, tail_size, size - tail_size)
    _require(len(tail) == tail_size, "WHEEL_ZIP_EOCD_INVALID")
    position = tail.rfind(b"PK\x05\x06")
    _require(position >= 0 and position + 22 <= len(tail), "WHEEL_ZIP_EOCD_INVALID")
    _, disk, central_disk, disk_count, count, central_size, central_offset, comment = (
        struct.unpack_from("<4s4H2IH", tail, position)
    )
    _require(comment == 0, "WHEEL_COMMENT_INVALID")
    _require(position + 22 == len(tail), "WHEEL_ZIP_EOCD_INVALID")
    eocd_offset = size - tail_size + position
    _require(
        disk_count != 0xFFFF
        and count != 0xFFFF
        and central_size != 0xFFFFFFFF
        and central_offset != 0xFFFFFFFF,
        "WHEEL_ZIP64_UNSUPPORTED",
    )
    _require(
        eocd_offset < 20 or os.pread(descriptor, 4, eocd_offset - 20) != b"PK\x06\x07",
        "WHEEL_ZIP64_UNSUPPORTED",
    )
    _require(disk == central_disk == 0 and disk_count == count, "WHEEL_MULTIDISK_UNSUPPORTED")
    _require(0 < count <= MAX_WHEEL_MEMBERS, "WHEEL_MEMBERS_INVALID")
    _require(0 < central_size <= MAX_CENTRAL_BYTES, "WHEEL_CENTRAL_TOO_LARGE")
    _require(central_offset + central_size == eocd_offset, "WHEEL_CENTRAL_INVALID")
    central = os.pread(descriptor, central_size, central_offset)
    _require(len(central) == central_size, "WHEEL_CENTRAL_INVALID")
    position, actual_count = 0, 0
    while position < len(central):
        _require(
            position + 46 <= len(central) and central[position : position + 4] == b"PK\x01\x02",
            "WHEEL_CENTRAL_INVALID",
        )
        actual_count += 1
        _require(actual_count <= MAX_WHEEL_MEMBERS, "WHEEL_MEMBERS_INVALID")
        name_size, extra_size, member_comment, member_disk = struct.unpack_from(
            "<4H", central, position + 28
        )
        compressed, expanded = struct.unpack_from("<2I", central, position + 20)
        local_offset = struct.unpack_from("<I", central, position + 42)[0]
        needed = struct.unpack_from("<H", central, position + 6)[0]
        _require(
            needed < 45
            and compressed != 0xFFFFFFFF
            and expanded != 0xFFFFFFFF
            and local_offset != 0xFFFFFFFF,
            "WHEEL_ZIP64_UNSUPPORTED",
        )
        _require(member_disk == 0, "WHEEL_MULTIDISK_UNSUPPORTED")
        _require(member_comment == 0, "WHEEL_COMMENT_INVALID")
        end = position + 46 + name_size + extra_size + member_comment
        _require(name_size > 0 and end <= len(central), "WHEEL_CENTRAL_INVALID")
        extra_position, extra_end = position + 46 + name_size, end
        while extra_position < extra_end:
            _require(extra_position + 4 <= extra_end, "WHEEL_CENTRAL_INVALID")
            kind, length = struct.unpack_from("<2H", central, extra_position)
            _require(kind != 0x0001, "WHEEL_ZIP64_UNSUPPORTED")
            extra_position += 4 + length
            _require(extra_position <= extra_end, "WHEEL_CENTRAL_INVALID")
        position = end
    _require(actual_count == count, "WHEEL_CENTRAL_COUNT_INVALID")
    return actual_count


def verify_wheel(pin: WheelPin, source_root: Path) -> VerifiedWheel:
    _require(
        pin.role in ROLE_INFO and re.fullmatch(r"[0-9a-f]{64}", pin.sha256) is not None,
        "WHEEL_PIN_INVALID",
    )
    distribution, version, namespace, project = ROLE_INFO[pin.role]
    parsed_name, parsed_version, build, tags = parse_wheel_filename(pin.path.name)
    _require(
        canonicalize_name(parsed_name) == distribution
        and str(parsed_version) == version
        and not build,
        "WHEEL_IDENTITY_INVALID",
    )
    if project is not None:
        expected_filename = distribution.replace("-", "_") + f"-{version}-py3-none-any.whl"
        _require(pin.path.name == expected_filename, "WHEEL_FILENAME_INVALID")
    _protected(pin.path)
    descriptor = os.open(pin.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        initial = os.fstat(descriptor)
        _require(
            stat.S_ISREG(initial.st_mode)
            and initial.st_nlink == 1
            and stat.S_IMODE(initial.st_mode) == 0o600,
            "WHEEL_FILE_INVALID",
        )
        _require(0 < initial.st_size <= MAX_WHEEL_BYTES, "WHEEL_SIZE_INVALID")
        digest = hashlib.sha256()
        offset = 0
        while chunk := os.pread(descriptor, min(1024**2, MAX_WHEEL_BYTES + 1 - offset), offset):
            digest.update(chunk)
            offset += len(chunk)
            _require(offset <= MAX_WHEEL_BYTES, "WHEEL_SIZE_INVALID")
        _require(
            offset == initial.st_size and digest.hexdigest() == pin.sha256, "WHEEL_HASH_MISMATCH"
        )
        member_count = _wheel_central_directory(descriptor, initial.st_size)
        _require(
            _epoch(initial) == _epoch(os.fstat(descriptor)) == _epoch(pin.path.lstat()),
            "WHEEL_CHANGED",
        )
        with os.fdopen(os.dup(descriptor), "rb") as stream, zipfile.ZipFile(stream) as archive:
            _require(not archive.comment, "WHEEL_COMMENT_INVALID")
            infos = archive.infolist()
            _require(len(infos) == member_count, "WHEEL_MEMBERS_INVALID")
            names: dict[str, zipfile.ZipInfo] = {}
            expanded = 0
            for info in infos:
                _safe_name(info.filename)
                _require(info.filename not in names, "WHEEL_DUPLICATE_MEMBER")
                _require(not info.is_dir() and not info.flag_bits & 1, "WHEEL_MEMBER_INVALID")
                mode = info.external_attr >> 16
                _require(not mode or stat.S_ISREG(mode), "WHEEL_MEMBER_INVALID")
                _require(info.file_size <= MAX_MEMBER_BYTES, "WHEEL_MEMBER_TOO_LARGE")
                expanded += info.file_size
                _require(expanded <= MAX_EXPANDED_BYTES, "WHEEL_EXPANDED_TOO_LARGE")
                names[info.filename] = info
            dist_info = distribution.replace("-", "_") + f"-{version}.dist-info"
            record_name = dist_info + "/RECORD"
            _require(
                {name.split("/", 1)[0] for name in names if ".dist-info/" in name} == {dist_info},
                "WHEEL_DIST_INFO_INVALID",
            )
            _require(
                record_name in names and names[record_name].file_size <= MAX_RECORD_BYTES,
                "WHEEL_RECORD_INVALID",
            )
            rows = csv.reader(io.StringIO(archive.read(record_name).decode("utf-8")), strict=True)
            records: dict[str, tuple[str, str]] = {}
            for row in rows:
                _require(len(row) == 3 and row[0] not in records, "WHEEL_RECORD_INVALID")
                _safe_name(row[0])
                records[row[0]] = row[1], row[2]
                _require(len(records) <= len(names), "WHEEL_RECORD_SET_INVALID")
            _require(set(records) == set(names), "WHEEL_RECORD_SET_INVALID")
            namespace_hashes: dict[str, str] = {}
            for name, info in names.items():
                declared_hash, declared_size = records[name]
                if name == record_name:
                    _require(not declared_hash and not declared_size, "WHEEL_RECORD_SELF_INVALID")
                    continue
                _require(
                    re.fullmatch(r"sha256=[A-Za-z0-9_-]{43}", declared_hash) is not None
                    and re.fullmatch(r"0|[1-9][0-9]{0,19}", declared_size) is not None,
                    "WHEEL_RECORD_VALUE_INVALID",
                )
                member_digest = hashlib.sha256()
                size = 0
                with archive.open(info) as member:
                    while chunk := member.read(1024**2):
                        member_digest.update(chunk)
                        size += len(chunk)
                        _require(size <= MAX_MEMBER_BYTES, "WHEEL_MEMBER_TOO_LARGE")
                encoded = base64.urlsafe_b64encode(member_digest.digest()).decode().rstrip("=")
                _require(
                    declared_hash == "sha256=" + encoded
                    and int(declared_size) == size == info.file_size,
                    "WHEEL_RECORD_CONTENT_MISMATCH",
                )
                if name.startswith(namespace + "/"):
                    namespace_hashes[name] = member_digest.hexdigest()
                elif name.startswith("eom_gpu_lease/"):
                    raise ImageReleaseError("IMAGE_RELEASE_MIXED_LEASE_OWNERSHIP")
                else:
                    _require(name.startswith(dist_info + "/"), "WHEEL_PAYLOAD_CLOSURE_INVALID")
            metadata_name, wheel_name = dist_info + "/METADATA", dist_info + "/WHEEL"
            _require(metadata_name in names and wheel_name in names, "WHEEL_METADATA_INVALID")
            _require(
                names[metadata_name].file_size <= MAX_METADATA_BYTES
                and names[wheel_name].file_size <= MAX_METADATA_BYTES,
                "WHEEL_METADATA_TOO_LARGE",
            )
            metadata = BytesParser().parsebytes(archive.read(metadata_name))
            wheel_metadata = BytesParser().parsebytes(archive.read(wheel_name))
            _require(
                len(metadata.get_all("Name", [])) == len(metadata.get_all("Version", [])) == 1,
                "WHEEL_METADATA_INVALID",
            )
            _require(
                canonicalize_name(metadata["Name"]) == distribution
                and metadata["Version"] == version,
                "WHEEL_METADATA_INVALID",
            )
            _require(
                set(wheel_metadata.get_all("Tag", [])) == {str(tag) for tag in tags},
                "WHEEL_TAG_INVALID",
            )
            requirements = tuple(
                sorted(str(Requirement(value)) for value in metadata.get_all("Requires-Dist", []))
            )
            python_requirement = str(SpecifierSet(metadata.get("Requires-Python", "")))
            if project is not None:
                expected = _source_requirements(source_root, project)
                _require(
                    (distribution, version, requirements, python_requirement) == expected,
                    "WHEEL_SOURCE_METADATA_MISMATCH",
                )
                _require(
                    namespace_hashes == _namespace_source(source_root, project, namespace),
                    "WHEEL_SOURCE_PAYLOAD_MISMATCH",
                )
                source_project = tomllib.loads(
                    _read_file(
                        source_root / project / "pyproject.toml", maximum=MAX_METADATA_BYTES
                    ).decode()
                )["project"]
                scripts = source_project.get("scripts", {})
                entries_name = dist_info + "/entry_points.txt"
                if scripts:
                    _require(
                        entries_name in names
                        and names[entries_name].file_size <= MAX_METADATA_BYTES,
                        "WHEEL_ENTRY_POINTS_INVALID",
                    )
                    entries = _EntryPointsParser(interpolation=None, strict=True)
                    entries.read_string(archive.read(entries_name).decode("utf-8"))
                    _require(
                        entries.sections() == ["console_scripts"]
                        and dict(entries.items("console_scripts")) == scripts,
                        "WHEEL_ENTRY_POINTS_INVALID",
                    )
                else:
                    _require(entries_name not in names, "WHEEL_ENTRY_POINTS_INVALID")
                top_name = dist_info + "/top_level.txt"
                _require(
                    top_name in names
                    and names[top_name].file_size == len(namespace) + 1
                    and archive.read(top_name) == (namespace + "\n").encode(),
                    "WHEEL_TOP_LEVEL_INVALID",
                )
                _require(
                    wheel_metadata.get("Root-Is-Purelib") == "true"
                    and wheel_metadata.get("Wheel-Version") == "1.0",
                    "WHEEL_TAG_INVALID",
                )
                _require(
                    set(metadata.get_all("Provides-Extra", []))
                    == set(source_project.get("optional-dependencies", {})),
                    "WHEEL_EXTRA_INVALID",
                )
                generated = {"METADATA", "WHEEL", "RECORD", "top_level.txt", "entry_points.txt"}
                _require(
                    all(
                        not name.startswith(dist_info + "/")
                        or name.split("/", 1)[1] in generated
                        or name.startswith(dist_info + "/licenses/")
                        for name in names
                    ),
                    "WHEEL_METADATA_CLOSURE_INVALID",
                )
                if pin.role == "GPU_LEASE":
                    _require(
                        set(namespace_hashes)
                        == {"eom_gpu_lease/__init__.py", "eom_gpu_lease/lease.py"}
                        and not requirements,
                        "LEASE_WHEEL_CLOSURE_INVALID",
                    )
            result = VerifiedWheel(
                pin,
                distribution,
                version,
                requirements,
                python_requirement,
                tuple(sorted(namespace_hashes.items())),
                tuple(sorted(str(tag) for tag in tags)),
            )
        _require(
            _epoch(initial) == _epoch(os.fstat(descriptor)) == _epoch(pin.path.lstat()),
            "WHEEL_CHANGED",
        )
        return result
    finally:
        os.close(descriptor)


def verify_build_wheels(
    profile: str, source_root: Path, pins: tuple[WheelPin, ...]
) -> tuple[VerifiedWheel, ...]:
    _require(profile in PREFIXES, "PROFILE_INVALID")
    roles = tuple(pin.role for pin in pins)
    _require(len(set(roles)) == len(roles), "WHEEL_DUPLICATE_ROLE")
    required = {"CONTRACT", "PROVIDER"} | ({"TRAINER"} if profile == "trainer" else set())
    _require(required <= set(roles) <= required | {"GPU_LEASE"}, "WHEEL_SET_INVALID")
    verified = tuple(verify_wheel(pin, source_root) for pin in pins)
    needs_lease = any(
        canonicalize_name(Requirement(value).name) == "eom-gpu-lease"
        for wheel in verified
        for value in wheel.requirements
    )
    _require(
        ("GPU_LEASE" in roles) == needs_lease,
        "LEASE_WHEEL_REQUIRED" if needs_lease else "LEASE_WHEEL_UNEXPECTED",
    )
    local_versions = {wheel.distribution: wheel.version for wheel in verified}
    for wheel in verified:
        for value in wheel.requirements:
            requirement = Requirement(value)
            name = canonicalize_name(requirement.name)
            if name in local_versions:
                _require(
                    requirement.url is None
                    and requirement.specifier.contains(local_versions[name]),
                    "SOURCE_DEPENDENCY_PINS_MISMATCH",
                )
    return verified


def _site_packages(prefix: Path) -> Path:
    _protected(prefix)
    matches = tuple((prefix / "lib").glob("python3.*/site-packages"))
    # Conda can retain python3.1 -> python3.11 for its Python3.11 layout.
    # A lexical alias is not a second runtime, but never select through that
    # alias or admit a different/escaping physical site as an implicit fallback.
    canonical = prefix / "lib/python3.11/site-packages"
    _require(
        bool(matches) and all(path.resolve(strict=True) == canonical for path in matches),
        "RUNTIME_SITE_INVALID",
    )
    _protected(canonical)
    return canonical


def verify_installed_lease_ownership(prefix: Path) -> dict[str, str]:
    site = _site_packages(prefix)
    # A sourceless sibling is not genuinely absent lease code, even without a RECORD owner.
    for bytecode in (site / "eom_gpu_lease.pyc", site / "eom_gpu_lease.pyo"):
        _require(
            not bytecode.exists() and not bytecode.is_symlink(),
            "INSTALLED_LEASE_BYTECODE_FORBIDDEN",
        )
    _require(
        next((site / "__pycache__").glob("eom_gpu_lease.*.py[co]"), None) is None,
        "INSTALLED_LEASE_BYTECODE_FORBIDDEN",
    )
    versions: dict[str, str] = {}
    owners: dict[str, str] = {}
    canonical_files: set[str] = set()
    for metadata_directory in site.glob("*.dist-info"):
        _protected(metadata_directory)
        for filename in ("METADATA", "RECORD"):
            # Conda legitimately hardlinks unrelated installed metadata to its protected cache.
            # Wheel/source inputs and the canonical lease payload retain single-link admission.
            _read_file(
                metadata_directory / filename,
                maximum=MAX_RECORD_BYTES,
                single_link=metadata_directory.name.startswith("eom_gpu_lease-"),
            )
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = canonicalize_name(distribution.metadata["Name"])
        _require(name not in versions, "INSTALLED_DUPLICATE_DISTRIBUTION")
        versions[name] = distribution.version
        if name == "eom-gpu-lease":
            metadata_root = f"eom_gpu_lease-{distribution.version}.dist-info/"
            for filename in ("METADATA", "RECORD"):
                _read_file(site / metadata_root / filename, maximum=MAX_RECORD_BYTES)
            direct_url = site / metadata_root / "direct_url.json"
            if direct_url.exists():
                value = json.loads(_read_file(direct_url, maximum=MAX_METADATA_BYTES))
                _require(
                    not value.get("dir_info", {}).get("editable", False), "INSTALLED_EDITABLE_LEASE"
                )
        for member in distribution.files or ():
            value = member.as_posix()
            if name == "eom-gpu-lease":
                _safe_name(value)
                _require(
                    value.startswith("eom_gpu_lease/") or value.startswith(metadata_root),
                    "INSTALLED_LEASE_COMPONENT_INVALID",
                )
                _require(
                    Path(value).suffix not in {".pyc", ".pyo"}, "INSTALLED_LEASE_BYTECODE_FORBIDDEN"
                )
            if value.startswith("eom_gpu_lease/"):
                _require(
                    name == "eom-gpu-lease" and value not in owners,
                    "INSTALLED_MIXED_LEASE_OWNERSHIP",
                )
                owners[value] = name
                path = site / value
                _protected(path)
                _require(path.is_file() and not path.is_symlink(), "INSTALLED_LEASE_FILE_INVALID")
                _require(path.suffix not in {".pyc", ".pyo"}, "INSTALLED_LEASE_BYTECODE_FORBIDDEN")
                _require(
                    member.hash is not None
                    and member.hash.mode == "sha256"
                    and member.size is not None,
                    "INSTALLED_LEASE_RECORD_INVALID",
                )
                member_hash = member.hash
                assert member_hash is not None
                raw = _read_file(path, maximum=8 * 1024**2)
                encoded = (
                    base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
                )
                _require(
                    member_hash.value == encoded and member.size == len(raw),
                    "INSTALLED_LEASE_RECORD_MISMATCH",
                )
                canonical_files.add(value)
    directory = site / "eom_gpu_lease"
    if directory.exists():
        _protected(directory)
        observed: set[str] = set()
        for path in directory.rglob("*"):
            _protected(path)
            _require(path.suffix not in {".pyc", ".pyo"}, "INSTALLED_LEASE_BYTECODE_FORBIDDEN")
            value = path.relative_to(site).as_posix()
            if path.is_dir():
                _require(value == "eom_gpu_lease/__pycache__", "INSTALLED_UNOWNED_LEASE_FILE")
            else:
                observed.add(value)
        _require(
            observed == canonical_files == {"eom_gpu_lease/__init__.py", "eom_gpu_lease/lease.py"},
            "INSTALLED_UNOWNED_LEASE_FILE",
        )
    else:
        _require(not canonical_files and "eom-gpu-lease" not in versions, "INSTALLED_LEASE_MISSING")
    return versions


def _runtime_environment(prefix: Path) -> dict[str, str]:
    _require(prefix in PREFIXES.values(), "RUNTIME_PREFIX_INVALID")
    _protected(prefix)
    interpreter = (prefix / "bin/python").resolve(strict=True)
    _require(interpreter.is_relative_to(prefix), "RUNTIME_INTERPRETER_INVALID")
    _protected(interpreter)
    code = (
        "import json, sys; from packaging.markers import default_environment; "
        "from packaging.tags import sys_tags; "
        "print(json.dumps({'prefix': sys.prefix, 'environment': default_environment(), "
        "'tags': [str(value) for value in sys_tags()]}))"
    )
    process = subprocess.Popen(
        (str(interpreter), "-I", "-B", "-c", code),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"},
    )
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + RUNTIME_METADATA_TIMEOUT_SECONDS
    try:
        _require(process.stdout is not None, "RUNTIME_METADATA_INVALID")
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "RUNTIME_METADATA_TIMEOUT")
                if not selector.select(remaining):
                    raise ImageReleaseError("IMAGE_RELEASE_RUNTIME_METADATA_TIMEOUT")
                chunk = os.read(process.stdout.fileno(), min(65536, MAX_METADATA_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= MAX_METADATA_BYTES, "RUNTIME_METADATA_TOO_LARGE")
                chunks.append(chunk)
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "RUNTIME_METADATA_TIMEOUT")
        try:
            status = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise ImageReleaseError("IMAGE_RELEASE_RUNTIME_METADATA_TIMEOUT") from error
        _require(status == 0, "RUNTIME_METADATA_INVALID")
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait()
        finally:
            if process.stdout is not None:
                process.stdout.close()
    value = json.loads(b"".join(chunks))
    _require(value["prefix"] == str(prefix), "RUNTIME_PREFIX_INVALID")
    _require(
        isinstance(value["tags"], list)
        and 0 < len(value["tags"]) <= 10000
        and all(isinstance(tag, str) and len(tag) <= 128 for tag in value["tags"]),
        "RUNTIME_METADATA_INVALID",
    )
    return {str(name): str(item) for name, item in value["environment"].items()} | {
        "extra": "",
        "_wheel_tags": "\n".join(value["tags"]),
    }


def verify_deploy_wheels(
    profile: str, source_root: Path, pins: tuple[WheelPin, ...], prefix: Path
) -> tuple[VerifiedWheel, ...]:
    local = tuple(pin for pin in pins if pin.role not in {"PEFT", "BITSANDBYTES"})
    verified = verify_build_wheels(profile, source_root, local)
    external_roles = {"PEFT"} | ({"BITSANDBYTES"} if profile == "trainer" else set())
    external = tuple(pin for pin in pins if pin.role in {"PEFT", "BITSANDBYTES"})
    _require(
        {pin.role for pin in external} == external_roles and len(external) == len(external_roles),
        "DEPENDENCY_WHEEL_SET_INVALID",
    )
    all_wheels = verified + tuple(verify_wheel(pin, source_root) for pin in external)
    versions = verify_installed_lease_ownership(prefix)
    versions.update({wheel.distribution: wheel.version for wheel in all_wheels})
    environment = _runtime_environment(prefix)
    for wheel in all_wheels:
        _require(
            bool(set(wheel.tags) & set(environment["_wheel_tags"].splitlines())),
            "DEPENDENCY_WHEEL_TAG_MISMATCH",
        )
        _require(
            SpecifierSet(wheel.python_requirement).contains(environment["python_version"]),
            "DEPENDENCY_PYTHON_MISMATCH",
        )
        for value in wheel.requirements:
            requirement = Requirement(value)
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            name = canonicalize_name(requirement.name)
            _require(
                requirement.url is None
                and name in versions
                and requirement.specifier.contains(versions[name]),
                "DEPENDENCY_CLOSURE_MISMATCH",
            )
    return all_wheels


def _copy_pin(pin: WheelPin, destination: Path) -> WheelPin:
    _require(re.fullmatch(r"[0-9a-f]{64}", pin.sha256) is not None, "WHEEL_PIN_INVALID")
    _require(pin.path.is_absolute() and ".." not in pin.path.parts, "INPUT_PATH_INVALID")
    for parent in pin.path.parents:
        _require(not parent.is_symlink(), "INPUT_PATH_INVALID")
    descriptor = os.open(pin.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    output: int | None = None
    target = destination / pin.path.name
    try:
        initial = os.fstat(descriptor)
        _require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1, "INPUT_FILE_INVALID")
        _require(
            not initial.st_mode & 0o022 and 0 < initial.st_size <= MAX_WHEEL_BYTES,
            "INPUT_FILE_INVALID",
        )
        output = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, 1024**2):
            total += len(chunk)
            _require(total <= MAX_WHEEL_BYTES, "INPUT_FILE_INVALID")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(output, view)
                _require(written > 0, "QUARANTINE_WRITE_FAILED")
                view = view[written:]
        os.fsync(output)
        _require(
            total == initial.st_size and digest.hexdigest() == pin.sha256, "INPUT_HASH_MISMATCH"
        )
        _require(
            _epoch(initial) == _epoch(os.fstat(descriptor)) == _epoch(pin.path.lstat()),
            "INPUT_CHANGED",
        )
        return WheelPin(pin.role, target, pin.sha256)
    finally:
        if output is not None:
            os.close(output)
        os.close(descriptor)


def _git_archive_bytes(repository: Path, commit: str, paths: tuple[str, ...]) -> bytes:
    process = subprocess.Popen(
        ("/usr/bin/git", "-C", str(repository), "archive", commit, *paths),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
    )
    try:
        _require(process.stdout is not None, "SOURCE_ARCHIVE_INVALID")
        assert process.stdout is not None
        parts: list[bytes] = []
        total = 0
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                _require(
                    remaining > 0 and bool(selector.select(remaining)), "SOURCE_ARCHIVE_INVALID"
                )
                chunk = os.read(process.stdout.fileno(), min(1024**2, MAX_SOURCE_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= MAX_SOURCE_BYTES, "SOURCE_ARCHIVE_INVALID")
                parts.append(chunk)
        _require(
            process.wait(timeout=max(0.001, deadline - time.monotonic())) == 0 and total > 0,
            "SOURCE_ARCHIVE_INVALID",
        )
        return b"".join(parts)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


def _stage_source(
    repository: Path, commit: str, destination: Path, pins: tuple[WheelPin, ...]
) -> None:
    _require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "SOURCE_COMMIT_INVALID")
    paths = tuple(project for pin in pins if (project := ROLE_INFO[pin.role][3]) is not None)
    payload = _git_archive_bytes(repository, commit, paths)
    archive_path = destination.parent / "source.tar"
    _write_private(archive_path, payload)
    destination.mkdir(mode=0o700)
    parents = {
        parent.as_posix()
        for prefix in paths
        for parent in PurePosixPath(prefix).parents
        if parent != PurePosixPath(".")
    }
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        members = archive.getmembers()
        _require(len(members) <= 10000, "SOURCE_ARCHIVE_INVALID")
        total = 0
        for member in members:
            name = member.name.rstrip("/")
            _safe_name(name)
            _require(
                any(name == prefix or name.startswith(prefix + "/") for prefix in paths)
                or (member.isdir() and name in parents),
                "SOURCE_ARCHIVE_INVALID",
            )
            _require(member.isdir() or member.isfile(), "SOURCE_ARCHIVE_LINK_INVALID")
            target = destination / name
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            total += member.size
            _require(
                member.size <= 8 * 1024**2 and total <= MAX_SOURCE_BYTES,
                "SOURCE_ARCHIVE_SIZE_INVALID",
            )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            _require(stream is not None, "SOURCE_ARCHIVE_INVALID")
            assert stream is not None
            payload = stream.read(8 * 1024**2 + 1)
            _require(len(payload) == member.size, "SOURCE_ARCHIVE_SIZE_INVALID")
            _write_private(target, payload)


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "RECEIPT_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _receipt(
    stage: Path, phase: str, profile: str, commit: str, pins: tuple[WheelPin, ...]
) -> None:
    payload = {
        "schema_version": "image-lease-release-receipt/1.0",
        "phase": phase,
        "profile": profile,
        "source_commit": commit,
        "created_at": datetime.now(UTC).isoformat(),
        "wheels": [
            {"role": pin.role, "filename": pin.path.name, "sha256": pin.sha256} for pin in pins
        ],
        "gpu_shared_lease_activation_verified": False,
        "all_entrypoint_migration_verified": False,
    }
    _write_private(
        stage / (phase.lower() + ".json"),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result, "RECEIPT_INVALID")
        result[key] = value
    return result


def _receipt_pins(stage: Path, profile: str, commit: str) -> tuple[WheelPin, ...]:
    value = json.loads(
        _read_file(stage / "deploy_admitted.json", maximum=32 * 1024),
        object_pairs_hook=_unique_object,
    )
    _require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema_version",
            "phase",
            "profile",
            "source_commit",
            "created_at",
            "wheels",
            "gpu_shared_lease_activation_verified",
            "all_entrypoint_migration_verified",
        },
        "RECEIPT_INVALID",
    )
    _require(
        value["schema_version"] == "image-lease-release-receipt/1.0"
        and value["phase"] == "DEPLOY_ADMITTED"
        and value["profile"] == profile
        and value["source_commit"] == commit
        and value["gpu_shared_lease_activation_verified"] is False
        and value["all_entrypoint_migration_verified"] is False,
        "RECEIPT_CONTEXT_MISMATCH",
    )
    _require(
        isinstance(value["created_at"], str)
        and datetime.fromisoformat(value["created_at"]).utcoffset() == UTC.utcoffset(None)
        and isinstance(value["wheels"], list)
        and 3 <= len(value["wheels"]) <= 6,
        "RECEIPT_INVALID",
    )
    pins: list[WheelPin] = []
    roles: set[str] = set()
    for member in value["wheels"]:
        _require(
            isinstance(member, dict) and set(member) == {"role", "filename", "sha256"},
            "RECEIPT_INVALID",
        )
        role, filename, digest = member["role"], member["filename"], member["sha256"]
        _require(
            isinstance(role, str)
            and role in ROLE_INFO
            and role not in roles
            and isinstance(filename, str)
            and filename.endswith(".whl")
            and "/" not in filename
            and "\\" not in filename
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "RECEIPT_INVALID",
        )
        roles.add(role)
        pins.append(WheelPin(role, stage / "wheels" / filename, digest))
    return tuple(pins)


def verify_installed_release(
    profile: str, source_root: Path, pins: tuple[WheelPin, ...], prefix: Path
) -> None:
    wheels = verify_deploy_wheels(profile, source_root, pins, prefix)
    site = _site_packages(prefix)
    installed = {
        str(canonicalize_name(value.metadata["Name"])): value
        for value in importlib.metadata.distributions(path=[str(site)])
    }
    for wheel in wheels:
        _require(wheel.distribution in installed, "INSTALLED_DISTRIBUTION_MISSING")
        distribution = installed[wheel.distribution]
        _require(distribution.version == wheel.version, "INSTALLED_VERSION_MISMATCH")
        records = {value.as_posix(): value for value in distribution.files or ()}
        for name, digest in wheel.namespace_hashes:
            _require(name in records, "INSTALLED_RECORD_MISSING")
            member = records[name]
            raw = _read_file(site / name, maximum=MAX_MEMBER_BYTES)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
            _require(
                member.hash is not None
                and member.hash.mode == "sha256"
                and member.hash.value == encoded
                and member.size == len(raw),
                "INSTALLED_RECORD_MISMATCH",
            )
            _require(_digest(raw) == digest, "INSTALLED_PAYLOAD_MISMATCH")


def _pins(options: argparse.Namespace) -> tuple[WheelPin, ...]:
    result: list[WheelPin] = []
    for role in ROLE_INFO:
        field = role.lower()
        wheel, digest = getattr(options, field + "_wheel"), getattr(options, field + "_sha256")
        _require((wheel is None) == (digest is None), "WHEEL_ARGUMENTS_INVALID")
        if wheel is not None:
            result.append(WheelPin(role, Path(wheel), digest))
    return tuple(result)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("build", "prepare", "mark-mutation", "installed", "recovery")
    )
    parser.add_argument("--profile", choices=tuple(PREFIXES), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--repository", type=Path)
    for role in ROLE_INFO:
        option = role.lower().replace("_", "-")
        parser.add_argument("--" + option + "-wheel")
        parser.add_argument("--" + option + "-sha256")
    options = parser.parse_args(arguments)
    try:
        os.umask(0o077)
        _require(
            re.fullmatch(r"[0-9a-f]{40}", options.source_commit) is not None,
            "SOURCE_COMMIT_INVALID",
        )
        _protected(options.stage, private=True)
        if options.action == "build":
            _require(options.source_root is not None, "SOURCE_ARGUMENTS_INVALID")
            pins = _pins(options)
            _require(
                {path.name for path in (options.stage / "dist").iterdir()}
                == {pin.path.name for pin in pins}
                and all(pin.path.parent == options.stage / "dist" for pin in pins),
                "BUILD_WHEEL_SET_INVALID",
            )
            verify_build_wheels(options.profile, options.source_root, pins)
            return 0
        _require(os.geteuid() == 0, "ROOT_REQUIRED")
        if options.action == "prepare":
            _require(options.repository == Path("/home/eom/EOM"), "SOURCE_ARGUMENTS_INVALID")
            wheels_directory = options.stage / "wheels"
            wheels_directory.mkdir(mode=0o700)
            pins = tuple(_copy_pin(pin, wheels_directory) for pin in _pins(options))
            _stage_source(options.repository, options.source_commit, options.stage / "source", pins)
            prefix = PREFIXES[options.profile]
            if not prefix.exists() and options.profile == "trainer":
                prefix = PREFIXES["provider"]
            verify_deploy_wheels(options.profile, options.stage / "source", pins, prefix)
            _receipt(options.stage, "DEPLOY_ADMITTED", options.profile, options.source_commit, pins)
            return 0
        if options.action == "recovery" and not (options.stage / "deploy_admitted.json").exists():
            _receipt(options.stage, "ADMISSION_FAILED", options.profile, options.source_commit, ())
            return 0
        pins = _receipt_pins(options.stage, options.profile, options.source_commit)
        if options.action == "installed":
            verify_installed_release(
                options.profile, options.stage / "source", pins, PREFIXES[options.profile]
            )
            _receipt(
                options.stage, "INSTALLED_VERIFIED", options.profile, options.source_commit, pins
            )
        elif options.action == "mark-mutation":
            prefix = PREFIXES[options.profile]
            if not prefix.exists() and options.profile == "trainer":
                prefix = PREFIXES["provider"]
            verify_deploy_wheels(options.profile, options.stage / "source", pins, prefix)
            _receipt(
                options.stage, "MUTATION_STARTED", options.profile, options.source_commit, pins
            )
        else:
            _receipt(
                options.stage, "RECOVERY_REQUIRED", options.profile, options.source_commit, pins
            )
        return 0
    except Exception:
        print("IMAGE_RELEASE_ADMISSION_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

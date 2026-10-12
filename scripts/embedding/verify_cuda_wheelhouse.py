"""Offline prefetch inspection only; never install, extract or import wheel packages."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import struct
import sys
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from itertools import pairwise
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import BinaryIO, cast
from urllib.parse import unquote, urlsplit

LOCK_SHA256 = "1c1bf705f0a0af11f30ee669b870a60a786d3faa344b62fe2bc2095d1fd464ba"
PREFETCH_LOCK_SHA256 = "011c16be625ebb01125c08dfae9f1f927aca9a20903e917df7d512bb94f94e19"
WHEEL_COUNT = 25
TOTAL_BYTES = 3_848_835_734
MAX_WHEEL_BYTES = 2 * 1024**3
MAX_ZIP_ENTRIES = 20_000
MAX_CENTRAL_BYTES = 16 * 1024**2
MAX_MEMBER_BYTES = 2 * 1024**3
MAX_EXPANDED_WHEEL_BYTES = 4 * 1024**3
MAX_EXPANDED_TOTAL_BYTES = 8 * 1024**3
MAX_METADATA_BYTES = 128 * 1024
MAX_COMPRESSION_RATIO = 100
_LOCK_LINE = re.compile(r"([a-z0-9-]+) @ (https://\S+) --hash=sha256:([a-f0-9]{64})")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:\+[a-zA-Z0-9_.-]+)?")
_MARKERS = MappingProxyType(
    {
        "python_version": "3.12",
        "python_full_version": "3.12.13",
        "platform_system": "Linux",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "sys_platform": "linux",
        "os_name": "posix",
        "extra": "",
    }
)


class WheelhouseVerificationError(ValueError):
    """Stable content-free rejection; filenames/content are not exception output."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WheelhouseVerificationError(code)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


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


@dataclass(frozen=True)
class WheelPin:
    name: str
    version: str
    filename: str
    sha256: str
    metadata_root: str
    tags: tuple[str, ...]


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    _require(
        path.is_absolute() and ".." not in path.parts and not path.is_relative_to(Path("/mnt/nas")),
        "DIRECTORY_PATH_INVALID",
    )
    opened: list[tuple[int, int | None, str, tuple[int, ...]]] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with ExitStack() as descriptors:
        for member in path.parts:
            parent = opened[-1][0] if opened else None
            descriptor = os.open(member, flags, dir_fd=parent)
            descriptors.callback(os.close, descriptor)
            value = os.fstat(descriptor)
            identity = (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode)
            opened.append((descriptor, parent, member, identity))
            sticky_root = value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
            _require(
                value.st_uid in {0, os.geteuid()} and (not value.st_mode & 0o022 or sticky_root),
                "DIRECTORY_OWNER_MODE_INVALID",
            )
        leaf = os.fstat(descriptor)
        _require(
            leaf.st_uid == os.geteuid() and stat.S_IMODE(leaf.st_mode) == 0o700,
            "DIRECTORY_NOT_PRIVATE",
        )
        yield descriptor
        for fd, parent, member, initial in opened:
            named = os.stat(member, dir_fd=parent, follow_symlinks=False)
            current = os.fstat(fd)
            for value in (named, current):
                _require(
                    initial
                    == (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode),
                    "DIRECTORY_EPOCH_CHANGED",
                )


def _version_key(version: str) -> tuple[int, ...]:
    _require(_VERSION.fullmatch(version) is not None, "VERSION_UNSUPPORTED")
    numbers = tuple(int(part) for part in version.split("+", 1)[0].split("."))
    _require(len(numbers) <= 8, "VERSION_UNSUPPORTED")
    return numbers + (0,) * (8 - len(numbers))


def _compare(left: str, operator: str, right: str, *, version: bool) -> bool:
    if version:
        first, second = _version_key(left), _version_key(right)
        order = (first > second) - (first < second)
    else:
        order = (left > right) - (left < right)
    if operator == "==":
        return order == 0 and ("+" not in right or left.lower() == right.lower())
    if operator == "!=":
        return not _compare(left, "==", right, version=version)
    if operator == ">=":
        return order >= 0
    if operator == "<=":
        return order <= 0
    if operator == ">":
        return order > 0
    if operator == "<":
        return order < 0
    raise WheelhouseVerificationError("COMPARATOR_UNSUPPORTED")


def _marker_applies(source: str) -> bool:
    # Parse a bounded comparison/boolean subset, never eval model/package strings.
    operators = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.GtE: ">=",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.Lt: "<",
    }

    def visit(node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = tuple(visit(value) for value in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        _require(isinstance(node, ast.Compare), "MARKER_UNSUPPORTED")
        if not isinstance(node, ast.Compare):
            raise WheelhouseVerificationError("MARKER_UNSUPPORTED")
        _require(len(node.ops) == len(node.comparators) == 1, "MARKER_UNSUPPORTED")
        name, literal = node.left, node.comparators[0]
        _require(
            isinstance(name, ast.Name)
            and name.id in _MARKERS
            and isinstance(literal, ast.Constant)
            and isinstance(literal.value, str),
            "MARKER_UNSUPPORTED",
        )
        if not isinstance(name, ast.Name) or not isinstance(literal, ast.Constant):
            raise WheelhouseVerificationError("MARKER_UNSUPPORTED")
        operator = operators.get(type(node.ops[0]))
        _require(operator is not None, "MARKER_UNSUPPORTED")
        return _compare(
            _MARKERS[name.id],
            operator or "",
            str(literal.value),
            version=name.id in {"python_version", "python_full_version"},
        )

    _require(len(source) <= 1024, "MARKER_TOO_LARGE")
    return visit(ast.parse(source.strip(), mode="eval").body)


def _satisfies(version: str, specification: str) -> bool:
    for clause in specification.strip().strip("()").split(","):
        if not clause.strip():
            continue
        matched = re.fullmatch(r"\s*(==|!=|>=|<=|>|<)\s*(\S+)\s*", clause)
        _require(matched is not None, "REQUIREMENT_UNSUPPORTED")
        if matched is None or not _compare(version, matched[1], matched[2], version=True):
            return False
    return True


def _active_requirements(payload: bytes) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    message = BytesParser().parsebytes(payload)
    _require(
        len(message.get_all("Name", [])) == len(message.get_all("Version", [])) == 1,
        "METADATA_IDENTITY_INVALID",
    )
    python_spec = message.get("Requires-Python", "")
    _require(_satisfies("3.12.13", str(python_spec)), "PYTHON_REQUIREMENT_MISMATCH")
    requirements = []
    for raw in message.get_all("Requires-Dist", []):
        body, separator, marker = str(raw).partition(";")
        if separator and not _marker_applies(marker):
            continue
        matched = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(.*)", body)
        _require(matched is not None, "REQUIREMENT_UNSUPPORTED")
        if matched is not None:
            requirements.append((_normalize(matched[1]), matched[2].strip()))
    return str(message["Name"]), str(message["Version"]), tuple(sorted(set(requirements)))


def _lock(payload: bytes, expected_sha256: str, expected_count: int) -> tuple[WheelPin, ...]:
    _require(hashlib.sha256(payload).hexdigest() == expected_sha256, "LOCK_HASH_MISMATCH")
    pins: dict[str, WheelPin] = {}
    for line in payload.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        matched = _LOCK_LINE.fullmatch(line)
        _require(matched is not None, "LOCK_LINE_INVALID")
        if matched is None:
            raise WheelhouseVerificationError("LOCK_LINE_INVALID")
        name, url, digest = matched.groups()
        location = urlsplit(url)
        _require(
            location.hostname in {"download-r2.pytorch.org", "files.pythonhosted.org"}
            and location.username is None
            and location.password is None
            and not location.query
            and not location.fragment,
            "LOCK_URL_INVALID",
        )
        filename = unquote(location.path.rsplit("/", 1)[-1])
        parts = filename.removesuffix(".whl").split("-")
        _require(
            filename.endswith(".whl")
            and len(parts) == 5
            and _normalize(parts[0]) == name
            and _VERSION.fullmatch(parts[1]) is not None
            and "/" not in filename
            and "\\" not in filename
            and "\x00" not in filename,
            "LOCK_FILENAME_INVALID",
        )
        _require(
            parts[2] in {"cp312", "py3", "py2.py3"}
            and parts[3] in {"cp312", "none"}
            and (
                parts[4] == "any"
                or all(
                    tag.startswith("manylinux") and tag.endswith("_x86_64")
                    for tag in parts[4].split(".")
                )
            ),
            "LOCK_TARGET_INVALID",
        )
        _require(name not in pins, "LOCK_DUPLICATE_PACKAGE")
        tags = tuple(
            sorted(
                f"{python}-{abi}-{platform}"
                for python in parts[2].split(".")
                for abi in parts[3].split(".")
                for platform in parts[4].split(".")
            )
        )
        pins[name] = WheelPin(
            name, parts[1], filename, digest, f"{parts[0]}-{parts[1]}.dist-info", tags
        )
    _require(
        1 <= expected_count <= WHEEL_COUNT and len(pins) == expected_count, "LOCK_COUNT_MISMATCH"
    )
    _require(len({pin.filename for pin in pins.values()}) == len(pins), "LOCK_DUPLICATE_FILENAME")
    return tuple(sorted(pins.values(), key=lambda pin: pin.filename))


def _bounded_zip_directory(descriptor: int, size: int) -> int:
    """Count bounded ZIP32 central headers on the held FD before ZipInfo allocation."""
    tail_size = min(size, 65557)
    tail = os.pread(descriptor, tail_size, size - tail_size)
    _require(len(tail) == tail_size, "ZIP_DIRECTORY_INVALID")
    position = tail.rfind(b"PK\x05\x06")
    _require(position >= 0 and position + 22 <= len(tail), "ZIP_DIRECTORY_INVALID")
    _, disk, central_disk, disk_count, count, central_size, central_offset, comment = (
        struct.unpack_from("<4s4H2IH", tail, position)
    )
    _require(comment == 0, "ZIP_COMMENT_UNSUPPORTED")
    _require(position + 22 == len(tail), "ZIP_DIRECTORY_INVALID")
    eocd_offset = size - tail_size + position
    _require(
        disk_count != 0xFFFF
        and count != 0xFFFF
        and central_size != 0xFFFFFFFF
        and central_offset != 0xFFFFFFFF,
        "ZIP64_UNSUPPORTED",
    )
    _require(
        eocd_offset < 20 or os.pread(descriptor, 4, eocd_offset - 20) != b"PK\x06\x07",
        "ZIP64_UNSUPPORTED",
    )
    _require(disk == central_disk == 0 and disk_count == count, "ZIP_MULTIDISK_UNSUPPORTED")
    _require(0 < count <= MAX_ZIP_ENTRIES, "ZIP_ENTRY_LIMIT")
    _require(0 < central_size <= MAX_CENTRAL_BYTES, "ZIP_CENTRAL_LIMIT")
    _require(central_offset + central_size == eocd_offset, "ZIP_DIRECTORY_INVALID")
    central = os.pread(descriptor, central_size, central_offset)
    _require(len(central) == central_size, "ZIP_DIRECTORY_INVALID")
    position, actual_count = 0, 0
    while position < len(central):
        _require(
            position + 46 <= len(central) and central[position : position + 4] == b"PK\x01\x02",
            "ZIP_DIRECTORY_INVALID",
        )
        actual_count += 1
        _require(actual_count <= MAX_ZIP_ENTRIES, "ZIP_ENTRY_LIMIT")
        needed = struct.unpack_from("<H", central, position + 6)[0]
        compression = struct.unpack_from("<H", central, position + 10)[0]
        _require(
            compression in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
            "ZIP_COMPRESSION_INVALID",
        )
        compressed, expanded = struct.unpack_from("<2I", central, position + 20)
        name_size, extra_size, member_comment, member_disk = struct.unpack_from(
            "<4H", central, position + 28
        )
        local_offset = struct.unpack_from("<I", central, position + 42)[0]
        _require(
            needed < 45
            and compressed != 0xFFFFFFFF
            and expanded != 0xFFFFFFFF
            and local_offset != 0xFFFFFFFF,
            "ZIP64_UNSUPPORTED",
        )
        _require(member_disk == 0, "ZIP_MULTIDISK_UNSUPPORTED")
        _require(member_comment == 0, "ZIP_COMMENT_UNSUPPORTED")
        _require(0 < name_size <= 512 and extra_size <= 4096, "ZIP_DIRECTORY_INVALID")
        end = position + 46 + name_size + extra_size
        _require(end <= len(central), "ZIP_DIRECTORY_INVALID")
        extra_position = position + 46 + name_size
        while extra_position < end:
            _require(extra_position + 4 <= end, "ZIP_DIRECTORY_INVALID")
            kind, length = struct.unpack_from("<2H", central, extra_position)
            _require(kind != 1, "ZIP64_UNSUPPORTED")
            extra_position += 4 + length
            _require(extra_position <= end, "ZIP_DIRECTORY_INVALID")
        position = end
    _require(actual_count == count, "ZIP_DIRECTORY_COUNT_MISMATCH")
    return actual_count


def _archive(
    stream: BinaryIO, pin: WheelPin, size: int
) -> tuple[dict[str, object], tuple[tuple[str, str], ...]]:
    member_count = _bounded_zip_directory(stream.fileno(), size)
    with zipfile.ZipFile(stream) as archive:
        members = archive.infolist()
        _require(len(members) == member_count, "ZIP_ENTRY_LIMIT")
        names: dict[str, zipfile.ZipInfo] = {}
        ranges = []
        expanded = 0
        for member in members:
            name = member.orig_filename
            normalized = name[:-1] if member.is_dir() else name
            path = PurePosixPath(normalized)
            mode = member.external_attr >> 16
            _require(
                0 < len(name) <= 512
                and name == member.filename
                and "\\" not in name
                and ":" not in name
                and not any(ord(char) < 32 for char in name)
                and not path.is_absolute()
                and path.as_posix() == normalized
                and not any(part in {"", ".", ".."} for part in path.parts),
                "ZIP_PATH_INVALID",
            )
            _require(name not in names, "ZIP_DUPLICATE_MEMBER")
            _require(
                stat.S_IFMT(mode) in {0, stat.S_IFREG, stat.S_IFDIR}
                and not mode & 0o6000
                and not member.flag_bits & 1
                and (stat.S_IFMT(mode) != stat.S_IFDIR or member.is_dir()),
                "ZIP_MEMBER_TYPE_INVALID",
            )
            _require(
                member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                "ZIP_COMPRESSION_INVALID",
            )
            _require(
                0 <= member.file_size <= MAX_MEMBER_BYTES
                and member.file_size <= max(member.compress_size, 1) * MAX_COMPRESSION_RATIO,
                "ZIP_EXPANSION_LIMIT",
            )
            expanded += member.file_size
            _require(expanded <= MAX_EXPANDED_WHEEL_BYTES, "ZIP_EXPANSION_LIMIT")
            stream.seek(member.header_offset)
            header = stream.read(30)
            _require(len(header) == 30 and header[:4] == b"PK\x03\x04", "ZIP_LOCAL_HEADER_INVALID")
            fields = struct.unpack("<IHHHHHIIIHH", header)
            _require(
                fields[2] == member.flag_bits and fields[3] == member.compress_type,
                "ZIP_LOCAL_HEADER_INVALID",
            )
            raw_name = stream.read(fields[9])
            _require(
                raw_name.decode("utf-8" if member.flag_bits & 0x800 else "cp437") == name,
                "ZIP_LOCAL_HEADER_INVALID",
            )
            end = member.header_offset + 30 + fields[9] + fields[10] + member.compress_size
            _require(
                0 <= member.header_offset < end <= archive.start_dir, "ZIP_MEMBER_RANGE_INVALID"
            )
            ranges.append((member.header_offset, end))
            names[name] = member
        ranges.sort()
        _require(
            ranges[0][0] == 0 and all(first[1] <= second[0] for first, second in pairwise(ranges)),
            "ZIP_MEMBER_OVERLAP",
        )
        roots = {
            name.split("/", 1)[0] for name in names if name.split("/", 1)[0].endswith(".dist-info")
        }
        _require(roots == {pin.metadata_root}, "ZIP_METADATA_ROOT_INVALID")

        def small_member(suffix: str, limit: int) -> bytes:
            name = pin.metadata_root + "/" + suffix
            _require(name in names and not names[name].is_dir(), "ZIP_METADATA_MISSING")
            _require(0 < names[name].file_size <= limit, "ZIP_METADATA_LIMIT")
            with archive.open(names[name]) as reader:
                payload = reader.read(limit + 1)
            _require(len(payload) == names[name].file_size <= limit, "ZIP_METADATA_LIMIT")
            return payload

        metadata = small_member("METADATA", MAX_METADATA_BYTES)
        wheel = BytesParser().parsebytes(small_member("WHEEL", 4096))
        _require(pin.metadata_root + "/RECORD" in names, "ZIP_RECORD_MISSING")
        _require(
            wheel.get("Wheel-Version") == "1.0"
            and wheel.get("Root-Is-Purelib") in {"true", "false"},
            "WHEEL_METADATA_INVALID",
        )
        _require(tuple(sorted(wheel.get_all("Tag", []))) == pin.tags, "WHEEL_TAG_MISMATCH")
        name, version, requirements = _active_requirements(metadata)
        _require(
            _normalize(name) == pin.name and version == pin.version, "METADATA_IDENTITY_MISMATCH"
        )
        return {
            **asdict(pin),
            "zip_entries": len(members),
            "declared_expanded_bytes": expanded,
            "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
            "active_requirements": requirements,
        }, requirements


def verify_wheelhouse(
    *,
    lock_path: Path,
    wheelhouse: Path,
    expected_lock_sha256: str = LOCK_SHA256,
    expected_count: int = WHEEL_COUNT,
    expected_total_bytes: int = TOTAL_BYTES,
) -> dict[str, object]:
    """Hold all verified wheel FDs until exact inventory/epochs/closure pass together."""
    try:
        with ExitStack() as stack:
            lock_fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            stack.callback(os.close, lock_fd)
            initial_lock = os.fstat(lock_fd)
            _require(
                stat.S_ISREG(initial_lock.st_mode)
                and initial_lock.st_nlink == 1
                and 0 < initial_lock.st_size <= 64 * 1024,
                "LOCK_FILE_INVALID",
            )
            lock_bytes = os.read(lock_fd, 64 * 1024 + 1)
            pins = _lock(lock_bytes, expected_lock_sha256, expected_count)
            if expected_lock_sha256 == LOCK_SHA256:
                _require(
                    hashlib.sha256(lock_bytes + b"\n").hexdigest() == PREFETCH_LOCK_SHA256,
                    "PREFETCH_LOCK_EQUIVALENCE_MISMATCH",
                )
            directory = stack.enter_context(_directory(wheelhouse))
            expected_names = {pin.filename for pin in pins}

            def inventory() -> set[str]:
                names = set()
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        names.add(entry.name)
                        _require(len(names) <= len(pins), "WHEELHOUSE_INVENTORY_MISMATCH")
                return names

            _require(inventory() == expected_names, "WHEELHOUSE_INVENTORY_MISMATCH")
            opened = []
            total = 0
            for pin in pins:
                fd = os.open(
                    pin.filename,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                stack.callback(os.close, fd)
                initial = os.fstat(fd)
                _require(
                    stat.S_ISREG(initial.st_mode)
                    and initial.st_uid == os.geteuid()
                    and initial.st_nlink == 1
                    and not initial.st_mode & 0o6002
                    and 0 < initial.st_size <= MAX_WHEEL_BYTES,
                    "WHEEL_FILE_INVALID",
                )
                total += initial.st_size
                _require(total <= expected_total_bytes, "WHEELHOUSE_BYTE_COUNT_MISMATCH")
                opened.append((pin, fd, initial))
            _require(total == expected_total_bytes, "WHEELHOUSE_BYTE_COUNT_MISMATCH")
            inspections = []
            expanded = 0
            by_name = {pin.name: pin for pin in pins}
            for pin, fd, initial in opened:
                digest = hashlib.sha256()
                read_bytes = 0
                while chunk := os.read(fd, min(8 * 1024**2, initial.st_size + 1 - read_bytes)):
                    read_bytes += len(chunk)
                    _require(read_bytes <= initial.st_size, "WHEEL_EPOCH_CHANGED")
                    digest.update(chunk)
                _require(read_bytes == initial.st_size, "WHEEL_EPOCH_CHANGED")
                _require(digest.hexdigest() == pin.sha256, "WHEEL_HASH_MISMATCH")
                with os.fdopen(os.dup(fd), "rb") as stream:
                    inspection, requirements = _archive(stream, pin, initial.st_size)
                for name, specification in requirements:
                    _require(name in by_name, "DEPENDENCY_MISSING")
                    _require(
                        _satisfies(by_name[name].version, specification),
                        "DEPENDENCY_VERSION_MISMATCH",
                    )
                expanded += cast(int, inspection["declared_expanded_bytes"])
                _require(expanded <= MAX_EXPANDED_TOTAL_BYTES, "ZIP_AGGREGATE_EXPANSION_LIMIT")
                inspections.append(
                    {
                        **inspection,
                        "bytes": initial.st_size,
                        "file_mode": f"{stat.S_IMODE(initial.st_mode):04o}",
                    }
                )
            _require(inventory() == expected_names, "WHEELHOUSE_INVENTORY_MISMATCH")
            for pin, fd, initial in opened:
                named = os.stat(pin.filename, dir_fd=directory, follow_symlinks=False)
                _require(
                    _epoch(initial) == _epoch(os.fstat(fd)) == _epoch(named), "WHEEL_EPOCH_CHANGED"
                )
            _require(
                _epoch(initial_lock) == _epoch(os.fstat(lock_fd)) == _epoch(lock_path.lstat()),
                "LOCK_EPOCH_CHANGED",
            )
            report: dict[str, object] = {
                "report_version": "cuda-wheelhouse-inspection/1.0",
                "scope": "RAW_WHEEL_HASH_ZIP_STRUCTURE_SMALL_METADATA_ONLY",
                "verified_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "lock_sha256": expected_lock_sha256,
                "prefetch_lock_sha256": (
                    PREFETCH_LOCK_SHA256 if expected_lock_sha256 == LOCK_SHA256 else None
                ),
                "wheel_count": len(pins),
                "total_bytes": total,
                "declared_expanded_bytes": expanded,
                "wheelhouse_mode": "0700",
                "uid": os.geteuid(),
                "wheels": inspections,
                "immutable_root_quarantine_required": True,
                "installed_record_verified": False,
                "cuda_verified": False,
            }
        return report
    except WheelhouseVerificationError:
        raise
    except (OSError, ValueError, SyntaxError, zipfile.BadZipFile, RuntimeError):
        raise WheelhouseVerificationError("WHEELHOUSE_UNTRUSTED_INPUT_INVALID") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument(
        "--lock", type=Path, default=Path(__file__).parent / "cuda-runtime-wheels.lock"
    )
    options = parser.parse_args()
    try:
        report = verify_wheelhouse(lock_path=options.lock, wheelhouse=options.wheelhouse)
    except WheelhouseVerificationError as error:
        print(f"VERIFICATION_FAILED:{error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

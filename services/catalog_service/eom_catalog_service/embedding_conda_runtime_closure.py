"""Read-only fixed Conda31 transformation ledger; never whole-runtime admission."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import stat
import struct
import subprocess
import tarfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import IO, Any, Protocol, cast

from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    require_runtime_proof,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelInstallationPin,
    VerifiedRuntimeWheelMembers,
    observe_runtime_wheel_installation,
    verify_installed_runtime_wheel,
)

_SOURCE_SHA = "sha256:3decd31fdcd240cefca05b8fbd708e0dce724f63a3d255684617a6e2fcef010c"
_NAMES = frozenset(
    [
        "_libgcc_mutex",
        "_openmp_mutex",
        "bzip2",
        "ca-certificates",
        "ld_impl_linux-64",
        "libexpat",
        "libffi",
        "libgcc",
        "libgcc-ng",
        "libstdcxx",
        "libuuid",
        "libxcb",
        "libzlib",
        "ncurses",
        "openssl",
        "packaging",
        "pip",
        "pthread-stubs",
        "python",
        "readline",
        "setuptools",
        "sqlite",
        "tk",
        "tzdata",
        "wheel",
        "xorg-libx11",
        "xorg-libxau",
        "xorg-libxdmcp",
        "xorg-xorgproto",
        "xz",
        "zlib",
    ]
)
_OVERLAYS = (
    ("packaging", "26.2", "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e"),
    ("pip", "26.1.2", "382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"),
    ("setuptools", "83.0.0", "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3"),
    ("wheel", "0.47.0", "212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced"),
)
_ZSTD_PATH = Path("/usr/bin/zstd")
_ZSTD_SHA = "sha256:7c5468b370f7c47eda07281e3437fafc568f95d10420051e3aa522709f9342c5"
_ZSTD_SIZE = 1022760
_MAX_EXPANDED = 8 * 1024**3
_MAX_MEMBERS = 100000
_MAX_METADATA = 16 * 1024**2
_TRANSFORMATION_COUNTS = (161, 111)
_CACHE_COUNTS = (1133, 779, 395)
# These original metadata-only members are absent from info/paths.json and never installed.
_LICENSES = (
    (
        "_openmp_mutex",
        "LICENSE",
        1510,
        "d939c95d76d470fe1796d8a24ca1ee28c920fc85f61c57059de993586fa60071",
    ),
    ("bzip2", "LICENSE", 1896, "c6dbbf828498be844a89eaa3b84adbab3199e342eb5cb2ed2f0d4ba7ec0f38a3"),
    (
        "ld_impl_linux-64",
        "COPYING3.LIB",
        7639,
        "a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c",
    ),
    (
        "ld_impl_linux-64",
        "COPYING",
        18002,
        "231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c",
    ),
    (
        "ld_impl_linux-64",
        "COPYING3",
        35147,
        "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    ),
    (
        "ld_impl_linux-64",
        "COPYING.LIB",
        25291,
        "56bdea73b6145ef6ac5259b3da390b981d840c24cb03b8e1cbc678de7ecfa18d",
    ),
    ("libffi", "LICENSE", 1132, "67894089811f93fca47a76f85e017da6f8582d4ba0905963c6e0f1ad6df7a195"),
    (
        "libuuid",
        "Documentation/licenses/COPYING.BSD-3",
        1391,
        "9b718a9460fed5952466421235bc79eb49d4e9eacc920d7a9dd6285ab8fd6c6d",
    ),
    ("libxcb", "COPYING", 1337, "c5ffbfeaa501071ceeb97b7de2c0d703fdaa35de01c0fb6cbac1c28453a3e9fd"),
    (
        "libzlib",
        "LICENSE",
        1002,
        "e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2",
    ),
    (
        "ncurses",
        "COPYING",
        1447,
        "b2feb54f39529abe226f709a292584fde48a2e5721559fee417d2cdd51cb7cc1",
    ),
    (
        "openssl",
        "LICENSE.txt",
        10175,
        "7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a",
    ),
    (
        "readline",
        "COPYING",
        35147,
        "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    ),
    (
        "sqlite",
        "LICENSE.md",
        263,
        "9c6479123f32a1ed50d9a0af203dfe8972e65035b0cdeef436b5f8d0924517fe",
    ),
    (
        "tk",
        "tcl8.6.15/license.terms",
        2255,
        "c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16",
    ),
    (
        "wheel",
        "LICENSE.txt",
        1107,
        "30c23618679108f3e8ea1d2a658c7ca417bdfc891c98ef1a89fa4ff0c9828654",
    ),
    (
        "xorg-libx11",
        "COPYING",
        46458,
        "2e7012a140f000735a7172674a2d314398d79622444fba65d108b029b29ab283",
    ),
    (
        "xorg-libxau",
        "COPYING",
        1148,
        "56abe29bb1d9806a9e04fa9f80fed2c0f18027594df3f098148d814aef6bddfa",
    ),
    (
        "xorg-libxdmcp",
        "COPYING",
        1178,
        "8a3c3f35b0dbcb60a4e242b9e4394a352a65bb27deb2938ea1e2e62a626e16e9",
    ),
    ("xz", "COPYING", 3119, "616a3ad264ce29b8f1cb97e53037b139d406899ca8d1f799651e17bfa09830b8"),
    ("zlib", "LICENSE", 1002, "e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2"),
)
_CROSS_LINKS = (
    (
        "python",
        "compiler_compat/ld",
        "ld_impl_linux-64",
        "bin/x86_64-conda-linux-gnu-ld",
        "70d094c82cbcf7b2f2447c475c57e965b54f8e7698f82ca1871a4a015b2d5634",
        2941304,
    ),
    (
        "zlib",
        "lib/libz.so",
        "libzlib",
        "lib/libz.so.1.3.2",
        "d1e842e199a902992c7b778b8482f4777ccd3cbe9c26f8a44c783d9e6601da79",
        117416,
    ),
)
_STALE_SOURCES = frozenset(
    {
        "lib/python3.12/_sysconfigdata__linux_x86_64-linux-gnu.py",
        "lib/python3.12/_sysconfigdata_x86_64_conda_cos6_linux_gnu.py",
        "lib/python3.12/_sysconfigdata_x86_64_conda_linux_gnu.py",
        "lib/python3.12/config-3.12-x86_64-linux-gnu/python-config.py",
    }
)


def _require(condition: bool, code: str = "INVALID") -> None:
    require_runtime_proof(condition, "CONDA_" + code)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _size(value: object, maximum: int, *, empty: bool = False) -> bool:
    return type(value) is int and (0 if empty else 1) <= value <= maximum


def _json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    def non_json(_value: str) -> None:
        raise ValueError("non-JSON constant")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=non_json)
        _require(type(value) is dict)
        return cast(dict[str, Any], value)
    except (ValueError, UnicodeError, RecursionError):
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CONDA_INVALID") from None


def _path(value: object) -> str:
    _require(
        type(value) is str
        and 0 < len(value.encode()) <= 512
        and not value.startswith("/")
        and "\\" not in value
        and all(ord(c) >= 32 for c in value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and PurePosixPath(value).as_posix() == value,
        "PATH_INVALID",
    )
    return str(value)


@dataclass(frozen=True, slots=True)
class CondaRuntimeArchivePin:
    filename: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require(
            type(self.filename) is str
            and len(self.filename) <= 255
            and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,249}\.conda", self.filename)
            is not None
            and _sha(self.sha256)
            and _size(self.size_bytes, 64 * 1024**2)
        )


@dataclass(frozen=True, slots=True)
class CondaRuntimeAuditPlan:
    profile: str
    source_list_sha256: str
    source_list_size_bytes: int
    archives: tuple[CondaRuntimeArchivePin, ...]
    overlay_archives: tuple[RuntimeWheelArchivePin, ...]

    def __post_init__(self) -> None:
        _validate_plan(self)


@dataclass(frozen=True, slots=True)
class CondaRuntimeByteAudit:
    profile: str
    source_list_sha256: str
    archive_closure_sha256: str
    overlay_closure_sha256: str
    regular_members: int
    link_members: int
    binary_relocations: int
    text_relocations: int
    archived_caches: int
    retained_caches: int
    absent_generated_caches: int
    licensing_members: int
    ledger_sha256: str
    installed_members: frozenset[Path]
    installed_links: tuple[tuple[Path, str], ...]
    overlay_wheels: tuple[VerifiedRuntimeWheelMembers, ...]


class CondaArchiveToolAdmission(Protocol):
    """Independent owner-held executable/loader/environment fence; not a parsed grant."""

    def assert_current(self) -> None: ...

    def open_zstd(self) -> subprocess.Popen[bytes]:
        """Spawn only the independently captured fixed decoder through its held FD."""
        ...


def _validate_plan(plan: CondaRuntimeAuditPlan) -> None:
    _require(
        type(plan) is CondaRuntimeAuditPlan
        and type(plan.profile) is str
        and plan.profile in {"CPU_INDEX_FP32", "CUDA_INDEX_FP32"}
        and _sha(plan.source_list_sha256)
        and plan.source_list_sha256 == _SOURCE_SHA
        and _size(plan.source_list_size_bytes, 128 * 1024)
        and type(plan.archives) is tuple
        and len(plan.archives) == 31
        and type(plan.overlay_archives) is tuple
        and len(plan.overlay_archives) == 4
    )
    for pin in plan.archives:
        _require(type(pin) is CondaRuntimeArchivePin)
        pin.__post_init__()
    for overlay in plan.overlay_archives:
        _require(type(overlay) is RuntimeWheelArchivePin)
        overlay.__post_init__()
    names = tuple(pin.filename for pin in plan.archives)
    _require(names == tuple(sorted(set(names))))
    _require(sum(pin.size_bytes for pin in plan.archives) <= 64 * 1024**2)
    expected = tuple(
        (f"{name}-{version}-py3-none-any.whl", "sha256:" + sha) for name, version, sha in _OVERLAYS
    )
    _require(tuple((pin.wheel_filename, pin.sha256) for pin in plan.overlay_archives) == expected)


def _tool_fence(tool: CondaArchiveToolAdmission) -> None:
    try:
        _require(tool is not None, "TOOL_UNAVAILABLE")
        result = cast(Callable[[], object], tool.assert_current)()
        _require(result is None and callable(tool.open_zstd), "TOOL_UNAVAILABLE")
    except Exception:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CONDA_TOOL_UNAVAILABLE") from None


class _ToolReader:
    """Bounded duplex pipe; one fixed zstd command, absolute deadline and owned cleanup."""

    def __init__(
        self, compressed: IO[bytes], deadline: float, *, tool: CondaArchiveToolAdmission
    ) -> None:
        self.compressed = compressed
        self.deadline = min(deadline, time.monotonic() + 10)
        _require(time.monotonic() < self.deadline, "TOOL_TIMEOUT")
        self.selector = selectors.DefaultSelector()
        self.pending = b""
        self.buffer = bytearray()
        self.eof = False
        self.expanded = 0
        try:
            _tool_fence(tool)
            self.process = tool.open_zstd()
            _require(
                self.process.stdin is not None and self.process.stdout is not None,
                "TOOL_UNAVAILABLE",
            )
            assert self.process.stdin is not None and self.process.stdout is not None
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE)
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            if hasattr(self, "process"):
                self.close(success=False)
            else:
                self.selector.close()
            raise

    def read(self, size: int) -> bytes:
        _require(type(size) is int and 0 < size <= 65536, "STREAM_INVALID")
        _require(time.monotonic() < self.deadline, "TOOL_TIMEOUT")
        while not self.buffer and not self.eof:
            remaining = self.deadline - time.monotonic()
            _require(remaining > 0, "TOOL_TIMEOUT")
            events = self.selector.select(remaining)
            _require(time.monotonic() < self.deadline, "TOOL_TIMEOUT")
            for key, _events in events:
                if key.events == selectors.EVENT_WRITE:
                    if not self.pending:
                        self.pending = self.compressed.read(65536)
                    if not self.pending:
                        self.selector.unregister(key.fileobj)
                        assert self.process.stdin is not None
                        self.process.stdin.close()
                    else:
                        try:
                            count = os.write(key.fd, self.pending)
                            self.pending = self.pending[count:]
                        except BlockingIOError:
                            pass
                else:
                    try:
                        raw = os.read(key.fd, 65536)
                    except BlockingIOError:
                        continue
                    if raw:
                        self.expanded += len(raw)
                        _require(self.expanded <= _MAX_EXPANDED, "STREAM_OVERFLOW")
                        self.buffer.extend(raw)
                    else:
                        self.selector.unregister(key.fileobj)
                        self.eof = True
                _require(time.monotonic() < self.deadline, "TOOL_TIMEOUT")
        raw = bytes(self.buffer[:size])
        del self.buffer[:size]
        _require(time.monotonic() < self.deadline, "TOOL_TIMEOUT")
        return raw

    def exact(self, size: int) -> bytes:
        _require(type(size) is int and 0 <= size <= 64 * 1024**2, "STREAM_INVALID")
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            raw = self.read(min(remaining, 65536))
            _require(bool(raw), "TAR_TRUNCATED")
            chunks.append(raw)
            remaining -= len(raw)
        return b"".join(chunks)

    def close(self, *, success: bool) -> None:
        try:
            if success:
                _require(
                    self.eof
                    and self.process.stdin is not None
                    and self.process.stdin.closed
                    and not self.pending,
                    "TOOL_INCOMPLETE",
                )
                remaining = self.deadline - time.monotonic()
                _require(remaining > 0, "TOOL_TIMEOUT")
                try:
                    _require(self.process.wait(timeout=remaining) == 0, "TOOL_FAILED")
                except subprocess.TimeoutExpired:
                    raise InstalledRuntimeProofError(
                        "INSTALLED_RUNTIME_CONDA_TOOL_TIMEOUT"
                    ) from None
        finally:
            try:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                raise InstalledRuntimeProofError(
                    "INSTALLED_RUNTIME_CONDA_TOOL_CLEANUP_UNCERTAIN"
                ) from None
            finally:
                self.selector.close()
                for stream in (self.process.stdin, self.process.stdout):
                    if stream is not None:
                        stream.close()


@dataclass(slots=True)
class _Budget:
    members: int = 0
    expanded: int = 0
    metadata: int = 0
    licenses: dict[tuple[str, str], tuple[str, int]] = field(default_factory=dict)


def _pax(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    while raw:
        match = re.match(rb"([1-9][0-9]{0,5}) ", raw)
        _require(match is not None, "TAR_INVALID")
        assert match is not None
        length = int(match[1])
        _require(
            len(match[0]) < length <= len(raw) and raw[length - 1 : length] == b"\n", "TAR_INVALID"
        )
        record = raw[len(match[0]) : length - 1].decode("utf-8", "strict")
        key, separator, value = record.partition("=")
        _require(
            separator == "="
            and key in {"path", "linkpath", "mtime", "atime", "ctime"}
            and key not in result,
            "TAR_INVALID",
        )
        result[key] = value
        raw = raw[length:]
    return result


def _tar_members(reader: _ToolReader, budget: _Budget) -> Iterator[tarfile.TarInfo]:
    pax: dict[str, str] = {}
    while True:
        header = reader.exact(512)
        if header == bytes(512):
            _require(not pax and reader.exact(512) == bytes(512), "TAR_INVALID")
            while raw := reader.read(65536):
                _require(not any(raw), "TAR_INVALID")
                budget.expanded += len(raw)
                _require(budget.expanded <= _MAX_EXPANDED, "STREAM_OVERFLOW")
            return
        try:
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError):
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CONDA_TAR_INVALID") from None
        budget.members += 1
        budget.expanded += 512 + ((member.size + 511) // 512) * 512
        _require(
            budget.members <= _MAX_MEMBERS and budget.expanded <= _MAX_EXPANDED, "STREAM_OVERFLOW"
        )
        _require(0 <= member.size <= 2 * 1024**3, "TAR_INVALID")
        if member.type == tarfile.XHDTYPE:
            _require(not pax and member.size <= 64 * 1024, "TAR_INVALID")
            pax = _pax(reader.exact(member.size))
            reader.exact((-member.size) % 512)
            continue
        _require(
            member.type in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.SYMTYPE, tarfile.DIRTYPE},
            "TAR_INVALID",
        )
        member.name = pax.get("path", member.name)
        member.linkname = pax.get("linkpath", member.linkname)
        if "mtime" in pax:
            _require(
                re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?", pax["mtime"]) is not None, "TAR_INVALID"
            )
            member.mtime = float(pax["mtime"])
        pax = {}
        member.name = _path(member.name.rstrip("/") if member.isdir() else member.name)
        _require(member.isreg() or member.size == 0, "TAR_INVALID")
        yield member
        reader.exact((-member.size) % 512)


def _source_rows(
    raw: bytes, pins: tuple[CondaRuntimeArchivePin, ...]
) -> dict[str, tuple[str, str, str, str]]:
    expected = {pin.filename: pin for pin in pins}
    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in raw.decode("utf-8", "strict").splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+\.conda)  (https://repo\.anaconda\.com/pkgs/main/(?:linux-64|noarch)/[A-Za-z0-9_.+-]+\.conda)",
            line,
        )
        _require(match is not None)
        assert match is not None
        sha, filename, url = match.groups()
        _require(filename in expected and expected[filename].sha256 == "sha256:" + sha)
        name, version, build = filename[:-6].rsplit("-", 2)
        _require(name in _NAMES and name not in rows)
        subdir = "noarch" if name in {"pip", "tzdata"} else "linux-64"
        _require(url == f"https://repo.anaconda.com/pkgs/main/{subdir}/{filename}")
        rows[name] = (version, build, filename, url)
    _require(set(rows) == _NAMES and len(expected) == len(rows))
    return rows


def _zip(descriptor: int, pin: CondaRuntimeArchivePin) -> zipfile.ZipFile:
    tail = os.pread(descriptor, min(pin.size_bytes, 65557), max(0, pin.size_bytes - 65557))
    index = tail.rfind(b"PK\x05\x06")
    _require(index >= 0 and index + 22 == len(tail), "ZIP_INVALID")
    end = struct.unpack("<4s4H2LH", tail[index : index + 22])
    _require(
        end[1] == end[2] == end[7] == 0
        and end[3] == end[4] == 3
        and 0 < end[5] <= 65536
        and end[6] + end[5] == pin.size_bytes - 22,
        "ZIP_INVALID",
    )
    central = os.pread(descriptor, end[5], end[6])
    cursor = 0
    for _ in range(3):
        _require(
            central[cursor : cursor + 4] == b"PK\x01\x02" and cursor + 46 <= len(central),
            "ZIP_INVALID",
        )
        fields = struct.unpack("<4s6H3L5H2L", central[cursor : cursor + 46])
        _require(
            fields[11] == fields[12] == fields[13] == 0
            and 0 < fields[10] <= 255
            and max(fields[8], fields[9], fields[16]) < 0xFFFFFFFF,
            "ZIP_INVALID",
        )
        cursor += 46 + fields[10] + fields[11] + fields[12]
    _require(cursor == len(central), "ZIP_INVALID")
    stream = os.fdopen(os.dup(descriptor), "rb")
    try:
        archive = zipfile.ZipFile(stream)
        stem = pin.filename[:-6]
        expected = {"metadata.json", f"info-{stem}.tar.zst", f"pkg-{stem}.tar.zst"}
        _require({entry.filename for entry in archive.infolist()} == expected, "ZIP_INVALID")
        ranges: list[tuple[int, int]] = []
        for entry in archive.infolist():
            _require(
                entry.compress_type == zipfile.ZIP_STORED
                and entry.flag_bits == 0
                and entry.file_size <= pin.size_bytes
                and entry.compress_size == entry.file_size,
                "ZIP_INVALID",
            )
            header = os.pread(descriptor, 30, entry.header_offset)
            _require(len(header) == 30, "ZIP_INVALID")
            local = struct.unpack("<4s5H3L2H", header)
            _require(
                local[0] == b"PK\x03\x04"
                and local[2] == entry.flag_bits
                and local[3] == entry.compress_type
                and local[6] == entry.CRC
                and 0 < local[9] <= 255
                and local[10] in {0, 20},
                "ZIP_INVALID",
            )
            name = os.pread(descriptor, local[9], entry.header_offset + 30)
            extra = os.pread(descriptor, local[10], entry.header_offset + 30 + local[9])
            _require(name == entry.filename.encode("ascii"), "ZIP_INVALID")
            ordinary = (
                local[1] == 20
                and local[7:9] == (entry.compress_size, entry.file_size)
                and extra == b""
            )
            local_sizes = (
                local[1] == 45
                and local[7] == local[8] == 0xFFFFFFFF
                and extra == struct.pack("<HHQQ", 1, 16, entry.file_size, entry.compress_size)
            )
            _require(ordinary or local_sizes, "ZIP_INVALID")
            stop = entry.header_offset + 30 + local[9] + local[10] + entry.compress_size
            _require(0 <= entry.header_offset < stop <= end[6], "ZIP_INVALID")
            ranges.append((entry.header_offset, stop))
        ordered = sorted(ranges)
        _require(all(first[1] <= second[0] for first, second in pairwise(ordered)), "ZIP_INVALID")
        metadata = archive.getinfo("metadata.json")
        _require(metadata.file_size <= 8192, "ZIP_INVALID")
        raw = archive.read(metadata)
        empty_mutex = (
            pin.filename == "_libgcc_mutex-0.1-main.conda"
            and pin.sha256
            == "sha256:476626712f60e5ef0fe04c354727152b1ee5285d57ccd3575c7be930122bd051"
        )
        _require(
            (empty_mutex and raw == b"") or _json(raw) == {"conda_pkg_format_version": 2},
            "ZIP_INVALID",
        )
        return archive
    except Exception:
        stream.close()
        raise


def _relocate(raw: bytes, placeholder: str, mode: str, prefix: Path) -> bytes:
    _require(
        type(placeholder) is str
        and 1 <= len(placeholder) <= 1024
        and type(mode) is str
        and mode in {"text", "binary"}
    )
    target = str(prefix)
    _require(" " not in target and len(target) <= len(placeholder))
    result = raw
    for encoding in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
        old, new = placeholder.encode(encoding), target.encode(encoding)
        if mode == "text":
            result = result.replace(old, new)
        else:

            def replace(match: re.Match[bytes], old: bytes = old, new: bytes = new) -> bytes:
                span = match.group(0)
                changed = span.replace(old, new)
                return changed + bytes(len(span) - len(changed))

            zeros = "\0".encode(encoding)
            pattern = re.escape(old) + b"(?:(?!(?:" + zeros + b")).)*" + zeros
            result = re.sub(pattern, replace, result, flags=re.DOTALL)
    return result


def _mapped(path: str, noarch: str | None) -> str:
    if noarch == "python":
        if path.startswith("site-packages/"):
            return "lib/python3.12/" + path
        if path.startswith("python-scripts/"):
            return "bin/" + path.removeprefix("python-scripts/")
    return path


@dataclass(frozen=True, slots=True)
class _Member:
    package: str
    source_sha256: str
    final_sha256: str
    source_size: int
    size: int
    mtime: int
    mode: int
    link: str | None
    cache_header: bytes | None


def _info(reader: _ToolReader, budget: _Budget) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    for member in _tar_members(reader, budget):
        _require(member.name not in names, "TAR_INVALID")
        names.add(member.name)
        _require(member.isreg() or member.isdir(), "TAR_INVALID")
        if member.name in {"info/index.json", "info/paths.json", "info/link.json"}:
            _require(member.size <= 8 * 1024**2, "METADATA_INVALID")
            budget.metadata += member.size
            _require(budget.metadata <= _MAX_METADATA, "METADATA_INVALID")
            result[member.name] = _json(reader.exact(member.size))
        else:
            remaining = member.size
            while remaining:
                raw = reader.read(min(remaining, 65536))
                _require(bool(raw), "TAR_TRUNCATED")
                remaining -= len(raw)
    _require({"info/index.json", "info/paths.json"} <= result.keys(), "METADATA_INVALID")
    return result


def _cache_source(path: str) -> str:
    match = re.fullmatch(r"(.+)/__pycache__/([^/]+)\.cpython-312\.pyc", path)
    _require(match is not None, "BYTECODE_INVALID")
    assert match is not None
    return match[1] + "/" + match[2] + ".py"


def _payload(
    reader: _ToolReader,
    budget: _Budget,
    metadata: dict[str, dict[str, Any]],
    package: str,
    prefix: Path,
    ledger: dict[str, _Member],
) -> tuple[int, int]:
    paths_doc = metadata["info/paths.json"]
    _require(
        set(paths_doc) == {"paths", "paths_version"}
        and type(paths_doc["paths_version"]) is int
        and paths_doc["paths_version"] == 1
        and type(paths_doc["paths"]) is list
        and len(paths_doc["paths"]) <= _MAX_MEMBERS,
        "METADATA_INVALID",
    )
    declared: dict[str, dict[str, Any]] = {}
    for row in paths_doc["paths"]:
        _require(
            type(row) is dict
            and set(row)
            in (
                {"_path", "path_type", "sha256", "size_in_bytes"},
                {
                    "_path",
                    "path_type",
                    "sha256",
                    "size_in_bytes",
                    "file_mode",
                    "prefix_placeholder",
                },
            ),
            "METADATA_INVALID",
        )
        path = _path(row["_path"])
        _require(
            path not in declared
            and row["path_type"] in {"hardlink", "softlink"}
            and type(row["sha256"]) is str
            and _sha("sha256:" + row["sha256"])
            and _size(row["size_in_bytes"], 2 * 1024**3, empty=True),
            "METADATA_INVALID",
        )
        declared[path] = row
        if "prefix_placeholder" in row:
            _require(
                type(row["prefix_placeholder"]) is str
                and 0 < len(row["prefix_placeholder"]) <= 1024
                and type(row["file_mode"]) is str
                and row["file_mode"] in {"text", "binary"},
                "METADATA_INVALID",
            )
        if row["path_type"] == "softlink" and row["sha256"] == _hash(b"").removeprefix("sha256:"):
            _require(
                (package, path) in {("ncurses", "lib/terminfo"), ("python", "lib/python3.1")}
                and row["size_in_bytes"] == 0,
                "LINK_INVALID",
            )
    link_doc = metadata.get("info/link.json", {})
    noarch = link_doc.get("noarch", {}).get("type")
    _require(
        noarch in {None, "python", "generic"}
        and (package in {"pip", "tzdata"}) == (noarch is not None),
        "METADATA_INVALID",
    )
    observed: set[str] = set()
    binary = text = 0
    licenses = {
        (name, "info/licenses/" + path): (size, "sha256:" + sha)
        for name, path, size, sha in _LICENSES
    }
    for member in _tar_members(reader, budget):
        if member.isdir():
            continue
        path = member.name
        if path not in declared:
            key = (package, path)
            _require(
                member.isreg() and key in licenses and key not in budget.licenses,
                "MEMBER_SET_MISMATCH",
            )
            _require(not member.mode & 0o111, "MEMBER_INVALID")
            expected_size, expected_sha = licenses[key]
            _require(member.size == expected_size and member.size <= 1024**2, "MEMBER_INVALID")
            raw = reader.exact(member.size)
            _require(
                _hash(raw) == expected_sha and not os.path.lexists(prefix / path),
                "MEMBER_HASH_MISMATCH",
            )
            budget.metadata += member.size
            _require(budget.metadata <= _MAX_METADATA, "METADATA_INVALID")
            budget.licenses[key] = (expected_sha, expected_size)
            continue
        _require(path in declared and path not in observed, "MEMBER_SET_MISMATCH")
        observed.add(path)
        row = declared[path]
        final_path = _mapped(path, noarch)
        _require(final_path not in ledger, "OWNERSHIP_CONFLICT")
        header: bytes | None = None
        if member.issym():
            _require(
                row["path_type"] == "softlink"
                and 0 < len(member.linkname.encode()) <= 512
                and not member.linkname.startswith("/")
                and "\\" not in member.linkname,
                "LINK_INVALID",
            )
            ledger[final_path] = _Member(
                package,
                "sha256:" + row["sha256"],
                "",
                row["size_in_bytes"],
                row["size_in_bytes"],
                int(member.mtime),
                0,
                member.linkname,
                None,
            )
            continue
        _require(
            row["path_type"] == "hardlink" and member.size == row["size_in_bytes"], "MEMBER_INVALID"
        )
        digest = hashlib.sha256()
        transformed = "prefix_placeholder" in row
        _require(not transformed or member.size <= 64 * 1024**2, "MEMBER_INVALID")
        chunks: list[bytes] = []
        remaining = member.size
        while remaining:
            raw = reader.read(min(remaining, 65536))
            _require(bool(raw), "TAR_TRUNCATED")
            digest.update(raw)
            if transformed:
                chunks.append(raw)
            if path.endswith(".pyc") and header is None:
                header = raw[:16]
            remaining -= len(raw)
        original = "sha256:" + digest.hexdigest()
        _require(original == "sha256:" + row["sha256"], "MEMBER_HASH_MISMATCH")
        final_hash, final_size = original, member.size
        if transformed:
            computed = _relocate(
                b"".join(chunks), row["prefix_placeholder"], row["file_mode"], prefix
            )
            final_hash, final_size = _hash(computed), len(computed)
            binary += row["file_mode"] == "binary"
            text += row["file_mode"] == "text"
        if path.endswith((".pyc", ".pyo")):
            _cache_source(final_path)
            _require(
                header is not None
                and len(header) == 16
                and header[:8] == b"\xcb\x0d\x0d\x0a" + bytes(4),
                "BYTECODE_INVALID",
            )
        _require(
            not final_path.endswith(("/pre-link.sh", "/post-link.sh", "/pre-unlink.sh")),
            "HOOK_FORBIDDEN",
        )
        ledger[final_path] = _Member(
            package,
            original,
            final_hash,
            member.size,
            final_size,
            int(member.mtime),
            member.mode & 0o777 & ~0o022,
            None,
            header,
        )
    _require(observed == set(declared), "MEMBER_SET_MISMATCH")
    return binary, text


def _candidate_wheel(
    pin: RuntimeWheelArchivePin,
    name: str,
    version: str,
    prefix: Path,
    files: NumericalRuntimeFileSnapshots,
) -> RuntimeWheelInstallationPin:
    try:
        return observe_runtime_wheel_installation(pin, name, version, prefix=prefix, files=files)
    except InstalledRuntimeProofError as exc:
        if exc.code == "INSTALLED_RUNTIME_WHEEL_OBSERVATION_INVALID":
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CONDA_OVERLAY_INVALID") from None
        raise


def _link_target(path: str, target: str) -> str:
    parts = list(PurePosixPath(path).parent.parts)
    for part in target.split("/"):
        _require(part not in {"", "."}, "LINK_INVALID")
        if part == "..":
            _require(bool(parts), "LINK_ESCAPE")
            parts.pop()
        else:
            parts.append(part)
    return _path("/".join(parts))


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


def _observe_link(
    path: Path, expected: str | None, owner_uid: int
) -> tuple[tuple[int, ...], tuple[tuple[Path, tuple[int, ...]], ...]]:
    descriptors: list[int] = []
    ancestors: list[tuple[Path, tuple[int, ...]]] = []
    try:
        for component in path.parent.parts:
            named = ancestors[-1][0] / component if ancestors else Path(component)
            descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptors[-1] if descriptors else None,
            )
            value = os.fstat(descriptor)
            descriptors.append(descriptor)
            test_sticky = (
                owner_uid != 0
                and named == Path("/tmp")
                and value.st_uid == 0
                and value.st_mode & stat.S_ISVTX
            )
            _require(
                value.st_uid in {0, owner_uid} and (not value.st_mode & 0o022 or bool(test_sticky)),
                "LINK_UNPROTECTED",
            )
            ancestors.append((named, _identity(value)))
        value = os.stat(path.name, dir_fd=descriptors[-1], follow_symlinks=False)
        if expected is None:
            leaf = os.open(
                path.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptors[-1],
            )
            descriptors.append(leaf)
            _require(
                _identity(os.fstat(leaf)) == _identity(value)
                and value.st_uid == owner_uid
                and not value.st_mode & 0o022,
                "LINK_INVALID",
            )
        else:
            _require(
                stat.S_ISLNK(value.st_mode)
                and value.st_uid == owner_uid
                and value.st_nlink == 1
                and os.readlink(path.name, dir_fd=descriptors[-1]) == expected,
                "LINK_INVALID",
            )
        initial = _identity(value)
        _require(
            _identity(path.lstat()) == initial,
            "LINK_CHANGED",
        )
        for descriptor, (named, epoch) in zip(
            descriptors[: len(ancestors)], ancestors, strict=True
        ):
            _require(
                _identity(os.fstat(descriptor)) == epoch and _identity(named.lstat()) == epoch,
                "LINK_CHANGED",
            )
        return initial, tuple(ancestors)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _metadata_records(
    prefix: Path,
    rows: dict[str, tuple[str, str, str, str]],
    ledger: dict[str, _Member],
    files: NumericalRuntimeFileSnapshots,
    source_indices: dict[str, dict[str, Any]],
    archive_pins: dict[str, CondaRuntimeArchivePin],
) -> int:
    generated = 0
    by_owner = {name: set[str]() for name in rows}
    for path, member in ledger.items():
        by_owner[member.package].add(path)
    for name, (version, build, filename, url) in rows.items():
        raw = files.observe_protected_member_bytes(
            prefix / "conda-meta" / f"{name}-{version}-{build}.json", maximum=1024**2
        ).raw
        record = _json(raw)
        _require(
            (
                record.get("name"),
                record.get("version"),
                record.get("build"),
                record.get("fn"),
                record.get("url"),
            )
            == (name, version, build, filename, url),
            "METADATA_INVALID",
        )
        _require(
            all(_same_value(record.get(key), value) for key, value in source_indices[name].items())
            and record.get("sha256") == archive_pins[filename].sha256.removeprefix("sha256:")
            and type(record.get("size")) is int
            and record.get("size") == archive_pins[filename].size_bytes,
            "METADATA_INVALID",
        )
        paths = record.get("paths_data", {})
        _require(
            type(paths) is dict
            and type(paths.get("paths_version")) is int
            and paths.get("paths_version") == 1
            and type(paths.get("paths")) is list
            and len(paths["paths"]) <= _MAX_MEMBERS,
            "METADATA_INVALID",
        )
        observed: set[str] = set()
        expected = by_owner[name]
        for row in paths["paths"]:
            _require(type(row) is dict, "METADATA_INVALID")
            path = _path(row.get("_path"))
            _require(path not in observed, "METADATA_INVALID")
            observed.add(path)
            if path not in expected:
                if name == "pip" and path in {"bin/pip", "bin/pip3"}:
                    _require(row.get("path_type") == "unix_python_entry_point", "METADATA_INVALID")
                    continue
                _require(
                    name == "pip" and path.endswith(".pyc") and _cache_source(path) in expected,
                    "METADATA_INVALID",
                )
                _require(not os.path.lexists(prefix / path), "BYTECODE_INVALID")
                generated += 1
            else:
                member = ledger[path]
                _require(
                    row.get("path_type") == ("softlink" if member.link is not None else "hardlink"),
                    "METADATA_INVALID",
                )
                _require(
                    row.get("sha256") == member.source_sha256.removeprefix("sha256:"),
                    "METADATA_INVALID",
                )
                _require(
                    type(row.get("size_in_bytes")) is int
                    and row.get("size_in_bytes") == member.source_size,
                    "METADATA_INVALID",
                )
        listed = record.get("files")
        _require(
            type(listed) is list
            and len(listed) == len(observed)
            and all(type(path) is str for path in listed)
            and expected <= observed
            and set(listed) == observed,
            "METADATA_INVALID",
        )
    return generated


def _same_value(left: object, right: object, depth: int = 0) -> bool:
    if type(left) is not type(right) or depth > 32:
        return False
    if type(right) is dict:
        assert isinstance(left, dict) and isinstance(right, dict)
        return left.keys() == right.keys() and all(
            _same_value(left[key], value, depth + 1) for key, value in right.items()
        )
    if type(right) is list:
        assert isinstance(left, list) and isinstance(right, list)
        return len(left) == len(right) and all(
            _same_value(a, b, depth + 1) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def audit_installed_conda31(
    plan: CondaRuntimeAuditPlan,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
    tool_admission: CondaArchiveToolAdmission,
) -> CondaRuntimeByteAudit:
    """Content-free public boundary; owned IO cleanup stays inside the mechanical audit."""
    try:
        return _audit_installed_conda31(
            plan,
            prefix=prefix,
            archive_root=archive_root,
            files=files,
            tool_admission=tool_admission,
        )
    except InstalledRuntimeProofError:
        raise
    except Exception:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_CONDA_INVALID") from None


def _audit_installed_conda31(
    plan: CondaRuntimeAuditPlan,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
    tool_admission: CondaArchiveToolAdmission,
) -> CondaRuntimeByteAudit:
    """Compare authoritative source bytes with a fixed materialization; no grant/write."""
    _validate_plan(plan)
    _require(isinstance(prefix, Path) and prefix.is_absolute() and ".." not in prefix.parts)
    _require(
        isinstance(archive_root, Path)
        and archive_root.is_absolute()
        and ".." not in archive_root.parts
    )
    _tool_fence(tool_admission)
    deadline = time.monotonic() + 180
    ledger: dict[str, _Member] = {}
    budget = _Budget()
    binary = text = 0
    links: dict[
        Path, tuple[str | None, tuple[int, ...], tuple[tuple[Path, tuple[int, ...]], ...]]
    ] = {}
    source_path = archive_root / plan.source_list_sha256.removeprefix("sha256:") / "sources.lock"
    source = files.read(
        source_path,
        sha256=plan.source_list_sha256,
        size=plan.source_list_size_bytes,
        maximum=128 * 1024,
    )
    rows = _source_rows(source, plan.archives)
    overlay_members: set[Path] = set()
    overlay_wheels: list[VerifiedRuntimeWheelMembers] = []
    overlay_roots: set[Path] = set()
    source_indices: dict[str, dict[str, Any]] = {}
    with ExitStack() as stack:
        archives: dict[str, zipfile.ZipFile] = {}
        for pin in plan.archives:
            archive_path = archive_root / pin.sha256.removeprefix("sha256:") / pin.filename
            descriptor, _raw = stack.enter_context(
                files.verified_open(
                    archive_path, sha256=pin.sha256, size=pin.size_bytes, maximum=64 * 1024**2
                )
            )
            archive = _zip(descriptor, pin)
            stack.callback(archive.fp.close if archive.fp is not None else lambda: None)
            stack.callback(archive.close)
            archives[pin.filename] = archive
        for overlay, (name, version, _sha_value) in zip(
            plan.overlay_archives, _OVERLAYS, strict=True
        ):
            candidate = _candidate_wheel(overlay, name, version, prefix, files)
            verified = verify_installed_runtime_wheel(
                candidate, prefix=prefix, archive_root=archive_root, files=files
            )
            _require(
                not overlay_members.intersection(verified.installed_members), "OWNERSHIP_CONFLICT"
            )
            overlay_members.update(verified.installed_members)
            overlay_wheels.append(verified)
            overlay_roots.update(verified.namespace_roots)
        files.require_closed_namespaces(
            overlay_roots, {path for path in overlay_members if path.parent != prefix / "bin"}
        )
        files.verify(_ZSTD_PATH, sha256=_ZSTD_SHA, size=_ZSTD_SIZE, maximum=2 * 1024**2)
        for name, (version, build, filename, _url) in rows.items():
            metadata: dict[str, dict[str, Any]] = {}
            for kind in ("info", "pkg"):
                _tool_fence(tool_admission)
                files.assert_unchanged()
                compressed = stack.enter_context(
                    archives[filename].open(f"{kind}-{filename[:-6]}.tar.zst")
                )
                reader = _ToolReader(compressed, deadline, tool=tool_admission)
                success = False
                try:
                    if kind == "info":
                        metadata = _info(reader, budget)
                        index = metadata["info/index.json"]
                        source_indices[name] = index
                        _require(
                            (index.get("name"), index.get("version"), index.get("build"))
                            == (name, version, build),
                            "METADATA_INVALID",
                        )
                    else:
                        if name == "pip":
                            _require(
                                metadata.get("info/link.json", {})
                                .get("noarch", {})
                                .get("entry_points")
                                == [
                                    "pip = pip._internal.cli.main:main",
                                    "pip3 = pip._internal.cli.main:main",
                                ],
                                "METADATA_INVALID",
                            )
                        counts = _payload(reader, budget, metadata, name, prefix, ledger)
                        binary += counts[0]
                        text += counts[1]
                    success = True
                finally:
                    reader.close(success=success)
                _tool_fence(tool_admission)
        _require((binary, text) == _TRANSFORMATION_COUNTS, "TRANSFORMATION_SET_MISMATCH")
        _require(
            set(budget.licenses)
            == {
                (name, "info/licenses/" + path)
                for name, path, _size_value, _hash_value in _LICENSES
            },
            "LICENSE_SET_MISMATCH",
        )
        generated = _metadata_records(
            prefix,
            rows,
            ledger,
            files,
            source_indices,
            {pin.filename: pin for pin in plan.archives},
        )
        overlay_names = {name for name, _version, _sha_value in _OVERLAYS}
        for path, member in ledger.items():
            target = prefix / path
            if member.package in overlay_names and target not in overlay_members:
                _require(not os.path.lexists(target), "OVERLAY_SURVIVOR")
            elif target not in overlay_members and member.link is None:
                files.verify(
                    target, sha256=member.final_sha256, size=member.size, maximum=2 * 1024**3
                )
                _require(stat.S_IMODE(target.lstat().st_mode) == member.mode, "MEMBER_MODE_INVALID")
        files.assert_unchanged()
        archived_caches = retained = 0
        for path, member in ledger.items():
            target = prefix / path
            overlaid = target in overlay_members
            replaced_package = member.package in overlay_names
            if member.cache_header is not None:
                archived_caches += 1
                source_name = _cache_source(path)
                _require(source_name in ledger, "BYTECODE_INVALID")
                original_source = ledger[source_name]
                header_mtime, header_size = struct.unpack("<2I", member.cache_header[8:16])
                _require(
                    header_mtime == (original_source.mtime & 0xFFFFFFFF)
                    and header_size == original_source.source_size,
                    "BYTECODE_INVALID",
                )
                if member.package == "python":
                    retained += 1
                    value = (prefix / source_name).lstat()
                    current = (int(value.st_mtime) & 0xFFFFFFFF, value.st_size) == (
                        header_mtime,
                        header_size,
                    )
                    _require(current != (source_name in _STALE_SOURCES), "BYTECODE_INVALID")
                else:
                    _require(not os.path.lexists(target), "BYTECODE_INVALID")
                    continue
            if replaced_package and not overlaid:
                _require(not os.path.lexists(target), "OVERLAY_SURVIVOR")
                continue
            if overlaid:
                continue
            if member.link is not None:
                resolved = _link_target(path, member.link)
                seen = {path}
                while resolved in ledger and ledger[resolved].link is not None:
                    _require(resolved not in seen and len(seen) < 64, "LINK_CYCLE")
                    seen.add(resolved)
                    resolved = _link_target(resolved, str(ledger[resolved].link))
                destination = prefix / resolved
                if resolved not in ledger:
                    _require(
                        (member.package, path, resolved)
                        in {
                            ("ncurses", "lib/terminfo", "share/terminfo"),
                            ("python", "lib/python3.1", "lib/python3.12"),
                        }
                        and any(
                            name.startswith(resolved + "/") and row.package == member.package
                            for name, row in ledger.items()
                        )
                        and member.source_sha256 == _hash(b"")
                        and member.size == 0,
                        "LINK_INVALID",
                    )
                    directory_epoch, directory_ancestors = _observe_link(
                        destination, None, files.owner_uid
                    )
                    links[destination] = (None, directory_epoch, directory_ancestors)
                else:
                    owner = ledger[resolved]
                    if owner.package == member.package:
                        _require(
                            member.source_sha256 == owner.source_sha256
                            and member.source_size == owner.source_size,
                            "LINK_INVALID",
                        )
                    else:
                        _require(
                            (
                                member.package,
                                path,
                                owner.package,
                                resolved,
                                member.source_sha256.removeprefix("sha256:"),
                                member.source_size,
                            )
                            in _CROSS_LINKS,
                            "LINK_INVALID",
                        )
                    _require(
                        owner.link is None and destination not in overlay_members, "LINK_INVALID"
                    )
                    files.verify(
                        destination, sha256=owner.final_sha256, size=owner.size, maximum=2 * 1024**3
                    )
                initial, ancestors = _observe_link(target, member.link, files.owner_uid)
                links[target] = (member.link, initial, ancestors)
                continue
        _require((archived_caches, retained, generated) == _CACHE_COUNTS, "BYTECODE_SET_MISMATCH")
        caches = {
            prefix / path
            for path, member in ledger.items()
            if member.package == "python" and member.cache_header is not None
        }
        files.require_closed_namespaces({path.parent for path in caches}, caches)
    files.assert_unchanged()
    for link_path, (link, initial, ancestors) in links.items():
        _require(
            _identity(link_path.lstat()) == initial
            and (link is None or os.readlink(link_path) == link)
            and all(_identity(parent.lstat()) == value for parent, value in ancestors),
            "LINK_CHANGED",
        )
    _tool_fence(tool_admission)
    _require(time.monotonic() < deadline, "TOOL_TIMEOUT")
    ledger_digest = hashlib.sha256()
    for path, member in sorted(ledger.items()):
        record = (
            path,
            member.package,
            member.source_sha256,
            member.final_sha256,
            member.size,
            member.link,
        )
        ledger_digest.update(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        )
    for (name, path), (sha, size) in sorted(budget.licenses.items()):
        ledger_digest.update(
            json.dumps((name, path, sha, size), separators=(",", ":")).encode() + b"\n"
        )

    def digest(value: object) -> str:
        return _hash(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        )

    return CondaRuntimeByteAudit(
        plan.profile,
        plan.source_list_sha256,
        digest([(pin.filename, pin.sha256, pin.size_bytes) for pin in plan.archives]),
        digest([(pin.wheel_filename, pin.sha256, pin.size_bytes) for pin in plan.overlay_archives]),
        sum(member.link is None for member in ledger.values()),
        sum(member.link is not None for member in ledger.values()),
        binary,
        text,
        archived_caches,
        retained,
        generated,
        len(budget.licenses),
        "sha256:" + ledger_digest.hexdigest(),
        frozenset(
            {
                prefix / path
                for path, member in ledger.items()
                if not (member.package in overlay_names and prefix / path not in overlay_members)
                and not (member.cache_header is not None and member.package != "python")
            }
            | {
                prefix / "conda-meta" / f"{name}-{version}-{build}.json"
                for name, (version, build, _filename, _url) in rows.items()
            }
            | {path for wheel in overlay_wheels for path in wheel.all_installed_members}
        ),
        tuple(
            sorted(
                (path, target)
                for path, (target, _epoch, _parents) in links.items()
                if target is not None
            )
        ),
        tuple(overlay_wheels),
    )

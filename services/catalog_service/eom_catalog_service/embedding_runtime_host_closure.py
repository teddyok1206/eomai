"""Fixed Linux tool seed: actual protected bytes, loader closure and held executable FDs.

This is not native installation admission. Root OS maintenance must drain users before
changing the loader/libraries; an executable FD cannot freeze the dynamic loader opens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import stat
import struct
import subprocess
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    require_runtime_proof,
)

# PyTorch CPU's pinned ELF metadata is 1,509,162 bytes; producer and parser share one bound.
MAX_READELF_OUTPUT_BYTES = 2 * 1024**2

_ABSENT_SEARCH_ROUTES = MappingProxyType(
    {
        "/lib/intel64": Path("/usr/lib/intel64"),
        "/lib/intel64_win": Path("/usr/lib/intel64_win"),
        "/lib/win-x64": Path("/usr/lib/win-x64"),
        # The absent parent proves the CUDA wheel's nested route cannot supply a library.
        "/usr/local/cuda/lib64": Path("/usr/local/cuda"),
    }
)

_LIB = Path("/usr/lib/x86_64-linux-gnu")
_LOADER = _LIB / "ld-linux-x86-64.so.2"
_ZSTD = Path("/usr/bin/zstd")
_READELF = Path("/usr/bin/x86_64-linux-gnu-readelf")
_CACHE = Path("/etc/ld.so.cache")
_CONFIG = Path("/etc/ld.so.conf.d")
_PRELOAD = Path("/etc/ld.so.preload")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C"}
# Exact reviewed raw OS candidates, not a root grant or a declaration of admission.
_FILES = (
    (_ZSTD, 1022760, "7c5468b370f7c47eda07281e3437fafc568f95d10420051e3aa522709f9342c5"),
    (_READELF, 789280, "871be389739ecf9924b052c2fde4d2a2068a54e882201b9c34897337a5a0a130"),
    (_LOADER, 236616, "c20a2dc8917c755f02b94049356320fe1f62ac7d9f8994731f807d9df39302da"),
    (
        _LIB / "libz.so.1.3",
        113000,
        "86200da370f20476a2507e9097a789b5ef97269b4ca8d5e164ad82dab9d99892",
    ),
    (
        _LIB / "liblzma.so.5.4.5",
        202904,
        "696e868dd0700a19a6d65fc01608ec2d70d3cb91f65710e89180cd2e688f30cb",
    ),
    (
        _LIB / "liblz4.so.1.9.4",
        137440,
        "40bffd0a098387368b16b992abd5f7cf43c0fa2f05cabe5a6d483719554adfda",
    ),
    (
        _LIB / "libctf-nobfd.so.0.0.0",
        216096,
        "586a020b55a53a8f8029a300c6e9d2d83b33c69c493baa4a9e9f102c30779b13",
    ),
    (
        _LIB / "libzstd.so.1.5.5",
        755864,
        "0a2128bc10841fb29e76d08d945864dfb0b6a66da5df6df5d8299197439e54bb",
    ),
    (
        _LIB / "libsframe.so.1.0.0",
        35168,
        "d2e00d05f3713bb0d5eb9f1a212cca2b34cd789a0c4cc0c529ee77827237383f",
    ),
    (
        _LIB / "libc.so.6",
        2129424,
        "3a15d66867d83762c7f2f1e37359cb8f6c5743edb369c65285cb0b1c4f7498bf",
    ),
    (
        _LIB / "libpthread.so.0",
        14408,
        "90491a21ce44efcf3bd4b65ec82501c091d7ebe7f8d9b341dd01d721001d9ecd",
    ),
    (
        _LIB / "libdl.so.2",
        14408,
        "c2994527172cc23b7fb0f7d611b71e00a37da27af12c2e5e9e0dc1a742886c96",
    ),
    (
        _LIB / "libutil.so.1",
        14408,
        "5181d2b5de571bf054395684bfe77db685badf0163ac50b5e47d2148b52f11c3",
    ),
    (
        _LIB / "libm.so.6",
        952616,
        "fce00b6f25f459cf4ae0b7fae4257909a1a8a86f9149e7c029a5d617baf1ccd0",
    ),
    (
        _LIB / "librt.so.1",
        14624,
        "6d072187d88e092e81561a44c03a4a41397319022c6d43519757cc051c576d82",
    ),
    (
        _LIB / "libresolv.so.2",
        64008,
        "1d730ea434da5a5595bc6a961d7a9ace83e03703205df9644044b3dca79c362f",
    ),
    (
        _LIB / "libgcc_s.so.1",
        183024,
        "d93224d2b0dab4247598be683adca02f5cf00586f99c187579cd7e92058fb7cb",
    ),
    (
        _LIB / "libstdc++.so.6.0.33",
        2592224,
        "1fd75fe70354a416d75aef22bcae68c47bd25d20e2d0568c30b1a9838cf62f11",
    ),
    (_CACHE, 45467, "bc2b95fdb167f457249c288055aa78a2fe3e67364b66d73a8f6d8dc745bcf3f3"),
    (
        Path("/etc/ld.so.conf"),
        34,
        "d4b198c463418b493208485def26a6f4c57279467b9dfa491b70433cedb602e8",
    ),
    (_CONFIG / "libc.conf", 44, "90d4c7e43e7661cd116010eb9f50ad5817e43162df344bd1ad10898851b15d41"),
    (
        _CONFIG / "x86_64-linux-gnu.conf",
        100,
        "f03e4740e6922b4f4a1181cd696b52f62f9f10d003740a8940f7121795c59c98",
    ),
    (
        _CONFIG / "fakeroot-x86_64-linux-gnu.conf",
        38,
        "af7edc777dd224bade078ba540538444db69856533c02e18a7f9fbbdd23bd181",
    ),
)
_ALIASES = (
    (Path("/usr/bin/readelf"), "x86_64-linux-gnu-readelf"),
    (Path("/lib"), "usr/lib"),
    (Path("/lib64"), "usr/lib64"),
    (Path("/usr/lib64/ld-linux-x86-64.so.2"), "../lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"),
    (_LIB / "libz.so.1", "libz.so.1.3"),
    (_LIB / "liblzma.so.5", "liblzma.so.5.4.5"),
    (_LIB / "liblz4.so.1", "liblz4.so.1.9.4"),
    (_LIB / "libctf-nobfd.so.0", "libctf-nobfd.so.0.0.0"),
    (_LIB / "libzstd.so.1", "libzstd.so.1.5.5"),
    (_LIB / "libsframe.so.1", "libsframe.so.1.0.0"),
    (_LIB / "libstdc++.so.6", "libstdc++.so.6.0.33"),
)
_SONAMES = {
    "libz.so.1": _LIB / "libz.so.1.3",
    "liblzma.so.5": _LIB / "liblzma.so.5.4.5",
    "liblz4.so.1": _LIB / "liblz4.so.1.9.4",
    "libctf-nobfd.so.0": _LIB / "libctf-nobfd.so.0.0.0",
    "libzstd.so.1": _LIB / "libzstd.so.1.5.5",
    "libsframe.so.1": _LIB / "libsframe.so.1.0.0",
    "libstdc++.so.6": _LIB / "libstdc++.so.6.0.33",
    **{
        name: _LIB / name
        for name in (
            "libc.so.6",
            "libpthread.so.0",
            "libdl.so.2",
            "libutil.so.1",
            "libm.so.6",
            "librt.so.1",
            "libresolv.so.2",
            "libgcc_s.so.1",
        )
    },
    "ld-linux-x86-64.so.2": _LOADER,
}
_NEEDED = {
    _ZSTD: ("libz.so.1", "liblzma.so.5", "liblz4.so.1", "libc.so.6"),
    _READELF: ("libctf-nobfd.so.0", "libz.so.1", "libzstd.so.1", "libsframe.so.1", "libc.so.6"),
    _LOADER: (),
    **{
        path: ("libc.so.6",)
        for path in _SONAMES.values()
        if path
        not in {_LOADER, _LIB / "libc.so.6", _LIB / "libm.so.6", _LIB / "libctf-nobfd.so.0.0.0"}
    },
    _LIB / "libctf-nobfd.so.0.0.0": ("libz.so.1", "libc.so.6"),
    _LIB / "libc.so.6": ("ld-linux-x86-64.so.2",),
    _LIB / "libm.so.6": ("libc.so.6", "ld-linux-x86-64.so.2"),
    _LIB / "libgcc_s.so.1": ("libc.so.6", "ld-linux-x86-64.so.2"),
    _LIB / "libstdc++.so.6.0.33": (
        "libm.so.6",
        "libc.so.6",
        "ld-linux-x86-64.so.2",
        "libgcc_s.so.1",
    ),
}
_SEARCH = (
    _LIB,
    Path("/usr/lib"),
    Path("/usr/local/lib"),
    Path("/usr/local/lib/x86_64-linux-gnu"),
    _LIB / "libfakeroot",
)


def _require(condition: bool, code: str = "INVALID") -> None:
    require_runtime_proof(condition, "HOST_" + code)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seed_bytes(files: tuple[tuple[Path, int, str], ...] | None = None) -> bytes:
    return json.dumps(
        {
            "files": [
                (str(path), size, "sha256:" + sha)
                for path, size, sha in (_FILES if files is None else files)
            ],
            "aliases": [(str(path), target) for path, target in _ALIASES],
            "absent_search_routes": [
                (route, str(path)) for route, path in _ABSENT_SEARCH_ROUTES.items()
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


FIXED_EMBEDDING_HOST_SEED_SHA256 = _hash(_seed_bytes())


def _files_with_loader_cache(
    *,
    cache_byte_count: int,
    cache_sha256: str,
) -> tuple[tuple[Path, int, str], ...]:
    _require(
        type(cache_byte_count) is int
        and 48 <= cache_byte_count <= 128 * 1024
        and type(cache_sha256) is str
        and re.fullmatch(r"sha256:[0-9a-f]{64}", cache_sha256) is not None,
        "SEED_INVALID",
    )
    _require(sum(path == _CACHE for path, _size, _sha in _FILES) == 1, "SEED_INVALID")
    return tuple(
        (path, cache_byte_count, cache_sha256.removeprefix("sha256:"))
        if path == _CACHE
        else (path, size, sha)
        for path, size, sha in _FILES
    )


def embedding_host_configuration_seed(*, cache_byte_count: int, cache_sha256: str) -> str:
    """Pure target seed derivation; replacing metadata never admits bytes or a runtime."""
    return _hash(
        _seed_bytes(
            _files_with_loader_cache(cache_byte_count=cache_byte_count, cache_sha256=cache_sha256)
        )
    )


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


def _directory(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


class _HostRoutes:
    """Only fixed OS aliases, named absences and protected ancestor identities."""

    def __init__(self, owner_uid: int) -> None:
        self.owner_uid = owner_uid
        self.directories: dict[Path, tuple[int, ...]] = {}
        self.aliases: dict[Path, tuple[tuple[int, ...], str]] = {}
        self.absent: set[Path] = set()

    def parent(self, path: Path) -> None:
        for parent in reversed(path.parents):
            if parent in self.directories:
                continue
            value = parent.lstat()
            sticky = (
                self.owner_uid != 0
                and parent == Path("/tmp")
                and bool(value.st_mode & stat.S_ISVTX)
            )
            _require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid in {0, self.owner_uid}
                and (not value.st_mode & 0o022 or sticky),
                "ROUTE_UNPROTECTED",
            )
            self.directories[parent] = _directory(value)

    def alias(self, path: Path, target: str) -> None:
        self.parent(path)
        value = path.lstat()
        _require(
            stat.S_ISLNK(value.st_mode)
            and value.st_uid == self.owner_uid
            and value.st_nlink == 1
            and os.readlink(path) == target,
            "ALIAS_INVALID",
        )
        self.aliases[path] = (_identity(value), target)

    def absence(self, path: Path) -> None:
        # Missing nested route retains its first absent component and protected parent.
        for parent in reversed((path, *path.parents)):
            if parent == Path("/"):
                continue
            try:
                parent.lstat()
            except FileNotFoundError:
                self.parent(parent)
                self.absent.add(parent)
                return
        _require(False, "UNEXPECTED_ROUTE")

    def assert_current(self) -> None:
        for path, initial in self.directories.items():
            _require(_directory(path.lstat()) == initial, "ROUTE_CHANGED")
        for path, (initial, target) in self.aliases.items():
            _require(
                _identity(path.lstat()) == initial and os.readlink(path) == target, "ALIAS_CHANGED"
            )
        for path in self.absent:
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            _require(False, "ROUTE_CHANGED")


@dataclass(frozen=True, slots=True)
class _Elf:
    soname: str | None
    needed: tuple[str, ...]
    interpreter: str | None
    definitions: frozenset[str]
    requirements: tuple[tuple[str, frozenset[str]], ...]


def _elf(raw: bytes) -> _Elf:
    """Bounded native ELF64 seed reader; no loading, section framework or foreign ABI."""
    _require(type(raw) is bytes and 64 <= len(raw) <= 8 * 1024**2, "ELF_INVALID")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", raw)
    (
        ident,
        kind,
        machine,
        version,
        _entry,
        phoff,
        _shoff,
        _flags,
        ehsize,
        phsize,
        phcount,
        *_rest,
    ) = header
    _require(
        ident[:7] == b"\x7fELF\x02\x01\x01"
        and ident[7] in {0, 3}
        and ident[8:] == bytes(8)
        and kind in {2, 3}
        and machine == 62
        and version == 1
        and ehsize == 64
        and phsize == 56
        and 0 < phcount <= 128
        and 64 <= phoff <= len(raw) - phcount * 56,
        "ELF_INVALID",
    )
    loads: list[tuple[int, int, int]] = []
    dynamic: tuple[int, int] | None = None
    interpreter: str | None = None
    for index in range(phcount):
        tag, _flags, offset, address, _physical, size, memory, alignment = struct.unpack_from(
            "<IIQQQQQQ", raw, phoff + index * 56
        )
        _require(
            offset <= len(raw)
            and size <= len(raw) - offset
            and size <= memory
            and (alignment in {0, 1} or alignment & (alignment - 1) == 0),
            "ELF_INVALID",
        )
        if tag == 1:
            loads.append((address, offset, size))
        elif tag == 2:
            _require(
                dynamic is None and size > 0 and size % 16 == 0 and size <= 65536, "ELF_INVALID"
            )
            dynamic = offset, size
        elif tag == 3:
            _require(interpreter is None and size <= 128, "ELF_INVALID")
            interpreter = _string(raw, offset, offset + size)
            _require(interpreter == "/lib64/ld-linux-x86-64.so.2", "ELF_LOADER_INVALID")
    _require(dynamic is not None and bool(loads), "ELF_INVALID")
    assert dynamic is not None

    def offset_of(address: int, size: int) -> int:
        candidates = [
            offset + address - base
            for base, offset, length in loads
            if base <= address and size <= length - (address - base)
        ]
        _require(len(candidates) == 1, "ELF_INVALID")
        return candidates[0]

    tags: dict[int, list[int]] = {}
    ended = False
    for offset in range(dynamic[0], sum(dynamic), 16):
        tag, value = struct.unpack_from("<QQ", raw, offset)
        if tag == 0:
            ended = True
            _require(value == 0, "ELF_INVALID")
        else:
            _require(not ended, "ELF_INVALID")
            tags.setdefault(tag, []).append(value)
    _require(ended and len(tags.get(5, ())) == len(tags.get(10, ())) == 1, "ELF_INVALID")
    _require(
        not {15, 29, 22, 0x7FFFFFFD, 0x7FFFFFFF, 0x6FFFFEFC, 0x6FFFFEFB}.intersection(tags),
        "ELF_SEARCH_INVALID",
    )
    _require(
        all(value & ~0x18 == 0 for value in tags.get(30, ()))
        and all(value & ~0x8000009 == 0 for value in tags.get(0x6FFFFFFB, ())),
        "ELF_FLAGS_INVALID",
    )
    strsize = tags[10][0]
    _require(0 < strsize <= 1024**2, "ELF_INVALID")
    strings = offset_of(tags[5][0], strsize)

    def text(index: int) -> str:
        _require(0 <= index < strsize, "ELF_INVALID")
        return _string(raw, strings + index, strings + strsize)

    needed = tuple(text(index) for index in tags.get(1, ()))
    _require(
        len(needed) <= 32
        and len(set(needed)) == len(needed)
        and all(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", name) for name in needed),
        "ELF_INVALID",
    )
    _require(len(tags.get(14, ())) <= 1, "ELF_INVALID")
    soname = text(tags[14][0]) if 14 in tags else None
    definitions: set[str] = set()
    requirements: dict[str, frozenset[str]] = {}
    for address_tag, count_tag, definition in (
        (0x6FFFFFFC, 0x6FFFFFFD, True),
        (0x6FFFFFFE, 0x6FFFFFFF, False),
    ):
        _require((address_tag in tags) == (count_tag in tags), "ELF_VERSION_INVALID")
        if address_tag not in tags:
            continue
        _require(
            len(tags[address_tag]) == len(tags[count_tag]) == 1 and 0 < tags[count_tag][0] <= 256,
            "ELF_VERSION_INVALID",
        )
        address = tags[address_tag][0]
        visited: set[int] = set()
        for ordinal in range(tags[count_tag][0]):
            _require(address not in visited, "ELF_VERSION_INVALID")
            visited.add(address)
            base = offset_of(address, 20 if definition else 16)
            if definition:
                current, flags, _index, count, _hash_value, auxiliary, following = (
                    struct.unpack_from("<HHHHIII", raw, base)
                )
                _require(flags & ~3 == 0, "ELF_VERSION_INVALID")
                file = ""
            else:
                current, count, name, auxiliary, following = struct.unpack_from("<HHIII", raw, base)
                file = text(name)
                _require(file in needed and file not in requirements, "ELF_VERSION_INVALID")
            _require(
                current == 1 and 0 < count <= 256 and auxiliary >= (20 if definition else 16),
                "ELF_VERSION_INVALID",
            )
            cursor = address + auxiliary
            names: set[str] = set()
            aux_seen: set[int] = set()
            first = ""
            for item in range(count):
                _require(cursor not in aux_seen, "ELF_VERSION_INVALID")
                aux_seen.add(cursor)
                where = offset_of(cursor, 8 if definition else 16)
                if definition:
                    name, next_aux = struct.unpack_from("<II", raw, where)
                else:
                    _hash_value, flags, _index, name, next_aux = struct.unpack_from(
                        "<IHHII", raw, where
                    )
                    _require(flags & ~2 == 0, "ELF_VERSION_INVALID")
                value = text(name)
                _require(
                    re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", value) is not None,
                    "ELF_VERSION_INVALID",
                )
                names.add(value)
                first = value if item == 0 else first
                _require((next_aux == 0) == (item == count - 1), "ELF_VERSION_INVALID")
                cursor += next_aux
            if definition:
                _require(first not in definitions, "ELF_VERSION_INVALID")
                definitions.add(first)
            else:
                requirements[file] = frozenset(names)
            _require((following == 0) == (ordinal == tags[count_tag][0] - 1), "ELF_VERSION_INVALID")
            address += following
    return _Elf(soname, needed, interpreter, frozenset(definitions), tuple(requirements.items()))


def _string(raw: bytes, offset: int, end: int) -> str:
    _require(0 <= offset < end <= len(raw), "STRING_INVALID")
    stop = raw.find(b"\0", offset, min(end, offset + 513))
    _require(stop >= offset, "STRING_INVALID")
    value = raw[offset:stop].decode("ascii", "strict")
    _require(bool(value) and all(32 <= ord(char) < 127 for char in value), "STRING_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class EmbeddingLoaderCacheEntry:
    name: str
    path: str
    abi: int
    osversion: int
    hardware: int


def read_embedding_loader_cache_entries(raw: bytes) -> tuple[EmbeddingLoaderCacheEntry, ...]:
    """Bounded existing cache ABI parser; returned paths are data, never resolution grants."""
    _require(type(raw) is bytes and 48 <= len(raw) <= 128 * 1024, "CACHE_INVALID")
    magic, count, strings, flags, extension = struct.unpack_from("<20sIIB3xI", raw)
    start = 48 + count * 24
    _require(
        magic == b"glibc-ld.so.cache1.1"
        and 0 < count <= 4096
        and flags == 2
        and raw[29:32] == bytes(3)
        and raw[36:48] == bytes(12)
        and start < len(raw)
        and 0 < strings <= len(raw) - start
        and start + strings <= extension <= len(raw),
        "CACHE_INVALID",
    )
    entries: list[EmbeddingLoaderCacheEntry] = []
    for index in range(count):
        abi, key, value, osversion, hardware = struct.unpack_from("<IIIIQ", raw, 48 + index * 24)
        _require(
            start <= key < start + strings and start <= value < start + strings, "CACHE_INVALID"
        )
        name, path = _string(raw, key, start + strings), _string(raw, value, start + strings)
        entries.append(EmbeddingLoaderCacheEntry(name, path, abi, osversion, hardware))
    return tuple(entries)


def embedding_host_loader_cache_routes() -> tuple[tuple[str, str], ...]:
    """The unchanged CPU base routes; CUDA may validate but never modify this table."""
    return tuple(
        (name, "/lib/x86_64-linux-gnu/" + name)
        for name in _SONAMES
        if name != "ld-linux-x86-64.so.2"
    )


def validate_embedding_loader_cache(raw: bytes) -> None:
    """Keep the released CPU interpretation, including ignoring unrelated cache names."""
    observed: dict[str, list[tuple[int, str, int, int]]] = {}
    for entry in read_embedding_loader_cache_entries(raw):
        name = entry.name
        if name in _SONAMES and name != "ld-linux-x86-64.so.2":
            observed.setdefault(name, []).append(
                (entry.abi, entry.path, entry.osversion, entry.hardware)
            )
    _require(set(observed) == set(_SONAMES) - {"ld-linux-x86-64.so.2"}, "CACHE_SET_MISMATCH")
    for name, entries in observed.items():
        _require(entries == [(0x303, "/lib/x86_64-linux-gnu/" + name, 0, 0)], "CACHE_ROUTE_INVALID")


def _cleanup(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_CLEANUP_UNCERTAIN") from None
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


class ProtectedEmbeddingHostClosure:
    """Owner-held current fixed seed; not a serialized or native admission certificate."""

    def __init__(
        self,
        files: NumericalRuntimeFileSnapshots,
        routes: _HostRoutes,
        stack: ExitStack,
        descriptors: dict[Path, int],
        identities: dict[Path, tuple[int, ...]],
        seed_sha256: str,
        soname_versions: dict[str, frozenset[str]] | None = None,
        assert_mount_current: Callable[[], None] | None = None,
    ) -> None:
        self._files, self._routes, self._stack = files, routes, stack
        self._descriptors, self._identities = descriptors, identities
        self.seed_sha256 = seed_sha256
        self._soname_versions = {} if soname_versions is None else dict(soname_versions)
        self._loader_path = _LOADER
        self._assert_mount_current = assert_mount_current
        self._closed = False

    def __enter__(self) -> ProtectedEmbeddingHostClosure:
        self.assert_current()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self.assert_current()
            finally:
                self._closed = True
                self._stack.close()

    def assert_current(self) -> None:
        try:
            _require(not self._closed, "CLOSED")
            if self._assert_mount_current is not None:
                self._assert_mount_current()
            self._files.assert_unchanged()
            self._routes.assert_current()
            for path, descriptor in self._descriptors.items():
                _require(
                    _identity(os.fstat(descriptor))
                    == _identity(path.lstat())
                    == self._identities[path],
                    "FD_CHANGED",
                )
                _no_capability(descriptor)
        except OSError:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_FILE_UNAVAILABLE") from None

    def _spawn(
        self, tool: Path, *, member: int | None, deadline: float | None = None
    ) -> subprocess.Popen[bytes]:
        self.assert_current()
        if deadline is not None:
            _require(time.monotonic() < deadline, "TOOL_TIMEOUT")
        descriptor = self._descriptors[tool]
        command = (
            ["/usr/bin/zstd", "-q", "-d", "-c"]
            if tool == _ZSTD
            else [
                "/usr/bin/readelf",
                "--wide",
                "--file-header",
                "--program-headers",
                "--dynamic",
                "--version-info",
                f"/proc/self/fd/{member}",
            ]
        )
        process = subprocess.Popen(
            command,
            executable=f"/proc/self/fd/{descriptor}",
            pass_fds=(descriptor,) if member is None else (descriptor, member),
            stdin=subprocess.PIPE if member is None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=dict(_ENV),
            cwd="/",
            close_fds=True,
        )
        try:
            self.assert_current()
            if deadline is not None:
                _require(time.monotonic() < deadline, "TOOL_TIMEOUT")
            return process
        except BaseException:
            _cleanup(process)
            raise

    def open_zstd(self) -> subprocess.Popen[bytes]:
        """Only this fixed decoder; the Conda owner owns bounded duplex IO and reaping."""
        try:
            return self._spawn(_ZSTD, member=None)
        except InstalledRuntimeProofError:
            raise
        except Exception:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_TOOL_UNAVAILABLE") from None

    def fixed_soname_versions(self, name: str) -> frozenset[str]:
        """Exact captured immutable definitions only, not an arbitrary host resolver."""
        self.assert_current()
        _require(type(name) is str and name in self._soname_versions, "SONAME_UNAVAILABLE")
        return self._soname_versions[name]

    def fixed_loader_path(self) -> Path:
        """Actual source-fixed captured loader identity; aliases/epochs remain current."""
        self.assert_current()
        _require(self._loader_path in self._descriptors, "LOADER_UNAVAILABLE")
        return self._loader_path

    def assert_mapped_file(self, path: Path, *, device: int, inode: int) -> None:
        """Match an observed executable mapping against this already captured host ledger.

        No path resolution, new allowlist or byte rehash occurs. The caller independently
        owns process/start-time/unit observation; these ordinary values cannot attest it.
        """
        self.assert_current()
        _require(
            type(device) is int and type(inode) is int and device >= 0 and inode > 0,
            "MAPPED_FILE_INVALID",
        )
        initial = self._identities.get(path)
        _require(
            initial is not None
            and initial[:2] == (device, inode)
            and path in self._descriptors
            and os.pread(self._descriptors[path], 4, 0) == b"\x7fELF",
            "MAPPED_FILE_UNAVAILABLE",
        )

    def assert_absent_search_route(self, route: str) -> None:
        """Only the pinned, actually absent vendor directories; never a host search grant."""
        _require(type(route) is str, "ROUTE_INVALID")
        canonical = _ABSENT_SEARCH_ROUTES.get(route)
        _require(canonical is not None and canonical in self._routes.absent, "ROUTE_INVALID")
        self.assert_current()

    def inspect_elf(self, descriptor: int, *, deadline: float) -> bytes:
        """Fixed readelf on an already owner-held member FD; bounded absolute deadline."""
        _require(
            type(descriptor) is int
            and descriptor >= 0
            and type(deadline) is float
            and time.monotonic() < deadline <= time.monotonic() + 90,
            "INSPECTION_INVALID",
        )
        try:
            initial = _identity(os.fstat(descriptor))
        except OSError:
            raise InstalledRuntimeProofError(
                "INSTALLED_RUNTIME_HOST_INSPECTION_UNAVAILABLE"
            ) from None
        _require(
            stat.S_ISREG(initial[4])
            and initial[2] == self._files.owner_uid
            and initial[5] == 1
            and not initial[4] & 0o6022
            and 64 <= initial[6] <= 2 * 1024**3,
            "INSPECTION_INVALID",
        )
        _no_capability(descriptor)
        finish = min(deadline, time.monotonic() + 10)
        selector: selectors.BaseSelector | None = None
        process: subprocess.Popen[bytes] | None = None
        try:
            selector = selectors.DefaultSelector()
            process = self._spawn(_READELF, member=descriptor, deadline=finish)
            _require(process.stdout is not None, "TOOL_UNAVAILABLE")
            assert process.stdout is not None
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            chunks: list[bytes] = []
            count = 0
            while True:
                _require(time.monotonic() < finish, "TOOL_TIMEOUT")
                events = selector.select(finish - time.monotonic())
                _require(time.monotonic() < finish, "TOOL_TIMEOUT")
                if not events:
                    continue
                try:
                    raw = os.read(process.stdout.fileno(), 65536)
                except BlockingIOError:
                    continue
                _require(time.monotonic() < finish, "TOOL_TIMEOUT")
                if not raw:
                    break
                count += len(raw)
                _require(count <= MAX_READELF_OUTPUT_BYTES, "TOOL_OVERFLOW")
                chunks.append(raw)
            _require(process.wait(timeout=max(0, finish - time.monotonic())) == 0, "TOOL_FAILED")
            _require(time.monotonic() < finish, "TOOL_TIMEOUT")
            _require(_identity(os.fstat(descriptor)) == initial, "INSPECTION_CHANGED")
            self.assert_current()
            _require(time.monotonic() < finish, "TOOL_TIMEOUT")
            return b"".join(chunks)
        except subprocess.TimeoutExpired:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_TOOL_TIMEOUT") from None
        except InstalledRuntimeProofError:
            raise
        except Exception:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_TOOL_UNAVAILABLE") from None
        finally:
            try:
                if process is not None:
                    _cleanup(process)
            finally:
                if selector is not None:
                    selector.close()


def _no_capability(descriptor: int) -> None:
    try:
        _require(not os.getxattr(descriptor, "security.capability"), "CAPABILITY_INVALID")
    except OSError as exc:
        _require(exc.errno in {61, 95}, "CAPABILITY_UNAVAILABLE")


def capture_protected_embedding_host(
    *, expected_seed_sha256: str, files: NumericalRuntimeFileSnapshots
) -> ProtectedEmbeddingHostClosure:
    """Compare actual fixed seed with a separate caller-held expected pin before tools.

    This current local byte/epoch result does not establish root maintenance ownership,
    historical bootstrap provenance, whole-prefix admission or operator authority.
    """
    _require(
        type(expected_seed_sha256) is str
        and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_seed_sha256) is not None
        and expected_seed_sha256 == _hash(_seed_bytes()),
        "SEED_PIN_INVALID",
    )
    return _capture_embedding_host(
        expected_seed_sha256=expected_seed_sha256, files=files, fixed_files=_FILES
    )


def _capture_embedding_host(
    *,
    expected_seed_sha256: str,
    files: NumericalRuntimeFileSnapshots,
    fixed_files: tuple[tuple[Path, int, str], ...],
    assert_mount_current: Callable[[], None] | None = None,
) -> ProtectedEmbeddingHostClosure:
    _require(
        type(files) is NumericalRuntimeFileSnapshots
        and type(files.owner_uid) is int
        and files.owner_uid >= 0,
        "FILES_INVALID",
    )
    # Fixed host checks must not grow with the caller's later whole-prefix inventory.
    # The caller still owns the complete prefix check; this owner retains every host check.
    host_files = NumericalRuntimeFileSnapshots(files.owner_uid)
    stack = ExitStack()
    try:
        routes = _HostRoutes(host_files.owner_uid)
        for path, target in _ALIASES:
            routes.alias(path, target)
        routes.absence(_PRELOAD)
        for route in _ABSENT_SEARCH_ROUTES.values():
            routes.absence(route)
        host_files.require_closed_namespaces(
            {_CONFIG}, {path for path, _size, _sha in fixed_files if path.parent == _CONFIG}
        )
        descriptors: dict[Path, int] = {}
        identities: dict[Path, tuple[int, ...]] = {}
        objects: dict[Path, _Elf] = {}
        for path, size, sha in fixed_files:
            routes.parent(path)
            _require(
                type(size) is int
                and 0 < size <= 8 * 1024**2
                and re.fullmatch(r"[0-9a-f]{64}", sha) is not None,
                "SEED_INVALID",
            )
            descriptor, raw = stack.enter_context(
                host_files.verified_open(
                    path, sha256="sha256:" + sha, size=size, maximum=8 * 1024**2, retain_bytes=True
                )
            )
            descriptors[path] = descriptor
            identities[path] = _identity(os.fstat(descriptor))
            _no_capability(descriptor)
            if path in _NEEDED:
                objects[path] = _elf(raw)
                _require(set(objects[path].needed) == set(_NEEDED[path]), "DEPENDENCY_SET_MISMATCH")
                expected_soname = next(
                    (name for name, target in _SONAMES.items() if target == path), None
                )
                _require(objects[path].soname == expected_soname, "SONAME_INVALID")
                if path in {_ZSTD, _READELF}:
                    _require(
                        objects[path].interpreter == "/lib64/ld-linux-x86-64.so.2",
                        "ELF_LOADER_INVALID",
                    )
            elif path == _CACHE:
                validate_embedding_loader_cache(raw)
        for current in objects.values():
            for name, required in current.requirements:
                _require(required <= objects[_SONAMES[name]].definitions, "VERSION_UNAVAILABLE")
        for root in _SEARCH:
            routes.absence(root / "glibc-hwcaps")
            if root == _LIB:
                continue
            for name in _SONAMES:
                routes.absence(root / name)
        result = ProtectedEmbeddingHostClosure(
            host_files,
            routes,
            stack,
            descriptors,
            identities,
            expected_seed_sha256,
            {name: objects[path].definitions for name, path in _SONAMES.items()},
            assert_mount_current,
        )
        result.assert_current()
        return result
    except InstalledRuntimeProofError:
        stack.close()
        raise
    except Exception:
        stack.close()
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_INVALID") from None

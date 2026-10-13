"""Synthetic fixed-host bytes/FD/process tests, not OS or runtime admission."""

from __future__ import annotations

import errno
import hashlib
import os
import selectors
import stat
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _deny(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("invalid/unavailable input must not read or spawn")


def _elf(
    *,
    needed: tuple[str, ...] = (),
    soname: str | None = None,
    interpreter: bool = False,
    definition: str | None = None,
    requirement: tuple[str, str] | None = None,
    extra: tuple[int, int] | None = None,
) -> bytes:
    raw = bytearray(2048)
    strings = bytearray(b"\0")

    def name(value: str) -> int:
        offset = len(strings)
        strings.extend(value.encode() + b"\0")
        return offset

    tags = [(5, 0x400000 + 1024)]
    tags.extend((1, name(value)) for value in needed)
    if soname is not None:
        tags.append((14, name(soname)))
    if definition is not None:
        tags += [(0x6FFFFFFC, 0x400000 + 1536), (0x6FFFFFFD, 1)]
        struct.pack_into("<HHHHIII", raw, 1536, 1, 0, 2, 1, 0, 20, 0)
        struct.pack_into("<II", raw, 1556, name(definition), 0)
    if requirement is not None:
        tags += [(0x6FFFFFFE, 0x400000 + 1600), (0x6FFFFFFF, 1)]
        struct.pack_into("<HHIII", raw, 1600, 1, 1, name(requirement[0]), 16, 0)
        struct.pack_into("<IHHII", raw, 1616, 0, 0, 2, name(requirement[1]), 0)
    if extra is not None:
        tags.append(extra)
    tags.extend(((10, len(strings)), (0, 0)))
    for index, pair in enumerate(tags):
        struct.pack_into("<QQ", raw, 512 + index * 16, *pair)
    raw[1024 : 1024 + len(strings)] = strings
    phcount = 3 if interpreter else 2
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        raw,
        0,
        b"\x7fELF\x02\x01\x01" + bytes(9),
        3,
        62,
        1,
        0,
        64,
        0,
        0,
        64,
        56,
        phcount,
        0,
        0,
        0,
    )
    struct.pack_into("<IIQQQQQQ", raw, 64, 1, 5, 0, 0x400000, 0, len(raw), len(raw), 4096)
    struct.pack_into(
        "<IIQQQQQQ", raw, 120, 2, 6, 512, 0x400200, 0, len(tags) * 16, len(tags) * 16, 8
    )
    if interpreter:
        path = b"/lib64/ld-linux-x86-64.so.2\0"
        raw[256 : 256 + len(path)] = path
        struct.pack_into("<IIQQQQQQ", raw, 176, 3, 4, 256, 0x400100, 0, len(path), len(path), 1)
    return bytes(raw)


def _cache(entries: tuple[tuple[str, str, int, int, int], ...]) -> bytes:
    start = 48 + len(entries) * 24
    strings = bytearray()
    rows = bytearray()
    for name, path, abi, version, hardware in entries:
        key = start + len(strings)
        strings.extend(name.encode() + b"\0")
        value = start + len(strings)
        strings.extend(path.encode() + b"\0")
        rows.extend(struct.pack("<IIIIQ", abi, key, value, version, hardware))
    return (
        struct.pack(
            "<20sIIB3xI12x",
            b"glibc-ld.so.cache1.1",
            len(entries),
            len(strings),
            2,
            start + len(strings),
        )
        + rows
        + strings
    )


@pytest.mark.parametrize("flags", [0x1, 0x8, 0x9, 0x8000000, 0x8000009])
def test_fixed_host_supports_now_nodelete_pie_without_search_changes(flags: int) -> None:
    assert host._elf(_elf(extra=(0x6FFFFFFB, flags))).needed == ()


@pytest.mark.parametrize("flags", [0x2, 0x4, 0x10, 0x800, 0x800000B])
def test_fixed_host_rejects_unreviewed_dynamic_flags(flags: int) -> None:
    with pytest.raises(InstalledRuntimeProofError, match="ELF_FLAGS_INVALID"):
        host._elf(_elf(extra=(0x6FFFFFFB, flags)))


def _put(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    path.chmod(mode)


@dataclass(frozen=True)
class _Fixture:
    expected: str
    files: NumericalRuntimeFileSnapshots
    zstd: Path
    readelf: Path
    loader: Path
    library: Path
    cache: Path
    config: Path
    alias: Path
    preload: Path
    search: Path

    def capture(self) -> host.ProtectedEmbeddingHostClosure:
        return host.capture_protected_embedding_host(
            expected_seed_sha256=self.expected, files=self.files
        )


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fault: str | None = None
) -> _Fixture:
    zstd, readelf = tmp_path / "usr/bin/zstd", tmp_path / "usr/bin/readelf-body"
    loader, library = tmp_path / "usr/lib/loader", tmp_path / "usr/lib/libc.so.6"
    cache, config, preload = (
        tmp_path / "etc/cache",
        tmp_path / "etc/conf.d",
        tmp_path / "etc/preload",
    )
    alias, search = tmp_path / "usr/bin/readelf", tmp_path / "other"
    version = "GLIBC_2.38"
    tool = _elf(needed=("libc.so.6",), interpreter=True, requirement=("libc.so.6", version))
    libc = _elf(
        needed=("ld-linux-x86-64.so.2",),
        soname="libc.so.6",
        definition="WRONG" if fault == "version" else version,
    )
    if fault == "dependency":
        tool = _elf(needed=("unowned.so",), interpreter=True)
    raw_members = {
        zstd: tool,
        readelf: tool,
        loader: _elf(soname="ld-linux-x86-64.so.2"),
        library: libc,
        cache: _cache((("libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6", 0x303, 0, 0),)),
        config / "one.conf": b"/usr/lib\n",
    }
    for path, raw in raw_members.items():
        _put(path, raw)
    search.mkdir(mode=0o700)
    alias.symlink_to("readelf-body")
    monkeypatch.setattr(
        host, "_FILES", tuple((path, len(raw), _hash(raw)[7:]) for path, raw in raw_members.items())
    )
    monkeypatch.setattr(host, "_ALIASES", ((alias, "readelf-body"),))
    monkeypatch.setattr(
        host,
        "_ABSENT_SEARCH_ROUTES",
        {route: library.parent / route.rsplit("/", 1)[1] for route in host._ABSENT_SEARCH_ROUTES},
    )
    monkeypatch.setattr(
        host,
        "_NEEDED",
        {
            zstd: ("libc.so.6",),
            readelf: ("libc.so.6",),
            loader: (),
            library: ("ld-linux-x86-64.so.2",),
        },
    )
    monkeypatch.setattr(host, "_SONAMES", {"libc.so.6": library, "ld-linux-x86-64.so.2": loader})
    for name, value in (
        ("_ZSTD", zstd),
        ("_READELF", readelf),
        ("_LOADER", loader),
        ("_LIB", library.parent),
        ("_CACHE", cache),
        ("_CONFIG", config),
        ("_PRELOAD", preload),
    ):
        monkeypatch.setattr(host, name, value)
    monkeypatch.setattr(host, "_SEARCH", (library.parent, search))
    for path in tmp_path.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
    tmp_path.chmod(0o700)
    return _Fixture(
        _hash(host._seed_bytes()),
        NumericalRuntimeFileSnapshots(os.geteuid()),
        zstd,
        readelf,
        loader,
        library,
        cache,
        config,
        alias,
        preload,
        search,
    )


def test_source_fixed_seed_has_exact_bounded_pins_and_no_native_admission() -> None:
    assert len(host._FILES) == 23 and len(host._ALIASES) == 11
    assert {"librt.so.1", "libresolv.so.2", "libgcc_s.so.1", "libstdc++.so.6"} <= set(host._SONAMES)
    assert all(
        type(size) is int and 0 < size <= 8 * 1024**2 and len(sha) == 64
        for _path, size, sha in host._FILES
    )
    assert _hash(host._seed_bytes()) == host.FIXED_EMBEDDING_HOST_SEED_SHA256
    assert not hasattr(host, "NativeEmbeddingInstallationAdmission")


def test_complete_synthetic_seed_retains_fd_routes_bytes_and_closes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    capture = fixture.capture()
    descriptors = tuple(capture._descriptors.values())
    assert capture.seed_sha256 == fixture.expected
    capture.assert_current()
    assert capture.fixed_loader_path() == fixture.loader
    assert capture.fixed_soname_versions("libc.so.6") == frozenset({"GLIBC_2.38"})
    with pytest.raises(InstalledRuntimeProofError, match="SONAME_UNAVAILABLE"):
        capture.fixed_soname_versions("unregistered.so")
    capture.close()
    capture.close()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    with pytest.raises(InstalledRuntimeProofError, match="HOST_CLOSED"):
        capture.assert_current()
    with pytest.raises(InstalledRuntimeProofError, match="HOST_CLOSED"):
        capture.fixed_loader_path()


@pytest.mark.parametrize("expected", [None, True, 1, "bad", "sha256:" + "a" * 64])
def test_unaccepted_expected_pin_denies_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: Any
) -> None:
    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(subprocess, "Popen", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="SEED_PIN_INVALID"):
        host.capture_protected_embedding_host(
            expected_seed_sha256=expected, files=NumericalRuntimeFileSnapshots(os.geteuid())
        )


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "dependency",
        "raw",
        "mode",
        "hardlink",
        "alias_hardlink",
        "symlink",
        "alias",
        "config_extra",
        "preload",
        "hwcap",
        "competing",
    ],
)
def test_seed_failure_never_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, fault=fault)
    if fault == "raw":
        fixture.library.write_bytes(b"changed")
    elif fault == "mode":
        fixture.library.chmod(0o666)
    elif fault == "hardlink":
        os.link(fixture.library, fixture.library.parent / "other")
    elif fault == "alias_hardlink":
        os.link(fixture.alias, fixture.alias.parent / "other", follow_symlinks=False)
    elif fault == "symlink":
        fixture.library.unlink()
        fixture.library.symlink_to(fixture.loader.name)
    elif fault == "alias":
        fixture.alias.unlink()
        fixture.alias.symlink_to(fixture.zstd.name)
    elif fault == "config_extra":
        _put(fixture.config / "extra.conf", b"extra")
    elif fault == "preload":
        _put(fixture.preload, b"inject")
    elif fault == "hwcap":
        (fixture.search / "glibc-hwcaps").mkdir()
    elif fault == "competing":
        _put(fixture.search / "libc.so.6", b"competing")
    monkeypatch.setattr(subprocess, "Popen", _deny)
    with pytest.raises(InstalledRuntimeProofError):
        fixture.capture()


@pytest.mark.parametrize(
    "fault", ["loader", "library", "cache", "alias", "config", "preload", "parent", "fd"]
)
def test_current_epoch_revalidation_denies_every_seed_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    capture = fixture.capture()
    if fault in {"loader", "library", "cache"}:
        path = getattr(fixture, fault)
        path.write_bytes(path.read_bytes() + b"changed")
    elif fault == "alias":
        fixture.alias.unlink()
        fixture.alias.symlink_to("zstd")
    elif fault == "config":
        _put(fixture.config / "extra.conf", b"extra")
    elif fault == "preload":
        _put(fixture.preload, b"new")
    elif fault == "parent":
        fixture.loader.parent.chmod(0o777)
    else:
        replacement = os.open(fixture.library, os.O_RDONLY)
        try:
            os.dup2(replacement, capture._descriptors[fixture.loader])
        finally:
            os.close(replacement)
    with pytest.raises(InstalledRuntimeProofError):
        capture.assert_current()
    with pytest.raises(InstalledRuntimeProofError):
        capture.close()


def test_same_bytes_named_inode_replacement_denies_and_closes_all_held_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    capture = fixture.capture()
    descriptors = tuple(capture._descriptors.values())
    raw = fixture.library.read_bytes()
    fixture.library.rename(fixture.library.parent / "old")
    _put(fixture.library, raw)
    with pytest.raises(InstalledRuntimeProofError, match="FD_CHANGED"):
        capture.assert_current()
    with pytest.raises(InstalledRuntimeProofError):
        capture.close()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("capability", [b"capability", b"", None])
def test_capability_closure_does_not_ignore_os_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capability: bytes | None
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    if capability is None:

        def failure(_fd: int, _name: str) -> NoReturn:
            raise OSError(errno.EACCES, "synthetic")

        monkeypatch.setattr(os, "getxattr", failure)
    else:
        monkeypatch.setattr(os, "getxattr", lambda _fd, _name: capability)
    if capability == b"":
        with fixture.capture() as capture:
            capture.assert_current()
    else:
        with pytest.raises(InstalledRuntimeProofError, match="CAPABILITY"):
            fixture.capture()


@pytest.mark.parametrize(
    "mutation",
    [
        "class",
        "endian",
        "machine",
        "phcount",
        "phsize",
        "offset",
        "dynamic",
        "string",
        "rpath",
        "runpath",
        "filter",
        "audit",
        "flags",
        "flags1",
        "loader",
        "version",
    ],
)
def test_native_seed_elf_denies_foreign_routes_bounds_and_versions(mutation: str) -> None:
    raw = bytearray(
        _elf(needed=("libc.so.6",), interpreter=True, requirement=("libc.so.6", "GLIBC_2.38"))
    )
    if mutation == "class":
        raw[4] = 1
    elif mutation == "endian":
        raw[5] = 2
    elif mutation == "machine":
        struct.pack_into("<H", raw, 18, 183)
    elif mutation == "phcount":
        struct.pack_into("<H", raw, 56, 129)
    elif mutation == "phsize":
        struct.pack_into("<H", raw, 54, 1)
    elif mutation == "offset":
        struct.pack_into("<Q", raw, 128, len(raw) + 1)
    elif mutation == "dynamic":
        struct.pack_into("<Q", raw, 512 + 16 * 5, 1)
    elif mutation == "string":
        struct.pack_into("<Q", raw, 520, 2**64 - 1)
    elif mutation in {"rpath", "runpath", "filter", "audit", "flags", "flags1"}:
        tags = {
            "rpath": 15,
            "runpath": 29,
            "filter": 0x7FFFFFFF,
            "audit": 0x6FFFFEFC,
            "flags": 30,
            "flags1": 0x6FFFFFFB,
        }
        raw = bytearray(_elf(extra=(tags[mutation], 0x800)))
    elif mutation == "loader":
        raw[256:263] = b"/unsafe"
    else:
        struct.pack_into("<H", raw, 1600, 2)
    with pytest.raises(InstalledRuntimeProofError):
        host._elf(bytes(raw))


def test_complete_version_requirements_are_compared_not_just_maximum() -> None:
    parsed = host._elf(
        _elf(needed=("libc.so.6",), requirement=("libc.so.6", "GLIBC_2.38"), definition="EXAMPLE_1")
    )
    assert parsed.definitions == frozenset({"EXAMPLE_1"})
    assert parsed.requirements == (("libc.so.6", frozenset({"GLIBC_2.38"})),)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "abi",
        "version",
        "hardware",
        "route",
        "key",
        "strings",
        "reserved",
        "format",
        "count",
    ],
)
def test_native_cache_never_guesses_or_accepts_competing_routes(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    monkeypatch.setattr(
        host,
        "_SONAMES",
        {"libc.so.6": Path("/usr/lib/libc.so.6"), "ld-linux-x86-64.so.2": Path("/usr/lib/loader")},
    )
    entry = ("libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6", 0x303, 0, 0)
    rows = (entry, entry) if fault == "duplicate" else (entry,)
    raw = bytearray(_cache(rows))
    if fault == "abi":
        struct.pack_into("<I", raw, 48, 0x103)
    elif fault == "version":
        struct.pack_into("<I", raw, 60, 1)
    elif fault == "hardware":
        struct.pack_into("<Q", raw, 64, 1)
    elif fault == "route":
        raw = bytearray(_cache(((entry[0], "/unowned/libc.so.6", *entry[2:]),)))
    elif fault == "key":
        struct.pack_into("<I", raw, 52, 0)
    elif fault == "strings":
        struct.pack_into("<I", raw, 24, 2**32 - 1)
    elif fault == "reserved":
        raw[40] = 1
    elif fault == "format":
        raw[0] = 0
    elif fault == "count":
        struct.pack_into("<I", raw, 20, 2**32 - 1)
    with pytest.raises(InstalledRuntimeProofError):
        host._cache(bytes(raw))


def _synthetic_child(monkeypatch: pytest.MonkeyPatch, script: str) -> list[subprocess.Popen[bytes]]:
    actual = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def spawn(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        assert command[0] in {"/usr/bin/zstd", "/usr/bin/readelf"}
        executable = kwargs.pop("executable")
        fd = int(executable.removeprefix("/proc/self/fd/"))
        assert fd in kwargs["pass_fds"] and stat.S_ISREG(os.fstat(fd).st_mode)
        assert kwargs["env"] == host._ENV and kwargs["cwd"] == "/" and kwargs["close_fds"]
        assert kwargs["stderr"] == subprocess.DEVNULL
        if command[0] == "/usr/bin/readelf":
            assert command[1:-1] == [
                "--wide",
                "--file-header",
                "--program-headers",
                "--dynamic",
                "--version-info",
            ]
            assert int(command[-1].removeprefix("/proc/self/fd/")) in kwargs["pass_fds"]
        else:
            assert command == ["/usr/bin/zstd", "-q", "-d", "-c"]
        process = actual([sys.executable, "-I", "-S", "-B", "-c", script], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    return children


def test_fixed_readelf_fd_bound_argv_has_bounded_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    children = _synthetic_child(monkeypatch, "print('synthetic fixed readelf')")
    with fixture.capture() as capture:
        assert (
            capture.inspect_elf(
                capture._descriptors[fixture.library], deadline=time.monotonic() + 1.0
            )
            == b"synthetic fixed readelf\n"
        )
    assert len(children) == 1 and children[0].poll() == 0
    assert children[0].stdout is not None and children[0].stdout.closed


@pytest.mark.parametrize("fault", ["file", "directory", "symlink"])
@pytest.mark.parametrize("route", ["/lib/intel64", "/usr/local/cuda/lib64"])
def test_vendor_search_route_must_actually_be_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, route: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    target = host._ABSENT_SEARCH_ROUTES[route]
    if fault == "file":
        _put(target, b"unapproved search route")
    elif fault == "directory":
        target.mkdir(mode=0o700)
    else:
        target.symlink_to(tmp_path / "missing")
    with pytest.raises(InstalledRuntimeProofError):
        fixture.capture()


def test_vendor_search_absence_is_current_and_unknown_routes_remain_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(InstalledRuntimeProofError), fixture.capture() as capture:
        for route in host._ABSENT_SEARCH_ROUTES:
            capture.assert_absent_search_route(route)
        with pytest.raises(InstalledRuntimeProofError, match="ROUTE_INVALID"):
            capture.assert_absent_search_route("/tmp/unchecked")
        host._ABSENT_SEARCH_ROUTES["/lib/intel64"].mkdir(mode=0o700)
        capture.assert_absent_search_route("/lib/intel64")


def test_host_check_cost_does_not_grow_with_later_prefix_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with fixture.capture() as capture:
        members = []
        for index in range(64):
            member = tmp_path / f"prefix-member-{index}"
            _put(member, b"synthetic unrelated prefix member")
            fixture.files.observe_protected_member_identity(member)
            members.append(member)
        tracked = set(members)
        original = Path.lstat
        unrelated_checks = 0

        def counted(path: Path) -> os.stat_result:
            nonlocal unrelated_checks
            if path in tracked:
                unrelated_checks += 1
            return original(path)

        monkeypatch.setattr(Path, "lstat", counted)
        for _ in range(4):
            capture.assert_current()
        assert unrelated_checks == 0
        fixture.files.assert_unchanged()
        assert unrelated_checks == 64
        # Prefix work still owns its complete final checks; host operations do not replace them.
        members[-1].chmod(0o660)
        capture.assert_current()
        with pytest.raises(InstalledRuntimeProofError):
            fixture.files.assert_unchanged()


def test_fixed_readelf_accepts_two_mib_at_shared_parser_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    children = _synthetic_child(
        monkeypatch, "import sys; sys.stdout.buffer.write(b'x' * (2 * 1024**2))"
    )
    with fixture.capture() as capture:
        raw = capture.inspect_elf(
            capture._descriptors[fixture.library], deadline=time.monotonic() + 2.0
        )
        assert len(raw) == host.MAX_READELF_OUTPUT_BYTES == 2 * 1024**2
    assert children[0].poll() == 0
    assert children[0].stdout is not None and children[0].stdout.closed


@pytest.mark.parametrize("deadline", [True, 1, float("nan"), float("inf"), -1.0])
def test_readelf_exact_deadline_validation_precedes_fd_access_or_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deadline: Any
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with fixture.capture() as capture:
        monkeypatch.setattr(subprocess, "Popen", _deny)
        with pytest.raises(InstalledRuntimeProofError, match="INSPECTION_INVALID"):
            capture.inspect_elf(1000000, deadline=deadline)


def test_readelf_closed_member_fd_returns_content_free_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with fixture.capture() as capture:
        monkeypatch.setattr(subprocess, "Popen", _deny)
        with pytest.raises(InstalledRuntimeProofError, match="INSPECTION_UNAVAILABLE"):
            capture.inspect_elf(1000000, deadline=time.monotonic() + 1.0)


@pytest.mark.parametrize("phase", ["select", "read", "wait", "return"])
def test_absolute_deadline_cannot_be_reset_or_passed_after_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    process_type = subprocess.Popen
    children = _synthetic_child(monkeypatch, "print('x')")
    capture = fixture.capture()
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    if phase == "select":
        original_select = selectors.EpollSelector.select

        def late_select(
            selector: selectors.EpollSelector, timeout: float | None = None
        ) -> list[tuple[selectors.SelectorKey, int]]:
            result = original_select(selector, timeout)
            clock[0] = 2.0
            return result

        monkeypatch.setattr(selectors.EpollSelector, "select", late_select)
    elif phase == "read":
        original_read = os.read

        def late_read(fd: int, size: int) -> bytes:
            result = original_read(fd, size)
            clock[0] = 2.0
            return result

        monkeypatch.setattr(os, "read", late_read)
    elif phase == "wait":
        original_wait = cast(
            "Callable[[subprocess.Popen[bytes], float | None], int]", process_type.wait
        )

        def late_wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
            result = original_wait(process, timeout)
            clock[0] = 2.0
            return result

        monkeypatch.setattr(process_type, "wait", late_wait)
    else:
        original_assert = capture.assert_current
        checks = [0]

        def late_assert() -> None:
            original_assert()
            checks[0] += 1
            if checks[0] == 3:
                clock[0] = 2.0

        monkeypatch.setattr(capture, "assert_current", late_assert)
    try:
        with pytest.raises(InstalledRuntimeProofError, match="TOOL_TIMEOUT"):
            capture.inspect_elf(capture._descriptors[fixture.library], deadline=1.0)
    finally:
        capture.close()
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize(
    "fault", ["timeout", "overflow", "failure", "selector", "blocking", "register"]
)
def test_readelf_io_failures_always_reap_and_close_owned_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    scripts = {
        "timeout": "import time; time.sleep(30)",
        "overflow": "import sys; sys.stdout.buffer.write(b'x'*(2*1024**2+1)); sys.stdout.flush()",
        "failure": "raise SystemExit(7)",
    }
    children = _synthetic_child(monkeypatch, scripts.get(fault, "import time; time.sleep(30)"))
    capture = fixture.capture()
    if fault == "selector":
        monkeypatch.setattr(selectors, "DefaultSelector", _deny)
    elif fault == "blocking":
        monkeypatch.setattr(os, "set_blocking", _deny)
    elif fault == "register":

        class FailingSelector(selectors.EpollSelector):
            def register(
                self, fileobj: Any, events: int, data: Any = None
            ) -> selectors.SelectorKey:
                raise OSError("synthetic")

        monkeypatch.setattr(selectors, "DefaultSelector", FailingSelector)
    try:
        with pytest.raises((InstalledRuntimeProofError, AssertionError)):
            capture.inspect_elf(
                capture._descriptors[fixture.library],
                deadline=time.monotonic() + (0.05 if fault == "timeout" else 2.0),
            )
    finally:
        capture.close()
    assert not children if fault == "selector" else len(children) == 1
    for child in children:
        assert child.poll() is not None and child.stdout is not None and child.stdout.closed


def test_post_spawn_epoch_failure_reaps_before_returning_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    actual = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def spawn(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        kwargs.pop("executable")
        child = actual(
            [sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        fixture.loader.write_bytes(b"drift after spawn")
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    capture = fixture.capture()
    with pytest.raises(InstalledRuntimeProofError):
        capture.open_zstd()
    assert children[0].poll() is not None
    assert children[0].stdin is not None and children[0].stdin.closed
    assert children[0].stdout is not None and children[0].stdout.closed
    with pytest.raises(InstalledRuntimeProofError):
        capture.close()


def test_linux_actual_executable_fd_is_used_not_the_named_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Inert actual process only, a synthetic current handle (not host acceptance).
    executable = tmp_path / "held-true"
    _put(executable, Path("/usr/bin/true").read_bytes(), mode=0o700)
    descriptor = os.open(executable, os.O_RDONLY | os.O_CLOEXEC)
    stack = ExitStack()
    stack.callback(os.close, descriptor)
    monkeypatch.setattr(host, "_ZSTD", executable)
    capture = host.ProtectedEmbeddingHostClosure(
        NumericalRuntimeFileSnapshots(os.geteuid()),
        host._HostRoutes(os.geteuid()),
        stack,
        {executable: descriptor},
        {executable: host._identity(os.fstat(descriptor))},
        _hash(b"synthetic"),
    )
    try:
        process = capture.open_zstd()
        assert process.stdin is not None and process.stdout is not None
        process.stdin.close()
        assert process.stdout.read(1) == b"" and process.wait(timeout=1) == 0
        process.stdout.close()
    finally:
        capture.close()


def test_actual_current_host_import_closure_is_stdlib_under_no_site() -> None:
    source = Path(host.__file__).parent.parent
    code = """
import sys
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_runtime_host_closure as host
import eom_catalog_service.embedding_conda_runtime_closure as conda
import eom_catalog_service.embedding_runtime_files as files
for forbidden in ('pydantic','jsonschema','eom_catalog_contracts','eom_identifiers',
                  'torch','transformers','numpy','safetensors','tokenizers'):
 assert not any(n==forbidden or n.startswith(forbidden+'.') for n in sys.modules)
assert len(host._FILES)==23 and hasattr(conda.CondaArchiveToolAdmission,'open_zstd')
assert hasattr(files.NumericalRuntimeFileSnapshots,'observe_protected_member_bytes')
print('STDLIB_HOST_IMPORT_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(source)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_HOST_IMPORT_PASS"

"""Synthetic local ZIPs only; no network, installed packages, large wheels or CUDA."""

from __future__ import annotations

import ast
import hashlib
import os
import stat
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.embedding import verify_cuda_wheelhouse as verifier


@dataclass
class Prepared:
    lock: Path
    wheelhouse: Path
    wheel: Path
    lock_sha256: str = ""
    total_bytes: int = 0

    def seal(self, *, wheel_sha256: str | None = None) -> None:
        digest = wheel_sha256 or hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.lock.write_text(
            "package-a @ https://files.pythonhosted.org/packages/synthetic/"
            + self.wheel.name
            + " --hash=sha256:"
            + digest
            + "\n",
            encoding="utf-8",
        )
        self.lock_sha256 = hashlib.sha256(self.lock.read_bytes()).hexdigest()
        self.total_bytes = self.wheel.stat().st_size

    def verify(self) -> dict[str, object]:
        return verifier.verify_wheelhouse(
            lock_path=self.lock,
            wheelhouse=self.wheelhouse,
            expected_lock_sha256=self.lock_sha256,
            expected_count=1,
            expected_total_bytes=self.total_bytes,
        )


def prepared(
    tmp_path: Path,
    *,
    metadata: bytes | None = None,
    tag: str = "py3-none-any",
    extras: tuple[tuple[str | zipfile.ZipInfo, bytes], ...] = (),
) -> Prepared:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir(mode=0o700)
    wheel = wheelhouse / "package_a-1.0.0-py3-none-any.whl"
    root = "package_a-1.0.0.dist-info"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package_a/__init__.py", b"raise AssertionError('must never execute')\n")
        archive.writestr(
            root + "/METADATA",
            metadata
            or (
                b"Metadata-Version: 2.4\nName: package-a\nVersion: 1.0.0\n"
                b"Requires-Python: >=3.9\n\n"
            ),
        )
        archive.writestr(
            root + "/WHEEL",
            ("Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: " + tag + "\n").encode(),
        )
        archive.writestr(root + "/RECORD", b"synthetic-unchecked-record\n")
        for member, payload in extras:
            archive.writestr(member, payload)
    wheel.chmod(0o664)
    value = Prepared(tmp_path / "download.lock", wheelhouse, wheel)
    value.seal()
    return value


def rejects(value: Prepared, code: str) -> None:
    with pytest.raises(verifier.WheelhouseVerificationError, match="^" + code + "$"):
        value.verify()


def test_synthetic_report_is_metadata_only_and_never_imports_package(tmp_path: Path) -> None:
    value = prepared(
        tmp_path, extras=(("package_a/vendor/other-2.0.dist-info/METADATA", b"vendored"),)
    )
    report = value.verify()
    assert report["wheel_count"] == 1 and report["total_bytes"] == value.total_bytes
    assert report["lock_sha256"] == value.lock_sha256 and report["prefetch_lock_sha256"] is None
    assert report["wheelhouse_mode"] == "0700"
    assert report["immutable_root_quarantine_required"] is True
    assert report["installed_record_verified"] is report["cuda_verified"] is False
    assert "package_a" not in sys.modules
    assert "must never execute" not in str(report)
    wheels = report["wheels"]
    assert isinstance(wheels, list) and len(wheels) == 1
    assert wheels[0]["file_mode"] == "0664"
    assert wheels[0]["version"] == "1.0.0"


@pytest.mark.parametrize(
    "name", ("../escape", "/absolute", "a//b", "a/./b", "a/../b", "a\\b", "C:drive", "a\nb")
)
def test_zip_path_rejections(tmp_path: Path, name: str) -> None:
    rejects(prepared(tmp_path, extras=((name, b"unsafe"),)), "ZIP_PATH_INVALID")


def test_zip_null_filename_is_rejected_before_truncation(tmp_path: Path) -> None:
    value = prepared(tmp_path, extras=(("safe.txt", b"unsafe"),))
    value.wheel.write_bytes(value.wheel.read_bytes().replace(b"safe.txt", b"bad\x00.txt"))
    value.seal()
    rejects(value, "ZIP_PATH_INVALID")


def test_zip_duplicate_member_is_rejected(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        value = prepared(tmp_path, extras=(("package_a/__init__.py", b"duplicate"),))
    rejects(value, "ZIP_DUPLICATE_MEMBER")


@pytest.mark.parametrize(
    "mode",
    (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4600, stat.S_IFREG | 0o2600),
)
def test_zip_special_and_privileged_modes_are_rejected(tmp_path: Path, mode: int) -> None:
    member = zipfile.ZipInfo("special")
    member.create_system = 3
    member.external_attr = mode << 16
    rejects(prepared(tmp_path, extras=((member, b"target"),)), "ZIP_MEMBER_TYPE_INVALID")


def test_zip_unsupported_compression_is_rejected(tmp_path: Path) -> None:
    member = zipfile.ZipInfo("compressed")
    member.compress_type = zipfile.ZIP_BZIP2
    rejects(prepared(tmp_path, extras=((member, b"payload"),)), "ZIP_COMPRESSION_INVALID")


def test_zip_encryption_flag_is_rejected(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    payload = bytearray(value.wheel.read_bytes())
    payload[6] |= 1
    central = payload.index(b"PK\x01\x02")
    payload[central + 8] |= 1
    value.wheel.write_bytes(payload)
    value.seal()
    rejects(value, "ZIP_MEMBER_TYPE_INVALID")


def test_zip_overlap_is_rejected(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    payload = bytearray(value.wheel.read_bytes())
    central = payload.index(b"PK\x01\x02")
    size = int.from_bytes(payload[central + 20 : central + 24], "little")
    payload[central + 20 : central + 24] = (size + 1).to_bytes(4, "little")
    value.wheel.write_bytes(payload)
    value.seal()
    rejects(value, "ZIP_MEMBER_OVERLAP")


def test_zip_expansion_ratio_is_bounded(tmp_path: Path) -> None:
    rejects(prepared(tmp_path, extras=(("bomb", bytes(65536)),)), "ZIP_EXPANSION_LIMIT")


@pytest.mark.parametrize(
    ("constant", "code"),
    (
        ("MAX_ZIP_ENTRIES", "ZIP_ENTRY_LIMIT"),
        ("MAX_MEMBER_BYTES", "ZIP_EXPANSION_LIMIT"),
        ("MAX_EXPANDED_WHEEL_BYTES", "ZIP_EXPANSION_LIMIT"),
        ("MAX_EXPANDED_TOTAL_BYTES", "ZIP_AGGREGATE_EXPANSION_LIMIT"),
        ("MAX_METADATA_BYTES", "ZIP_METADATA_LIMIT"),
    ),
)
def test_declared_packaging_bounds_fail_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    code: str,
) -> None:
    value = prepared(tmp_path)
    monkeypatch.setattr(verifier, constant, 1)
    rejects(value, code)


@pytest.mark.parametrize(
    ("metadata", "code"),
    (
        (b"Name: other\nVersion: 1.0.0\n", "METADATA_IDENTITY_MISMATCH"),
        (b"Name: package-a\nVersion: 2.0.0\n", "METADATA_IDENTITY_MISMATCH"),
        (b"Name: package-a\nName: package-a\nVersion: 1.0.0\n", "METADATA_IDENTITY_INVALID"),
        (
            b"Name: package-a\nVersion: 1.0.0\nRequires-Python: >=3.13\n",
            "PYTHON_REQUIREMENT_MISMATCH",
        ),
        (b"Name: package-a\nVersion: 1.0.0\nRequires-Dist: missing>=1\n", "DEPENDENCY_MISSING"),
        (
            b"Name: package-a\nVersion: 1.0.0\nRequires-Dist: package-a>=2\n",
            "DEPENDENCY_VERSION_MISMATCH",
        ),
        (
            b"Name: package-a\nVersion: 1.0.0\nRequires-Dist: missing; __import__('os')\n",
            "MARKER_UNSUPPORTED",
        ),
    ),
)
def test_metadata_identity_platform_and_closure_rejections(
    tmp_path: Path, metadata: bytes, code: str
) -> None:
    rejects(prepared(tmp_path, metadata=metadata), code)


def test_inactive_extras_are_not_solved_or_executed(tmp_path: Path) -> None:
    value = prepared(
        tmp_path,
        metadata=(
            b"Name: package-a\nVersion: 1.0.0\n"
            b"Requires-Dist: missing; extra == 'gpu'\n"
            b"Requires-Dist: missing; python_version < '3.9'\n"
            b"Requires-Dist: package-a>=1; platform_system == 'Linux' "
            b"and python_version >= '3.12'\n"
        ),
    )
    assert value.verify()["wheel_count"] == 1


def test_another_top_level_distribution_and_foreign_wheel_tag_fail(tmp_path: Path) -> None:
    rejects(prepared(tmp_path, tag="cp311-cp311-manylinux_2_28_x86_64"), "WHEEL_TAG_MISMATCH")


def test_another_top_level_metadata_root_fails(tmp_path: Path) -> None:
    rejects(
        prepared(tmp_path, extras=(("other-1.0.dist-info/METADATA", b"other"),)),
        "ZIP_METADATA_ROOT_INVALID",
    )


@pytest.mark.parametrize("mode", (0o666, 0o4644, 0o2644))
def test_world_writable_or_privileged_wheel_files_fail(tmp_path: Path, mode: int) -> None:
    value = prepared(tmp_path)
    value.wheel.chmod(mode)
    rejects(value, "WHEEL_FILE_INVALID")


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo"))
def test_non_regular_or_linked_files_fail(tmp_path: Path, kind: str) -> None:
    value = prepared(tmp_path)
    if kind == "hardlink":
        os.link(value.wheel, tmp_path / "linked")
        rejects(value, "WHEEL_FILE_INVALID")
    else:
        value.wheel.unlink()
        if kind == "symlink":
            value.wheel.symlink_to(tmp_path / "absent")
        else:
            os.mkfifo(value.wheel)
        rejects(
            value,
            "WHEELHOUSE_UNTRUSTED_INPUT_INVALID" if kind == "symlink" else "WHEEL_FILE_INVALID",
        )


def test_private_directory_and_exact_inventory_are_required(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    value.wheelhouse.chmod(0o755)
    rejects(value, "DIRECTORY_NOT_PRIVATE")


def test_symlink_ancestor_is_not_followed(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    alias = tmp_path / "ancestor-alias"
    alias.symlink_to(value.wheelhouse, target_is_directory=True)
    value.wheelhouse = alias
    rejects(value, "WHEELHOUSE_UNTRUSTED_INPUT_INVALID")


def test_lock_symlink_is_not_followed(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    alias = tmp_path / "lock-alias"
    alias.symlink_to(value.lock)
    value.lock = alias
    rejects(value, "WHEELHOUSE_UNTRUSTED_INPUT_INVALID")


def test_directory_fd_is_closed_when_initial_stat_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    original_open, original_stat = os.open, os.fstat
    directories: list[int] = []

    def opened(path: Any, flags: int, **kwargs: Any) -> int:
        fd = original_open(path, flags, **kwargs)
        if flags & os.O_DIRECTORY:
            directories.append(fd)
        return fd

    def failed(fd: int) -> os.stat_result:
        if fd in directories:
            raise OSError("synthetic stat failure")
        return original_stat(fd)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "fstat", failed)
    rejects(value, "WHEELHOUSE_UNTRUSTED_INPUT_INVALID")
    assert directories
    for fd in directories:
        with pytest.raises(OSError):
            original_stat(fd)


def test_directory_cleanup_attempts_all_closes_and_redacts_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    original_open, original_close, original_stat = os.open, os.close, os.fstat
    directories: list[int] = []
    closed: list[int] = []

    def opened(path: Any, flags: int, **kwargs: Any) -> int:
        fd = original_open(path, flags, **kwargs)
        if flags & os.O_DIRECTORY:
            directories.append(fd)
        return fd

    def failed_once(fd: int) -> None:
        original_close(fd)
        if fd in directories:
            closed.append(fd)
            if len(closed) == 1:
                raise OSError("synthetic private cleanup failure")

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "close", failed_once)
    rejects(value, "WHEELHOUSE_UNTRUSTED_INPUT_INVALID")
    assert closed == list(reversed(directories))
    for fd in directories:
        with pytest.raises(OSError):
            original_stat(fd)


def test_growing_file_hash_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = prepared(tmp_path)
    inode = value.wheel.stat().st_ino
    original = os.read
    changed = False

    def growing(fd: int, maximum: int) -> bytes:
        nonlocal changed
        chunk = original(fd, maximum)
        if os.fstat(fd).st_ino == inode and not changed:
            changed = True
            value.wheel.write_bytes(value.wheel.read_bytes() + b"grew")
        return chunk

    monkeypatch.setattr(os, "read", growing)
    rejects(value, "WHEEL_EPOCH_CHANGED")


@pytest.mark.parametrize("change", ("extra", "missing", "bad-total", "bad-lock", "bad-wheel"))
def test_exact_inventory_hashes_and_byte_count_fail(tmp_path: Path, change: str) -> None:
    value = prepared(tmp_path)
    code = "WHEELHOUSE_INVENTORY_MISMATCH"
    if change == "extra":
        (value.wheelhouse / "unexpected").write_bytes(b"extra")
    elif change == "missing":
        value.wheel.unlink()
    elif change == "bad-total":
        value.total_bytes += 1
        code = "WHEELHOUSE_BYTE_COUNT_MISMATCH"
    elif change == "bad-lock":
        value.lock_sha256 = "0" * 64
        code = "LOCK_HASH_MISMATCH"
    else:
        value.seal(wheel_sha256="0" * 64)
        code = "WHEEL_HASH_MISMATCH"
    rejects(value, code)


@pytest.mark.parametrize("change", ("wheel-content", "wheel-replacement", "lock-content"))
def test_named_and_fd_epochs_hold_until_whole_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    value = prepared(tmp_path)
    original = verifier._archive

    def mutate(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if change == "lock-content":
            value.lock.write_bytes(value.lock.read_bytes() + b"# changed\n")
        elif change == "wheel-content":
            value.wheel.write_bytes(value.wheel.read_bytes() + b"changed")
        else:
            payload = value.wheel.read_bytes()
            value.wheel.unlink()
            value.wheel.write_bytes(payload)
        return result

    monkeypatch.setattr(verifier, "_archive", mutate)
    rejects(value, "LOCK_EPOCH_CHANGED" if change == "lock-content" else "WHEEL_EPOCH_CHANGED")


def test_source_imports_only_stdlib_and_has_no_network_or_extraction_boundary() -> None:
    source = Path(verifier.__file__).read_text(encoding="utf-8")
    imports = {
        node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    }
    roots = {module.split(".", 1)[0] for module in imports if module is not None}
    roots.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert roots.issubset(sys.stdlib_module_names | {"__future__"})
    assert "urllib.request" not in imports
    assert "extractall" not in source and "extract(" not in source
    assert "import torch" not in source and "pip" not in imports


def _central_member(*, name: bytes = b"x", extra: bytes = b"", comment: bytes = b"") -> bytes:
    header = bytearray(46)
    header[:4] = b"PK\x01\x02"
    struct.pack_into("<H", header, 6, 20)
    struct.pack_into("<3H", header, 28, len(name), len(extra), len(comment))
    return bytes(header) + name + extra + comment


@pytest.mark.parametrize(
    "fault,code",
    [
        ("declared_count", "ZIP_ENTRY_LIMIT"),
        ("actual_count", "ZIP_ENTRY_LIMIT"),
        ("forged_count", "ZIP_DIRECTORY_COUNT_MISMATCH"),
        ("central_bytes", "ZIP_CENTRAL_LIMIT"),
        ("zip64_count", "ZIP64_UNSUPPORTED"),
        ("zip64_size", "ZIP64_UNSUPPORTED"),
        ("zip64_extra", "ZIP64_UNSUPPORTED"),
        ("zip64_version", "ZIP64_UNSUPPORTED"),
        ("zip64_locator", "ZIP64_UNSUPPORTED"),
        ("disk", "ZIP_MULTIDISK_UNSUPPORTED"),
        ("member_disk", "ZIP_MULTIDISK_UNSUPPORTED"),
        ("comment", "ZIP_COMMENT_UNSUPPORTED"),
        ("member_comment", "ZIP_COMMENT_UNSUPPORTED"),
        ("name_bound", "ZIP_DIRECTORY_INVALID"),
        ("extra_bound", "ZIP_DIRECTORY_INVALID"),
        ("trailing_central", "ZIP_DIRECTORY_INVALID"),
        ("truncated_extra", "ZIP_DIRECTORY_INVALID"),
        ("trailing_archive", "ZIP_DIRECTORY_INVALID"),
    ],
)
def test_central_limits_precede_zipfile_allocation_and_close_all_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, code: str
) -> None:
    value = prepared(tmp_path)
    central, count, size, disk, comment = _central_member(), 1, 47, 0, b""
    if fault == "declared_count":
        count = verifier.MAX_ZIP_ENTRIES + 1
    elif fault == "actual_count":
        central *= verifier.MAX_ZIP_ENTRIES + 1
    elif fault == "forged_count":
        count = 2
    elif fault == "central_bytes":
        size = verifier.MAX_CENTRAL_BYTES + 1
    elif fault == "zip64_count":
        count = 0xFFFF
    elif fault == "zip64_size":
        size = 0xFFFFFFFF
    elif fault == "zip64_extra":
        central = _central_member(extra=struct.pack("<2H", 1, 0))
    elif fault == "zip64_version":
        central = central[:6] + struct.pack("<H", 45) + central[8:]
    elif fault == "zip64_locator":
        central += b"PK\x06\x07" + b"\x00" * 16
    elif fault == "disk":
        disk = 1
    elif fault == "member_disk":
        central = central[:34] + struct.pack("<H", 1) + central[36:]
    elif fault == "comment":
        comment = b"unsupported"
    elif fault == "member_comment":
        central = _central_member(comment=b"unsupported")
    elif fault == "name_bound":
        central = _central_member(name=b"x" * 513)
    elif fault == "extra_bound":
        central = _central_member(extra=bytes(4097))
    elif fault == "trailing_central":
        central += b"trailing"
    elif fault == "truncated_extra":
        central = _central_member(extra=struct.pack("<2H", 2, 5))
    if fault not in {"central_bytes", "zip64_size"}:
        size = len(central)
    payload = (
        central
        + struct.pack("<4s4H2IH", b"PK\x05\x06", disk, 0, count, count, size, 0, len(comment))
        + comment
    )
    if fault == "trailing_archive":
        payload += b"trailing"
    value.wheel.write_bytes(payload)
    value.seal()
    original_open, original_dup, original_pread = os.open, os.dup, os.pread
    descriptors: set[int] = set()
    pread_descriptors: set[int] = set()
    reads: list[int] = []

    def observed_open(path: Any, flags: int, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, **kwargs)
        descriptors.add(descriptor)
        return descriptor

    def observed_dup(descriptor: int) -> int:
        duplicate = original_dup(descriptor)
        descriptors.add(duplicate)
        return duplicate

    def observed_pread(descriptor: int, size: int, offset: int) -> bytes:
        pread_descriptors.add(descriptor)
        reads.append(size)
        return original_pread(descriptor, size, offset)

    def deny_zipfile(*args: object, **kwargs: object) -> None:
        pytest.fail("ZipFile allocated before bounded central bytes and actual count admission")

    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(os, "dup", observed_dup)
    monkeypatch.setattr(os, "pread", observed_pread)
    monkeypatch.setattr(zipfile, "ZipFile", deny_zipfile)
    rejects(value, code)
    assert len(pread_descriptors) == 1
    assert max(reads) <= verifier.MAX_CENTRAL_BYTES
    if fault == "central_bytes":
        assert max(reads) <= 65557
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)

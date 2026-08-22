#!/srv/eom/conda/envs/eom-hwpx/bin/python
"""Verify or normalize the dedicated HWPX Python runtime package layout."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import stat
import sys
import sysconfig
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

EXPECTED_PREFIX = Path("/srv/eom/conda/envs/eom-hwpx")
DIRECTORY_MODE = 0o755
REGULAR_FILE_MODE = 0o644
CONSOLE_SCRIPT_MODE = 0o755
SHARED_LIBRARY_MODE = 0o755
NODE_RUNTIME_LIBRARY_NAMES: Final = (
    "libnode.so.115",
    "libz.so.1",
    "libuv.so.1",
    "libcrypto.so.3",
    "libssl.so.3",
    "libicui18n.so.73",
    "libicuuc.so.73",
    "libstdc++.so.6",
    "libgcc_s.so.1",
    "libicudata.so.73",
)


class PythonRuntimeLayoutError(RuntimeError):
    """A stable fail-closed package-layout error."""


@dataclass(frozen=True)
class LayoutEntry:
    path: Path
    device: int
    inode: int
    links: int
    size: int
    modified_ns: int
    kind: str
    expected_mode: int


@dataclass(frozen=True)
class LayoutResult:
    entries: int
    changes: int


def _fail(code: str) -> PythonRuntimeLayoutError:
    return PythonRuntimeLayoutError(code)


def _contained_symlink(path: Path, root: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise _fail("HWPX_RUNTIME_LAYOUT_SYMLINK_ESCAPE") from exc


def inventory_layout(
    root: Path, *, expected_uid: int, expected_gid: int
) -> tuple[LayoutEntry, ...]:
    """Return a stable snapshot without following symlinks."""

    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise _fail("HWPX_RUNTIME_LAYOUT_ROOT_UNAVAILABLE") from exc
    if root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise _fail("HWPX_RUNTIME_LAYOUT_ROOT_UNSAFE")

    entries: list[LayoutEntry] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise _fail("HWPX_RUNTIME_LAYOUT_ENTRY_UNAVAILABLE") from exc
        if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
            raise _fail("HWPX_RUNTIME_LAYOUT_OWNERSHIP_MISMATCH")
        if stat.S_ISDIR(metadata.st_mode):
            entries.append(
                LayoutEntry(
                    current,
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_nlink,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    "directory",
                    DIRECTORY_MODE,
                )
            )
            try:
                children = sorted(current.iterdir(), key=lambda value: value.name, reverse=True)
            except OSError as exc:
                raise _fail("HWPX_RUNTIME_LAYOUT_DIRECTORY_UNREADABLE") from exc
            pending.extend(children)
        elif stat.S_ISREG(metadata.st_mode):
            entries.append(
                LayoutEntry(
                    current,
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_nlink,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    "file",
                    REGULAR_FILE_MODE,
                )
            )
        elif stat.S_ISLNK(metadata.st_mode):
            _contained_symlink(current, root)
        else:
            raise _fail("HWPX_RUNTIME_LAYOUT_SPECIAL_FILE")
    return tuple(entries)


def identity_has_required_access(
    entry: LayoutEntry, metadata: os.stat_result, uid: int, gids: set[int]
) -> bool:
    """Evaluate the read/traverse bits for a distinct service identity."""

    mode = stat.S_IMODE(metadata.st_mode)
    if uid == metadata.st_uid:
        relevant = (mode >> 6) & 0o7
    elif metadata.st_gid in gids:
        relevant = (mode >> 3) & 0o7
    else:
        relevant = mode & 0o7
    required = 0o5 if entry.kind in {"directory", "executable"} else 0o4
    return relevant & required == required


def _verify_console_scripts(paths: Iterable[Path], *, expected_uid: int, expected_gid: int) -> None:
    for path in paths:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise _fail("HWPX_RUNTIME_CONSOLE_SCRIPT_UNAVAILABLE") from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or stat.S_IMODE(metadata.st_mode) != CONSOLE_SCRIPT_MODE
        ):
            raise _fail("HWPX_RUNTIME_CONSOLE_SCRIPT_MISMATCH")


def _runtime_file_entry(
    path: Path,
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
    kind: str,
    expected_mode: int,
) -> LayoutEntry:
    try:
        boundary = boundary.resolve(strict=True)
        metadata = path.lstat()
        if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
            raise _fail("HWPX_RUNTIME_FILE_MISMATCH")
        if stat.S_ISLNK(metadata.st_mode):
            _contained_symlink(path, boundary)
            target = path.resolve(strict=True)
        elif stat.S_ISREG(metadata.st_mode):
            target = path
        else:
            raise _fail("HWPX_RUNTIME_FILE_UNSAFE")
        target.resolve(strict=True).relative_to(boundary)
        target_metadata = target.lstat()
    except PythonRuntimeLayoutError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise _fail("HWPX_RUNTIME_FILE_UNAVAILABLE") from exc
    if (
        not stat.S_ISREG(target_metadata.st_mode)
        or target.is_symlink()
        or target_metadata.st_uid != expected_uid
        or target_metadata.st_gid != expected_gid
    ):
        raise _fail("HWPX_RUNTIME_FILE_MISMATCH")
    return LayoutEntry(
        target,
        target_metadata.st_dev,
        target_metadata.st_ino,
        target_metadata.st_nlink,
        target_metadata.st_size,
        target_metadata.st_mtime_ns,
        kind,
        expected_mode,
    )


def verify_runtime_executables(
    paths: Iterable[Path],
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
    service_uid: int | None = None,
    service_gids: set[int] | None = None,
) -> LayoutResult:
    entries = tuple(
        _runtime_file_entry(
            path,
            boundary=boundary,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            kind="executable",
            expected_mode=CONSOLE_SCRIPT_MODE,
        )
        for path in paths
    )
    for entry in entries:
        metadata = entry.path.lstat()
        if (
            metadata.st_dev != entry.device
            or metadata.st_ino != entry.inode
            or stat.S_IMODE(metadata.st_mode) != entry.expected_mode
        ):
            raise _fail("HWPX_RUNTIME_EXECUTABLE_MODE_MISMATCH")
        if service_uid is not None and not identity_has_required_access(
            entry, metadata, service_uid, service_gids or set()
        ):
            raise _fail("HWPX_RUNTIME_EXECUTABLE_ACCESS_MISMATCH")
    return LayoutResult(entries=len(entries), changes=0)


def _runtime_library_entries(
    paths: Iterable[Path],
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
) -> tuple[LayoutEntry, ...]:
    return tuple(
        _runtime_file_entry(
            path,
            boundary=boundary,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            kind="library",
            expected_mode=SHARED_LIBRARY_MODE,
        )
        for path in paths
    )


def verify_runtime_libraries(
    paths: Iterable[Path],
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
    service_uid: int,
    service_gids: set[int],
) -> LayoutResult:
    entries = _runtime_library_entries(
        paths,
        boundary=boundary,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    for entry in entries:
        metadata = entry.path.lstat()
        if metadata.st_dev != entry.device or metadata.st_ino != entry.inode:
            raise _fail("HWPX_RUNTIME_LIBRARY_CHANGED")
        if stat.S_IMODE(metadata.st_mode) & 0o002:
            raise _fail("HWPX_RUNTIME_LIBRARY_MODE_UNSAFE")
        if not identity_has_required_access(entry, metadata, service_uid, service_gids):
            raise _fail("HWPX_RUNTIME_LIBRARY_ACCESS_MISMATCH")
    return LayoutResult(entries=len(entries), changes=0)


def verify_layout(
    root: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    console_scripts: Iterable[Path] = (),
    service_uid: int | None = None,
    service_gids: set[int] | None = None,
) -> LayoutResult:
    entries = inventory_layout(root, expected_uid=expected_uid, expected_gid=expected_gid)
    for entry in entries:
        metadata = entry.path.lstat()
        if (
            metadata.st_dev != entry.device
            or metadata.st_ino != entry.inode
            or stat.S_IMODE(metadata.st_mode) != entry.expected_mode
        ):
            raise _fail("HWPX_RUNTIME_LAYOUT_MODE_MISMATCH")
        if service_uid is not None and not identity_has_required_access(
            entry, metadata, service_uid, service_gids or set()
        ):
            raise _fail("HWPX_RUNTIME_LAYOUT_SERVICE_ACCESS_MISMATCH")
    _verify_console_scripts(
        console_scripts,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return LayoutResult(entries=len(entries), changes=0)


def _normalize_entry(entry: LayoutEntry) -> bool:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if entry.kind == "directory":
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(entry.path, flags)
    except OSError as exc:
        raise _fail("HWPX_RUNTIME_LAYOUT_ENTRY_OPEN_FAILED") from exc
    try:
        current = os.fstat(descriptor)
        if current.st_dev != entry.device or current.st_ino != entry.inode:
            raise _fail("HWPX_RUNTIME_LAYOUT_ENTRY_CHANGED")
        mode = stat.S_IMODE(current.st_mode)
        if mode == entry.expected_mode:
            return False
        os.fchmod(descriptor, entry.expected_mode)
        return True
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise _fail("HWPX_RUNTIME_FILE_COPY_FAILED")
        view = view[written:]


def _materialize_private_runtime_file(entry: LayoutEntry, *, boundary: Path) -> None:
    """Break an external hardlink without changing the reviewed runtime bytes."""

    try:
        parent = entry.path.parent.resolve(strict=True)
        parent.relative_to(boundary.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise _fail("HWPX_RUNTIME_FILE_BOUNDARY_MISMATCH") from exc
    temporary_name = f".{entry.path.name}.eom-runtime-layout-{os.getpid()}"
    directory_descriptor = os.open(parent, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    source_descriptor = -1
    target_descriptor = -1
    created = False
    try:
        source_descriptor = os.open(entry.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        source_metadata = os.fstat(source_descriptor)
        if (
            source_metadata.st_dev != entry.device
            or source_metadata.st_ino != entry.inode
            or source_metadata.st_nlink != entry.links
            or source_metadata.st_size != entry.size
            or source_metadata.st_mtime_ns != entry.modified_ns
        ):
            raise _fail("HWPX_RUNTIME_FILE_CHANGED")
        target_descriptor = os.open(
            temporary_name,
            os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_descriptor,
        )
        created = True
        source_digest = hashlib.sha256()
        while chunk := os.read(source_descriptor, 1024 * 1024):
            source_digest.update(chunk)
            _write_all(target_descriptor, chunk)
        os.fchmod(target_descriptor, entry.expected_mode)
        os.fsync(target_descriptor)
        os.lseek(target_descriptor, 0, os.SEEK_SET)
        target_digest = hashlib.sha256()
        while chunk := os.read(target_descriptor, 1024 * 1024):
            target_digest.update(chunk)
        if target_digest.digest() != source_digest.digest():
            raise _fail("HWPX_RUNTIME_FILE_COPY_MISMATCH")
        source_after = os.fstat(source_descriptor)
        if (
            source_after.st_dev != entry.device
            or source_after.st_ino != entry.inode
            or source_after.st_nlink != entry.links
            or source_after.st_size != entry.size
            or source_after.st_mtime_ns != entry.modified_ns
        ):
            raise _fail("HWPX_RUNTIME_FILE_CHANGED")
        os.replace(
            temporary_name,
            entry.path.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
        created = False
    except OSError as exc:
        raise _fail("HWPX_RUNTIME_FILE_COPY_FAILED") from exc
    finally:
        if target_descriptor >= 0:
            os.close(target_descriptor)
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if created:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
        os.close(directory_descriptor)


def normalize_runtime_executables(
    paths: Iterable[Path],
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
) -> LayoutResult:
    entries = tuple(
        _runtime_file_entry(
            path,
            boundary=boundary,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            kind="executable",
            expected_mode=CONSOLE_SCRIPT_MODE,
        )
        for path in paths
    )
    changes = 0
    for entry in entries:
        if stat.S_IMODE(entry.path.lstat().st_mode) == entry.expected_mode:
            continue
        if entry.links > 1:
            _materialize_private_runtime_file(entry, boundary=boundary)
        else:
            _normalize_entry(entry)
        changes += 1
    verify_runtime_executables(
        paths,
        boundary=boundary,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return LayoutResult(entries=len(entries), changes=changes)


def normalize_runtime_libraries(
    paths: Iterable[Path],
    *,
    boundary: Path,
    expected_uid: int,
    expected_gid: int,
    service_uid: int,
    service_gids: set[int],
) -> LayoutResult:
    entries = _runtime_library_entries(
        paths,
        boundary=boundary,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    changes = 0
    for entry in entries:
        metadata = entry.path.lstat()
        accessible = identity_has_required_access(entry, metadata, service_uid, service_gids)
        if accessible and not stat.S_IMODE(metadata.st_mode) & 0o002:
            continue
        if entry.links > 1:
            _materialize_private_runtime_file(entry, boundary=boundary)
        else:
            _normalize_entry(entry)
        changes += 1
    verify_runtime_libraries(
        paths,
        boundary=boundary,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        service_uid=service_uid,
        service_gids=service_gids,
    )
    return LayoutResult(entries=len(entries), changes=changes)


def normalize_layout(
    root: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    console_scripts: Iterable[Path] = (),
) -> LayoutResult:
    """Normalize only a fully validated inventory and return the change count."""

    entries = inventory_layout(root, expected_uid=expected_uid, expected_gid=expected_gid)
    _verify_console_scripts(
        console_scripts,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    changes = sum(_normalize_entry(entry) for entry in entries)
    verify_layout(
        root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        console_scripts=console_scripts,
    )
    return LayoutResult(entries=len(entries), changes=changes)


def runtime_paths() -> tuple[
    Path,
    tuple[Path, ...],
    tuple[Path, ...],
    tuple[Path, ...],
]:
    prefix = Path(sys.prefix).resolve()
    if prefix != EXPECTED_PREFIX:
        raise _fail("HWPX_RUNTIME_PREFIX_MISMATCH")
    purelib = Path(sysconfig.get_paths()["purelib"])
    try:
        purelib.resolve(strict=True).relative_to(prefix)
    except (OSError, ValueError) as exc:
        raise _fail("HWPX_RUNTIME_PURELIB_MISMATCH") from exc
    return (
        purelib,
        (prefix / "bin/eom-hwpx",),
        (prefix / "bin/node",),
        tuple(prefix / "lib" / name for name in NODE_RUNTIME_LIBRARY_NAMES),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-hwpx-python-layout")
    parser.add_argument(
        "action",
        choices=(
            "verify",
            "normalize",
            "verify-node",
            "normalize-node",
            "verify-node-libraries",
            "normalize-node-libraries",
        ),
    )
    arguments = parser.parse_args()
    root, console_scripts, runtime_executables, runtime_libraries = runtime_paths()
    expected_uid = os.getuid()
    expected_gid = os.getgid()
    distinct_service_uid = -1
    distinct_service_gids: set[int] = set()
    try:
        if arguments.action == "normalize-node-libraries":
            result = normalize_runtime_libraries(
                runtime_libraries,
                boundary=EXPECTED_PREFIX,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
                service_uid=distinct_service_uid,
                service_gids=distinct_service_gids,
            )
        elif arguments.action == "verify-node-libraries":
            result = verify_runtime_libraries(
                runtime_libraries,
                boundary=EXPECTED_PREFIX,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
                service_uid=distinct_service_uid,
                service_gids=distinct_service_gids,
            )
        elif arguments.action == "normalize-node":
            result = normalize_runtime_executables(
                runtime_executables,
                boundary=EXPECTED_PREFIX,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
        elif arguments.action == "verify-node":
            result = verify_runtime_executables(
                runtime_executables,
                boundary=EXPECTED_PREFIX,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
        else:
            result = (
                normalize_layout(
                    root,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                    console_scripts=console_scripts,
                )
                if arguments.action == "normalize"
                else verify_layout(
                    root,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                    console_scripts=console_scripts,
                )
            )
            executable_result = (
                normalize_runtime_executables(
                    runtime_executables,
                    boundary=EXPECTED_PREFIX,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
                if arguments.action == "normalize"
                else verify_runtime_executables(
                    runtime_executables,
                    boundary=EXPECTED_PREFIX,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
            )
            library_result = (
                normalize_runtime_libraries(
                    runtime_libraries,
                    boundary=EXPECTED_PREFIX,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                    service_uid=distinct_service_uid,
                    service_gids=distinct_service_gids,
                )
                if arguments.action == "normalize"
                else verify_runtime_libraries(
                    runtime_libraries,
                    boundary=EXPECTED_PREFIX,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                    service_uid=distinct_service_uid,
                    service_gids=distinct_service_gids,
                )
            )
            result = LayoutResult(
                entries=result.entries + executable_result.entries + library_result.entries,
                changes=result.changes + executable_result.changes + library_result.changes,
            )
    except PythonRuntimeLayoutError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print("HWPX_RUNTIME_LAYOUT=PASS")
    print(f"hwpx_runtime_layout_entries={result.entries}")
    print(f"hwpx_runtime_layout_changes={result.changes}")


if __name__ == "__main__":
    main()

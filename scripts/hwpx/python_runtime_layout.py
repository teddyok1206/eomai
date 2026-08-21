#!/srv/eom/conda/envs/eom-hwpx/bin/python
"""Verify or normalize the dedicated HWPX Python runtime package layout."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import sysconfig
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

EXPECTED_PREFIX = Path("/srv/eom/conda/envs/eom-hwpx")
DIRECTORY_MODE = 0o755
REGULAR_FILE_MODE = 0o644
CONSOLE_SCRIPT_MODE = 0o755


class PythonRuntimeLayoutError(RuntimeError):
    """A stable fail-closed package-layout error."""


@dataclass(frozen=True)
class LayoutEntry:
    path: Path
    device: int
    inode: int
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
                    "file",
                    REGULAR_FILE_MODE,
                )
            )
        elif stat.S_ISLNK(metadata.st_mode):
            _contained_symlink(current, root)
        else:
            raise _fail("HWPX_RUNTIME_LAYOUT_SPECIAL_FILE")
    return tuple(entries)


def identity_can_read(
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
    required = 0o5 if entry.kind == "directory" else 0o4
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
        if service_uid is not None and not identity_can_read(
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


def runtime_paths() -> tuple[Path, tuple[Path, ...]]:
    prefix = Path(sys.prefix).resolve()
    if prefix != EXPECTED_PREFIX:
        raise _fail("HWPX_RUNTIME_PREFIX_MISMATCH")
    purelib = Path(sysconfig.get_paths()["purelib"])
    try:
        purelib.resolve(strict=True).relative_to(prefix)
    except (OSError, ValueError) as exc:
        raise _fail("HWPX_RUNTIME_PURELIB_MISMATCH") from exc
    return purelib, (prefix / "bin/eom-hwpx",)


def main() -> None:
    parser = argparse.ArgumentParser(prog="eom-hwpx-python-layout")
    parser.add_argument("action", choices=("verify", "normalize"))
    arguments = parser.parse_args()
    root, console_scripts = runtime_paths()
    expected_uid = os.getuid()
    expected_gid = os.getgid()
    try:
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
    except PythonRuntimeLayoutError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print("HWPX_RUNTIME_LAYOUT=PASS")
    print(f"hwpx_runtime_layout_entries={result.entries}")
    print(f"hwpx_runtime_layout_changes={result.changes}")


if __name__ == "__main__":
    main()

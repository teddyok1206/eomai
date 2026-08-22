"""Race-resistant private builder-to-Manager filesystem handoff."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from pathlib import Path

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode

HANDOFF_DIRECTORY_MODE = 0o750
HANDOFF_FILE_MODE = 0o640
_PRIVATE_DIRECTORY_MODES = frozenset({0o700, 0o2700, HANDOFF_DIRECTORY_MODE})
_PRIVATE_FILE_MODES = frozenset({0o600, HANDOFF_FILE_MODE})


def finalize_success_handoff(
    workspace: Path,
    result_path: Path,
    *,
    output_file_names: Iterable[str],
) -> None:
    """Expose only named validated output files to the private Manager group."""

    output_directory = workspace / "output"
    _verify_workspace_boundary(workspace, result_path, output_directory)
    for name in output_file_names:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise _handoff_error("builder handoff file name is unsafe")
        _finalize_regular_file(output_directory / name)
    _finalize_regular_file(result_path)
    _finalize_directory(output_directory)


def finalize_failure_result(workspace: Path, result_path: Path) -> None:
    """Expose a schema-valid failed result without exposing private workspace material."""

    _verify_workspace_boundary(workspace, result_path, None)
    _finalize_regular_file(result_path)


def write_private_json(path: Path, value: object) -> None:
    """Write canonical JSON, then enforce the pre-handoff private file mode."""

    from eom_hwpx_builder.util import write_json

    write_json(path, value)
    _set_private_regular_file(path)


def prepare_private_handoff_file(path: Path) -> None:
    """Make one builder-created regular file private before validation and handoff."""

    _set_private_regular_file(path)


def _verify_workspace_boundary(
    workspace: Path, result_path: Path, output_directory: Path | None
) -> None:
    try:
        workspace_metadata = workspace.lstat()
    except OSError as exc:
        raise _handoff_error("builder workspace is missing") from exc
    if (
        not stat.S_ISDIR(workspace_metadata.st_mode)
        or workspace.is_symlink()
        or workspace_metadata.st_gid != os.getegid()
        or stat.S_IMODE(workspace_metadata.st_mode) & 0o007
    ):
        raise _handoff_error("builder workspace boundary is unsafe")
    if result_path.resolve(strict=False).parent != workspace or result_path.name != "result.json":
        raise _handoff_error("builder result escaped its fixed workspace path")
    if output_directory is not None and output_directory != workspace / "output":
        raise _handoff_error("builder output escaped its fixed workspace path")
    if output_directory is not None:
        try:
            output_metadata = output_directory.lstat()
        except OSError as exc:
            raise _handoff_error("builder handoff directory is unavailable") from exc
        if (
            not stat.S_ISDIR(output_metadata.st_mode)
            or output_directory.is_symlink()
            or output_metadata.st_uid != os.geteuid()
            or output_metadata.st_gid != os.getegid()
            or stat.S_IMODE(output_metadata.st_mode) not in _PRIVATE_DIRECTORY_MODES
        ):
            raise _handoff_error("builder handoff directory metadata is invalid")


def _set_private_regular_file(path: Path) -> None:
    descriptor = _open_regular_file(path)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid():
            raise _handoff_error("builder handoff file identity is invalid")
        os.fchmod(descriptor, 0o600)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise _handoff_error("builder handoff file private mode was not applied")
    finally:
        os.close(descriptor)


def _finalize_regular_file(path: Path) -> None:
    descriptor = _open_regular_file(path)
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) not in _PRIVATE_FILE_MODES
        ):
            raise _handoff_error("builder handoff file metadata is invalid")
        os.fchmod(descriptor, HANDOFF_FILE_MODE)
        final = os.fstat(descriptor)
        if (
            final.st_uid != os.geteuid()
            or final.st_gid != os.getegid()
            or stat.S_IMODE(final.st_mode) != HANDOFF_FILE_MODE
        ):
            raise _handoff_error("builder handoff file mode was not applied")
    finally:
        os.close(descriptor)


def _finalize_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _handoff_error("builder handoff directory is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) not in _PRIVATE_DIRECTORY_MODES
        ):
            raise _handoff_error("builder handoff directory metadata is invalid")
        os.fchmod(descriptor, HANDOFF_DIRECTORY_MODE)
        final = os.fstat(descriptor)
        if (
            final.st_uid != os.geteuid()
            or final.st_gid != os.getegid()
            or stat.S_IMODE(final.st_mode) != HANDOFF_DIRECTORY_MODE
        ):
            raise _handoff_error("builder handoff directory mode was not applied")
    finally:
        os.close(descriptor)


def _open_regular_file(path: Path) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _handoff_error("builder handoff file is unavailable") from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise _handoff_error("builder handoff object is not a regular file")
    return descriptor


def _handoff_error(message: str) -> HwpxError:
    return HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, message)

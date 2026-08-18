#!/usr/bin/python3 -I
"""Root-installed fixed Codex worker executable for systemd template units.

This module intentionally imports only the Python standard library. Deployment copies the exact
source to ``/usr/local/libexec/eom-worker-exec`` as a root-owned executable, so worker execution
does not trust an ``eom``-writable virtual environment or repository checkout.
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO

MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
FINALIZATION_ERROR_EXIT = 74
WORKSPACE_ERROR_EXIT = 78
CODEX_BINARY = Path("/usr/local/bin/codex")
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
JOB_ID_PATTERN = re.compile(r"\Ajob_[0-9a-f]{32}\Z", re.ASCII)
SLOT_USERS = {
    "01": "eom-cdx-01",
    "02": "eom-cdx-02",
    "03": "eom-cdx-03",
    "04": "eom-cdx-04",
    "05": "eom-cdx-05",
}


def validate_job_id(value: str) -> str:
    if JOB_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid canonical EOM job ID")
    return value


def expected_workspace(slot_id: str, job_id: str) -> tuple[str, Path, Path]:
    try:
        linux_user = SLOT_USERS[slot_id]
    except KeyError as exc:
        raise ValueError("unknown worker slot") from exc
    validated_job_id = validate_job_id(job_id)
    worker_root = Path("/srv/eom/workspaces") / linux_user
    return linux_user, worker_root, worker_root / validated_job_id


def _validate_runtime_identity(linux_user: str) -> None:
    account = pwd.getpwnam(linux_user)
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise ValueError("worker process identity does not match fixed slot")


def _validate_directory(path: Path, *, group_id: int, mode: int) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_gid != group_id
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise ValueError("worker directory violates the fixed boundary")


def _validate_codex_binary() -> None:
    link_metadata = CODEX_BINARY.lstat()
    resolved = CODEX_BINARY.resolve(strict=True)
    metadata = resolved.stat()
    if (
        link_metadata.st_uid != 0
        or link_metadata.st_gid != 0
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise ValueError("Codex executable violates the fixed boundary")


def _open_input(path: Path, *, workspace: Path, group_id: int) -> BinaryIO:
    if path.parent != workspace:
        raise ValueError("worker input escaped workspace")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_gid != group_id
            or metadata.st_size > MAX_INPUT_BYTES
            or stat.S_IMODE(metadata.st_mode) != 0o640
        ):
            raise ValueError("worker input violates the file contract")
    except Exception:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "rb")


def _write_capture(path: Path, value: bytes, *, workspace: Path) -> None:
    if path.parent != workspace:
        raise ValueError("worker log escaped workspace")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o640)
    try:
        os.write(descriptor, value[-MAX_RESULT_BYTES:])
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)


def finalize_result(path: Path, workspace: Path, *, group_id: int) -> None:
    if path.parent != workspace or path.name != "result.json":
        raise ValueError("worker result path escaped workspace")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_gid != group_id
            or metadata.st_size > MAX_RESULT_BYTES
        ):
            raise ValueError("worker result violates the file contract")
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)


def codex_command(workspace: Path) -> tuple[str, ...]:
    return (
        str(CODEX_BINARY),
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--cd",
        str(workspace),
        "--output-schema",
        str(workspace / "worker-result.schema.json"),
        "--output-last-message",
        str(workspace / "result.json"),
        "-",
    )


def execute(slot_id: str, job_id: str) -> int:
    linux_user, worker_root, workspace = expected_workspace(slot_id, job_id)
    _validate_runtime_identity(linux_user)
    group_id = os.getegid()
    _validate_directory(worker_root, group_id=group_id, mode=0o2770)
    _validate_directory(workspace, group_id=group_id, mode=0o2770)
    resolved_root = worker_root.resolve(strict=True)
    resolved_workspace = workspace.resolve(strict=True)
    if resolved_workspace.parent != resolved_root:
        raise ValueError("worker workspace escaped fixed slot root")

    schema_path = workspace / "worker-result.schema.json"
    result_path = workspace / "result.json"
    if result_path.exists() or result_path.is_symlink():
        raise ValueError("worker result already exists")

    home = Path("/srv/eom/worker-homes") / linux_user
    _validate_directory(home, group_id=group_id, mode=0o700)
    _validate_codex_binary()
    environment = {
        "CODEX_HOME": str(home / ".codex"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PATH": PATH_VALUE,
    }
    with _open_input(schema_path, workspace=workspace, group_id=group_id):
        pass
    with _open_input(workspace / "worker-input.json", workspace=workspace, group_id=group_id):
        pass
    with _open_input(workspace / "prompt.txt", workspace=workspace, group_id=group_id) as prompt:
        completed = subprocess.run(
            codex_command(workspace),
            stdin=prompt,
            capture_output=True,
            check=False,
            cwd=workspace,
            env=environment,
        )

    try:
        _write_capture(workspace / "worker.stdout.log", completed.stdout, workspace=workspace)
        _write_capture(workspace / "worker.stderr.log", completed.stderr, workspace=workspace)
    except (OSError, ValueError):
        print("worker log finalization failed", file=sys.stderr)
        return FINALIZATION_ERROR_EXIT

    if completed.returncode != 0:
        return completed.returncode if completed.returncode > 0 else 128 - completed.returncode
    try:
        finalize_result(result_path, workspace, group_id=group_id)
    except (OSError, ValueError):
        print("worker result finalization failed", file=sys.stderr)
        return FINALIZATION_ERROR_EXIT
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-worker-exec")
    parser.add_argument("--slot", choices=tuple(SLOT_USERS), required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        return execute(args.slot, args.job_id)
    except (KeyError, OSError, ValueError):
        print("worker execution boundary validation failed", file=sys.stderr)
        return WORKSPACE_ERROR_EXIT


if __name__ == "__main__":
    raise SystemExit(main())

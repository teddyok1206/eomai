"""Worker-side Codex launcher that finalizes the private-group result handoff."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

MAX_RESULT_BYTES = 1024 * 1024
FINALIZATION_ERROR_EXIT = 74


def finalize_result(path: Path, workspace: Path) -> None:
    if path.parent.resolve() != workspace.resolve() or path.name != "result.json":
        raise ValueError("worker result path escaped workspace")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RESULT_BYTES:
            raise ValueError("worker result violates the file contract")
        if metadata.st_gid != os.getgid():
            raise ValueError("worker result does not inherit the private group")
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-worker-entry")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("worker command is required")
    completed = subprocess.run(command, stdin=sys.stdin.buffer, check=False)
    if completed.returncode != 0:
        return completed.returncode
    try:
        finalize_result(args.result, Path.cwd())
    except (OSError, ValueError):
        print("worker result finalization failed", file=sys.stderr)
        return FINALIZATION_ERROR_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

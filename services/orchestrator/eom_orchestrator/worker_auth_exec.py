#!/usr/bin/python3 -I
"""Root-installed, fixed-identity, non-generating Codex authentication status probe."""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path

CODEX_BINARY = Path("/usr/local/bin/codex")
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
VERSION_PATTERN = re.compile(rb"\Acodex-cli ([0-9]+\.[0-9]+\.[0-9]+)\s*\Z", re.ASCII)
SLOT_USERS = {
    "01": "eom-cdx-01",
    "02": "eom-cdx-02",
    "03": "eom-cdx-03",
    "04": "eom-cdx-04",
    "05": "eom-cdx-05",
}
AUTH_REQUIRED_EXIT = 20
PROBE_INVALID_EXIT = 21
PROBE_TIMEOUT_EXIT = 22


def _validate_identity(linux_user: str) -> tuple[Path, int, int]:
    account = pwd.getpwnam(linux_user)
    if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
        raise ValueError("authentication probe identity differs")
    home = Path("/srv/eom/worker-homes") / linux_user
    metadata = home.lstat()
    if (
        home.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != account.pw_uid
        or metadata.st_gid != account.pw_gid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("worker home boundary differs")
    return home, account.pw_uid, account.pw_gid


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
        raise ValueError("Codex executable boundary differs")


def execute(slot_id: str) -> int:
    linux_user = SLOT_USERS[slot_id]
    home, _, _ = _validate_identity(linux_user)
    _validate_codex_binary()
    codex_home = home / ".codex"
    try:
        metadata = codex_home.lstat()
    except FileNotFoundError:
        print("CODEX_AUTH_REQUIRED", file=sys.stdout)
        return AUTH_REQUIRED_EXIT
    if (
        codex_home.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("Codex authentication directory boundary differs")
    environment = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PATH": PATH_VALUE,
    }
    try:
        version = subprocess.run(
            (str(CODEX_BINARY), "--version"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=environment,
            timeout=15,
        )
        if version.returncode != 0 or VERSION_PATTERN.fullmatch(version.stdout) is None:
            print("CODEX_AUTH_PROBE_INVALID", file=sys.stdout)
            return PROBE_INVALID_EXIT
        status = subprocess.run(
            (str(CODEX_BINARY), "login", "status"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=environment,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("CODEX_AUTH_PROBE_TIMEOUT", file=sys.stdout)
        return PROBE_TIMEOUT_EXIT
    if status.returncode != 0:
        print("CODEX_AUTH_REQUIRED", file=sys.stdout)
        return AUTH_REQUIRED_EXIT
    print("CODEX_AUTH_READY", file=sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eom-worker-auth-status")
    parser.add_argument("--slot", choices=tuple(SLOT_USERS), required=True)
    args = parser.parse_args(argv)
    try:
        return execute(args.slot)
    except (KeyError, OSError, ValueError):
        print("CODEX_AUTH_PROBE_INVALID", file=sys.stdout)
        return PROBE_INVALID_EXIT


if __name__ == "__main__":
    raise SystemExit(main())

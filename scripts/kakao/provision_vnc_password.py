"""One-time operator-only VNC credential setup; no account login or secret output.

Uses installed tigervnc-tools instead of a second DES/password implementation.
Never overwrites a credential or starts a browser. Run from a protected operator copy.
"""

from __future__ import annotations

import fcntl
import getpass
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path

TARGET = Path("/var/lib/eom-kakao/vnc.passwd")
LOCK = TARGET.parent / "profile.lock"
TOOL = "/usr/bin/tigervncpasswd"


def encode_password(value: str) -> bytes:
    if len(value) != 8 or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError("VNC_PASSWORD_REQUIRES_8_ASCII_CHARACTERS")
    result = subprocess.run(
        (TOOL, "-f"),
        input=value.encode("ascii") + b"\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode or len(result.stdout) not in {8, 16}:
        raise ValueError("VNC_PASSWORD_TOOL_FAILED")
    return result.stdout


def main() -> None:
    if os.getresuid() != (0, 0, 0) or not sys.stdin.isatty():
        raise ValueError("VNC_PROTECTED_INTERACTIVE_OPERATOR_REQUIRED")
    parent = TARGET.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError("VNC_PARENT_INVALID")
    if TARGET.exists() or TARGET.is_symlink():
        raise ValueError("VNC_PASSWORD_ALREADY_EXISTS_NOT_CHANGED")
    first = getpass.getpass("새 원격 화면 전용 비밀번호 (영문/숫자/기호 정확히 8자): ")
    second = getpass.getpass("같은 원격 화면 비밀번호 확인: ")
    if first != second:
        raise ValueError("VNC_PASSWORD_CONFIRMATION_MISMATCH")
    encoded = encode_password(first)
    del first, second
    raw = subprocess.check_output(
        (
            "/usr/bin/systemctl",
            "list-units",
            "--all",
            "--no-legend",
            "--plain",
            "--state=active,activating,deactivating,reloading",
            "eom-kakao-*",
        )
    )
    if raw.strip():
        raise ValueError("VNC_RUNTIME_MUST_BE_STOPPED")
    user = pwd.getpwnam("eom-kakao")
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != user.pw_uid or info.st_nlink != 1:
            raise ValueError("VNC_PROFILE_LOCK_INVALID")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = os.open(
            TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        with os.fdopen(output, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), user.pw_uid, user.pw_gid)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    print("VNC_PASSWORD_PROVISIONED; VALUE_NOT_LOGGED; BROWSER_NOT_STARTED", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error) if type(error) is ValueError else type(error).__name__
        print("VNC_SETUP_STOP=" + code, file=sys.stderr)
        raise SystemExit(1) from None

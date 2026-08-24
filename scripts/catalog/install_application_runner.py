#!/usr/bin/env python3
"""Install the reviewed Catalog application unit after its dedicated secret exists."""

from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPOSITORY = Path("/home/eom/EOM")
TARGET_ENV = Path("/etc/eom/secrets/catalog-manager.env")
UNIT_SOURCE = REPOSITORY / "infra/systemd/eom-catalog-application-runner.service"
UNIT_TARGET = Path("/etc/systemd/system/eom-catalog-application-runner.service")
CATALOG_RUNTIME_ROLE = "eom_catalog_manager_runtime"


def fail(message: str) -> None:
    raise SystemExit(message)


def _metadata_is(path: Path, uid: int, gid: int, mode: int) -> bool:
    metadata = path.lstat()
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and metadata.st_uid == uid
        and metadata.st_gid == gid
        and stat.S_IMODE(metadata.st_mode) == mode
    )


def _read_regular(path: Path, uid: int, gid: int, mode: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == uid
            and metadata.st_gid == gid
            and stat.S_IMODE(metadata.st_mode) == mode
        ):
            fail(f"unsafe protected file metadata: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_catalog_secret(raw: bytes) -> None:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        fail("Catalog runtime secret encoding is invalid")
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail("Catalog runtime secret syntax is invalid")
        key, value = line.split("=", 1)
        if key in values or any(ord(character) < 32 for character in value):
            fail("Catalog runtime secret entry is invalid")
        values[key] = value
    if set(values) != {"EOM_DATABASE_URL"}:
        fail("Catalog runtime secret key set is invalid")
    parsed = urlsplit(values["EOM_DATABASE_URL"])
    if (
        parsed.username != CATALOG_RUNTIME_ROLE
        or parsed.password is None
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 5432
        or not unquote(parsed.path.removeprefix("/"))
    ):
        fail("Catalog runtime database URL identity is invalid")


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) != 2:
        fail("usage: install_application_runner.py EXPECTED_COMMIT (as root)")
    expected_commit = sys.argv[1]
    if len(expected_commit) != 40 or any(
        character not in "0123456789abcdef" for character in expected_commit
    ):
        fail("expected commit is invalid")
    actual_commit = subprocess.run(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != expected_commit:
        fail("repository source commit mismatch")
    if subprocess.run(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout:
        fail("repository working tree is not clean")
    root_uid = pwd.getpwnam("root").pw_uid
    root_gid = grp.getgrnam("root").gr_gid
    api_gid = grp.getgrnam("eom-api").gr_gid
    pwd.getpwnam("eom-catalog-manager")
    if not _metadata_is(TARGET_ENV, root_uid, api_gid, 0o640):
        fail("dedicated Catalog runtime secret is unavailable")
    _validate_catalog_secret(_read_regular(TARGET_ENV, root_uid, api_gid, 0o640))
    subprocess.run(
        ["/usr/bin/install", "-o", "root", "-g", "root", "-m", "0644", UNIT_SOURCE, UNIT_TARGET],
        check=True,
    )
    if not _metadata_is(UNIT_TARGET, root_uid, root_gid, 0o644):
        fail("Catalog application unit installation verification failed")
    print("catalog_application_runner_install=PASS")


if __name__ == "__main__":
    main()

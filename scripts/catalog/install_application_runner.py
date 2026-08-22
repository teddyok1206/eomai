#!/usr/bin/env python3
"""Install the reviewed Catalog manager unit and its DB-only runtime secret."""

from __future__ import annotations

import grp
import os
import pwd
import secrets
import stat
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path("/home/eom/EOM")
SOURCE_ENV = Path("/etc/eom/secrets/api.env")
TARGET_ENV = Path("/etc/eom/secrets/catalog-manager.env")
UNIT_SOURCE = REPOSITORY / "infra/systemd/eom-catalog-application-runner.service"
UNIT_TARGET = Path("/etc/systemd/system/eom-catalog-application-runner.service")


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
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
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


def _parse_source(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        fail("API runtime secret encoding is invalid")
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail("API runtime secret syntax is invalid")
        key, value = line.split("=", 1)
        if key in values or not key or any(ord(character) < 32 for character in value):
            fail("API runtime secret entry is invalid")
        values[key] = value
    required = {
        "EOM_API_DATABASE_URL",
        "EOM_API_TOKEN_HASH_KEY",
        "EOM_API_FINGERPRINT_KEY",
    }
    if set(values) != required:
        fail("API runtime secret key set is invalid")
    return values


def _install_secret(content: bytes, uid: int, gid: int) -> None:
    if TARGET_ENV.exists() or TARGET_ENV.is_symlink():
        if not _metadata_is(TARGET_ENV, uid, gid, 0o640):
            fail("existing Catalog manager secret metadata is unsafe")
        if _read_regular(TARGET_ENV, uid, gid, 0o640) == content:
            return
    temporary = TARGET_ENV.with_name(f".{TARGET_ENV.name}.{secrets.token_hex(8)}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, 0o640)
        if os.write(descriptor, content) != len(content):
            fail("Catalog manager secret write was incomplete")
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, TARGET_ENV)
    parent_descriptor = os.open(TARGET_ENV.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    if _read_regular(TARGET_ENV, uid, gid, 0o640) != content:
        fail("Catalog manager secret installation verification failed")


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
    eom_gid = grp.getgrnam("eom").gr_gid
    api_gid = grp.getgrnam("eom-api").gr_gid
    secrets_parent = TARGET_ENV.parent
    parent_metadata = secrets_parent.lstat()
    if not (
        stat.S_ISDIR(parent_metadata.st_mode)
        and not secrets_parent.is_symlink()
        and parent_metadata.st_uid == root_uid
        and parent_metadata.st_gid == eom_gid
        and stat.S_IMODE(parent_metadata.st_mode) == 0o750
    ):
        fail("runtime secret directory metadata is unsafe")
    values = _parse_source(_read_regular(SOURCE_ENV, root_uid, api_gid, 0o640))
    content = f"EOM_DATABASE_URL={values['EOM_API_DATABASE_URL']}\n".encode()
    _install_secret(content, root_uid, api_gid)
    subprocess.run(
        ["/usr/bin/install", "-o", "root", "-g", "root", "-m", "0644", UNIT_SOURCE, UNIT_TARGET],
        check=True,
    )
    if not _metadata_is(UNIT_TARGET, root_uid, root_gid, 0o644):
        fail("Catalog manager unit installation verification failed")
    print("catalog_application_runner_install=PASS")


if __name__ == "__main__":
    main()

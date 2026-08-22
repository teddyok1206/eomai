#!/usr/bin/env python3
"""Reconcile only the reviewed structured-Item ADMIN permission."""

from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path

from eom_identity_service.models import PermissionRecord, RolePermissionRecord, RoleRecord
from eom_identity_service.repository import seed_builtin_rbac
from eom_operator_identity import ROLE_PERMISSIONS, PermissionKey, RoleKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import create_engine, select

REPOSITORY = Path("/home/eom/EOM")
SOURCE_ENV = Path("/etc/eom/secrets/api.env")
NEW_PERMISSION = PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT.value


def fail(message: str) -> None:
    raise SystemExit(message)


def _read_api_database_url() -> str:
    root_uid = pwd.getpwnam("root").pw_uid
    api_gid = grp.getgrnam("eom-api").gr_gid
    descriptor = os.open(SOURCE_ENV, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == root_uid
            and metadata.st_gid == api_gid
            and stat.S_IMODE(metadata.st_mode) == 0o640
        ):
            fail("API runtime secret metadata is unsafe")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        lines = b"".join(chunks).decode("utf-8").splitlines()
    except UnicodeError:
        fail("API runtime secret encoding is invalid")
    values: dict[str, str] = {}
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
    return values["EOM_API_DATABASE_URL"]


def verify_allowed_delta(
    role_keys: set[str],
    permission_keys: set[str],
    role_permission_pairs: set[tuple[str, str]],
) -> tuple[int, int]:
    expected_roles = {role.value for role in RoleKey}
    expected_permissions = {permission.value for permission in PermissionKey}
    expected_pairs = {
        (role.value, permission.value)
        for role, permissions in ROLE_PERMISSIONS.items()
        for permission in permissions
    }
    if role_keys != expected_roles:
        fail("built-in role inventory drift blocks permission reconciliation")
    if not permission_keys.issubset(expected_permissions):
        fail("unexpected permission blocks reconciliation")
    missing_permissions = expected_permissions - permission_keys
    if not missing_permissions.issubset({NEW_PERMISSION}):
        fail("unrelated missing permission blocks reconciliation")
    if not role_permission_pairs.issubset(expected_pairs):
        fail("unexpected built-in role-permission mapping blocks reconciliation")
    missing_pairs = expected_pairs - role_permission_pairs
    allowed_missing_pairs = {(RoleKey.ADMIN.value, NEW_PERMISSION)}
    if not missing_pairs.issubset(allowed_missing_pairs):
        fail("unrelated missing role-permission mapping blocks reconciliation")
    return len(missing_permissions), len(missing_pairs)


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) != 2:
        fail("usage: reconcile_structured_item_permission.py EXPECTED_COMMIT (as root)")
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

    engine = create_engine(_read_api_database_url(), pool_pre_ping=True)
    sessions = build_session_factory(engine)
    try:
        with sessions.begin() as session:
            roles = {row.role_key: row for row in session.scalars(select(RoleRecord))}
            permissions = {
                row.permission_key: row for row in session.scalars(select(PermissionRecord))
            }
            pairs = {
                (role_key, permission_key)
                for role_key, permission_key in session.execute(
                    select(RoleRecord.role_key, PermissionRecord.permission_key)
                    .join(
                        RolePermissionRecord,
                        RolePermissionRecord.role_id == RoleRecord.role_id,
                    )
                    .join(
                        PermissionRecord,
                        PermissionRecord.permission_id == RolePermissionRecord.permission_id,
                    )
                )
            }
            permission_additions, pair_additions = verify_allowed_delta(
                set(roles),
                set(permissions),
                pairs,
            )
            seed_builtin_rbac(session)
            session.flush()
            final_permissions = {
                row.permission_key for row in session.scalars(select(PermissionRecord))
            }
            final_pairs = {
                (role_key, permission_key)
                for role_key, permission_key in session.execute(
                    select(RoleRecord.role_key, PermissionRecord.permission_key)
                    .join(
                        RolePermissionRecord,
                        RolePermissionRecord.role_id == RoleRecord.role_id,
                    )
                    .join(
                        PermissionRecord,
                        PermissionRecord.permission_id == RolePermissionRecord.permission_id,
                    )
                )
            }
            if verify_allowed_delta(set(roles), final_permissions, final_pairs) != (0, 0):
                fail("structured Item permission reconciliation did not converge")
    finally:
        engine.dispose()
    print(f"structured_item_permission_added={permission_additions}")
    print(f"structured_item_admin_mapping_added={pair_additions}")
    print("structured_item_permission_reconciliation=PASS")


if __name__ == "__main__":
    main()

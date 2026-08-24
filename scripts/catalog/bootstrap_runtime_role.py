#!/usr/bin/env python3
"""Create/reconcile the dedicated DB-only Catalog application role and secret."""

from __future__ import annotations

import grp
import os
import pwd
import secrets
import stat
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql

REPOSITORY = Path("/home/eom/EOM")
POSTGRES_ENV = Path("/etc/eom/secrets/postgres.env")
TARGET_ENV = Path("/etc/eom/secrets/catalog-manager.env")
ROLE = "eom_catalog_manager_runtime"
LEGACY_ROLE = "eom_api_runtime"

sys.path.insert(0, str(REPOSITORY / "services/catalog_service"))
from eom_catalog_service.runtime_privileges import INSERT_TABLES, TABLE_PRIVILEGES  # noqa: E402


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def _read_regular(path: Path, *, expected_uid: int, allowed_modes: frozenset[int]) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or stat.S_IMODE(metadata.st_mode) not in allowed_modes
            or metadata.st_mode & 0o007
        ):
            fail(f"unsafe protected file metadata: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_env(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        fail("protected environment encoding is invalid")
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail("protected environment syntax is invalid")
        key, value = line.split("=", 1)
        if key in values or not key or any(ord(character) < 32 for character in value):
            fail("protected environment entry is invalid")
        values[key] = value
    return values


def _existing_password(root_uid: int, api_gid: int, database: str) -> str | None:
    if not TARGET_ENV.exists():
        return None
    metadata = TARGET_ENV.lstat()
    if (
        TARGET_ENV.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != root_uid
        or metadata.st_gid != api_gid
        or stat.S_IMODE(metadata.st_mode) != 0o640
    ):
        fail("existing Catalog runtime secret metadata is unsafe")
    values = _parse_env(
        _read_regular(TARGET_ENV, expected_uid=root_uid, allowed_modes=frozenset({0o640}))
    )
    if set(values) != {"EOM_DATABASE_URL"}:
        fail("existing Catalog runtime secret key set is invalid")
    parsed = urlsplit(values["EOM_DATABASE_URL"])
    username = parsed.username
    password = parsed.password
    if password is None:
        fail("existing Catalog runtime database URL is invalid")
    if (
        parsed.scheme != "postgresql+psycopg"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 5432
        or unquote(parsed.path.removeprefix("/")) != database
        or parsed.query
        or parsed.fragment
    ):
        fail("existing Catalog runtime database URL is invalid")
    if username == LEGACY_ROLE:
        # Phase 7 splits Catalog away from the historical shared API runtime role. The exact
        # loopback/database identity above is the only legacy form eligible for this one-way
        # transition. Generate a fresh dedicated credential and leave the API role untouched.
        return None
    if username != ROLE:
        fail("existing Catalog runtime database URL is invalid")
    return unquote(password)


def _install_secret(content: bytes, root_uid: int, api_gid: int) -> None:
    temporary = TARGET_ENV.with_name(f".{TARGET_ENV.name}.{secrets.token_hex(8)}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchown(descriptor, root_uid, api_gid)
        os.fchmod(descriptor, 0o640)
        if os.write(descriptor, content) != len(content):
            fail("Catalog runtime secret write was incomplete")
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


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) != 1:
        fail("run bootstrap_runtime_role.py without arguments as root")
    root_uid = pwd.getpwnam("root").pw_uid
    api_gid = grp.getgrnam("eom-api").gr_gid
    parent = TARGET_ENV.parent
    parent_metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != root_uid
        or stat.S_IMODE(parent_metadata.st_mode) != 0o750
    ):
        fail("runtime secret directory metadata is unsafe")
    admin = _parse_env(
        _read_regular(POSTGRES_ENV, expected_uid=root_uid, allowed_modes=frozenset({0o600, 0o640}))
    )
    required = {"POSTGRES_PASSWORD"}
    if not required.issubset(admin):
        fail("PostgreSQL administrator secret is incomplete")
    database = admin.get("POSTGRES_DB", "eom")
    administrator = admin.get("POSTGRES_USER", "postgres")
    password = _existing_password(root_uid, api_gid, database) or secrets.token_urlsafe(48)
    connection = psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user=administrator,
        password=admin["POSTGRES_PASSWORD"],
        dbname=database,
        autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(password)
                )
            )
        else:
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(password)
                )
            )
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(ROLE))
        )
        cursor.execute(
            "SELECT granted.rolname FROM pg_auth_members membership "
            "JOIN pg_roles granted ON granted.oid = membership.roleid "
            "JOIN pg_roles member ON member.oid = membership.member "
            "WHERE member.rolname = %s",
            (ROLE,),
        )
        for (granted_role,) in cursor.fetchall():
            cursor.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(str(granted_role)), sql.Identifier(ROLE)
                )
            )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET search_path TO app, pg_catalog").format(sql.Identifier(ROLE))
        )
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            )
        )
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            )
        )
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA app, public FROM {}").format(
                sql.Identifier(ROLE)
            )
        )
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA app FROM {}").format(
                sql.Identifier(ROLE)
            )
        )
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app FROM {}").format(
                sql.Identifier(ROLE)
            )
        )
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(ROLE)))
        for privilege, tables in TABLE_PRIVILEGES:
            cursor.execute(
                sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                    sql.SQL(privilege),
                    sql.SQL(", ").join(
                        sql.SQL("app.{}").format(sql.Identifier(table)) for table in tables
                    ),
                    sql.Identifier(ROLE),
                )
            )
        cursor.execute(
            "SELECT sequence_namespace.nspname, sequence.relname "
            "FROM pg_class sequence "
            "JOIN pg_namespace sequence_namespace "
            "ON sequence_namespace.oid = sequence.relnamespace "
            "JOIN pg_depend dependency ON dependency.objid = sequence.oid "
            "JOIN pg_class owner_table ON owner_table.oid = dependency.refobjid "
            "JOIN pg_namespace table_namespace ON table_namespace.oid = owner_table.relnamespace "
            "WHERE sequence.relkind = 'S' AND dependency.deptype IN ('a', 'i') "
            "AND table_namespace.nspname = 'app' AND owner_table.relname = ANY(%s)",
            (list(INSERT_TABLES),),
        )
        sequences = tuple((str(schema), str(name)) for schema, name in cursor.fetchall())
        if sequences:
            cursor.execute(
                sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(
                    sql.SQL(", ").join(
                        sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(name))
                        for schema, name in sequences
                    ),
                    sql.Identifier(ROLE),
                )
            )
        cursor.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
            "rolbypassrls "
            "FROM pg_roles WHERE rolname = %s",
            (ROLE,),
        )
        attributes = cursor.fetchone()
        if attributes is None or attributes[0] is not True or any(attributes[1:]):
            fail("Catalog runtime role has a prohibited attribute")
        cursor.execute(
            "SELECT has_schema_privilege(%s, 'app', 'CREATE'), "
            "has_schema_privilege(%s, 'public', 'CREATE'), "
            "has_database_privilege(%s, %s, 'CREATE'), "
            "has_database_privilege(%s, %s, 'TEMP')",
            (ROLE, ROLE, ROLE, database, ROLE, database),
        )
        if cursor.fetchone() != (False, False, False, False):
            fail("Catalog runtime role retains a prohibited creation privilege")
    connection.close()
    encoded_password = quote(password, safe="")
    encoded_database = quote(database, safe="")
    content = (
        f"EOM_DATABASE_URL=postgresql+psycopg://{ROLE}:{encoded_password}"
        f"@127.0.0.1:5432/{encoded_database}\n"
    ).encode()
    _install_secret(content, root_uid, api_gid)
    print("catalog_runtime_role_bootstrap=PASS")


if __name__ == "__main__":
    main()

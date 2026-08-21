#!/srv/eom/conda/envs/eom-api/bin/python
"""Reconcile the fixed least-privilege HWPX manager database identity."""

from __future__ import annotations

import grp
import os
import pwd
import secrets
import stat
import sys
from pathlib import Path
from typing import Never
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql
from sqlalchemy import create_engine

REPOSITORY = Path("/home/eom/EOM")
POSTGRES_ENV = Path("/etc/eom/secrets/postgres.env")
API_ENV = Path("/etc/eom/secrets/api.env")
TARGET = Path("/etc/eom/secrets/hwpx-manager.env")
ROLE = "eom_hwpx_manager_runtime"

sys.path.insert(0, str(REPOSITORY / "services/hwpx_manager"))
from eom_hwpx_manager.runtime_privileges import (  # noqa: E402
    INSERT_TABLES,
    TABLE_PRIVILEGES,
    manager_runtime_privileges_ready,
)


def fail(code: str) -> Never:
    print(code, file=sys.stderr)
    raise SystemExit(1)


def values(path: Path, *, owner: str, group: str, mode: int) -> dict[str, str]:
    metadata = path.lstat()
    expected = (pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid, mode)
    actual = (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or actual != expected:
        fail("HWPX_MANAGER_ENVIRONMENT_METADATA_MISMATCH")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def existing_password(api_url: str, database: str) -> str | None:
    target_values = values(TARGET, owner="root", group="eom-api", mode=0o640)
    if set(target_values) != {"EOM_DATABASE_URL"}:
        fail("HWPX_MANAGER_ENVIRONMENT_KEY_SET_MISMATCH")
    current = target_values["EOM_DATABASE_URL"]
    if current == api_url:
        return None
    parsed = urlsplit(current)
    if (
        parsed.scheme != "postgresql+psycopg"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 5432
        or parsed.username != ROLE
        or parsed.password is None
        or unquote(parsed.path.removeprefix("/")) != database
    ):
        fail("HWPX_MANAGER_DATABASE_IDENTITY_MISMATCH")
    password = parsed.password
    if password is None:
        fail("HWPX_MANAGER_DATABASE_IDENTITY_MISMATCH")
    return unquote(password)


def write_environment(url: str) -> None:
    temporary = TARGET.with_name(f".{TARGET.name}.{secrets.token_hex(8)}")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.write(descriptor, f"EOM_DATABASE_URL={url}\n".encode("ascii"))
        os.fsync(descriptor)
        os.fchown(descriptor, 0, grp.getgrnam("eom-api").gr_gid)
        os.fchmod(descriptor, 0o640)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, TARGET)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    if os.geteuid() != 0:
        fail("HWPX_MANAGER_RUNTIME_ROLE_REQUIRES_ROOT")
    parent = TARGET.parent.lstat()
    if (
        TARGET.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or (parent.st_uid, parent.st_gid, stat.S_IMODE(parent.st_mode))
        != (0, grp.getgrnam("eom").gr_gid, 0o750)
    ):
        fail("HWPX_MANAGER_ENVIRONMENT_PARENT_MISMATCH")
    admin = values(POSTGRES_ENV, owner="root", group="eom", mode=0o640)
    api = values(API_ENV, owner="root", group="eom-api", mode=0o640)
    if "POSTGRES_PASSWORD" not in admin or set(api) != {
        "EOM_API_DATABASE_URL",
        "EOM_API_TOKEN_HASH_KEY",
        "EOM_API_FINGERPRINT_KEY",
    }:
        fail("HWPX_MANAGER_AUTHORITATIVE_DATABASE_UNAVAILABLE")
    api_url = api["EOM_API_DATABASE_URL"]
    parsed_api = urlsplit(api_url)
    database = unquote(parsed_api.path.removeprefix("/"))
    if (
        parsed_api.scheme != "postgresql+psycopg"
        or parsed_api.hostname != "127.0.0.1"
        or parsed_api.port != 5432
        or not database
    ):
        fail("HWPX_MANAGER_AUTHORITATIVE_DATABASE_INVALID")
    password = existing_password(api_url, database) or secrets.token_urlsafe(48)

    connection = psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user=admin.get("POSTGRES_USER", "postgres"),
        password=admin["POSTGRES_PASSWORD"],
        dbname=database,
        autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,))
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
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                "NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(ROLE))
        )
        cursor.execute(
            "SELECT granted.rolname FROM pg_auth_members membership "
            "JOIN pg_roles granted ON granted.oid=membership.roleid "
            "JOIN pg_roles member ON member.oid=membership.member "
            "WHERE member.rolname=%s",
            (ROLE,),
        )
        for (granted,) in cursor.fetchall():
            cursor.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(str(granted)), sql.Identifier(ROLE)
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
        for statement in (
            "REVOKE ALL PRIVILEGES ON SCHEMA app, public FROM {}",
            "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA app FROM {}",
            "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app FROM {}",
            "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app FROM {}",
        ):
            cursor.execute(sql.SQL(statement).format(sql.Identifier(ROLE)))
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
            "JOIN pg_namespace sequence_namespace ON sequence_namespace.oid=sequence.relnamespace "
            "JOIN pg_depend dependency ON dependency.objid=sequence.oid "
            "JOIN pg_class owner_table ON owner_table.oid=dependency.refobjid "
            "JOIN pg_namespace table_namespace ON table_namespace.oid=owner_table.relnamespace "
            "WHERE sequence.relkind='S' AND dependency.deptype IN ('a','i') "
            "AND table_namespace.nspname='app' AND owner_table.relname=ANY(%s)",
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
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='app' AND table_type='BASE TABLE'"
        )
        for (table,) in cursor.fetchall():
            expected = {privilege for privilege, tables in TABLE_PRIVILEGES if str(table) in tables}
            for checked_privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
            ):
                cursor.execute(
                    "SELECT has_table_privilege(%s,%s,%s)",
                    (ROLE, f"app.{table}", checked_privilege),
                )
                if cursor.fetchone() != (checked_privilege in expected,):
                    fail("HWPX_MANAGER_TABLE_PRIVILEGE_MISMATCH")
        cursor.execute(
            "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=%s",
            (ROLE,),
        )
        attributes = cursor.fetchone()
        if attributes is None or attributes[0] is not True or any(attributes[1:]):
            fail("HWPX_MANAGER_ROLE_ATTRIBUTE_MISMATCH")
        cursor.execute(
            "SELECT has_database_privilege(%s,%s,'CONNECT'),"
            "has_database_privilege(%s,%s,'CREATE'),"
            "has_database_privilege(%s,%s,'TEMP')",
            (ROLE, database, ROLE, database, ROLE, database),
        )
        if cursor.fetchone() != (True, False, False):
            fail("HWPX_MANAGER_DATABASE_PRIVILEGE_MISMATCH")
        cursor.execute(
            "SELECT has_schema_privilege(%s,'app','CREATE'),"
            "has_schema_privilege(%s,'public','CREATE')",
            (ROLE, ROLE),
        )
        if cursor.fetchone() != (False, False):
            fail("HWPX_MANAGER_SCHEMA_PRIVILEGE_MISMATCH")
        cursor.execute(
            "SELECT 1 FROM pg_auth_members membership "
            "JOIN pg_roles member ON member.oid=membership.member "
            "WHERE member.rolname=%s LIMIT 1",
            (ROLE,),
        )
        if cursor.fetchone() is not None:
            fail("HWPX_MANAGER_ROLE_MEMBERSHIP_MISMATCH")
        cursor.execute(
            "SELECT sequence_namespace.nspname, sequence.relname "
            "FROM pg_class sequence "
            "JOIN pg_namespace sequence_namespace "
            "ON sequence_namespace.oid=sequence.relnamespace "
            "WHERE sequence.relkind='S' AND sequence_namespace.nspname='app'"
        )
        all_sequences = tuple((str(schema), str(name)) for schema, name in cursor.fetchall())
        for schema, name in all_sequences:
            cursor.execute(
                "SELECT has_sequence_privilege(%s,%s,'USAGE')",
                (ROLE, f"{schema}.{name}"),
            )
            if cursor.fetchone() != ((schema, name) in sequences,):
                fail("HWPX_MANAGER_SEQUENCE_PRIVILEGE_MISMATCH")
        cursor.execute(
            "SELECT COALESCE(bool_or(has_function_privilege(%s, procedure.oid, 'EXECUTE')), "
            "false) FROM pg_proc procedure "
            "JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace "
            "WHERE namespace.nspname='app'",
            (ROLE,),
        )
        if cursor.fetchone() != (False,):
            fail("HWPX_MANAGER_FUNCTION_PRIVILEGE_MISMATCH")
    connection.close()

    manager_url = (
        f"postgresql+psycopg://{ROLE}:{quote(password, safe='')}@127.0.0.1:5432/{database}"
    )
    write_environment(manager_url)
    target = values(TARGET, owner="root", group="eom-api", mode=0o640)
    if target != {"EOM_DATABASE_URL": manager_url}:
        fail("HWPX_MANAGER_ENVIRONMENT_WRITE_MISMATCH")
    engine = create_engine(manager_url)
    with engine.connect() as runtime_connection:
        if not manager_runtime_privileges_ready(runtime_connection):
            fail("HWPX_MANAGER_RUNTIME_PRIVILEGES_UNAVAILABLE")
        if runtime_connection.exec_driver_sql("SELECT current_user").scalar_one() != ROLE:
            fail("HWPX_MANAGER_RUNTIME_IDENTITY_MISMATCH")
        if (
            runtime_connection.exec_driver_sql(
                "SELECT version_num FROM app.alembic_version"
            ).scalar_one()
            != "20260821_0008"
        ):
            fail("HWPX_MANAGER_MIGRATION_MISMATCH")
    engine.dispose()
    print("hwpx_manager_runtime_role=READY")
    print("hwpx_manager_runtime_role_identity=eom_hwpx_manager_runtime")
    print("hwpx_manager_runtime_privilege_policy=FAIL_CLOSED")


if __name__ == "__main__":
    main()

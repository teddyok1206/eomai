#!/srv/eom/conda/envs/eom-api/bin/python
"""Prepare only a manifest-guarded disposable chat role; never production."""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import secrets
import stat
import subprocess
import sys
from pathlib import Path

import psycopg
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_environment,
    read_chat_preparation_file,
)
from eom_orchestrator.general_chat_role_preparation import (
    ChatRolePreparation,
    prepare_chat_role,
    require_chat_role_replay,
)
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy.engine import URL, make_url

from scripts.api.testdb_guard import (
    TestDatabaseManifest,
    validate_catalog_metadata,
    validate_state_directory,
)

REPOSITORY = Path("/home/eom/EOM")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("commit")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ChatError("GENERAL_CHAT_TEST_ROLE_REQUIRES_ROOT")
        commit = subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "status", "--porcelain=v1"], text=True
        )
        if args.commit != commit or dirty:
            raise ChatError("GENERAL_CHAT_TEST_SOURCE_MISMATCH")
        state = validate_state_directory(args.state)
        account = pwd.getpwnam("eom")
        node = state.lstat()
        if (node.st_uid, node.st_gid, stat.S_IMODE(node.st_mode)) != (
            account.pw_uid,
            account.pw_gid,
            0o700,
        ):
            raise ChatError("GENERAL_CHAT_TEST_STATE_INVALID")
        manifest_path = state / "manifest.json"
        raw_manifest = read_chat_preparation_file(
            manifest_path,
            uid=account.pw_uid,
            gid=account.pw_gid,
            mode=0o600,
        )
        manifest = TestDatabaseManifest.from_json(raw_manifest.decode("ascii"))
        owner_env = read_chat_environment(
            state / "owner.env", uid=account.pw_uid, gid=account.pw_gid, mode=0o600
        )
        url = make_url(owner_env["EOM_DATABASE_URL"])
        if (url.database, url.username, url.host, url.port) != (
            manifest.database,
            manifest.owner_role,
            "127.0.0.1",
            5432,
        ):
            raise ChatError("GENERAL_CHAT_TEST_STATE_INVALID")
        admin = read_chat_environment(
            Path("/etc/eom/secrets/postgres.env"), uid=0, gid=grp.getgrnam("eom").gr_gid, mode=0o640
        )
        target = state / "chat.env"
        secret_exists = target.exists() or target.is_symlink()
        if secret_exists:
            current = read_chat_environment(
                target, uid=account.pw_uid, gid=account.pw_gid, mode=0o600
            )
            if set(current) != {"EOM_GENERAL_CHAT_DATABASE_URL"}:
                raise ChatError("GENERAL_CHAT_TEST_STATE_INVALID")
            recorded = make_url(current["EOM_GENERAL_CHAT_DATABASE_URL"])
            if (
                (
                    recorded.drivername,
                    recorded.username,
                    recorded.host,
                    recorded.port,
                    recorded.database,
                )
                != (
                    "postgresql+psycopg",
                    manifest.runtime_role,
                    "127.0.0.1",
                    5432,
                    manifest.database,
                )
                or not recorded.password
                or recorded.query
            ):
                raise ChatError("GENERAL_CHAT_TEST_STATE_INVALID")
            password = recorded.password
        else:
            password = secrets.token_urlsafe(48)
        spec = ChatRolePreparation(manifest.runtime_role, manifest.database, manifest.marker)
        with (
            psycopg.connect(
                host="127.0.0.1",
                port=5432,
                user=admin.get("POSTGRES_USER", "postgres"),
                password=admin["POSTGRES_PASSWORD"],
                dbname=manifest.database,
                connect_timeout=5,
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT r.rolname, d.description FROM pg_database b "
                "JOIN pg_roles r ON r.oid=b.datdba LEFT JOIN pg_shdescription d "
                "ON d.objoid=b.oid AND d.classoid='pg_database'::regclass "
                "WHERE b.datname=%s",
                (manifest.database,),
            )
            database_row = cursor.fetchone()
            cursor.execute(
                "SELECT r.rolname, d.description FROM pg_roles r LEFT JOIN pg_shdescription d "
                "ON d.objoid=r.oid AND d.classoid='pg_authid'::regclass "
                "WHERE r.rolname=ANY(%s)",
                ([manifest.owner_role, manifest.runtime_role],),
            )
            markers: dict[str, str | None] = {
                str(name): None if marker is None else str(marker)
                for name, marker in cursor.fetchall()
            }
            validate_catalog_metadata(
                manifest,
                database_owner=None if database_row is None else str(database_row[0]),
                database_comment=None if database_row is None else str(database_row[1]),
                owner_comment=markers.get(manifest.owner_role),
                runtime_comment=markers.get(manifest.runtime_role),
                require_runtime=manifest.runtime_role in markers,
            )
            cursor.execute("SELECT version_num FROM app.alembic_version")
            if cursor.fetchone() != (CURRENT_MIGRATION_REVISION,):
                raise ChatError("GENERAL_CHAT_TEST_MIGRATION_MISMATCH")
            cursor.execute(
                "SELECT r.rolname, d.description FROM pg_namespace n "
                "JOIN pg_roles r ON r.oid=n.nspowner LEFT JOIN pg_description d "
                "ON d.objoid=n.oid AND d.classoid='pg_namespace'::regclass "
                "WHERE n.nspname='app'"
            )
            if cursor.fetchone() != (manifest.owner_role, manifest.marker):
                raise ChatError("GENERAL_CHAT_TEST_STATE_INVALID")
            exists = require_chat_role_replay(cursor, spec, secret_exists=secret_exists)
            if not secret_exists:
                protected_url = URL.create(
                    "postgresql+psycopg",
                    username=spec.role,
                    password=password,
                    host="127.0.0.1",
                    port=5432,
                    database=spec.database,
                )
                payload = (
                    "EOM_GENERAL_CHAT_DATABASE_URL="
                    + protected_url.render_as_string(hide_password=False)
                    + "\n"
                ).encode("ascii")
                # Durable credential first: failed DB preparation reuses it on
                # replay, rather than leaving a created role with a lost secret.
                install_chat_environment(target, payload, uid=account.pw_uid, gid=account.pw_gid)
            prepare_chat_role(cursor, spec, password=password, exists=exists)
        print("general_chat_disposable_role=PREPARED\nproduction_mutations=0\nmodel_calls=0")
        return 0
    except Exception as error:
        print(safe_chat_error_code(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

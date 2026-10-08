#!/srv/eom/conda/envs/eom-api/bin/python
"""Stage the fixed chat-owner role; does not migrate, activate or enroll auth."""

from __future__ import annotations

import argparse
import grp
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path

import psycopg
from eom_orchestrator.general_chat_owner_runtime import OWNER_DATABASE_ROLE
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_environment,
)
from eom_orchestrator.general_chat_role_preparation import (
    ChatRolePreparation,
    prepare_chat_role,
    require_chat_role_replay,
)
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

REPOSITORY = Path("/home/eom/EOM")
POSTGRES_ENV = Path("/etc/eom/secrets/postgres.env")
TARGET = Path("/etc/eom/secrets/general-chat.env")
ROLE_MARKER = "eom:general-chat:owner-runtime"


def require_preparation_boundary(commit: str) -> None:
    if os.geteuid() != 0:
        raise ChatError("GENERAL_CHAT_ROLE_REQUIRES_ROOT")
    actual = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain=v1"], text=True
    )
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or commit != actual or dirty:
        raise ChatError("GENERAL_CHAT_ROLE_SOURCE_MISMATCH")
    state = subprocess.check_output(
        ["systemctl", "show", "eom-general-chat.service", "--property=ActiveState", "--value"],
        text=True,
    ).strip()
    if state != "inactive":
        raise ChatError("GENERAL_CHAT_OWNER_MUST_BE_STOPPED")
    parent = TARGET.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or (
        parent.st_uid,
        parent.st_gid,
        stat.S_IMODE(parent.st_mode),
    ) != (0, grp.getgrnam("eom").gr_gid, 0o750):
        raise ChatError("GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID")


def retained_password(database: str) -> str | None:
    if not TARGET.exists() and not TARGET.is_symlink():
        return None
    values = read_chat_environment(TARGET, uid=0, gid=0, mode=0o600)
    if set(values) != {"EOM_GENERAL_CHAT_DATABASE_URL"}:
        raise ChatError("GENERAL_CHAT_ROLE_IDENTITY_CONFLICT")
    try:
        url = make_url(values["EOM_GENERAL_CHAT_DATABASE_URL"])
        if (
            (url.drivername, url.username, url.host, url.port, url.database)
            != ("postgresql+psycopg", OWNER_DATABASE_ROLE, "127.0.0.1", 5432, database)
            or not url.password
            or url.query
        ):
            raise ValueError()
        return url.password
    except (ValueError, ArgumentError):
        raise ChatError("GENERAL_CHAT_ROLE_IDENTITY_CONFLICT") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    args = parser.parse_args()
    try:
        require_preparation_boundary(args.commit)
        admin = read_chat_environment(
            POSTGRES_ENV, uid=0, gid=grp.getgrnam("eom").gr_gid, mode=0o640
        )
        database = admin["POSTGRES_DB"]
        administrator = admin["POSTGRES_USER"]
        if (
            re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database) is None
            or not administrator
            or not admin["POSTGRES_PASSWORD"]
        ):
            raise ChatError("GENERAL_CHAT_AUTHORITATIVE_DATABASE_INVALID")
        existing = retained_password(database)
        password = existing if existing is not None else secrets.token_urlsafe(48)
        spec = ChatRolePreparation(OWNER_DATABASE_ROLE, database, ROLE_MARKER)
        with (
            psycopg.connect(
                host="127.0.0.1",
                port=5432,
                user=administrator,
                password=admin["POSTGRES_PASSWORD"],
                dbname=database,
                connect_timeout=5,
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT current_database(), version_num FROM app.alembic_version")
            if cursor.fetchall() != [(database, CURRENT_MIGRATION_REVISION)]:
                raise ChatError("GENERAL_CHAT_ROLE_DATABASE_NOT_READY")
            cursor.execute("SELECT 1 FROM pg_stat_activity WHERE usename=%s LIMIT 1", (spec.role,))
            if cursor.fetchone() is not None:
                raise ChatError("GENERAL_CHAT_OWNER_MUST_BE_STOPPED")
            exists = require_chat_role_replay(cursor, spec, secret_exists=existing is not None)
            if existing is None:
                url = URL.create(
                    "postgresql+psycopg",
                    username=spec.role,
                    password=password,
                    host="127.0.0.1",
                    port=5432,
                    database=database,
                )
                payload = (
                    "EOM_GENERAL_CHAT_DATABASE_URL="
                    + url.render_as_string(hide_password=False)
                    + "\n"
                ).encode("ascii")
                install_chat_environment(TARGET, payload, uid=0, gid=0)
            prepare_chat_role(cursor, spec, password=password, exists=exists)
        print("general_chat_owner_role=STAGED\nservice_activation=NONE\nauth_enrollment=NONE")
        return 0
    except Exception as error:
        print(safe_chat_error_code(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
API_ENV="${EOM_API_ENV_TARGET:-/etc/eom/secrets/api.env}"
PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run bootstrap_runtime_role.sh as root.\n' >&2
  exit 1
fi
[[ -r "${POSTGRES_ENV}" ]] || {
  printf 'PostgreSQL administrator secret file is unavailable.\n' >&2
  exit 1
}
[[ -x "${PYTHON}" ]] || {
  printf 'The isolated eom-api Python is unavailable.\n' >&2
  exit 1
}
getent group eom-api >/dev/null || {
  printf 'Create the eom-api system group before the runtime database role.\n' >&2
  exit 1
}

set -a
source "${POSTGRES_ENV}"
set +a
export EOM_API_ENV_TARGET="${API_ENV}"

"${PYTHON}" <<'PY'
from __future__ import annotations

import grp
import os
import secrets
import stat
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql

ROLE = "eom_api_runtime"
READ_TABLES = (
    "alembic_version",
    "api_audit_events",
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "approval_requests",
    "artifact_revisions",
    "content_intake_batches",
    "content_intake_events",
    "content_intake_source_files",
    "content_pack_activations",
    "content_pack_events",
    "content_pack_files",
    "content_pack_profiles",
    "content_pack_releases",
    "content_packs",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "item_components",
    "item_events",
    "item_relationships",
    "item_revisions",
    "items",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "permissions",
    "role_permissions",
    "roles",
    "usage_plans",
    "usage_records",
    "workflow_commands",
    "workflow_definitions",
    "workflow_events",
    "workflow_instances",
    "workflow_step_runs",
)
INSERT_TABLES = (
    "api_audit_events",
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "content_pack_activations",
    "content_pack_events",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "item_events",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "usage_plans",
    "usage_records",
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
)
UPDATE_TABLES = (
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "content_pack_activations",
    "content_pack_releases",
    "items",
    "operator_credentials",
    "operator_role_assignments",
    "operators",
    "usage_plans",
)


def load_existing(path: Path) -> tuple[str, str, str] | None:
    if not path.exists():
        return None
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("existing API secret path is not a regular file")
    if (
        metadata.st_uid != 0
        or metadata.st_gid != grp.getgrnam("eom-api").gr_gid
        or stat.S_IMODE(metadata.st_mode) != 0o640
    ):
        raise SystemExit("existing API secret file ownership or mode is unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    required = {
        "EOM_API_DATABASE_URL",
        "EOM_API_TOKEN_HASH_KEY",
        "EOM_API_FINGERPRINT_KEY",
    }
    if set(values) != required:
        raise SystemExit("existing API secret file has an unexpected key set")
    parsed = urlsplit(values["EOM_API_DATABASE_URL"])
    if parsed.username != ROLE or parsed.password is None:
        raise SystemExit("existing API database URL is not for eom_api_runtime")
    return (
        unquote(parsed.password),
        values["EOM_API_TOKEN_HASH_KEY"],
        values["EOM_API_FINGERPRINT_KEY"],
    )


target = Path(os.environ["EOM_API_ENV_TARGET"])
existing = load_existing(target)
if existing is None:
    role_password = secrets.token_urlsafe(48)
    token_key = secrets.token_urlsafe(48)
    fingerprint_key = secrets.token_urlsafe(48)
else:
    role_password, token_key, fingerprint_key = existing

database = os.environ["POSTGRES_DB"]
connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname=database,
    autocommit=True,
)
with connection.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(ROLE), sql.Literal(role_password)
            )
        )
    else:
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(ROLE), sql.Literal(role_password)
            )
        )
    cursor.execute(
        sql.SQL(
            "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        ).format(sql.Identifier(ROLE))
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET search_path TO app, pg_catalog").format(
            sql.Identifier(ROLE)
        )
    )
    cursor.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
            sql.Identifier(database), sql.Identifier(ROLE)
        )
    )
    cursor.execute(
        sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(
            sql.Identifier(database)
        )
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(ROLE)
        )
    )
    cursor.execute(
        sql.SQL("REVOKE CREATE ON SCHEMA app, public FROM {}").format(sql.Identifier(ROLE))
    )
    cursor.execute(
        sql.SQL("GRANT USAGE ON SCHEMA app TO {}").format(sql.Identifier(ROLE))
    )
    for privilege, tables in (
        ("SELECT", READ_TABLES),
        ("INSERT", INSERT_TABLES),
        ("UPDATE", UPDATE_TABLES),
    ):
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
        sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO {}").format(
            sql.Identifier(ROLE)
        )
    )
    cursor.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        (ROLE,),
    )
    attributes = cursor.fetchone()
    if attributes is None or any(attributes):
        raise SystemExit("runtime database role has a prohibited role attribute")
    cursor.execute(
        "SELECT has_schema_privilege(%s, 'app', 'CREATE'), "
        "has_schema_privilege(%s, 'public', 'CREATE')",
        (ROLE, ROLE),
    )
    schema_create = cursor.fetchone()
    if schema_create is None or any(schema_create):
        raise SystemExit("runtime database role still has schema CREATE privilege")
    cursor.execute(
        sql.SQL("SELECT has_database_privilege(%s, {}, 'TEMP')").format(
            sql.Literal(database)
        ),
        (ROLE,),
    )
    if cursor.fetchone() != (False,):
        raise SystemExit("runtime database role still has temporary-table privilege")
connection.close()

runtime = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=ROLE,
    password=role_password,
    dbname=database,
)
with runtime.cursor() as cursor:
    cursor.execute("SELECT version_num FROM app.alembic_version")
    if cursor.fetchone() is None:
        raise SystemExit("runtime database role cannot read the migration revision")
    try:
        cursor.execute("CREATE TABLE app.eom_api_privilege_probe (id integer)")
    except psycopg.errors.InsufficientPrivilege:
        runtime.rollback()
    else:
        runtime.rollback()
        raise SystemExit("runtime database role unexpectedly created a table")
    try:
        cursor.execute("ALTER TABLE app.operators ADD COLUMN eom_api_privilege_probe integer")
    except psycopg.errors.InsufficientPrivilege:
        runtime.rollback()
    else:
        runtime.rollback()
        raise SystemExit("runtime database role unexpectedly altered a table")
    try:
        cursor.execute("CREATE TEMPORARY TABLE eom_api_temp_privilege_probe (id integer)")
    except psycopg.errors.InsufficientPrivilege:
        runtime.rollback()
    else:
        runtime.rollback()
        raise SystemExit("runtime database role unexpectedly created a temporary table")
runtime.close()

database_url = (
    f"postgresql+psycopg://{ROLE}:{quote(role_password, safe='')}"
    f"@127.0.0.1:5432/{quote(database, safe='')}"
)
payload = (
    f"EOM_API_DATABASE_URL={database_url}\n"
    f"EOM_API_TOKEN_HASH_KEY={token_key}\n"
    f"EOM_API_FINGERPRINT_KEY={fingerprint_key}\n"
)
target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(temporary, flags, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
os.chown(temporary, 0, grp.getgrnam("eom-api").gr_gid)
os.chmod(temporary, 0o640)
temporary.replace(target)
PY

printf 'eom_api_runtime and the protected API environment file are ready.\n'

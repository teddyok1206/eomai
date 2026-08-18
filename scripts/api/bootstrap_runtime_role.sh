#!/usr/bin/env bash
set -euo pipefail

POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
API_ENV="${EOM_API_ENV_TARGET:-/etc/eom/secrets/api.env}"
PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"
TEST_MODE="${EOM_API_TEST_MODE:-0}"

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
set -a
source "${POSTGRES_ENV}"
set +a

RUNTIME_ROLE="${EOM_API_RUNTIME_ROLE:-eom_api_runtime}"
DATABASE_NAME="${EOM_API_DATABASE_NAME:-${POSTGRES_DB}}"
ENV_OWNER="${EOM_API_ENV_OWNER:-root}"
ENV_GROUP="${EOM_API_ENV_GROUP:-eom-api}"
ENV_MODE="${EOM_API_ENV_MODE:-0640}"

if [[ "${TEST_MODE}" == "1" ]]; then
  [[ "${RUNTIME_ROLE}" =~ ^eom_api_test_runtime_[a-z0-9_]+$ ]] || {
    printf 'Disposable runtime role name is unsafe.\n' >&2
    exit 1
  }
  [[ "${DATABASE_NAME}" =~ ^eom_api_test_[a-z0-9_]+$ ]] || {
    printf 'Disposable database name is unsafe.\n' >&2
    exit 1
  }
  [[ "${API_ENV}" == /tmp/eom-api-testdb-*/runtime.env ]] || {
    printf 'Disposable runtime environment target is unsafe.\n' >&2
    exit 1
  }
  [[ "${ENV_OWNER}:${ENV_GROUP}:${ENV_MODE}" == "eom:eom:0600" ]] || {
    printf 'Disposable runtime environment metadata is unsafe.\n' >&2
    exit 1
  }
else
  [[ "${RUNTIME_ROLE}:${API_ENV}:${ENV_OWNER}:${ENV_GROUP}:${ENV_MODE}" == \
    "eom_api_runtime:/etc/eom/secrets/api.env:root:eom-api:0640" ]] || {
    printf 'Production runtime role boundary cannot be overridden.\n' >&2
    exit 1
  }
fi

getent group "${ENV_GROUP}" >/dev/null || {
  printf 'The target environment group is unavailable.\n' >&2
  exit 1
}
getent passwd "${ENV_OWNER}" >/dev/null || {
  printf 'The target environment owner is unavailable.\n' >&2
  exit 1
}

export EOM_API_DATABASE_NAME="${DATABASE_NAME}"
export EOM_API_ENV_GROUP="${ENV_GROUP}"
export EOM_API_ENV_MODE="${ENV_MODE}"
export EOM_API_ENV_OWNER="${ENV_OWNER}"
export EOM_API_ENV_TARGET="${API_ENV}"
export EOM_API_RUNTIME_ROLE="${RUNTIME_ROLE}"
export EOM_API_TEST_MODE="${TEST_MODE}"

"${PYTHON}" <<'PY'
from __future__ import annotations

import grp
import os
import pwd
import secrets
import stat
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql

ROLE = os.environ["EOM_API_RUNTIME_ROLE"]
DATABASE = os.environ["EOM_API_DATABASE_NAME"]
ENV_OWNER = os.environ["EOM_API_ENV_OWNER"]
ENV_GROUP = os.environ["EOM_API_ENV_GROUP"]
ENV_MODE = int(os.environ["EOM_API_ENV_MODE"], 8)
TEST_MODE = os.environ["EOM_API_TEST_MODE"] == "1"
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
        metadata.st_uid != pwd.getpwnam(ENV_OWNER).pw_uid
        or metadata.st_gid != grp.getgrnam(ENV_GROUP).gr_gid
        or stat.S_IMODE(metadata.st_mode) != ENV_MODE
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
    if (
        parsed.username != ROLE
        or parsed.password is None
        or unquote(parsed.path.removeprefix("/")) != DATABASE
    ):
        raise SystemExit("existing API database URL is not for the configured runtime role")
    return (
        unquote(parsed.password),
        values["EOM_API_TOKEN_HASH_KEY"],
        values["EOM_API_FINGERPRINT_KEY"],
    )


target = Path(os.environ["EOM_API_ENV_TARGET"])
parent_metadata = target.parent.lstat()
expected_parent = (
    pwd.getpwnam("eom").pw_uid if TEST_MODE else 0,
    grp.getgrnam("eom").gr_gid,
    0o700 if TEST_MODE else 0o750,
)
if (
    target.parent.is_symlink()
    or not stat.S_ISDIR(parent_metadata.st_mode)
    or (
        parent_metadata.st_uid,
        parent_metadata.st_gid,
        stat.S_IMODE(parent_metadata.st_mode),
    )
    != expected_parent
):
    raise SystemExit("API environment parent directory metadata is unsafe")
existing = load_existing(target)
if existing is None:
    role_password = secrets.token_urlsafe(48)
    token_key = secrets.token_urlsafe(48)
    fingerprint_key = secrets.token_urlsafe(48)
else:
    role_password, token_key, fingerprint_key = existing

database = DATABASE
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
        "SELECT granted.rolname "
        "FROM pg_auth_members membership "
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
        sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA app, public FROM {}").format(
            sql.Identifier(ROLE)
        )
    )
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
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
    cursor.execute(
        sql.SQL("REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app FROM {}").format(
            sql.Identifier(ROLE)
        )
    )
    cursor.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC")
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
        "SELECT sequence_namespace.nspname, sequence.relname "
        "FROM pg_class sequence "
        "JOIN pg_namespace sequence_namespace ON sequence_namespace.oid = sequence.relnamespace "
        "JOIN pg_depend dependency ON dependency.objid = sequence.oid "
        "JOIN pg_class owner_table ON owner_table.oid = dependency.refobjid "
        "JOIN pg_namespace table_namespace ON table_namespace.oid = owner_table.relnamespace "
        "WHERE sequence.relkind = 'S' "
        "AND dependency.deptype IN ('a', 'i') "
        "AND table_namespace.nspname = 'app' "
        "AND owner_table.relname = ANY(%s)",
        (list(INSERT_TABLES),),
    )
    required_sequences = tuple((str(schema), str(name)) for schema, name in cursor.fetchall())
    if required_sequences:
        cursor.execute(
            sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(
                sql.SQL(", ").join(
                    sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(name))
                    for schema, name in required_sequences
                ),
                sql.Identifier(ROLE),
            )
        )
    cursor.execute(
        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        (ROLE,),
    )
    attributes = cursor.fetchone()
    if attributes is None or attributes[0] is not True or any(attributes[1:]):
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
        sql.SQL(
            "SELECT has_database_privilege(%s, {}, 'CONNECT'), "
            "has_database_privilege(%s, {}, 'CREATE'), "
            "has_database_privilege(%s, {}, 'TEMP')"
        ).format(
            sql.Literal(database),
            sql.Literal(database),
            sql.Literal(database)
        ),
        (ROLE, ROLE, ROLE),
    )
    if cursor.fetchone() != (True, False, False):
        raise SystemExit("runtime database privilege set differs from the reviewed plan")
    cursor.execute(
        "SELECT 1 FROM pg_auth_members membership "
        "JOIN pg_roles member ON member.oid = membership.member "
        "WHERE member.rolname = %s LIMIT 1",
        (ROLE,),
    )
    if cursor.fetchone() is not None:
        raise SystemExit("runtime database role still has role membership")
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'app' AND table_type = 'BASE TABLE'"
    )
    for (table_name,) in cursor.fetchall():
        expected = {
            privilege
            for privilege, tables in (
                ("SELECT", READ_TABLES),
                ("INSERT", INSERT_TABLES),
                ("UPDATE", UPDATE_TABLES),
            )
            if table_name in tables
        }
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (ROLE, f"app.{table_name}", privilege),
            )
            if cursor.fetchone() != (privilege in expected,):
                raise SystemExit("runtime table privilege set differs from the reviewed plan")
    expected_sequence_names = {f"{schema}.{name}" for schema, name in required_sequences}
    cursor.execute(
        "SELECT sequence_schema, sequence_name FROM information_schema.sequences "
        "WHERE sequence_schema = 'app'"
    )
    for schema, sequence_name in cursor.fetchall():
        qualified = f"{schema}.{sequence_name}"
        cursor.execute(
            "SELECT has_sequence_privilege(%s, %s, 'USAGE')",
            (ROLE, qualified),
        )
        if cursor.fetchone() != (qualified in expected_sequence_names,):
            raise SystemExit("runtime sequence privilege set differs from the reviewed plan")
    cursor.execute(
        "SELECT procedure.oid::regprocedure::text "
        "FROM pg_proc procedure "
        "JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace "
        "WHERE namespace.nspname = 'app'"
    )
    for (signature,) in cursor.fetchall():
        cursor.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (ROLE, signature))
        if cursor.fetchone() != (False,):
            raise SystemExit("runtime role retains an unreviewed function privilege")
connection.close()

runtime = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=ROLE,
    password=role_password,
    dbname=database,
)
with runtime.cursor() as cursor:
    cursor.execute("SELECT current_user")
    if cursor.fetchone() != (ROLE,):
        raise SystemExit("runtime connection is not using the configured role")
    cursor.execute("SELECT version_num FROM app.alembic_version")
    if cursor.fetchone() is None:
        raise SystemExit("runtime database role cannot read the migration revision")
    cursor.execute(
        "INSERT INTO app.api_audit_events "
        "(api_audit_event_id, request_id, event_type, operation_id, http_method, "
        "route_template, outcome, http_status, created_at) "
        "VALUES (%s, %s, 'PRIVILEGE_PROBE', 'runtime_role_probe', 'POST', "
        "'/internal/privilege-probe', 'ROLLED_BACK', 204, CURRENT_TIMESTAMP)",
        (f"apiaudit_{secrets.token_hex(16)}", f"req_{secrets.token_hex(16)}"),
    )
    runtime.rollback()

    def expect_denied(statement: str) -> None:
        try:
            cursor.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            runtime.rollback()
        else:
            runtime.rollback()
            raise SystemExit("runtime database role unexpectedly passed a prohibited operation")

    expect_denied("CREATE TABLE app.eom_api_privilege_probe (id integer)")
    expect_denied("ALTER TABLE app.operators ADD COLUMN eom_api_privilege_probe integer")
    expect_denied("DROP TABLE app.operators")
    expect_denied("TRUNCATE TABLE app.api_audit_events")
    expect_denied("CREATE TEMPORARY TABLE eom_api_temp_privilege_probe (id integer)")
    cursor.execute(
        "SELECT name FROM pg_available_extensions "
        "WHERE installed_version IS NULL ORDER BY name LIMIT 1"
    )
    extension_row = cursor.fetchone()
    if extension_row is None:
        raise SystemExit("no uninstalled extension is available for the privilege probe")
    expect_denied(
        sql.SQL("CREATE EXTENSION {}").format(sql.Identifier(str(extension_row[0])))
    )
    expect_denied("CREATE ROLE eom_api_privilege_probe")
    expect_denied(f"ALTER ROLE {ROLE} CREATEDB")
    expect_denied("UPDATE app.alembic_version SET version_num = version_num")
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
if not target.parent.is_dir():
    raise SystemExit("API environment parent directory is unavailable")
temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(temporary, flags, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
os.chown(
    temporary,
    pwd.getpwnam(ENV_OWNER).pw_uid,
    grp.getgrnam(ENV_GROUP).gr_gid,
)
os.chmod(temporary, ENV_MODE)
temporary.replace(target)
PY

printf 'Runtime database role and protected environment file are reconciled.\n'

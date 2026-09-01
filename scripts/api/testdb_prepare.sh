#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"
BOOTSTRAP="${REPOSITORY_ROOT}/scripts/api/bootstrap_runtime_role.sh"

usage() {
  printf '%s\n' "usage: $0 [--reconcile /tmp/eom-api-testdb-<ID>]"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "test database preparation must run as root"
[[ -r "${POSTGRES_ENV}" ]] || fail "PostgreSQL administrator secret file is unavailable"
[[ -x "${PYTHON}" ]] || fail "isolated eom-api Python is unavailable"
[[ -f "${BOOTSTRAP}" ]] || fail "runtime role bootstrap is unavailable"

set -a
source "${POSTGRES_ENV}"
set +a

if (($# == 0)); then
  test_id="$(date -u +'%Y%m%d%H%M%S')_$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
  state_directory="/tmp/eom-api-testdb-${test_id}"
  install -d -o eom -g eom -m 0700 "${state_directory}"
  export EOM_API_TEST_ID="${test_id}"
  export EOM_API_TEST_STATE="${state_directory}"

  if ! PYTHONPATH="${REPOSITORY_ROOT}" "${PYTHON}" <<'PY'
from __future__ import annotations

import os
import pwd
import secrets
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

from scripts.api.testdb_guard import (
    TestDatabaseManifest,
    validate_application_schema_metadata,
)

manifest = TestDatabaseManifest.create(os.environ["EOM_API_TEST_ID"])
state = Path(os.environ["EOM_API_TEST_STATE"])
owner_password = secrets.token_urlsafe(48)
connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname="postgres",
    autocommit=True,
)
role_created = False
database_created = False
owner_env = state / "owner.env"
manifest_path = state / "manifest.json"
try:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT datname FROM pg_database WHERE datname = %s UNION ALL "
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
            (manifest.database, [manifest.owner_role, manifest.runtime_role]),
        )
        if cursor.fetchone() is not None:
            raise SystemExit("disposable database identity collision")
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(manifest.owner_role), sql.Literal(owner_password))
        )
        role_created = True
        cursor.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                sql.Identifier(manifest.database), sql.Identifier(manifest.owner_role)
            )
        )
        database_created = True
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET search_path TO app, public").format(
                sql.Identifier(manifest.owner_role)
            )
        )
        cursor.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(manifest.database), sql.Literal(manifest.marker)
            )
        )
        cursor.execute(
            sql.SQL("COMMENT ON ROLE {} IS {}").format(
                sql.Identifier(manifest.owner_role), sql.Literal(manifest.marker)
            )
        )
    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=manifest.database,
        autocommit=True,
    ) as application_connection:
        with application_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA app AUTHORIZATION {}").format(
                    sql.Identifier(manifest.owner_role)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA app TO {}").format(
                    sql.Identifier(manifest.owner_role)
                )
            )
            cursor.execute(
                sql.SQL("COMMENT ON SCHEMA app IS {}").format(sql.Literal(manifest.marker))
            )
    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user=manifest.owner_role,
        password=owner_password,
        dbname=manifest.database,
    ) as owner_connection:
        with owner_connection.cursor() as cursor:
            cursor.execute(
                "SELECT owner.rolname, description.description "
                "FROM pg_namespace namespace "
                "JOIN pg_roles owner ON owner.oid = namespace.nspowner "
                "LEFT JOIN pg_description description ON description.objoid = namespace.oid "
                "AND description.classoid = 'pg_namespace'::regclass "
                "WHERE namespace.nspname = 'app'"
            )
            schema_row = cursor.fetchone()
            cursor.execute(
                "SELECT current_schemas(false), "
                "has_schema_privilege(current_user, 'app', 'USAGE'), "
                "has_schema_privilege(current_user, 'app', 'CREATE')"
            )
            search_path, has_usage, has_create = cursor.fetchone() or ([], False, False)
    validate_application_schema_metadata(
        manifest,
        schema_owner=None if schema_row is None else str(schema_row[0]),
        schema_comment=None if schema_row is None else schema_row[1],
        effective_search_path=tuple(str(value) for value in search_path),
        has_usage=bool(has_usage),
        has_create=bool(has_create),
    )
    owner_url = (
        f"postgresql+psycopg://{manifest.owner_role}:{quote(owner_password, safe='')}"
        f"@127.0.0.1:5432/{manifest.database}"
    )
    owner_env.write_text(f"EOM_DATABASE_URL={owner_url}\n", encoding="ascii")
    manifest_path.write_text(manifest.to_json(), encoding="ascii")
    uid = pwd.getpwnam("eom").pw_uid
    gid = pwd.getpwnam("eom").pw_gid
    for path in (owner_env, manifest_path):
        os.chown(path, uid, gid)
        os.chmod(path, 0o600)
except BaseException:
    with connection.cursor() as cursor:
        if database_created:
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(manifest.database)))
        if role_created:
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(manifest.owner_role)))
    for path in (owner_env, manifest_path):
        path.unlink(missing_ok=True)
    raise
finally:
    connection.close()
PY
  then
    rmdir "${state_directory}" 2>/dev/null || true
    fail "disposable database preparation failed"
  fi
  printf 'Disposable API test database prepared: %s\n' "${state_directory}"
  printf 'Next unprivileged phase: scripts/api/testdb_run.sh migrate %s\n' "${state_directory}"
  exit 0
fi

if (($# != 2)) || [[ "$1" != "--reconcile" ]]; then
  usage >&2
  exit 2
fi
state_directory="$2"
export EOM_API_TEST_STATE="${state_directory}"

mapfile -d '' -t manifest_values < <(
  PYTHONPATH="${REPOSITORY_ROOT}" "${PYTHON}" <<'PY'
from __future__ import annotations

import os
from pathlib import Path

import psycopg

from scripts.api.testdb_guard import (
    TestDatabaseManifest,
    validate_catalog_metadata,
    validate_state_directory,
)

state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
manifest = TestDatabaseManifest.load(state / "manifest.json")
connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname="postgres",
)
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT owner.rolname, description.description "
        "FROM pg_database database "
        "JOIN pg_roles owner ON owner.oid = database.datdba "
        "LEFT JOIN pg_shdescription description ON description.objoid = database.oid "
        "AND description.classoid = 'pg_database'::regclass "
        "WHERE database.datname = %s",
        (manifest.database,),
    )
    database_row = cursor.fetchone()
    cursor.execute(
        "SELECT description.description FROM pg_roles role "
        "LEFT JOIN pg_shdescription description ON description.objoid = role.oid "
        "AND description.classoid = 'pg_authid'::regclass "
        "WHERE role.rolname = %s",
        (manifest.owner_role,),
    )
    owner_row = cursor.fetchone()
connection.close()
validate_catalog_metadata(
    manifest,
    database_owner=None if database_row is None else str(database_row[0]),
    database_comment=None if database_row is None else database_row[1],
    owner_comment=None if owner_row is None else owner_row[0],
    require_runtime=False,
)
for value in (manifest.database, manifest.runtime_role, manifest.marker):
    print(value, end="\0")
PY
)
((${#manifest_values[@]} == 3)) || fail "disposable database manifest verification failed"
database_name="${manifest_values[0]}"
runtime_role="${manifest_values[1]}"
marker="${manifest_values[2]}"

reconcile_runtime_role() {
  EOM_API_TEST_MODE=1 \
  EOM_API_DATABASE_NAME="${database_name}" \
  EOM_API_RUNTIME_ROLE="${runtime_role}" \
  EOM_API_ENV_TARGET="${state_directory}/runtime.env" \
  EOM_API_ENV_OWNER=eom \
  EOM_API_ENV_GROUP=eom \
  EOM_API_ENV_MODE=0600 \
  EOM_POSTGRES_ENV="${POSTGRES_ENV}" \
  EOM_API_PYTHON="${PYTHON}" \
    "${BOOTSTRAP}"
}

# Replay without drift proves the exact reconciliation is idempotent.
reconcile_runtime_role
reconcile_runtime_role

# The third pass proves a stale, overprivileged table grant is removed rather
# than retained by an additive-only bootstrap.
export EOM_API_TEST_RUNTIME_ROLE="${runtime_role}"
export EOM_API_DATABASE_NAME="${database_name}"
"${PYTHON}" <<'PY'
import os

import psycopg
from psycopg import sql

connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname=os.environ["EOM_API_DATABASE_NAME"],
    autocommit=True,
)
with connection.cursor() as cursor:
    cursor.execute(
        sql.SQL("GRANT DELETE ON TABLE app.workflow_instances TO {}").format(
            sql.Identifier(os.environ["EOM_API_TEST_RUNTIME_ROLE"])
        )
    )
connection.close()
PY
reconcile_runtime_role

export EOM_API_TEST_MARKER="${marker}"
export EOM_API_TEST_RUNTIME_ROLE="${runtime_role}"
"${PYTHON}" <<'PY'
import os

import psycopg
from psycopg import sql

connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname="postgres",
    autocommit=True,
)
with connection.cursor() as cursor:
    cursor.execute(
        sql.SQL("COMMENT ON ROLE {} IS {}").format(
            sql.Identifier(os.environ["EOM_API_TEST_RUNTIME_ROLE"]),
            sql.Literal(os.environ["EOM_API_TEST_MARKER"]),
        )
    )
connection.close()
PY

printf 'Disposable API runtime role reconciled.\n'
printf 'Next unprivileged phase: scripts/api/testdb_run.sh tests %s\n' "${state_directory}"

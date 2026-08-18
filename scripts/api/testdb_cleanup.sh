#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if (($# != 2)) || [[ "$1" != "--confirm" ]]; then
  printf '%s\n' "usage: $0 --confirm /tmp/eom-api-testdb-<ID>" >&2
  exit 2
fi
[[ "$(id -u)" -eq 0 ]] || fail "test database cleanup must run as root"
[[ -r "${POSTGRES_ENV}" ]] || fail "PostgreSQL administrator secret file is unavailable"
[[ -x "${PYTHON}" ]] || fail "isolated eom-api Python is unavailable"

state_directory="$2"
export EOM_API_TEST_STATE="${state_directory}"
set -a
source "${POSTGRES_ENV}"
set +a

PYTHONPATH="${REPOSITORY_ROOT}" "${PYTHON}" <<'PY'
from __future__ import annotations

import os
import shutil
from pathlib import Path

import psycopg
from psycopg import sql

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
    autocommit=True,
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
        "SELECT role.rolname, description.description FROM pg_roles role "
        "LEFT JOIN pg_shdescription description ON description.objoid = role.oid "
        "AND description.classoid = 'pg_authid'::regclass "
        "WHERE role.rolname = ANY(%s)",
        ([manifest.owner_role, manifest.runtime_role],),
    )
    role_comments = {str(name): comment for name, comment in cursor.fetchall()}
    runtime_exists = manifest.runtime_role in role_comments
    validate_catalog_metadata(
        manifest,
        database_owner=None if database_row is None else str(database_row[0]),
        database_comment=None if database_row is None else database_row[1],
        owner_comment=role_comments.get(manifest.owner_role),
        runtime_comment=role_comments.get(manifest.runtime_role),
        require_runtime=runtime_exists,
    )
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (manifest.database,),
    )
    cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(manifest.database)))
    if runtime_exists:
        cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(manifest.runtime_role)))
    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(manifest.owner_role)))
connection.close()
shutil.rmtree(state)
PY

printf 'Disposable API test database removed.\n'

#!/usr/bin/env bash
set -euo pipefail

POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
PYTHON="${EOM_OBSERVE_PYTHON:-/srv/eom/conda/envs/eom-observe/bin/python}"
REPOSITORY_ROOT="/home/eom/EOM"
export PYTHONPATH="${REPOSITORY_ROOT}/apps/observe_console"

if [[ ! -r "${POSTGRES_ENV}" ]]; then
  printf '%s\n' 'PostgreSQL secret file is unavailable' >&2
  exit 1
fi

set -a
source "${POSTGRES_ENV}"
set +a

"${PYTHON}" <<'PY'
import os

import psycopg
from psycopg import sql

from eom_observe.read_model import COLUMN_SELECT_GRANTS, FULL_SELECT_TABLES

connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname=os.environ["POSTGRES_DB"],
    autocommit=True,
)
with connection.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='eom_observe_ro'")
    if cursor.fetchone() is None:
        raise SystemExit("eom_observe_ro role is unavailable; bootstrap it first")
    cursor.execute(
        "ALTER ROLE eom_observe_ro NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    )
    cursor.execute("ALTER ROLE eom_observe_ro SET default_transaction_read_only = on")
    cursor.execute("ALTER ROLE eom_observe_ro SET search_path TO app, pg_catalog")
    cursor.execute("GRANT USAGE ON SCHEMA app TO eom_observe_ro")
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO eom_observe_ro").format(
            sql.SQL(", ").join(
                sql.SQL("{}.{}").format(sql.Identifier("app"), sql.Identifier(table))
                for table in FULL_SELECT_TABLES
            )
        )
    )
    for table, columns in COLUMN_SELECT_GRANTS.items():
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON TABLE {}.{} FROM eom_observe_ro").format(
                sql.Identifier("app"), sql.Identifier(table)
            )
        )
        cursor.execute(
            sql.SQL("GRANT SELECT ({}) ON TABLE {}.{} TO eom_observe_ro").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                sql.Identifier("app"),
                sql.Identifier(table),
            )
        )
connection.close()
PY

printf '%s\n' 'Observability read-only grants reconciled.'

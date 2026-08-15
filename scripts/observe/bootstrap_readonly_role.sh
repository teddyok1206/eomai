#!/usr/bin/env bash
set -euo pipefail

POSTGRES_ENV="${EOM_POSTGRES_ENV:-/etc/eom/secrets/postgres.env}"
PASSWORD_FILE="${EOM_OBSERVE_DB_PASSWORD_FILE:-/run/eom-observe-db-password}"
PYTHON="${EOM_OBSERVE_PYTHON:-/srv/eom/conda/envs/eom-observe/bin/python}"
export EOM_OBSERVE_DB_PASSWORD_FILE="$PASSWORD_FILE"

if [[ ! -r "$POSTGRES_ENV" ]]; then
  printf 'PostgreSQL secret file is unavailable\n' >&2
  exit 1
fi

set -a
source "$POSTGRES_ENV"
set +a

OBSERVE_PASSWORD="$(openssl rand -hex 32)"
umask 077
printf '%s\n' "$OBSERVE_PASSWORD" > "$PASSWORD_FILE"

"$PYTHON" <<'PY'
import os
from pathlib import Path

import psycopg
from psycopg import sql

password_file = Path(os.environ.get("EOM_OBSERVE_DB_PASSWORD_FILE", "/run/eom-observe-db-password"))
observe_password = password_file.read_text(encoding="ascii").strip()
database = os.environ["POSTGRES_DB"]
connection = psycopg.connect(
    host="127.0.0.1",
    port=5432,
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ["POSTGRES_PASSWORD"],
    dbname=database,
    autocommit=True,
)
tables = (
    "worker_slots", "jobs", "job_events", "artifacts", "artifact_revisions",
    "workflow_instances", "workflow_step_runs", "workflow_events", "approval_requests",
)
with connection.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='eom_observe_ro'")
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL("CREATE ROLE eom_observe_ro LOGIN PASSWORD {}").format(
                sql.Literal(observe_password)
            )
        )
    else:
        cursor.execute(
            sql.SQL("ALTER ROLE eom_observe_ro PASSWORD {}").format(sql.Literal(observe_password))
        )
    cursor.execute(
        "ALTER ROLE eom_observe_ro NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    )
    cursor.execute("ALTER ROLE eom_observe_ro SET default_transaction_read_only = on")
    cursor.execute("ALTER ROLE eom_observe_ro SET search_path TO app, pg_catalog")
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO eom_observe_ro").format(
            sql.Identifier(database)
        )
    )
    cursor.execute("GRANT USAGE ON SCHEMA app TO eom_observe_ro")
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO eom_observe_ro").format(
            sql.SQL(", ").join(
                sql.SQL("{}.{}").format(sql.Identifier("app"), sql.Identifier(table))
                for table in tables
            )
        )
    )
connection.close()
PY

printf 'Read-only role configured; password written to protected handoff file: %s\n' "$PASSWORD_FILE"

#!/usr/bin/env bash
set -euo pipefail

required_vars=(POSTGRES_DB POSTGRES_USER EOM_APP_USER EOM_APP_PASSWORD)
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "missing required environment variable: ${var}" >&2
    exit 2
  fi
done

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_user="$EOM_APP_USER" \
  --set=app_password="$EOM_APP_PASSWORD" \
  --set=db_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user"
  LOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOREPLICATION
  PASSWORD :'app_password';

ALTER DATABASE :"db_name" OWNER TO :"app_user";
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
\connect :"db_name"
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION :"app_user";
GRANT USAGE, CREATE ON SCHEMA app TO :"app_user";
ALTER ROLE :"app_user" SET search_path TO app, public;
SQL

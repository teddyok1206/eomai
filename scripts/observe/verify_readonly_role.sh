#!/usr/bin/env bash
set -euo pipefail

PYTHON="${EOM_OBSERVE_PYTHON:-/srv/eom/conda/envs/eom-observe/bin/python}"
SECRET_FILE="${EOM_OBSERVE_SECRET_FILE:-/etc/eom/secrets/observe.env}"
export EOM_OBSERVE_SECRET_FILE="$SECRET_FILE"

"$PYTHON" <<'PY'
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from eom_observe.settings import load_secrets

engine = create_engine(load_secrets().database_url, pool_pre_ping=True)
checks = {}
with engine.connect() as connection:
    checks["select"] = connection.scalar(text("SELECT count(*) >= 0 FROM jobs")) is True

statements = {
    "insert": "INSERT INTO worker_slots (slot_id, linux_user, role, enabled, gpu) VALUES ('zz','observe-denied','support',false,false)",
    "update": "UPDATE worker_slots SET enabled=enabled WHERE slot_id='01'",
    "delete": "DELETE FROM worker_slots WHERE slot_id='zz'",
    "create": "CREATE TABLE observe_write_must_fail (id integer)",
}
for name, sql in statements.items():
    denied = False
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text(sql))
            connection.rollback()
    except DBAPIError:
        denied = True
    checks[name] = denied

engine.dispose()
for name, passed in checks.items():
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
if not all(checks.values()):
    raise SystemExit(1)
PY

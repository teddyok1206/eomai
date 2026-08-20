# Application API Disposable Integration Database

Identity bootstrap, last-ADMIN, refresh, idempotency, migration, and concurrency tests require an
empty PostgreSQL database. They must never run against the deployed `eom` database. The harness
uses a UTC/random test ID, PostgreSQL names below 63 bytes, database and role comments, a manifest,
and exact owner validation.

The phases intentionally cross the privilege boundary twice:

```bash
sudo -n scripts/api/testdb_prepare.sh
sudo -k
scripts/api/testdb_run.sh verify /tmp/eom-api-testdb-<ID>
scripts/api/testdb_run.sh migrate /tmp/eom-api-testdb-<ID>

sudo -v
sudo -n scripts/api/testdb_prepare.sh --reconcile /tmp/eom-api-testdb-<ID>
sudo -k
scripts/api/testdb_run.sh tests /tmp/eom-api-testdb-<ID>

sudo -v
sudo -n scripts/api/testdb_cleanup.sh --confirm /tmp/eom-api-testdb-<ID>
sudo -k
```

Replace `<ID>` only with the exact non-sensitive directory printed by prepare. Codex does not run
these privileged phases. The state directory is `eom:eom:0700`; `owner.env`, `runtime.env`, and
`manifest.json` are 0600. Neither script prints a credential or URL. Do not source these files
outside the runner.

Prepare creates only `eom_api_test_*` names and records
`EOM_API_DISPOSABLE_TEST_DB:<ID>` comments. Migration runs as the isolated database owner. Runtime
reconciliation uses the production privilege plan in explicit test mode and creates a separate
runtime credential. Tests use the owner for fixture cleanup and the runtime role for rollback-only
DML plus DDL and migration denial probes.

Workflow definitions and API audit rows created during the integration phase remain immutable.
Per-test teardown must not delete them; the guarded final database cleanup removes the disposable
database and its history as one unit. The runtime approval test is therefore the final test in the
disposable test list because it intentionally retains its append-only audit and workflow records.

The prepare phase also reproduces the production schema prerequisite: `app` is owned by the
disposable migration owner, carries the disposable marker, and the owner's effective search path
is exactly `app, public`. The unprivileged `verify` action checks this without applying migrations.

Cleanup requires `--confirm`, a direct `/tmp/eom-api-testdb-*` directory, a valid manifest,
protected-name rejection, the expected owner, and exact database and role markers. It removes only
those guarded objects. If preparation fails before the runtime role exists, matching database and
owner markers are sufficient; an existing runtime role must also carry the marker. Never edit the
manifest to force cleanup.

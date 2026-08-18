# Platform Smoke Test

## Preconditions

- Run from `/home/eom/EOM` on branch `feat/platform-skeleton-v0`.
- PostgreSQL Compose is healthy on `127.0.0.1:5432`.
- `/mnt/nas` is mounted and `/mnt/nas/eom/artifacts` exists.
- `eom-cdx-01` is logged in with its own Codex subscription account.
- The operator can create transient systemd services.
- Do not read, copy, print, or log any Codex authentication file.

Use only the explicit environment binaries:

```bash
CORE=/srv/eom/conda/envs/eom-core
$CORE/bin/python --version
$CORE/bin/python -m pip install -e '.[dev]'
$CORE/bin/alembic upgrade head
```

## Preflight

```bash
$CORE/bin/eomctl system doctor
$CORE/bin/eomctl worker list
```

Doctor must report PostgreSQL, revision `20260815_0001`, NAS, Codex, systemctl, five worker users,
slot config, eom-core, staging, and five schemas as passing. Worker list must map `authoring` to
`eom-cdx-01` and report global Codex concurrency 3.

## Live Execution

This command consumes one live Codex subscription invocation:

```bash
$CORE/bin/eomctl job submit --message EOM_PLATFORM_SMOKE_TEST
```

Record the returned `job_id`, then inspect both aggregate state and ordered history:

```bash
$CORE/bin/eomctl job inspect <JOB_ID>
$CORE/bin/eomctl job events <JOB_ID>
```

Expected state order:

```text
CREATED
VALIDATED
QUEUED
CLAIMED
RUNNING
VALIDATING_RESULT
COMMITTING
SUCCEEDED
```

Inspect must show worker slot `01`, exit code `0`, logical artifact ID, revision ID, content and
manifest SHA-256 values, a DB artifact/revision record, and the final NAS path. The final directory
contains only validated `result.json` and `manifest.json`.

Reuse that execution for the marked E2E assertion without another model call:

```bash
EOM_RUN_CODEX_LIVE=1 EOM_LIVE_JOB_ID=<JOB_ID> \
  $CORE/bin/python -m pytest tests/e2e/test_codex_live.py -q
```

Normal pytest runs skip `codex_live` unless `EOM_RUN_CODEX_LIVE=1` is explicitly set.

## Failure Inspection

```bash
$CORE/bin/eomctl job inspect <JOB_ID>
$CORE/bin/eomctl job events <JOB_ID>
```

Timeout, nonzero exit, missing result, malformed result, hash mismatch, and unavailable NAS must end
in `FAILED`, never `SUCCEEDED`. Worker stdout/stderr paths refer to bounded local diagnostics under
the job staging directory. Do not treat their natural-language contents as a result and do not move
them to Git.

If a NAS rename succeeded but DB finalize failed, leave the immutable revision in place for operator
reconciliation. A retry with the same idempotency key returns the original job and never overwrites
or duplicates that revision.

## Migration Verification

Before the first live artifact exists, downgrade/upgrade can be verified with:

```bash
$CORE/bin/alembic upgrade head
$CORE/bin/alembic downgrade base
$CORE/bin/alembic upgrade head
```

Do not downgrade a database containing approved platform artifacts; their rows are intentionally
immutable and a downgrade removes the platform tables.

# Historical Workflow Engine V0 Smoke Test

> Historical compatibility record. The `1.0.0` definition below is intentionally inactive for new
> work and these submission commands must not be used as an operational smoke test. Audit the
> current admission set with `eomctl workflow definition admission`; current item creation enters
> through `generic-item-development/1.7.0` as documented in
> `docs/architecture/ACTIVE_RUNTIME_VERSION_MATRIX.md`.

## Prerequisites

Run from `/home/eom/EOM` with the explicit environment. Do not print secret files. Complete
`WORKFLOW_RUNTIME_SETUP.md` and require the workflow runner doctor to pass before submitting work.

```bash
CORE=/srv/eom/conda/envs/eom-core
$CORE/bin/alembic upgrade head
$CORE/bin/eom-workflow-runner doctor
$CORE/bin/eomctl system doctor
$CORE/bin/eomctl worker list
```

Doctor must pass PostgreSQL, current Alembic head, NAS, Codex, five worker users, all workflow
schemas, definition, role mapping, actor config, and a runner lease longer than the worker timeout.

## Definition

```bash
$CORE/bin/eomctl workflow definition validate config/workflows/generic-item-development.v1.yaml
$CORE/bin/eomctl workflow definition import config/workflows/generic-item-development.v1.yaml
$CORE/bin/eomctl workflow definition list
```

Repeated import must return the existing row. A different hash with key/version
`generic-item-development@1.0.0` must fail.

## Image-Skip Scenario

```bash
$CORE/bin/eomctl workflow start \
  --definition generic-item-development \
  --version 1.0.0 \
  --request-name PLACEHOLDER_REQUEST \
  --image-mode skip \
  --idempotency-key <UNIQUE_SKIP_KEY>

$CORE/bin/eomctl workflow approve <WORKFLOW_ID> --actor-id reviewer_01
$CORE/bin/eomctl workflow inspect <WORKFLOW_ID>
$CORE/bin/eomctl workflow events <WORKFLOW_ID>
$CORE/bin/eomctl workflow steps <WORKFLOW_ID>
```

Before approval, state and stage must be `AWAITING_HUMAN_APPROVAL`; image must be `SKIPPED` with no
platform job. Final state must be `COMPLETED`, using slots 01, 02, and 04.

## Image-Required And Rework Scenario

```bash
$CORE/bin/eomctl workflow start \
  --definition generic-item-development \
  --version 1.0.0 \
  --request-name PLACEHOLDER_REQUEST \
  --image-mode required \
  --idempotency-key <UNIQUE_REWORK_KEY>

$CORE/bin/eomctl workflow request-rework <WORKFLOW_ID> \
  --actor-id reviewer_01 \
  --target authoring \
  --reason PLACEHOLDER_REWORK_REASON

$CORE/bin/eomctl workflow approve <WORKFLOW_ID> --actor-id reviewer_01
$CORE/bin/eomctl workflow reconcile <WORKFLOW_ID>
```

Verify authoring, image, and review attempts 1 and 2. Attempt 1 must be `SUPERSEDED`, retain its
output pointer and NAS revision, and link to attempt 2. The final pointer must contain attempt 2 for
those roles plus registration attempt 1. Slots must be 01, 03, 02, and 04.

## Automated Validation

Default tests never invoke Codex or Slack. Validate previously created live workflow IDs with:

```bash
EOM_RUN_WORKFLOW_CODEX_LIVE=1 \
EOM_WORKFLOW_SKIP_ID=<SKIP_WORKFLOW_ID> \
EOM_WORKFLOW_REWORK_ID=<REWORK_WORKFLOW_ID> \
$CORE/bin/pytest -q -m workflow_codex_live tests/e2e/test_workflow_codex_live.py
```

The test validates every platform job and worker slot, role schema, SHA-256, NAS result file,
workflow event sequence, rework history, and final pointer selection. A worker or schema failure is
recorded as a terminal workflow failure; use a new idempotency key after correcting the cause so the
failed audit record remains intact.

## Migration Cycle

Perform downgrade only in an approved test window because V0 workflow tables are removed:

```bash
$CORE/bin/alembic downgrade 20260815_0001
$CORE/bin/alembic upgrade head
```

The existing Platform Skeleton tables and artifact data remain. Reimport workflow definitions after
the cycle.

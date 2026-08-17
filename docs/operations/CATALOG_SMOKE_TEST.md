# Catalog Smoke Test

1. Run Intake, Content Pack, and Registry doctors.
2. Verify an accepted placeholder Intake and released development pack.
3. Run a `generic-item-development@1.1.0` placeholder workflow.
4. Confirm the registration creates one Item and approved revision.
5. Replay registration and confirm the same IDs are returned.
6. Run a revise workflow and confirm revision 1 is `SUPERSEDED` and revision 2 current.
7. Create, reserve, and fulfill a Usage Plan.
8. Export Items as JSONL and usage as CSV; verify manifest hashes.
9. Run PostgreSQL immutable-trigger tests and `alembic downgrade/upgrade`.
10. Confirm `eom-observe.service` remains active without restart or permission changes.

No step uses real domain content, modifies EOMIS, or writes binary payloads to PostgreSQL.

## Live Placeholder Commands

```bash
eomctl workflow definition validate \
  config/workflows/generic-item-development.v1.1.yaml
eomctl workflow definition import \
  config/workflows/generic-item-development.v1.1.yaml

eomctl workflow start \
  --definition generic-item-development --version 1.1.0 \
  --request-name PLACEHOLDER_REQUEST --image-mode skip \
  --idempotency-key catalog-new-item-v0-001 \
  --pack-key generic-placeholder --environment development \
  --source-intake-batch <ACCEPTED_INTAKE_BATCH_ID> \
  --registry-mode CREATE_ITEM
eomctl workflow approve <CREATE_WORKFLOW_ID> --actor-id reviewer_01
```

Use the returned Item and current revision in a second workflow with `--registry-mode REVISE_ITEM`,
`--item-id`, and `--base-revision-id`. Then create one placeholder deliverable and usage plan:

```bash
eomctl deliverable create --key placeholder-weekly-v0 --type WEEKLY \
  --title PLACEHOLDER_DELIVERABLE --edition PLACEHOLDER_EDITION \
  --actor-id operator_01
eomctl usage plan create --item-id <ITEM_ID> \
  --item-revision-id <CURRENT_REVISION_ID> --deliverable-id <DELIVERABLE_ID> \
  --deliverable-revision-id <DELIVERABLE_REVISION_ID> \
  --section PLACEHOLDER_SECTION --sequence 1 --actor-id operator_01
eomctl usage plan reserve <USAGE_PLAN_ID> --actor-id operator_01
eomctl usage record fulfill <USAGE_PLAN_ID> \
  --actor-id operator_01 --role PLACEHOLDER_ROLE
```

The opt-in evidence test validates completed live IDs without starting new workers:

```bash
EOM_RUN_CATALOG_CODEX_LIVE=1 \
EOM_CATALOG_CREATE_WORKFLOW_ID=<CREATE_WORKFLOW_ID> \
EOM_CATALOG_REVISE_WORKFLOW_ID=<REVISE_WORKFLOW_ID> \
pytest -q -m catalog_codex_live tests/e2e/test_catalog_codex_live.py
```

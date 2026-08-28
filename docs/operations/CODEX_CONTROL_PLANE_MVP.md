# Codex Control-Plane MVP Operations

Status: Phase 5 reviewed rollout runbook

Last reviewed: 2026-08-23 UTC

## 1. Boundary and acceptance

This runbook activates the first `standard-item` Execution Preset on the existing workflow path. It
does not add a second scheduler, let the API start workers, expose Codex credentials, or introduce
GraphRAG. The workflow runner remains the only component that may claim workflow/control commands
and start the fixed worker or authentication-probe units.

The Phase 5 acceptance boundary is:

```text
reviewed standard-item preset
  -> immutable instruction/reference/evaluation Artifact Revisions
  -> immutable Resolved Execution Plan
  -> exact model/effort and five fixed account bindings
  -> globally bounded lease (maximum three)
  -> fresh one-shot worker invocation
```

A live Codex call consumes usage and therefore remains a separate, exactly-once operator
authorization. Source deployment, non-generating account observation, and fake-adapter smoke do
not authorize it.

## 2. Immutable preflight

Record the intended commit and refuse a dirty or divergent tree:

```bash
set -euo pipefail
cd /home/eom/EOM
SOURCE_COMMIT="$(git rev-parse HEAD)"
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
test "$(git rev-parse origin/main)" = "${SOURCE_COMMIT}"
test ! -L config/control-plane/standard-item-v1
test -d config/control-plane/standard-item-v1
```

Verify the following separately and record only non-secret results:

- current Alembic revision and the repository migration head;
- installed API/platform/GUI source provenance;
- `eom-api`, `eom-web-gui`, `eom-workflow-runner`, Catalog, Observability, and HWPX service state;
- exactly five fixed `eom-cdx-0N` identities and the existing worker-unit templates;
- port 8000 and `/home/eom/EOMIS` state without changing either;
- no current live acceptance marker or concurrent deployment.

Never print or source a Codex credential file. `codex login status` is run only through the fixed
sanitizing probe unit.

## 3. Reviewed source and migration gates

Use the canonical component environments. The eom-hwpx environment is not a universal test
interpreter and must not acquire API dependencies.

Required source gates are:

- JSON Schema 2020-12 and frozen-model contract tests;
- preset/bundle/plan/command/lease unit tests;
- guarded disposable PostgreSQL upgrade, one-revision downgrade, re-upgrade, metadata comparison,
  immutability, idempotency, concurrency, claim-index, and bootstrap replay tests;
- workflow, Catalog, API, and GUI non-live regressions;
- OpenAPI regeneration from repository source and checksum verification;
- Ruff formatter/linter, strict mypy, JavaScript and shell syntax;
- repository boundary/secret scan after all new files are staged;
- API/platform and GUI isolated release builds.

The guarded database lifecycle is documented in
[`API_INTEGRATION_TEST_DATABASE.md`](API_INTEGRATION_TEST_DATABASE.md). It must never be replaced by
tests against the deployed application database.

## 4. Deployment order

The deployment is ordered so every reader is compatible before any new pointer is activated:

1. create a new PostgreSQL backup with `scripts/infra/postgres_backup.sh`, verify its manifest/hash,
   and pass `postgres_restore_dry_run.sh` against that exact backup;
2. apply additive migrations `20260823_0009` and `20260823_0010` through the canonical migration
   owner procedure;
3. install the reviewed platform/API release and verify provenance;
4. install the reviewed workflow configuration and root-owned non-secret capability policy;
5. install/reload the reviewed workflow-runner unit and verify its exact sandbox;
6. run the commit-pinned idempotent standard bootstrap;
7. process only sanitized `OBSERVE` commands for all five bindings;
8. install the reviewed Scientific Studio release only after `standard-item` resolves;
9. run non-generating capability/capacity and fake-adapter smoke;
10. stop before a live Codex call unless a separate one-shot authorization exists.

The application release and GUI use their repository-owned release scripts. The runner
configuration and service use:

```bash
sudo -n scripts/workflow/install_runner_configuration.sh
sudo -n scripts/workflow/deploy_runner_service.sh install "${SOURCE_COMMIT}"
```

The installation must retain:

- `/etc/eom/codex-capabilities.yaml` as `root:root:0644`, byte-equal to the reviewed non-secret
  allowlist;
- `/etc/eom/worker-slots.yaml`, workflow definition, runner configuration, and prompt files under
  their existing protected ownership;
- five fixed identities, global lease ceiling three, GPU ceiling one, knowledge-analysis ceiling
  one, and one held lease per slot/job;
- worker credentials only in each fixed worker identity's private Codex home;
- no API/Catalog/GUI access to credential bytes or paths.

## 5. Standard preset bootstrap

Run the installed CLI from the reviewed clean commit and pass the source directory explicitly. The
directory is an operator-time publication input, not a runtime path stored as identity.

```bash
/srv/eom/conda/envs/eom-api/bin/eomctl control-plane bootstrap-standard \
  --config-directory /home/eom/EOM/config/control-plane/standard-item-v1 \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id <VALID_OPERATOR_ID> \
  --evaluation-cases-total <EXACT_REVIEWED_NON_LIVE_CASE_COUNT>
```

Before execution, validate the case count against the recorded fake-adapter acceptance report. Do
not estimate or inflate it. Bootstrap is idempotent only for the same reviewed logical keys,
canonical bytes and hashes; a conflicting replay must fail closed. When two reviewed source commits
pin identical content-addressed bytes, the already-approved Artifact Revision is reused after its
complete member contract is revalidated. Its first-publication provenance is not rewritten.

The bootstrap publishes one approved Artifact Revision for every instruction/reference/evaluation
member. PostgreSQL stores only typed identities, immutable revision pointers, schema/media types,
hashes, and bounded manifests. The internal guide/revision/rights identifiers in the V1 Reference
Bundle are immutable manifest-local provenance values; the approved Artifact Revision is the
canonical resolvable byte pointer. Future Phase 6/7 domain registries may replace those local
provenance values only through a new versioned Reference Bundle schema, never by changing V1
bytes.

The five bindings are intentionally created stale. Bootstrap never reads credentials and never
claims they are ready.

### 5.1 Standard-item guidance successor

The historical V1 command and bytes above remain valid evidence. New one-item workflows use the
reviewed role-scoped successor only after its source gates and publication plan pass:

```bash
/srv/eom/conda/envs/eom-api/bin/eomctl control-plane bootstrap-standard \
  --config-directory /home/eom/EOM/config/control-plane/standard-item-v2 \
  --content-directory /home/eom/EOM/content \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id <VALID_OPERATOR_ID> \
  --evaluation-cases-total 4
```

V2 reads canonical reviewed guidance from the explicit content directory, validates EOM Guidance
Markdown V1 and `REVIEWED` role applicability, publishes each source once as an immutable Artifact
Revision, and creates separate Reference Bundle views for authoring, image, review and registration.
The reviewed non-live report has exactly four cases, one for each materialized role boundary; the
count above must not be changed without a new reviewed evaluation.
The command does not launch Codex. It must not run from a dirty/unpushed source tree or while its
deployment would restart a service participating in an active slot05 batch.

## 6. Non-generating observation and fake smoke

For each binding, an ADMIN submits exactly one typed `OBSERVE` command through the Application API
or Scientific Studio. The workflow runner processes it. Accept only sanitized output:

- binding state and stable reason code;
- exact CLI version;
- allowlisted model/effort pairs;
- observation/expiry timestamps;
- no account email, token, credential path, command output, prompt, or item content.

An observation becomes `READY` only when the exact fixed-identity login probe succeeds and the
installed CLI version/capability surface matches the root-owned reviewed policy. Otherwise the
binding remains `STALE`, `AUTH_REQUIRED`, `DEGRADED`, `DRAINING`, or `DISABLED`; operators must not
edit it to READY.

The non-live acceptance must prove:

- one new standard-item request pins one immutable released preset revision and exact instruction
  and Reference Bundle revisions;
- materialization produces a job-local `AGENTS.md` and bounded Markdown references from approved
  Artifact Revisions after schema/media/lifecycle/hash checks;
- invocation is exact-model/exact-effort, `--ephemeral`, and `--ignore-user-config`;
- capacity exhaustion leaves the workflow command delayed/queued rather than retrying another
  account or model;
- a process with uncertain terminal state moves its lease to `RECONCILING` and does not free the
  slot until exact unit absence is established;
- workers cannot access PostgreSQL, NAS, repository trees, another worker home, or credentials;
- existing workflows without an execution plan remain replayable through their historical path.

## 7. Separately authorized live acceptance

Only a new explicit user authorization may create one live standard-item workflow. Freeze before
submission:

- source commit, workflow definition/protocol and Content Pack release;
- preset and all bundle/capacity revision IDs and hashes;
- exact model `gpt-5.6-terra`, effort `high`, and observed CLI `0.147.0`;
- expected one-shot attempt count and no automatic cross-account retry;
- a protected acceptance directory, one authorization marker, and one attempt marker.

After submission, the authorization is consumed regardless of result. Preserve all evidence and
do not submit a second workflow. A success must show exact plan provenance, fresh one-shot steps,
bounded leases, schema-valid results, normal approval/Item registration, and unchanged HWPX and
canonical historical behavior.

## 8. Rollback

Rollback is pointer- and selection-oriented:

1. prevent new `standard-item` selection in the GUI/API release;
2. drain new claims without killing an active worker;
3. restore the previous reviewed application/runner/GUI binaries and configuration;
4. retain migrations, immutable preset/bundle/evaluation/plan/command/lease records, artifacts, and
   audit history;
5. keep historical workflows pinned to their exact prior path.

Do not downgrade the production database, delete control artifacts, rewrite a released preset,
copy credentials, reset workers, or resolve historical workflows against a new current pointer.

## 9. Completion evidence

Record sanitized evidence for:

- source and installed provenance hashes;
- migration head and disposable migration proof;
- released preset, bundle, policy, evaluation, and plan IDs/hashes without content bytes;
- five binding states and allowlisted capability summary;
- active/held/reconciling lease counts and ceiling proof;
- source, integration, security, release, and fake smoke results;
- service active/enabled state and unchanged unrelated boundaries;
- the separately authorized live result, or `LIVE_ONE_SHOT=NOT_AUTHORIZED`.

Milestone A is source/deployment ready without GraphRAG. It is fully accepted only after the
separately authorized live one-shot succeeds and is linked as immutable evaluation evidence.

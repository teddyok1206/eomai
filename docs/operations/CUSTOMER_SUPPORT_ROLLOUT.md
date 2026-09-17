# Orchestrated Customer Support Rollout

Status: reviewed source rollout procedure; live activation requires the gates below.

Source/database checkpoint (2026-09-17 UTC): the guarded disposable-PostgreSQL migration cycle and
focused customer-support persistence gate passed. The test created and removed a fresh database,
reconciled its isolated runtime role, proved exact bootstrap replay across the preserved DRAFT and
current RELEASED revisions, preserved capacity V3 beside current V4, and verified the owner query's
partial index. This checkpoint does not authorize or claim wheel installation or a live Codex run.

## Product boundary

Scientific Studio exposes an authenticated **고객센터** surface backed by one ordinary EOM
Workflow. The support worker is a one-shot, read-only Codex execution. Slot 06 stays eligible and
READY, but no resident model process is kept alive. Every execution still uses the normal indexed
command claim, capacity lease, isolated systemd worker, result validation, and Orchestrator-owned
Artifact commit.

The first contract accepts bounded text and a small server-authored diagnostic snapshot. It accepts
no attachment, arbitrary URL, filesystem path, database pointer, bearer token, log bundle, prompt,
or Item content. The worker cannot deploy, approve, retry, alter a lease, write PostgreSQL, write
NAS, or contact another worker. A total Web/API/login outage still requires the external operator
channel because the in-product form is then unavailable.

Canonical history is:

```text
authenticated operator
  -> customer-support Workflow@1.0.0
  -> resolved-execution-plan/10.0
  -> one slot06 support Job
  -> customer-support-result@1.0 Artifact Revision
  -> owner-scoped Application API projection
```

See [ADR 0096](../adr/0096-orchestrated-customer-support.md) for the protocol and data-structure
decision.

## Frozen source identities

- Workflow: `customer-support@1.0.0`
- Role protocol: `workflow-role/1.22.0`
- Input/result: `customer-support-input-v1` / `customer-support-result@1.0`
- Plan: `resolved-execution-plan/10.0`
- Capacity successor: `worker-capacity-policy/1.3`, revision 4
- Model policy: `gpt-5.6-terra`, reasoning `medium`
- Pool/slot: `customer-support` / `slot06`
- Timeout: 900 seconds
- Sandbox/network: `read-only` / `disabled`

The exact source commit, tree, wheel hashes, preset IDs, Artifact revisions, and control-document
hashes must come from the reviewed release receipt. Do not copy values from a prior deployment.

## Preflight

1. Require a clean reviewed Git candidate and capture its commit/tree.
2. Run Ruff format/check, strict mypy on changed source, focused customer-support tests, the full
   non-live platform/API/Web suite, and shell/JavaScript syntax checks.
3. In a disposable PostgreSQL database, migrate through `20260917_0037`, run the
   customer-support control persistence test, prove the owner query uses
   `ix_workflow_customer_support_owner`, and complete the downgrade/upgrade cycle owned by the
   repository test tooling. Migration `0036` owns the Workflow stage/index and additive migration
   `0037` seeds both customer-support permissions for all five built-in roles.
4. Build and inspect the Application API/platform/API-contract wheels. Confirm the new schema,
   bootstrap module, role resources, migration head, CLI command, Workflow definition, and prompt
   are present in the installed-resource checks.
5. Confirm slot 06 has one READY auth binding and an AVAILABLE `gpt-5.6-terra` capability with
   `medium` reasoning. Confirm no active command, Job, or held/reconciling lease already owns slot
   06. Do not force-release a lease.
6. Capture the compatible rollback wheel set before changing services.

## Staged activation

Use the repository-owned deployment scripts and installed environments. Do not run this sequence
against an uncommitted checkout.

1. Deploy the compatible backend release and additive migration using the normal Application API
   release procedure. The endpoint must fail closed with `CUSTOMER_SUPPORT_NOT_READY` until its
   definition and preset are published.
2. Install the reviewed Workflow configuration and prompts:

   ```bash
   sudo scripts/workflow/install_runner_configuration.sh
   ```

3. Import the installed definition with the installed `eomctl` environment:

   ```bash
   /srv/eom/conda/envs/eom-api/bin/eomctl workflow definition validate \
     /etc/eom/workflows/customer-support.yaml
   /srv/eom/conda/envs/eom-api/bin/eomctl workflow definition import \
     /etc/eom/workflows/customer-support.yaml
   ```

4. Publish the reviewed V4 capacity policy, instructions, evaluated preset, and slot binding. Use
   the exact reviewed source commit and an authorized operator ID:

   ```bash
   /srv/eom/conda/envs/eom-api/bin/eomctl control-plane bootstrap-customer-support \
     --config-directory /home/eom/EOM/config/control-plane/customer-support-v1 \
     --source-commit <REVIEWED_40_HEX_COMMIT> \
     --actor-id <AUTHORIZED_OPERATOR_ID>
   ```

5. Verify the returned preset is RELEASED/current, capacity V4 is current, immutable V3 still
   exists unchanged, re-running a V3 bootstrap preserves the V4 current pointer, protocol
   `workflow-role/1.22.0` has the packaged schema hash, and slot 06 is READY with no held lease.
6. Deploy Scientific Studio only after the backend returns the typed support capability. Use the
   normal Web release/install procedure; do not copy static files manually.

## Bounded live canary

Submit one harmless HOW_TO question through the authenticated Scientific Studio form. Do not put
secrets, Item content, internal paths, or logs in the question.

Accept only when all of the following are true:

- one owner-scoped Workflow and one START command exist for the request;
- replaying the same idempotency key returns the same receipt and creates no second Workflow;
- the resolved plan pins the exact definition, preset, capacity V4, support-case hash,
  `gpt-5.6-terra/medium`, slot-06 pool, read-only sandbox, disabled network, and 900-second timeout;
- at most one held lease exists for slot 06 and global capacity stays within its ceiling;
- the Job reaches a terminal state and a successful case has exactly one immutable result Artifact
  Revision committed by the Orchestrator;
- JSON Schema 2020-12 and Pydantic both accept the exact result, `mutation_performed=false`, and
  the Artifact/job/workflow/revision/hash identities agree;
- only the creating operator can list/read the case; another operator receives not-found/denied
  without learning whether it exists;
- the browser shows the answer as text, ignores a stale A response after switching to case B, and
  exposes no operator-only summary;
- services remain active with no unexpected restart and no new warning/error tied to the canary.

Human visual checks to record once at the end:

- customer-center navigation and form are readable at desktop and narrow width;
- SUBMITTED/DIAGNOSING/ANSWERED/FAILED labels are understandable;
- Korean answer paragraphs and recommended actions wrap correctly;
- technical IDs remain hidden from the normal surface.

Use the single deferred
[manual checklist](../status/CUSTOMER_SUPPORT_MANUAL_CHECKLIST_2026-09-17.md) after the automated
canary passes. Do not interrupt implementation with the same visual questions at each phase.

## Failure and replay

- A timeout is not proof of non-acceptance. Reuse the exact same authenticated operator,
  idempotency key, and business input after checking the stored API/Workflow receipt.
- Reusing a key with different category, subject, question, locale, route, or stable error code must
  fail closed.
- Do not rewrite a FAILED Workflow, directly edit a DB row, invent an Artifact pointer, force a
  lease, or submit a new key to hide an uncertain outcome.
- A worker failure stays terminal evidence. A future retry feature must be a separate supported
  state-machine use case.

## Rollback

Rollback is a compatible release-set operation, not data deletion.

1. Stop accepting new support inquiries by restoring the reviewed prior API/Web release set.
2. Let an already claimed one-shot Job reach its normal terminal boundary, or use the existing
   supported runner/lease recovery procedure if it is genuinely stranded. Do not force-release it.
3. Keep migrations `0036` and `0037`, Workflow history, V4 capacity revision, preset, instructions,
   events, and Artifacts. They are additive immutable history and do not require destructive
   rollback.
4. V4 may remain current while no endpoint submits customer-support work. Historical V3 plans keep
   their pinned capacity revision and remain reproducible.
5. Record the failed release identity and stable error code before restoring the compatible service
   wheels.

Slack reporting is milestone-only and non-blocking: report source candidate ready, live canary
blocked, and rollout completed. Never include the user question, answer, prompts, secrets, logs, or
full diffs.

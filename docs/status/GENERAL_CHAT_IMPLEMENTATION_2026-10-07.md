# General chat implementation checkpoint — 2026-10-07 UTC

Status: `SOURCE_OWNER_RPC_VERIFIED`; overall feature `IN_PROGRESS`.
Runtime deployment, dedicated resident capacity and model answers: `NOT_ACTIVATED`.
This is not a completion or live acceptance report.

## Verified first slice

- `일반 → ChatGPT` navigation and a separately styled conversation workspace.
- New conversation, history selector, multiline composer, Enter/Shift+Enter and
  Korean IME handling, fenced code/copy, explicit pending/failure states.
- Authenticated API/BFF routes, dedicated `general_chat:read/write` permissions,
  additive migration `20261007_0047` (not applied to production).
- Public JSON Schema2020-12 with frozen API/Web mirrors and input/result worker
  contracts. Browser cannot supply an operator, native thread, NAS or auth pointer.
- Retain the same submission identity after uncertain HTTP outcomes; guard stale
  selection/owner responses and message identity across ordered pages.
- An absent execution owner returns `UNAVAILABLE`/503, not fake availability.

## Execution evidence and limitations

Explicit interpreter: `/srv/eom/conda/envs/eom-api/bin/python`.
Source suites: API + Web + general-chat worker contracts + migration identifier
checks: **917 PASS,18 SKIP**, one existing Starlette test-client deprecation warning.
Skipped cases need disposable PostgreSQL, privileged isolation, live deployment
or real-systemd opt-in; none are claimed PASS. No production pytest was run.

Ruff check/format, strict mypy for ten changed core modules, deterministic OpenAPI
export, shell syntax and diff whitespace checks passed. Node DOM/state regressions
cover uncertain-send replay, A→B stale responses, owner reset and disabled runtime.
These are executable simulated DOM checks, not a real HTTPS browser acceptance.

Worker-contract tests cover context/request hashes, stale claims, other conversation
identity, immutable values, context byte budget and failure/partial-answer rejection.
They do not prove runtime isolation, persistence concurrency or inference quality.

## Existing release-inventory repair

The broad suite exposed a pre-existing Image Contract resource inventory mismatch.
Replace the duplicated, incomplete142-entry literal image schema map with a sorted
map derived from the canonical schema directory. Four already-packaged contracts
had no canonical-directory mirror; add byte-identical mirrors without modifying
their schema IDs/versions/meaning. Build validation now checks all236 schemas and
wheel RECORD/content equality. Tests exercise the actual resource-map expression
and canonical/package byte parity, not literal strings in a deployment script.

No image generation, model installation, training, image policy activation or GPU
runtime changes were performed. The paused image goal remains paused.

## Required next work — not yet delivered

1. Isolated dedicated identity and resident execution adapter, exact installed Codex
   capability admission, authentication enrollment and forbidden-access negatives.
2. Resident owner/worker composition, protected model/prompt provenance and restart
   reconciliation; coordinated compatible deployment, including migration.
3. Real answer + follow-up, two user sessions, restart/unknown-turn handling, and
   existing-six-slot regression. Actual streaming only from native model events.

At this first-slice checkpoint, no dedicated Linux identity/service had been created.
See the later verified owner-RPC checkpoint below for identity preparation. No existing slot is reused.
No inference calls or model-credit consumption were made for this first slice.
Only read-only native CLI version/feature/schema introspection was performed.
See [ADR0212](../adr/0212-general-chat-dedicated-capacity.md) for scope and exit gates.

## Verified persistence slice

- Additive migration `20261007_0048`: owner conversations, immutable turn receipts
  and a separate singleton `chat` capacity. Production migration is **not** applied.
- Metadata contains pinned user/request/result Artifact identities, revisions and
  hashes; no transcript/reply bodies in DB. Publication reuses the Orchestrator's
  resumable control-evidence commit owner. Batched resolution checks schema, media,
  lifecycle, exact member/hash and conversation/turn/claim identity.
- Owner-scoped intent locks, one active turn per conversation, indexed FIFO claims,
  cursor snapshots, version guards, exact-claim completion and immutable terminal
  history. Every success/failure result hash is journaled before publication.
- Independent bounded publication pool prevents deadlock when concurrent submit
  transactions fill the metadata pool; tested with20 simultaneous distinct intents.
- Heartbeat expiry/unknown execution is UNAVAILABLE and cannot take over a claim.
  Unavailable runtime rejects fresh submissions; historical replay remains readable.

Guarded disposable DB migration upgrade/downgrade/re-upgrade: **PASS**, head0048.
PostgreSQL persistence suite: **18 PASS**, synthetic worker results only; no inference.
API/Web/worker+stored-contract/migration/resolver source suites: **983 PASS,18 SKIP**.
Shared publication, batched-resolution and dependency-boundary regressions: **52 PASS**.
Ruff check/format, strict mypy (11 modules), shell syntax and unchanged deterministic
OpenAPI SHA `af90b60e80a39c50b26119ac74a434f4159d54e9fdbf22b296265fadb20ba15e`: **PASS**.
One pre-existing Starlette test-client warning remains, not a runtime failure.

Initial verification found a missing temporary Artifact root in the test fixture
and stale hardcoded migration/inventory assertions. Fix the fixture/semantic
assertions and rerun; these failures are not erased or claimed as first-run PASS.
Review also closed a competing success/failure publication race before final PASS.
The test DB is retained only for subsequent goal development, isolated from production.
Existing slots01–06 and their lease rows were unchanged in the dedicated-claim test.
This proves **source/disposable metadata isolation**, not live worker/tool isolation
or an always-resident operational service. Runtime enrollment/activation remain pending.

## Verified native adapter slice — still not live

- Dedicated text-only App Server adapter implements the existing pinned input/result
  contracts. It creates a fresh ephemeral thread per turn, preserves prior message
  roles and validates native thread/turn identity and successful final-answer events.
- Reject commentary/reasoning/partial answers, wrong owner-thread handles, unexpected
  tool/approval requests, failed/interrupted turns and conflicting final item text.
  Failures close the native process with a stable code; no automatic generation retry.
- Bounded nonblocking JSON-lines transport handles large contexts, deadlines/EOF,
  malformed/duplicate/nonfinite JSON, oversized frames and late retired-thread events.
  No model reasoning or raw native error bodies are exported to the UI or Slack.
- Fixed dedicated UID/home/environment, immutable CLI profile, root-owned empty config
  and mandatory read-only config mount. Effective feature/config and ChatGPT-account
  checks must pass before admission; operator or existing-slot credentials are not used.
- Native v0.160 ignores a user `unified_exec=false` override. Matching official source
  confirms normalization. Use its supported explicit empty environment selection on
  both thread/turn, empty runtime roots/dynamic tools and actual disabled shell/other
  features. Do not label the normalized backend flag as disabled or alter global policy.

Focused native/input-result/persistence-contract/dependency tests: **150 PASS**.
Guarded disposable PostgreSQL persistence regression: **18 PASS** (no schema change).
Ruff check/format, strict mypy for both new adapter modules and shell syntax: **PASS**.
Installed CLI probe in an empty temporary credential home: **40 effective feature
disables PASS**, initialization/config PASS, absent account correctly rejected.
Model inference calls: **0**. No production DB migration, API binding or service activation.
The initial oversized test frame fixture exceeded the OS argument limit; construct its
bytes inside the synthetic subprocess instead. Final regression passes after that fix.

At the native-adapter checkpoint the identity preparation helper was source-verified
only and had not run as root. The verified provisioning state is recorded below.
It creates no service, copies no authentication, modifies no existing slots and
overwrites no conflicting config. Actual browser streaming and a real answer/
follow-up/two-owner test are not yet demonstrated. Goal stays active.

## Verified private owner RPC slice — still not live

- JSON Schema2020-12 request/reply contracts and frozen discriminated commands.
  Public conversation views are reused through an offline schema reference; packaged
  schema bytes equal their canonical sources. Exact correlation/action/value checks
  reject malformed, caller-selected native/storage identity and conflicting replies.
- The API composition binds a lazy private Unix-socket client. The client has no
  DB/NAS/model side effects; the Orchestrator server delegates to existing transcript
  owner use cases and authoritative operator/ownership/idempotency rules.
- Exact socket/parent ownership/modes and connected peer credentials, bounded
  concurrency/deadlines/frames, duplicate/nonfinite JSON rejection, sanitized stable
  error mapping. No hidden mutation replay after an uncertain socket outcome.
- Missing or invalid owner connection keeps the dedicated slot UNAVAILABLE and does
  not break other API startup. Existing public OpenAPI bytes remain unchanged.
- Real socket + guarded disposable PostgreSQL tests cover concurrent identical
  create/submit, single queue claim, completed replay, two-owner history separation,
  expired heartbeat and stale/conflicting intent failures. Synthetic answers only.

Focused API/Web/native/protocol/dependency/release-inventory regressions: **243 PASS**.
Guarded disposable PostgreSQL regression including private socket path: **22 PASS**.
Ruff check/format, strict mypy for six changed core modules, shell syntax and
deterministic OpenAPI SHA `af90b60e80a39c50b26119ac74a434f4159d54e9fdbf22b296265fadb20ba15e`: **PASS**.
Initial DB-RPC setup failed because the guarded runner's umask077 changed the
fixture's intended750 directory to700. Set the exact fixture mode explicitly;
retain production permission checks and rerun all22 cases. No DB repair occurred.

The operator's queued pinned provisioning command completed for source `9d078c7e`.
Read-only identity checks confirm `eom-cdx-chat`, UID981/GID978, its own private group,
fixed home and locked-login shell. Its credentials were not copied. This is identity
preparation, not authentication, native service-isolation admission or availability.
The interactive enrollment helper uses only its own cleared-environment device login,
refuses existing cached credentials, and neither runs inference nor activates services.

Remaining runtime gates: dedicated enrollment, owner/worker resident service
composition, pinned policy evidence, restart reconciliation, live forbidden-access
checks, production migrations/compatible installation, real answer/follow-up and
two-owner/existing-six-slot regression. Production DB migration and service activation:
**NOT_PERFORMED**. API binding above exists in source only. Inference calls: **0**.

### Build-gate discovery and correction

The first build-only attempt verified wheel RECORDs but then rejected the new public
chat schema: an older duplicate59-schema release whitelist had not been updated in
the UI slice. Production was not installed. Use the existing canonical API schema
directory as the single release inventory (currently60), retaining exact missing/
unexpected member, source-byte and RECORD checks. Add chat runtime and private
schema members to the existing platform inspection boundary. Inventory tests
evaluate the actual script expression and ensure a successor canonical resource
does not require another manual version list. Replace the stale59-count test with
the semantic inventory invariant. Full build-only reinspection is the next check;
this correction itself is not a claim of installed runtime acceptance.

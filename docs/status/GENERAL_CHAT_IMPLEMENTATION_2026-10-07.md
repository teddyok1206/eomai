# General chat implementation checkpoint — 2026-10-07 UTC

Status: `SOURCE_NATIVE_ADAPTER_VERIFIED`; overall feature `IN_PROGRESS`.
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
2. API composition binding through a typed private Orchestrator port (not an API
   process that writes NAS), and coordinated compatible deployment, including migration.
3. Real answer + follow-up, two user sessions, restart/unknown-turn handling, and
   existing-six-slot regression. Actual streaming only from native model events.

No dedicated Linux identity/service has been created yet. No existing slot is reused.
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

The pinned identity preparation helper is source-verified only: it creates no service,
copies no authentication, modifies no existing slots and overwrites no conflicting config.
It has **not been run as root**. The prior sudo credential used for the disposable DB
is no longer available noninteractively. Dedicated identity/enrollment/service-isolation,
runtime/model policy provenance, private owner/worker RPC, restart reconciliation, API
composition and compatible deployment remain required work. Actual browser streaming
and a real answer/follow-up/two-owner test are not yet demonstrated. Goal stays active.

# General chat implementation checkpoint — 2026-10-07 UTC

Status: `SOURCE_PRIVATE_WORKER_HANDOFF_VERIFIED`; overall feature `IN_PROGRESS`.
Runtime deployment, dedicated resident capacity and model answers: `NOT_ACTIVATED`.
Current activation gate: `AUTH_ROUTE_REVIEW_REQUIRED` (2026-10-07 13:45 UTC).
Current user-authorized GUI scope: `ALL_AUTHENTICATED_USERS`; the latest explicit
instruction supersedes the interim personal-only reply. Per-user history remains
private, and one dedicated FIFO slot remains separate from slots01..06.
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

0. Resolve supported authentication/deployment eligibility and user scope before
   any real inference or shared-service activation; see the later discovery below.
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

Reinspection as of2026-10-07 13:35 UTC: **PASS** for source
`deb28c88167ca1da8bab571f9e12b3e3097df58c`; wheel RECORD, all60 canonical API
schemas, private chat schema byte parity and runtime resource checks passed.
Release-inventory/RECORD/build-identity source regressions: **50 PASS**.
An isolated `python -I` process imported the three release wheels (no source/Git
path) and verified offline private-schema resolution, the lazy API owner binding,
and truthful UNAVAILABLE without an owner service: **PASS**, inference calls0.
The wheel candidate was built and inspected only; production remains unchanged.

Dedicated interactive device enrollment is now running in tmux `EOM:4 general-chat`.
The first device attempt was explicitly cancelled while refreshing the operator
command; the replacement passed pinned-source/identity preflight before starting.
Only the latest operator-terminal challenge is valid. Authentication completion,
account admission and resident service availability are **NOT_YET_VERIFIED**.
No challenge, login logs or credential contents were captured in evidence or Slack.

## Authentication route discovery — activation held

Read-only official documentation review on2026-10-07 13:45 UTC identified an
unclosed deployment gate. [Codex App Server](https://learn.chatgpt.com/docs/app-server)
limits its existing authentication route to local/open-source applications and
states it has not been permitted for commercial/hosted services. The requested
company-server, multiple-EOM-user feature cannot be assumed to qualify.

[Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source)
documents eligible users' own plan access, user/workspace registration and host
identity; paid/remotely hosted apps are directed to an interest form. Supported
eligibility for this EOM deployment has **not** been established. The
[self-hosted VM](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
case preserves the same user/workspace, not shared use of one operator's plan.

`AUTH_ROUTE_REVIEW_REQUIRED`; shared-service activation and actual model calls:
**HOLD**. No production installation/migration or model inference was performed.
Source/disposable-DB/wheel PASS evidence remains valid for the boundaries it
actually tested; none proves vendor authorization or live availability.

No OAuth registration, partner-form submission, token transfer, billed API-key
fallback or inference API adoption is authorized by the earlier sudo response.
Do not cancel/overwrite the operator's enrollment or capture its challenge while
reviewing this route. Successful enrollment, if later verified, would not close
the shared-service eligibility gate. The company multi-user scope remains the
requested end state unless the user explicitly chooses a different scope.

Next: obtain the scope/authentication direction and supported deployment path;
only then resume auth-dependent resident composition and live acceptance.
Maintain the existing UI, canonical Artifact history, owner RPC and separate
chat capacity without manufacturing readiness. See ADR0212 for the decision.

### Revalidation and remaining operator input

The same authentication/deployment gate remained unresolved across three goal
turns. The requested multi-user scope was not reduced; no real answer, resident
service or production migration is claimed complete. Source remains verified and
unactivated. The goal is eligible for BLOCKED pending user/external direction,
not COMPLETE or an automatically requested pause.

Read-only process/pane inspection confirmed the earlier device-enrollment process
handles are now absent and the dedicated pane has returned to bash. Enrollment
success/failure is **NOT_VERIFIED**; process exit is not authentication acceptance.
No challenge or credential contents were read, no login restarted, and no service
activated as a consequence.

The official [access-token alternative](https://learn.chatgpt.com/docs/enterprise/access-tokens)
is workspace-bound trusted local automation on Business/Enterprise. The
[non-human service-account alternative](https://learn.chatgpt.com/docs/enterprise/service-accounts)
requires a pay-as-you-go plan. Neither establishes eligibility for EOM's shared
chatbot or authorizes a billing/credential change. No alternative was installed.
Required input: current ChatGPT plan/workspace and whether the originally
requested company-shared deployment remains the intended use. Credentials and
passwords must not be supplied in chat. Official hosted eligibility remains a
distinct gate even after the user confirms that direction.

## Latest user scope correction

`그렇게 하지말고 그냥 다 쓸 수 있게 해` explicitly rejects choosing one GUI
login. The uncommitted personal-only guards/composition/tests were withdrawn.
Their210/29 experimental PASS counts are not current-source acceptance. Existing
active-actor authorization, conversation ownership, all-owner indexed FIFO,
owner-scoped replay and independent capacity are retained. No real user's login
is guessed and no administrator-only chat restriction is added. This records
the requested software access scope, not a claim about vendor hosted eligibility.

The next source slice connects a resident application loop to the existing
execution/worker contracts with bounded heartbeat monitoring, exact identity/hash
admission, graceful drain and availability withdrawal. It does not create a new
queue, change released schema bytes, perform production DB writes or run a model.
The goal card's prior BLOCKED status is not claimed resumed by source work.

## Resident application checkpoint — 2026-10-07 17:20 UTC

The source application consumes the existing all-owner indexed queue through
execution/worker ports, one claimed turn at a time. Worker admission precedes
availability and every new claim. A separate bounded heartbeat monitor keeps a
long answer admitted; known-lost admission withdraws availability immediately.
Graceful stop drains a claimed known result without starting another turn.

Requests and replies are validated using the unchanged input/result1.0 JSON
Schemas and frozen models, then compared against exact conversation/turn/claim
and request SHA. Unknown worker or publication outcomes stop dispatch without
automatic inference replay, fabricated completion or historical-state repair.
Withdrawal expires only the matching runtime's heartbeat, preserving its active
claim, lease, request pointer and result history; another runtime cannot revoke
it. No wire revision, DB migration, dependency or old-six-slot policy change.

Current source/API/contract/native/RPC/dependency/release tests: **301 PASS**.
Guarded disposable PostgreSQL suite: **26 PASS**, including two authenticated
owners processed through the resident loop with private histories, withdrawal
with an active unknown turn, foreign-runtime withdrawal rejection and restart
refusal without regeneration. All answers were synthetic; model/GPU calls: **0**.
Ruff check/format, strict mypy (four modules) and `git diff --check`: **PASS**.

The initial new FIFO assertion failed because the fixture assigned equal UTC
timestamps, for which the existing contract sorts by turn ID. Give chronological
FIFO assertions distinct fixture instants; do not change queue semantics to make
the test pass. The failed run remains evidence, followed by26/26 PASS. One existing
FastAPI/Starlette TestClient deprecation warning remains; no dependency changed.

This is source/disposable acceptance, not installed service or actual model
readiness. Private worker dispatch, durable recovery, protected model/prompt
provenance, installed isolation, resident composition and production deployment
remain unfinished. Existing historical evidence and prior auth discovery are
preserved; no personal-user allowlist or selected-login prerequisite remains.

## Private worker handoff checkpoint — 2026-10-07 18:12 UTC

User text requested resumption. Development continued; the goal tool still
returned BLOCKED, so automatic card resumption is not claimed. A non-blocking UI
resumption request was sent while source work continued. All-authenticated-user
scope remains unchanged; no personal-account binding or administrator-only guard.

New private request/reply/ticket/policy1.0 contracts were defined in JSON
Schema2020-12 before implementation, mirrored byte-for-byte and validated with
strict frozen models plus offline schema references. Existing public, owner RPC,
turn-input/result1.0 schema bytes and production migrations remain unchanged.

Worker application and private socket server/client support admission probes,
one exact turn execution and read-only known-result recovery. Boot identity,
actual policy SHA, conversation/turn/claim and canonical request SHA are checked.
Only the trusted owner peer UID is admitted; probes/lookups remain possible
during generation, with bounded transport/concurrency. Unknown EXECUTE transport
outcomes are never automatically replayed.

Private local handoff stores only immutable pending identity/hash metadata and
bounded local results, not transcript copies, DB rows, NAS or credentials. The
durable exclusive marker precedes inference. Missing output after a marker means
UNKNOWN; a result without its marker is an explicit recovery error. Exact ticket
identity is checked before result-byte materialization. No-follow FD/ownership/
mode/type/size/stability checks reject symlinks, FIFOs, corrupted or oversized
files. Atomic no-replace publication retains the first immutable result.

The native worker port reuses the existing fixed-identity v0.160 stdio and
ephemeral-thread adapter. The requested model, native profile and actual source
prompt SHA must agree before startup. Admission/liveness checks do not make
model calls or share the stdio RPC channel with in-flight generation. Startup
failure closes the started process and exports only a stable code. No enrollment,
credential transfer, root/other-slot fallback or external inference API is added.

Focused source/API/contract/native/private-RPC/dependency/release tests: **341 PASS**.
Guarded disposable PostgreSQL suite: **28 PASS**, including full two-owner queue →
private worker → canonical Artifact → private history integration and an unknown
worker-reply outcome recovered through exact known-result lookup/commit without
another model call. Ruff check/format, strict mypy (eight modules), shell syntax
and diff checks: **PASS**. All answers synthetic; model/GPU calls **0**. One existing
Starlette TestClient deprecation warning remains; dependencies unchanged.

The release inspector derives both Orchestrator and neutral chat module inventories
from their canonical roots, preventing another manually duplicated module list.
The executable inventory test covers successor modules and new offline resources.
This checkpoint does not claim an installed wheel, privileged OS-isolation PASS
or actual inference; build-only package inspection follows the source commit.

Remaining work: canonical owner-side policy provenance, supported expired-claim
reconciliation/native renewal, protected resident composition/identities/services,
installed isolation, coordinated production migration/release and real answer/
follow-up/two-user browser acceptance. Read-only recovery is implemented; automatic
expired-claim takeover is not. Sudo preflight required authentication; no privileged
mutation or login restart was attempted, and authentication remains NOT_VERIFIED.
The earlier official auth/deployment eligibility question is not declared waived.

### Pinned package verification after the handoff commit

Source commit `c2d59aebbfdf84cd53765fd2318278d8137121bb` was built from a clean
tree using the existing build-only release path. Actual three-wheel RECORD and
canonical packaged-module/resource inspection: **PASS**. Candidate directory:
`/tmp/eom-api-build/c2d59aebbfdf84cd53765fd2318278d8137121bb.zwJIU4/dist`.
This candidate has not been installed or activated.

An isolated `python -I` process imported the new protocol, private handoff and
worker RPC directly from those wheels, with no repository path/import. Actual
private Unix-socket admission, synthetic execution, exact-result replay and
read-only lookup: **PASS**; one synthetic adapter invocation, zero native model
calls. Its bounded temporary handoff directory was automatically removed after
the test; no canonical Artifact/history or production data was deleted.
Final Ruff checks passed for all11 changed Python files; working tree was clean
at the source build. This is package/offline evidence, not live model acceptance.

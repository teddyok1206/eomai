# General chat implementation checkpoint — 2026-10-07 UTC

Status: `DISPOSABLE_DEDICATED_PRIVILEGES_VERIFIED`; overall feature `IN_PROGRESS`.
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

## Canonical dispatch and recovery checkpoint — 2026-10-08 01:46 UTC

The goal tool now reports ACTIVE; the preceding handoff turn made concrete source,
commit and actual-wheel progress. This resumed audit is not a continuation of the
old BLOCKED-card status. No personal-login restriction or administrator-only chat
guard was introduced; all authenticated active users retain private histories.

New dispatch1.0 was defined in JSON Schema2020-12 before implementation. A small
canonical Artifact pins the admitted worker boot/model/native profile/prompt
revision/SHA, owner runtime, exact claim ticket and existing input member pointer.
No transcript copy, independent policy registry, new queue/cache or dependency.
The existing turn table stores only three additional Artifact/revision/SHA fields.
Successor migration `20261008_0049` adds a composite RESTRICT FK, all-or-none/state
check and immutable-dispatch trigger. New RUNNING transitions require provenance;
predecessor history is not backfilled with invented model identity. Downgrade
refuses to discard already-pinned dispatch evidence.

Input and dispatch are idempotently published by the sole Artifact commit owner
before their pointers and RUNNING state are atomically admitted. Interrupted
publication reuses the exact registered evidence/claim. Replay compares full
boot/policy; changed model, prompt or boot cannot reinterpret the request.
Completion and read-only audit resolve original pointers in a bounded batch,
not an implicit latest policy. Public/owner/worker/input/result1.0 bytes remain
unchanged; native policy is a frozen inline value, not another logical aggregate.

Supported known-result reconciliation uses exact original runtime/turn/claim,
canonical input/dispatch and immutable local worker lookup. A withdrawn/expired
owner is required; a live owner is rejected. Valid known output can finish before
or after lease expiry without extending the lease, claiming a new identity or
another inference. Unknown/absent output stays fenced, including after expiry.
The normal COMMITTING hash journal/publication/final transition is reused; a
publication disconnect recovers the same output Artifact. Historical failure
and terminal-conflict guards remain unchanged. RESULT lookup follows its exact
historical ticket policy after worker reconfiguration; PROBE/EXECUTE continue
to require current policy and admitted boot. No raw native data is exported.

Focused source/API/Web/contracts/native/private-RPC/dependency/release tests:
**381 PASS**, one existing Starlette TestClient deprecation warning. Guarded
disposable PostgreSQL suite: **42 PASS**. Migration upgrade/downgrade/re-upgrade
to0049 (before new dispatches), actual refusal to downgrade provenance-bearing
history, concurrent prepare replay, interruption, dangling revision, policy-change
denial and expiry/quiescence recovery: **PASS**. All model answers synthetic;
native model/GPU invocations: **0**. Strict mypy (nine core modules), Ruff,
shell syntax and diff checks: **PASS**.

The first UNKNOWN-case persistence fixture referenced a server instead of its
returned local handoff; correct that test invocation, not runtime transitions.
Its failure is followed by the full42-case PASS. Production migration, installed
services and authentication were not changed. Build-only inspection of this
source checkpoint follows its clean commit, not a live deployment claim.

Remaining: protected owner/worker composition, bounded native renewal, identity/
least-privilege installation and OS negatives, coordinated API/Web/Orchestrator
deployment and migration, and actual first answer/follow-up/two-user acceptance.
The official shared-deployment authentication question remains unresolved rather
than waived; it does not prevent the source/disposable work above. The goal is
not complete, and source acceptance does not imply an always-ready live slot.

### Pinned dispatch/recovery package and runtime distinction

Commit `8e8f70efb4910d6c2a1cceefcecae2b9b1ab7e9b` was built from a clean tree.
Actual three-wheel RECORD/canonical resource inspection: **PASS**. Candidate:
`/tmp/eom-api-build/8e8f70efb4910d6c2a1cceefcecae2b9b1ab7e9b.J2mcwf/dist`.
Isolated `python -I`, importing only those wheels (no repository path), verified
offline dispatch schema references, real local worker RPC and historical-ticket
known-result recovery after synthetic policy/boot change: **PASS**. The owner was
synthetic for this package-only probe; actual PostgreSQL invariants are covered
by the separate42-case suite, not claimed from this probe. Native/GPU calls: **0**.
The probe's own bounded temporary handoff was automatically removed; canonical
production Artifacts/history were untouched.

Fresh read-only systemd inspection found both `eom-general-chat.service` and
`eom-general-chat-worker.service` **not-found/inactive**, confirming no resident
deployment. Dedicated worker UID981/GID978 exists; owner account `eom-general-chat`
does not. The tmux4 pane is still `general-chat`; no enrollment was restarted and
credential contents were not read. Thus the next work remains service composition
and protected installation, not declaring chat live or requesting another goal
card resumption. Goal tool status is ACTIVE.

## Resident service composition checkpoint — 2026-10-08 02:14 UTC

Two installed-module entrypoints compose the existing applications rather than
introducing a new scheduler, queue, registry or service framework. The isolated
worker hosts native stdio, exact local handoff and the private owner-only socket.
The Orchestrator owner hosts private API/history RPC, dedicated DB/Artifact
publication and a single recovery-first coordinator. All authenticated active
users retain separate histories; slots01–06 are unchanged.

Each admitted epoch passes its actual boot/policy explicitly to prepare. History
and known-result recovery no longer require constructing an invented worker boot
while the native process is unavailable. Recovery checks the original active
claim, canonical dispatch and local result before a fresh epoch is admitted.
UNKNOWN/ABSENT stays fenced; known completion reuses the original claim, lease
and immutable output. Execution unavailability does not stop owner-scoped reads.
Optional reporting failures do not stop execution or expose raw exception text.

Native retirement stops new connections, drains active handlers and preserves
durable local results before exit75/systemd restart. Local pending/results reside
in a private700 StateDirectory, not the transient socket RuntimeDirectory.
Manual stop drains without restarting; unknown pending markers survive restart.
Systemd KillMode=mixed gives the host a1300-second bounded drain window instead
of sending SIGTERM to the native process while it is answering. Native probes do
not initialize or restart the process; there is no generation retry/fallback.

Owner configuration requires a dedicated local database role, explicit model and
installed source commit. No global/admin database credential fallback. Read-only
startup admission checks exact role, migration head0049, elevated flags and denied
credential/identity/legacy-slot access. Metadata/publication pools remain separate
and bounded. Source units mount the worker config read-only, hide DB/NAS/other
worker homes from the worker, and hide worker homes from the Orchestrator owner.
Source unit verification is not a claim of live permissions/isolation.

Executed source/API/Web/contracts/private-RPC/release tests: **411 PASS**;
guarded disposable PostgreSQL: **45 PASS**. The actual SQL admission negative
rejects the broad disposable owner role; it does not certify an uncreated runtime
role. Systemd-analyze verify, Ruff check/format, strict mypy (nine changed core
modules) and diff checks: **PASS**. One existing Starlette TestClient deprecation
warning remains; no dependency changed. An initial persistence run found two
synthetic workers missing the new explicit identity property (40 PASS,2 FAIL);
the fixtures were corrected and the full45-case suite rerun successfully. Failed
test history is not hidden or represented as an operational failure.

No new schema/migration, production DB/service change, native inference or GPU
invocation in this checkpoint. Actual owner identity/least-privilege role,
protected environment installation, OS negatives, coordinated deployment and
first-answer/follow-up/two-user browser acceptance remain uncompleted live gates.
The existing auth/deployment eligibility gate has not been waived. Build-only
verification follows the clean source commit; this status is not live acceptance.

### Pinned resident-composition package verification — 2026-10-08 02:19 UTC

Source `4c0005d50cac16586116eea15750397cab47f817` was built from a clean tree.
Actual three-wheel RECORD/canonical-module inspection: **PASS**. Candidate:
`/tmp/eom-api-build/4c0005d50cac16586116eea15750397cab47f817.VYsIPc/dist`.
An isolated `python -I` process loaded the new owner/worker entrypoints,
coordinator, configuration and lifecycle solely from those wheels, with no
repository import/path. Real private Unix RPC exercised synthetic admission,
one answer, drained exit75 and exact durable-result lookup after reopening the
handoff: **PASS**. Native model calls and production mutations: **0**. The probe's
bounded temporary directory was automatically removed; no canonical production
Artifact or history was removed. Source unit syntax passed systemd-analyze verify.

Fresh systemd inspection still reports both chat services not-found/inactive.
This candidate is not installed or activated. Next required work remains the
protected owner/least-privilege role, actual service isolation negatives, supported
authentication-route decision, coordinated deployment and live acceptance. Goal
remains ACTIVE/unfinished; this checkpoint made concrete implementation progress.

## Dedicated owner privilege checkpoint — 2026-10-08 02:43 UTC

One closed immutable table/column privilege profile now drives both guarded
preparation and read-only owner startup admission. The Orchestrator owner can
publish canonical Artifacts and update chat metadata, but cannot read credentials,
change identities, use slots01–06, delete history, change Artifact approval, or
update job payloads. Admission also checks independent column ACLs, inherited or
PUBLIC access, memberships, DDL/ownership, definer functions and unrelated
sequence privileges. Inspection uses bounded batched catalog queries rather
than per-table/per-request lookups. No schema, migration, worker protocol,
dependency, queue or transcript store was added.

Protected preparation reads use bounded no-follow file descriptors and reject
symlinks, FIFOs, hard links, unsafe metadata and inconsistent reads. Credential
installation is durable and no-replace; a failed role transaction retains the
same protected credential for replay. Existing role/secret identity conflicts
stop before mutation; existing passwords are not silently rotated. A separate
source script prepares the locked owner OS identity without enabling services or
changing worker group membership. Neither preparation has been executed yet.

Re-executed source/API/Web/contracts/release regression: **468 PASS,12 SKIP**;
guarded disposable PostgreSQL baseline: **45 PASS**. The twelve skipped tests are
the new real limited-role positive/publication and negative-privilege cases;
they require guarded root preparation of that disposable database's runtime role
and its private `chat.env`. They are **PENDING**, not implied PASS. Initial fixture
registration and a mypy namespace invocation issue were corrected before these
results; no production state was involved. Ruff check/format (48 files), strict
mypy (six preparation/runtime modules), shell syntax and diff checks passed. One
pre-existing Starlette TestClient deprecation warning remains.

Both chat services are still not-found/inactive; the automation-terminal sudo
preflight required authentication. That did not establish the separate tmux
terminal's credential state (see the correction below). No owner identity,
production role, migration or runtime activation was
performed, and native/GPU calls remain zero for this checkpoint. The next bounded
privileged action is only the manifest-guarded disposable role plus private
credential preparation, followed by `chat-role-tests`; it is not production
deployment or a claim that the supported authentication gate is resolved.

### Fixed production preparation entrypoint — 2026-10-08 02:51 UTC

`scripts/chat/prepare_owner_role.py COMMIT` stages only the fixed dedicated owner
role and root:root600 environment, reusing the same closed profile and durable
credential adapter. There is no test/production override flag, shared admin URL,
password rotation, migration, service activation or auth enrollment. Before any
write it checks root, clean pinned source, stopped owner, protected parent,
authoritative loopback database/head0049, zero active target-role sessions and
matching role/secret ownership. An uncertain preparation must be inspected and
replayed with the same identity, not treated as an activation receipt.

New preparation guards/replay/redaction tests plus the existing source/API/Web/
contract/release suite: **492 PASS,12 SKIP**. The new24 cases are simulated
preparation boundary tests, not production or actual limited-role SQL acceptance.
Ruff check/format, strict mypy for the new script and diff checks: **PASS**.
The45-case disposable persistence baseline and the12 pending real role cases
remain distinct. The automation-terminal sudo preflight still required a
password; neither root preparer had been run at this checkpoint.

The earlier clean `bea6ce34dd217257d2a4ce4f3378feeaba2c07a1` runtime candidate's
three-wheel RECORD/canonical inventory and wheel-only imports/config negatives
passed at02:44 UTC. The production preparer is deployment code, not an activated
runtime. These results do not close supported auth, OS isolation, coordinated
installation or real answer/follow-up/two-user browser gates.

## Actual dedicated privilege acceptance — 2026-10-08 02:59 UTC

Correction: the earlier automation-terminal `sudo -n true` checks did not prove
that the operator's tmux credential had expired. An in-pane, exit-status-only
probe confirmed `EOM:4` / `general-chat` still had valid sudo authentication.
No pane history, password or auth-file contents were captured, and no new login
or credential enrollment was needed. Privileged work uses that verified terminal,
not a claim that a different terminal's failure invalidates its authorization.

Pinned clean-source preparation at
`092c4d95ed480dfbc26ea60953f07783ebc1b01d` completed successfully for the existing
guarded disposable manifest only. Its dedicated `chat.env` is eom:eom600; no
production role, migration, service, native inference or GPU was changed.

The new actual limited-role suite: **12 PASS**. It verifies positive startup
admission, canonical publication and replay for two private owners, cross-owner
read/list exclusion, and actual PostgreSQL denial of credential/identity/legacy
slot access, job-payload or Artifact-approval mutation, history deletion and DDL.
Independent extra/missing column grants are detected and restored through the
guarded fixture. The existing persistence/concurrency suite reran: **45 PASS**.

The first limited-role run had11 PASS/1 FAIL because the new test incorrectly
treated the returned conversation projection as a turn receipt. A second run
had11 PASS/1 FAIL because the added ownership-denial assertion used the wrong
stable error name. Both test assertions were corrected to the existing canonical
contracts; runtime code, schema bytes and role grants were unchanged. All12 cases
then passed. These failures are retained as test evidence, not reinterpreted as
an operational state-machine or permission defect.

Source baseline remains492 PASS/12 opt-in SKIP; those same12 opt-in cases have now
separately passed against actual disposable PostgreSQL. Runtime OS isolation,
supported authentication direction, coordinated production release and real
answer/follow-up/two-user browser acceptance remain pending. Feature is not live
or complete, and the original all-authenticated-user scope is unchanged.

### Owner OS preparation and real role replay — 2026-10-08 03:03 UTC

Clean source `3964f5700a24d063ffe033aa6bee1feb6a9ab379` prepared the dedicated
locked/nologin owner account (UID980, private primary GID977) and its
eom-general-chat:eom-api700 state directory. The account has no permanent
supplementary groups; source service-only groups remain scoped to that future
service. Worker UID981/GID978 and all six existing workers retain only their
own primary groups. No service unit was installed/enabled/started, and production
DB, native authentication, model inference and GPU were unchanged. This proves
identity preparation, not sandbox admission or residency.

Replaying the same guarded disposable role preparation succeeded. Its protected
credential file identity/metadata was unchanged, and actual limited-role login,
publication and denials passed again (**12 PASS**). Existing role credential was
retained, not copied or rotated. The earlier45-case persistence suite also passed
after first preparation. Actual isolation, supported-auth decision and production
release/browser/model acceptance remain required before completion.

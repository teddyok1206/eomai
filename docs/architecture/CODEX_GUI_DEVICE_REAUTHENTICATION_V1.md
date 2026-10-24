# Codex GUI Device Reauthentication V1

Status: reviewed implementation design

## 1. Responsibility and boundary

Scientific Studio may let a freshly authenticated ADMIN coordinate a ChatGPT device-code login for
one fixed Codex worker slot. It does not authenticate the user itself and it never accepts an OpenAI
password, API key, access token, refresh token, `auth.json`, or copied credential cache.

The boundary is deliberately split:

```text
ADMIN browser
  -> Scientific Studio BFF
  -> Application API (authorization, idempotency, durable state)
  -> workflow runner (state-machine processor)
  -> private auth-broker Unix socket (ephemeral challenge only)
  -> fixed systemd device-login unit
  -> exact eom-cdx-0N identity / that identity's CODEX_HOME
```

The browser receives only an allowlisted HTTPS verification URL and one-time user code. Those two
values are short-lived secrets: they may exist only in broker memory and the worker-owned `/run`
handoff, are revealed at most once, and are never written to PostgreSQL, audit events, application
logs, Slack, Git, NAS, or browser storage.

## 2. Canonical source and identity model

- `CodexAuthBindingRecord` remains the mutable current health projection for a fixed slot.
- `CodexAuthEnrollmentRecord` is the durable logical reauthentication attempt. Its state changes,
  but its request identity, slot, requested label, actor, and request hash never change.
- A successful attempt creates exactly one immutable `CodexAuthAssignmentRevisionRecord`. This is
  the canonical non-secret history of which operator-declared account label was assigned to which
  fixed binding. The binding's `current_assignment_revision_id` is the mutable current pointer.
- Credentials remain canonical only in the target worker identity's Codex credential store. EOM
  stores no credential pointer or credential hash because either would imply a supported read path.
- The account label is an operator assertion, not an identity claim extracted from token material.

IDs, revision IDs, request hashes, and transient device codes remain distinct. A filesystem path is
never persisted as identity.

## 3. Primary access patterns and structures

The expected host scale is five slots and at most one enrollment per slot.

- binding lookup: indexed `binding_id` / unique `worker_slot_id`;
- current assignment: one foreign-key pointer on the binding;
- immutable assignment history: ordered unique `(binding_id, revision_number)` B-tree lookup;
- active enrollment membership: partial unique index on `binding_id` for nonterminal states;
- FIFO processor claim: partial/indexed ordering by state, lease expiry, request time, and ID;
- transition validation: explicit typed transition table, not nested implicit conditionals;
- ephemeral challenge lookup: an in-memory map keyed by enrollment ID plus one worker-owned regular
  handoff file; both are bounded to five entries and ten minutes.

DB operations are O(log n) indexed lookups. Broker lookup is O(1). There are no scans over job or
event history and no binary or credential payload is stored in PostgreSQL.

## 4. State machine

```text
REQUESTED -> DRAINING -> READY_FOR_LOGIN -> WAITING_FOR_USER -> VERIFYING -> SUCCEEDED
                   \             \                 \              \
                    -----------------------------------------------> FAILED
                    -----------------------------------------------> CANCELLED
                    -----------------------------------------------> EXPIRED
```

Only `SUCCEEDED`, `FAILED`, `CANCELLED`, and `EXPIRED` are terminal. The processor may replay the
same idempotent transition after a crash, but it must never start two device-login units for one
enrollment or create two assignment revisions. There is no automatic second enrollment.

`REQUESTED` first drives the existing binding to `DRAINING`. `READY_FOR_LOGIN` is reachable only
when no `ACTIVE`/`RECONCILING` lease and no active fixed worker unit exists. The login helper starts
only then. The exact-identity non-generating auth and CLI/runtime probes must pass. Authentication
is committed before model tests, with the new assignment still `DRAINING`. The same enrollment
continues in `VERIFYING` and automatically executes the released synthetic compatibility probes.
The user does not start a separate verification or repeat device login for this phase. A fresh
auth observation plus admitted execution evidence makes the slot `READY` automatically. With no
passing model/effort pair, login may finish but the slot remains `DRAINING` with
`CONTROL_CAPABILITY_BINDING_UNVERIFIED`; it never inherits the old assignment's capabilities.

This changes no request/status schema, DB lifecycle, historical assignment or failed enrollment.
`SUCCEEDED` identifies a verified login assignment, not permission to dispatch model work. Only
the typed `UnverifiedCapabilityAssignment` for the just-created binding/revision is nonfatal here;
role, slot, runtime, policy, hash and persistence errors remain terminal. Before authentication is
committed they roll back its assignment; failures during subsequent model tests preserve the
successful authentication and leave the slot unavailable. Indexed binding/assignment and canonical
publication lookups plus the bounded policy replace no existing queue or storage owner.

### 4.1 Automatic model verification (2026-10-24)

- Contracts first: reuse the released JSON Schema 2020-12 and Pydantic
  `codex-compatibility-request/1.0`, invocation, probe result, and report contracts unchanged.
  No worker protocol, request/status family or DB migration is introduced.
- The exact new assignment and the complete protected policy determine a stable run identity.
  A policy change, including same-version runtime hashes or scopes, invalidates lookup. The
  request pins the installed source, binding, assignment, resource version and ordered pairs.
- Existing scopes on the fixed binding provide only the **candidate** model/effort pairs. Old
  assignment proofs are not admission. The probe executes on the newly authenticated worker using
  the normal fixed unit, an attached synthetic PNG and strict JSON output. Native model catalog
  visibility alone is not PASS, and no external LLM API or API-key billing path is added.
- A fresh fixed-slot native catalog narrows candidates to visible models/efforts with the required
  text/image modalities before inference; it does not grant admission. The resulting request is
  frozen. Replay uses that same checkpoint, not a newly discovered/latest catalog. A canonical
  completed report is reused even if local staging has been removed; an incomplete publication
  without its checkpoint is uncertain and cannot trigger a replacement inference.
- The released diagnostic stops at the first failure/uncertain call. Only its preceding PASS
  pairs can be admitted; FAIL/NOT_RUN pairs remain unavailable. Consequently completion does not
  claim that every configured model passed. The maximum call budget equals the bounded candidate
  set, with the released maximum of 64, inside the enrollment expiry window.
- Reuse the existing host-capacity advisory fence with enrollment-specific read checks rather than
  stopping producers: exact target `DRAINING`, valid enrollment, no held target lease, idle target
  unit, and spare current global/pool capacity. Already-running work continues, but **new host
  worker claims wait while the synchronous diagnostic holds this fence**. This explicit rare-login
  trade-off avoids a second queue/lease system; it is not a claim of zero scheduling impact.
- Normal 30-second polling claims are extended to the enrollment deadline for the bounded probe.
  A crash reuses the immutable local ledger: completed results/publication are replayed, and
  started-but-uncertain execution is never automatically inferred again. Capacity contention
  defers the same enrollment, rather than creating another login request.
- Only Orchestrator publishes the validated report and result members to NAS through the existing
  `ControlFileSetPublisher`. DB rows contain existing small job/manifest metadata and immutable
  pointers. Read admission resolves the canonical approved Artifact, protocol, lifecycle, manifest,
  member schemas and hashes, then checks runtime/policy identity and current assignment again.
  Local report files alone grant no permission.
- Authoring/review continue to require an identical passing pair on both **current** accounts.
  Other fixed roles are independently scoped. Periodic observation and ENABLE use this same
  read-admission resolver, so a successful automatic proof is not lost at the next health refresh.
- Existing V1 snapshots stay immutable. The shared SQL predicate excludes observations preceding
  the current assignment time (a dangling assigned revision fails closed). Account display, model
  selection and automatic health freshness use this same predicate. Worker acquisition additionally
  accepts only the latest snapshot for the binding, so a missing pair in the latest proof cannot
  fall back to an older snapshot that still advertises it. Legacy NULL assignments stay supported.
- OBSERVE/ENABLE are rejected during an active enrollment, including at the final locked write,
  so a stale manual refresh cannot replace its drained projection. Explicit DRAIN/DISABLE remain
  available as safety controls and invalidate an in-progress test rather than enabling work.
- Dependency direction: immutable policy values live in `reviewed_capability_policy`; canonical
  proof reads in `auth_enrollment_capability_admission`; execution/fencing in
  `auth_enrollment_capabilities`; the existing enrollment processor owns lifecycle. Existing policy
  class imports remain supported re-exports. Admission does not import the worker executor and no
  circular import is needed.

Access patterns remain indexed binding/assignment/publication lookup and ordered immutable
diagnostic iteration. Pair aggregation uses sets/maps, O(cases + policy entries), bounded to the
released limits. No binary DB values, extra cache, parallel queue, new dependency, root policy-file
writer or credential access is introduced. Before rollout, run disposable PostgreSQL concurrency
tests and an installed-release login canary; source test PASS is not live acceptance. Rollback first
drains the changed slot, restores the compatible prior release, and preserves assignment/report
history. Already FAILED enrollments are not reinterpreted as successful.

## 5. Transaction and concurrency boundary

The API transaction creates one schema-valid enrollment using a unique idempotency key and the
binding resource version. A partial unique index rejects concurrent active attempts. The runner
claims with `FOR UPDATE SKIP LOCKED` and a bounded lease. External systemd/broker work occurs outside
the row-lock transaction; terminal persistence is conditional on the claim owner and current state.

The fixed unit name contains only a validated slot and `authflow_<32 lowercase hex>` enrollment ID.
Polkit allows the workflow-runner identity to **start** only that exact unit family. Restart, stop,
transient units, arbitrary arguments, malformed IDs, and cross-service units remain denied.
Immediately before that one start, the processor commits `login_unit_started_at` under the claimed
enrollment row. A reclaimed `READY_FOR_LOGIN` enrollment with this marker may only observe its
existing unit/handoff; it must never issue another start. A crash between marker commit and unit
start therefore fails closed or expires instead of repeating an authentication attempt.

Cancellation is a separately authenticated command. V1 does not expose cancellation until a fixed,
audited stop boundary exists; expiry leaves the unit to its own bounded timeout and fails closed.

## 6. Broker and worker handoff

The root-installed login helper runs as the exact worker user with that worker's fixed `HOME` and
`CODEX_HOME`. It executes only:

```text
/usr/local/bin/codex login --device-auth
```

The helper parses a bounded stream and accepts only:

- an `https://` URL whose normalized host is `auth.openai.com`;
- a bounded uppercase/digit one-time code;
- a zero exit followed by the existing sanitized `codex login status` probe.

Codex's own plaintext diagnostic log is redirected to a worker-owned `0700` directory under the
ephemeral login runtime directory. The helper removes that directory before publishing a terminal
status; a cleanup failure is an explicit terminal failure and is never silently ignored.

It emits no raw CLI output. It writes a JSON Schema 2020-12 validated handoff with `O_EXCL`,
`O_NOFOLLOW`, regular-file checks, exact owner/group, mode `0640`, and an expiry. The login unit has
network access only because device authentication requires OpenAI HTTPS; it has no NAS, repository,
database, sudo, Docker, other worker home, or workspace access.

The broker is a dedicated unprivileged service. It may read only the five `/run/eom-codex-login-*`
handoff directories, expose a private `0660` Unix socket to the Application API, and start no
process itself. It validates peer UID, frame size, schema, path metadata, slot/enrollment equality,
and TTL. `REVEAL` is guarded both by broker memory and the API's durable `challenge_revealed_at`;
the worker removes the challenge at terminal login. The broker intentionally lacks directory write
permission. Status responses contain stable state/reason codes only.

## 7. API and GUI security

- every route requires active ADMIN, `codex_account:manage`, recent authentication, and CSRF at BFF;
- begin requires `If-Match` and a 16–128 byte idempotency key;
- the body contains only an NFC account label and an explicit acknowledgement that the slot is
  drained; password/token/API-key fields are rejected by `extra=forbid`;
- challenge retrieval is bound to the requesting ADMIN session and is one-time/no-store;
- responses set `Cache-Control: no-store`; the GUI never uses local/session storage, URL query
  parameters, clipboard automation, analytics, or Slack for the code;
- the verification link is rendered with a fixed host check and `rel="noopener noreferrer"`;
- generic exceptions return stable error codes and never include CLI output.

## 8. Failure, retry, and rollback

Missing/malformed/expired handoff, owner or mode mismatch, symlink, unit launch denial, lost claim,
auth probe failure, and CLI incompatibility are explicit failures. Credentials are never repaired or
copied. Retry means a new ADMIN-authorized enrollment with a new ID after the prior attempt is
terminal; it is never automatic.

Rollback disables the GUI action and runner processor, leaves the slot drained, and preserves
enrollment/assignment/audit history. It removes no credential and changes no active worker. An
operator can still use the documented protected-terminal login procedure.

## 9. Simpler alternative and rejection

Letting the API run `sudo codex login`, accepting an API key in a form, copying `auth.json`, parsing
the system journal, or storing a device code in PostgreSQL would be shorter. Each option gives a
public application an overly broad privilege or creates a durable credential path, so all are
rejected. A dedicated typed broker plus fixed systemd units is the smallest design that preserves
the existing worker identity, orchestrator, and credential boundaries.

## 10. Rollout boundary

Source, fake-CLI tests, disposable DB migration tests, and release artifacts may be completed while
another slot is working. Runtime installation must not restart the workflow runner or change worker
units while Slot 5 holds an active or reconciling lease. First deployment uses an idle slot and a
separately approved device-login attempt; Slot 5 account material is untouched.

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
only then. A login success is not enough to enable work: the exact-identity non-generating auth and
capability probes must pass before `SUCCEEDED`; the slot remains drained until an explicit existing
`ENABLE` command.

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

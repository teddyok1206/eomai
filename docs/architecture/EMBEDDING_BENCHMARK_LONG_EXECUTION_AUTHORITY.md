# Bounded embedding benchmark and genuine session lifetime

## Observed incompatibility (2026-10-24 UTC)

Original CPU execution `219a126ed01241569a7d62ad3f2fc7cc` failed waiting for a
checkpoint acknowledgement at 03:40:47 UTC. Its controller suppressed the underlying
continuation exception; the worker error alone does not prove that exception.
Read-only operational inspection independently establishes a temporal contradiction:
the only matching genuine benchmark session authenticated at
`2026-10-24T03:25:37.795356Z`, was 909.204644 seconds old at failure, and had an
unexpired ACCESS token until `03:55:37.795356Z`. The session/token were not revoked,
the session was unexpired, and the operator remained active. The configured 900-second
fence necessarily rejects this point, although the released native compute budget is
1200 seconds. The observed worker failure and this deterministic rejection are
separate evidence; do not fabricate the discarded inner exception.

## Smallest boundary correction

1. Responsibility: the existing benchmark owner composition selects a bounded
   administrator authentication-recency ceiling; Identity still checks the real
   session, ACCESS token, operator and permissions on every existing short SQL root.
   No new authentication provider, queue or worker authority is introduced.
2. Canonical source: actual Identity session/token rows and the genuine in-memory
   login. The authenticated timestamp is never changed, forged or interpreted as now.
3. Identity/revision: original requests, reservations, failed executions and their
   source releases remain immutable. Close the existing CPU1 failure through the
   supported post-start application before any explicit successor submission.
4. Pointers: keep exact request/policy/source/Graph/backend/Artifact revisions and
   hashes. This is a controller composition correction, not new worker message or
   compute-policy meaning. Released JSON Schema bytes and native units stay unchanged.
5. Access patterns: O(1) request-version/timeout selection; an ordered six-launch
   series; direct indexed Identity lookups. No new persisted state or cache.
6. Data structure: retain frozen owner pins. Legacy 180/600-second requests retain
   their 900-second ceiling. Only a validated v1.2 request with its released 1200-second
   budget permits a caller-selected ceiling up to Identity's existing 3600-second
   maximum. Ordinary application/GraphRAG caller defaults do not change.
7. Scope/complexity: one manually requested fixed-input benchmark, not a general
   long-lived credential. The real one-hour age bound remains enforced even after
   ACCESS-token refresh; O(1) additional checks and memory only.
8. Transactions/concurrency: current operator/session/token/permission locking stays
   unchanged. Refresh occurs only between clean terminal launches, with no active
   native execution or source transaction. Rotate through the existing HTTP refresh
   contract, then obtain a new verified capture; never reuse a stale capture after
   refresh-generation/token changes.
9. Dependency direction: composition owns the recency selection; the finite operator
   client owns localhost HTTP and memory-only token lifecycle. Identity/domain rules
   do not depend on HTTP, NAS, benchmark launchers or operator scripts.
10. Failure/retry: revoked/expired sessions, denied permissions, mismatched session,
    changed authenticated timestamp and failed/uncertain refresh fail closed. Refresh
    is not replayed automatically with a new identity. If genuine authentication age
    or absolute/idle expiry cannot cover the next bounded launch, request genuine
    login at that clean boundary. No refresh or reauthentication during a launch.
11. Alternative: globally increasing login lifetime or removing per-checkpoint
    authorization would affect unrelated users and operations. Merely enlarging the
    native deadline or repeating the same 900-second run leaves the contradiction.
    A new general job-credential framework is unnecessary for this bounded correction.

## Acceptance before another inference

- Reject widened legacy captures and any ceiling above 3600 seconds; reject malformed
  v1.2 policy/request and preserve existing source/permission/revocation checks.
- Genuine refresh uses the released request/response DTOs. Require same operator,
  same session and unchanged authenticated timestamp; token rotation is not a fresh
  human login. Credentials/tokens remain memory-only and never enter logs or files.
- Check remaining authentication, ACCESS, refresh, absolute and idle windows before
  dispatch; obtain a new actual capture after any rotation. Do not knowingly launch
  a 1200-second operation into a shorter remaining window.
- Identity exposes an execution-window planning check through the same authoritative
  locked-row validation as `assert_current()`. It keeps opaque capture details private,
  includes the current database idle deadline, and returns no transferable grant.
- Preserve and root-attest the failed original execution/cleanup, then use supported
  post-start closure and explicit successor/idempotency contracts. No row edits,
  success reinterpretation, automatic retry or output promotion from partial files.
- Installed no-model preflight and focused tests precede another user login. Record
  the actual configured bound and selected controller source in operational evidence.

This note records the approved goal's session-management correction. It does not
claim the original six-launch comparison, source failure closure, successor, or GPU
default activation has completed.

## Actual controller recognition in failure evidence

The failed controller is genuinely
`eom-embedding-benchmark-retry-3625ffd9.service`, with protected program
`/usr/local/libexec/eom-benchmark-budget1200-retry-3625ffd9/series.py` and SHA
`5cf3393574fbc5f7b419fd681f30abd1fde73418fdc7fe9aba9cab14c862a8e3`.
Existing failure evidence accepts only the older `eom-gpu-benchmark-*` supervisor
layout. A new alias, an unrelated failed unit or model-constructed invalid pin
cannot truthfully attest this original execution.

Extend the existing failure-evidence family with an additive schema successor if
the released schemas cannot express this actual controller. Define that JSON Schema
before the typed model and adapter behavior; leave predecessor schema bytes intact.
Keep the request/native execution at v1.2 and its 1200-second budget. Only controller
metadata recognition changes: enforce the exact protected unit/program family,
root ownership/mode/hash, PID1 original invocation, terminal state and empty retained
resources, plus the same original request/invocation/control/output/retirement hashes.
Reuse existing post-start capture, closure, immutable predecessor and successor
applications. No new queue, generic recovery framework, fake old-format proof or
direct row update is justified. Lookup/validation remains bounded O(1) plus the
existing fixed manifest member count; concurrency/idempotency remain in the existing
transactional append-only closure. Negative tests must reject mixed unit/program
families, forged hashes, active controllers, wrong source identities and missing cleanup.

## Completed-prefix continuation after a transport-only correction

The successor `job_a930cfc8b08b4cf385c5cf95370cbcb4` committed CPU ordinal1 and
successfully re-read its existing QUERY. Before ordinal2 the official refresh
adapter rejected a TCP child with inode0, before emitting HTTP headers/body. The
shared peer parser must treat this as pending acceptance and use its existing
bounded observation loop. Wrong accepted UID, ambiguity, malformed input and
timeout still reject before any credentials are sent. No HTTP/refresh replay is
introduced. The later owner-process check observed the already exited child; it
is secondary fail-closed evidence, not permission to weaken process identity.

Continuation design:

1. Existing Orchestrator journal is canonical for completed prefix, unresolved
   reservations and the next ordinal. Never manufacture receipts or copy vectors
   into a new Job. Reauthorize the pinned existing request and its original policy.
2. Keep the logical Job, benchmark revision, immutable CPU receipt/Artifact and all
   numerical/backend/Graph/source hashes. New controller source stays explicit in
   each later launch's preparation and producing Job; do not claim the old source.
3. The root-only local series selection gains a bounded first ordinal (default1).
   This is scheduling, not authority or a worker-wire/schema change. Existing
   association/request/owner/ordinal/device/Job checks still fence every launch.
4. Access pattern is a fixed ordered suffix of6 stages; O(6) time/O(6) receipt
   storage. Prefix membership remains in the indexed journal, not a parallel queue.
5. Controller-source equality alone is too coarse for resuming after an HTTP-only
   repair. Mixed controller releases are accepted only when their installed,
   root-protected measurement implementations match byte-for-byte across an
   explicit fixed member inventory. Numerical runtime/model pins and per-launch
   source/provenance/cleanup checks remain mandatory. Same-release paths retain
   their existing behavior; absent, mutable or differing implementations reject.
6. Implementation snapshots are temporary bounded materialization from immutable
   installed releases, not a persisted cache, runtime Git dependency or new
   registry. Deduplicate release IDs with a set; compare one fixed manifest per
   release, O(releases × fixed members) and bounded bytes. Hold/revalidate file
   identity through final measurement collection using existing runtime file
   snapshots. Installed releases remain immutable; registered producer/source
   and original Artifact provenance are separately revalidated during publication.
7. The Catalog infrastructure adapter owns protected installed-file resolution;
   the existing finalizer owns comparability and publication. Domain/contracts do
   not import filesystems or infrastructure. No new dependency or DB migration.
8. New real login/official refresh is required normally; no persisted credentials,
   impersonation or altered authentication timestamps. Restart no active native
   execution. Never turn a historical failed controller into a successful run.
9. Replays reuse the same request, registered prefix and original result pointer.
   Changed measurement code requires a separate cohort; an incomplete prefix or
   uncertain reservation requires its existing supported recovery, not skipping.
10. Tests cover pending→accepted peer proof, persistent pending, wrong UID and
    duplicate matches; root suffix order/bounds/mismatches; equal/changed/missing/
    writable controller members and immutable file snapshots; finalization replay.
11. Alternative: rerun CPU1 after every nonnumerical release change. It wastes a
    validated long measurement and couples HTTP maintenance to scientific output.
    Arbitrarily accepting mixed releases or relabeling old receipts is unsafe.

## Proven pre-ACK CUDA failure: one bounded same-Job recovery

Actual ordinal2 `f4ffefb468594414bcea524d4f5ebb98` exited before root ACK. Its
ready record and every output remain original; worker-result is empty. The
1200-second unit's bootstrap omitted SIGUSR1 reservation, and root observation
expected `-m` although the installed unit uses `-c`. Correct only the unit's
operational bootstrap/argv binding. Keep the numerical interpreter, SDK d381,
encoder/normalizer/codec, payload, recipe, input and time/memory limits unchanged.

The supported retirement preserved its original failed terminal before RESET.
PID1 then reported inactive/dead-resources-pinned/store1, not an active process.
Accept that narrow stopped state only with loaded unit, PID0, empty cgroup, no
pending Job/override and the original invocation. Finish only the not-yet-executed
fdstore clean using the preserved intent and current resource checks; never replay
RESET, send ACK, restart the unit or reinterpret the failed original as success.

The original six-stage journal cannot currently represent this proven zero-compute
attempt. Add a narrow recovery event, not a new queue or a general retry framework:

1. Orchestrator owns the same Job's append-only recovery and next reservation;
   Catalog infrastructure validates a pinned root-produced inspection. Root only
   observes/retires OS resources and seals evidence, never mutates Job rows.
2. Canonical sources remain the original request/policy/CPU1 receipt and immutable
   failed invocation, ready/empty-output/retirement records. A path is not identity.
3. Keep original Job/benchmark/input/policy revisions. A recovered failed attempt
   stays in history with its own execution ID. The next actual attempt gets a new
   execution ID for the same ordinal; no copying or relabeling numerical results.
4. The new JSON Schema2020-12 owner protocol precedes typed models and application
   behavior. Root observations and recovery decisions pin all identities/hashes,
   exact failed native invocation, absent ACK, zero constructor/forward counts,
   empty output manifest and confirmed resource retirement. This small immutable
   value belongs in existing event metadata; no binaries or new DB tables.
5. Dominant access is indexed Job lookup and ordered history (maximum32 events),
   plus set membership of execution IDs and recovered ordinals. One pre-ACK
   recovery per CUDA ordinal2/3/6 only; never an unbounded retry loop.
6. Lock the existing Job row in the current root transaction. Require actual
   caller/source/policy admission, last unresolved reservation matching the proof
   and unchanged completed prefix. Append RUNNING-to-RUNNING recovery once; do not
   update/delete old events. Concurrent recovery has one winner; exact replay
   creates no second event or unit. No migration/index change is needed.
7. History projection retains retired attempts separately and exposes the original
   completed prefix plus current ordinal. Execution IDs remain unique including
   retired attempts. Only a proven pre-ACK/no-output failure can leave this state.
8. Missing/stale/hash-different proof, any ACK, nonempty output, live process,
   retained resource, wrong actor or current source denial blocks recovery. A
   post-ACK/OOM/unknown model run is not eligible. Historical replay verifies the
   stored decision, not a mutable latest unit or invented successful worker result.
9. Bootstrap routing and GPU safety observation are not numerical measurement
   algorithms. Compare shared numerical/timing implementations across releases,
   and device-specific measurement code only among completed runs of that device.
   The old CPU1 did not execute GPU ready/retirement code. Every launch still pins
   actual source, exact backend and independent immutable numerical implementation
   hashes. Actual CPU unit bytes must stay unchanged; no threshold is relaxed.
10. Keep interfaces/application/domain/contracts dependency direction. CLI composes
    genuine authentication, typed fixed inspection and supported application; the
    journal owns concurrency/state. Source resolution stays at official Catalog
    and Identity boundaries, never model-supplied authority or worker DB/NAS access.
11. The simpler alternatives—direct row edits, ignoring the uncertain reservation,
    rerunning CPU1 or calling the bootstrap defect a GPU performance failure—do
    not preserve the requested experiment. This bounded event extends its existing
    checkpoint ownership and keeps every failed attempt distinguishable.

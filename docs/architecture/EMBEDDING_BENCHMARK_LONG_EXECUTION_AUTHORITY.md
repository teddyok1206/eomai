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

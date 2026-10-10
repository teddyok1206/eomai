# Inference Transfer owner HTTP session refresh

Status: SOURCE_IMPLEMENTATION; actual authentication/deployment is not run by this change.

1. **Responsibility and boundary.** The existing synchronous owner HTTP session renews
   its own transport credentials before the next request when its last verified access
   expiry is within 180 seconds. This exceeds the existing 120-second request timeout.
   No snapshot, comparison, worker, or publication request is automatically retried.
2. **Canonical source.** The installed fixed Application API owns login, refresh,
   revocation and `/api/v1/auth/me`. The client uses the existing `RefreshRequest`,
   `SingleResponse[TokenPair]` JSON Schema/Pydantic validation and fixed-peer proof.
   A local expiry does not prove current access or grant permissions.
3. **Identity and history.** Rotation must preserve the first verified operator ID,
   API session ID, `guiadmin` username and `authenticated_at`. It does not rewrite
   historical source/policy/Graph/request identities or initial permission digests.
4. **Resolution checks.** A successful refresh reply must match the exact session,
   contain usable future token expiries and require no password change. A separate
   reader authenticates the new bearer through `/me`; its expiry must equal the
   returned token expiry. Only then are the new secrets installed in memory.
5. **Access patterns.** One owner performs an ordered sequence of synchronous reads
   and explicit writes. Before each operation its existing `read()` entry refreshes
   if due and reads actual permissions. Post-operation authorization remains intact.
   A bearer-only session, which has no refresh secret, keeps the previous behavior.
6. **Data structure.** Private per-session expiry and identity values plus a terminal
   refresh-failure flag are sufficient. Secrets remain `SecretStr` in process memory;
   no token files, persistent cache, password retention, mutable global or new registry
   are introduced. This session is not a concurrent refresh-token coordinator.
7. **Complexity and bounds.** The normal authorization path remains one `/me` call;
   rotation adds one refresh POST and one independent `/me`. Space is constant.
   An access TTL no greater than the safety margin is explicitly unavailable rather
   than repeatedly rotating or changing server TTLs. The hint can become stale;
   the actual API remains authoritative and denied requests are never replayed.
8. **Transaction/concurrency.** Token consumption and replacement are the existing
   identity-service transaction. Before that side effect the client marks refresh
   as unusable until a fully validated replacement is committed. No DB, API schema,
   policy TTL, session timeout, `authenticated_at` or fresh-auth gate is changed.
9. **Dependency direction.** The HTTP infrastructure adapter owns renewal and imports
   existing authentication contracts. Domain/snapshot code is unchanged; it gains no
   direct DB/NAS or secret access. No dependency or service is added.
10. **Failure/retry/idempotency.** Revoked/expired refresh, malformed replies, identity
    drift, network failure and unknown POST outcome fail closed with existing safe
    codes. A possibly consumed refresh is never retried, including later `read()`
    calls. An independently authenticated new CLI login is required. Snapshot reads,
    comparison POST keys and existing uncertain workflow history are not rewritten
    or automatically resubmitted. Token renewal is not a new fresh login.
11. **Simpler alternative.** Reusing only the original access token fails during a
    multi-chunk corpus read longer than its default 1,800-second TTL. Raising TTLs or
    refreshing after an operation fails would change policy or risk replaying a
    completed write. Proactive renewal at the existing transport boundary preserves
    both current authorization and exact request history.

Source verification must cover near-expiry and already-expired access hints, correct
rotation, token/session/operator/authentication-time drift, changed/revoked permissions,
bearer-only behavior, no automatic retry after unknown consumption, fixed-peer checks
before secret materialization and sanitized failure output. These are source tests,
not claims of a successful live login, CPU execution or model quality.

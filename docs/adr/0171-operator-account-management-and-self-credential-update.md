# ADR 0171: Operator account management and self credential update

## Status

Accepted for implementation.

## Responsibility and boundary

The existing Identity service remains the sole owner of Operator accounts, credentials, roles,
sessions, and their audit events. The Application API exposes typed use cases. Scientific Studio is
only a BFF and presentation client; it does not reproduce identity rules or mutate identity tables.
Only a fresh ADMIN session may create or administer another Operator. Every authenticated ACTIVE
Operator may update their own login username and/or password after proving the current password.

`operator_id` is the immutable logical identity. `username` is a mutable login attribute and is not
an identifier for history, ownership, or authorization.

## Canonical source and revision model

`operators`, `operator_credentials`, active role assignments, and API sessions are canonical.
`OperatorRecord.lock_version` is the optimistic resource version. Operator events are an append-only
monotonic history. Studio session data is a temporary projection. A successful credential update
returns the rotated token pair and refreshed Operator projection in one response so a second HTTP
read cannot leave the BFF holding only the now-revoked token pair.
The existing `/auth/me` response remains unchanged; the new `/auth/account` projection is explicitly
versioned as `auth-current-account/1.0` and carries the optimistic resource version needed by this
use case.

## Pointers and resolution

Administration resolves an exact `operator_id`. Self-service resolves the Operator from the
authenticated API session and never accepts a target Operator ID. Resolution verifies ACTIVE state,
the current password, the expected resource version, normalized username uniqueness, and the exact
current session before rotating its tokens. Missing, disabled, stale, and conflicting targets fail
explicitly; no latest or alternate account is substituted.

## Access patterns and data structures

- Login and username uniqueness: indexed lookup by `normalized_username` (B-tree unique constraint,
  expected O(log n)).
- Self update and administration: primary-key lookup by `operator_id` with row lock (O(log n)).
- Role membership and active sessions: existing indexed relations and set-like unique constraints.
- Studio session invalidation after a credential change: one bounded scan of the in-process session
  index (O(s), where `s` is capped by the configured maximum), deleting only matching `operator_id`
  entries other than the current browser session.
- Audit: append-only events ordered by per-Operator sequence.

The expected account count is hundreds to low thousands. Operator lists stay bounded. Large payloads
and binary data are not stored or transferred by this feature.

## Transaction, concurrency, retry, and idempotency

A self credential update is one Identity transaction. It locks the Operator and credential rows,
checks `expected_resource_version`, changes the requested fields, increments the resource version,
revokes other sessions, rotates the current session, and appends one redacted event. Competing updates
to the same account cannot both apply from the same version. The database unique constraint is the
final guard for concurrent attempts to claim the same username. Different Operators use independent
rows and sessions and can work concurrently. Studio's bounded in-memory session index protects its
LRU map with a short re-entrant lock because FastAPI sync dependencies may resolve different browser
sessions on different threads; token refresh remains serialized only within the affected session.

Admin creation and management continue to use the existing Application API idempotency and
`If-Match` boundaries. A self update is not automatically retried because it consumes current-session
tokens; the client replaces its token pair only after a successful response.

## Dependency direction and adapters

Studio -> Application API -> Identity application services -> identity contracts/models. PostgreSQL,
HTTP, cookies, and browser state remain infrastructure concerns. Domain contracts do not import the
web or database adapters.

## Failure behavior

Wrong current passwords expose only the existing invalid-credentials error. Stale versions,
username conflicts, disabled accounts, revoked sessions, and password policy failures use stable
errors. No password, password hash, token, or full request body is written to audit events or Slack.

## Simpler alternative rejected

Changing only the browser's displayed username would leave login and canonical identity divergent.
Adding a second account store would duplicate authorization state. Updating without row locking and
an expected version would permit lost updates. Reusing the existing Identity transaction and unique
index is the smallest implementation that remains safe for concurrent users.

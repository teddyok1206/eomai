# ADR 0056: Long-running API idempotency claims

## Status

Accepted

## Context and responsibility

The Application API may synchronously call the private Catalog application boundary while creating
graph-grounded item evidence. That bounded call can take longer than the ordinary Catalog response
window. The API idempotency service owns transport replay and must prevent an expired request from
finalizing after a newer attempt has acquired the same command.

The canonical state is one `ApiIdempotencyRecord` selected by the indexed tuple of operator,
endpoint, and HMAC-derived idempotency-key hash. Its immutable request hash is distinct from its
record ID, current claim owner, resource ID, and response body. No Catalog payload or artifact bytes
are copied into this row.

## Decision

- `CREATE_ITEM_PRODUCTION_EVIDENCE` alone receives a 120-second Catalog response timeout. Other
  Catalog operations retain the 30-second default.
- API idempotency claims use a 180-second lease, leaving a bounded margin around the evidence call
  and its surrounding validation and transaction work.
- Every initial claim and expired-lease takeover creates a fresh server-side CSPRNG claim token.
  Client request IDs remain audit-correlation values and never authorize claim completion.
- `complete` changes the row only when it is still `PROCESSING` and the persisted token matches the
  caller's token. A stale completion fails with `API_IDEMPOTENCY_CLAIM_LOST`; a stale failure is a
  no-op so it cannot overwrite the current owner.
- A completed record remains the replay source. Request-hash drift under the same key fails closed.

## Access patterns and structures

Claim and replay are key lookups through the existing unique indexed identity tuple, followed by a
single row lock. Ownership comparison is constant time; storage remains `O(1)` per retained API
command. The expected scale and retention remain unchanged. A random token is a small immutable
value for one acquisition, not a separately persisted entity.

## Transactions, retries, and failure behavior

Initial insert and expired takeover each commit in a short transaction. The Catalog call runs
outside that transaction. Finalization locks the same row and performs a compare-and-set on state
and claim token. A request whose transport response is lost may replay the same operator, endpoint,
key, and request bytes; it either receives the completed response, observes the active lease, or
acquires an expired lease without allowing the prior callback to win later.

The API application service owns this policy. The private Unix-socket client only selects the
operation timeout; Catalog and domain contracts do not depend on API infrastructure.

## Alternatives

Using the client-visible request ID as the owner is insufficient because a client may legitimately
reuse it during a retry. Merely increasing the socket timeout or lease is also insufficient because
an overdue callback can still race a takeover. Periodic lease renewal would add a background
coordination path without removing the need for ownership compare-and-set, so the bounded lease plus
fresh acquisition token is the simpler current design.

## Verification

Tests cover one concurrent winner, expired takeover with a distinct token, stale failure no-op,
stale completion rejection, winning completion, request-hash conflict, timeout selection, and the
required timeout-to-lease margin. No schema, database migration, external dependency, or large DB
value is introduced.

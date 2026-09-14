# ADR 0087: Graph authorization recovery after a proven pre-commit failure

## Status

Accepted for implementation.

## Responsibility and canonical state

The mock-exam coordinator owns explicit operator authorization for its atomic 25-Item Graph
publication. The immutable execution checkpoint is canonical and pins the authorization, failure,
and any publication receipt. A fresh authentication can make an earlier authorization temporally
invalid even when a corrected Catalog release makes the same failed cohort safely retryable.

## Recovery rule and pointers

One shared application rule permits supersession only when no Graph publication pointer exists,
the failure is retryable and belongs to `GRAPH_PUBLICATION`, the new authorization explicitly
supersedes the old authorization hash, its timestamp is later, and its access-policy revision and
hash are unchanged. `KNOWLEDGE_GRAPH_STALE_CURRENT` may authorize a new Graph base as before.
`APPROVED_ITEM_GRAPH_ANALYSIS_INELIGIBLE` may only authorize the exact same Graph revision and hash:
Catalog emits that code before its atomic Graph publication call, so it proves that no Graph commit
was made. Unknown outcomes and all other failures remain bound to the original idempotency identity.

## Access pattern, complexity, and concurrency

The rule performs constant-time comparisons over immutable scalar pointers: O(1) time and space at
the expected single-checkpoint scale. The coordinator persists the superseding authorization in one
checkpoint CAS revision before making another Catalog call. The checkpoint store calls the same
rule, preventing drift between command behavior and monotonic persistence. Catalog retains its own
idempotency and expected-current-snapshot transaction boundary.

## Failure, retry, dependency direction, and alternatives

A missing supersession link, stale timestamp, policy drift, base drift for the same-base failure, a
prior publication, or an unrecognized failure fails closed with the existing stable authorization
mismatch. No schema, database, Artifact, NAS layout, dependency, or worker behavior changes. Editing
the old authorization, weakening its time check, treating every retryable exception as pre-commit,
or reusing an expired access session would make history ambiguous and is therefore insufficient.

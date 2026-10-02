# ADR 0168: Educational quality review workbench

## Status

Accepted for implementation on 2026-10-02.

## Responsibility and boundary

The Application API owns a human evaluation aggregate for an immutable released assessment
Assembly.  It does not approve Items, change Catalog lifecycle state, publish an exam, or replace
the existing production A/B/C rating contract.  Catalog remains the canonical source for Assembly
and Item revisions.  The workbench records how reviewers assessed that exact product.

The dominant operations are: lookup by plan or session ID, ordered iteration by Item position,
one observation per session and position, reviewer-session uniqueness, optimistic concurrent
updates, and append-free immutable finalization.  These are represented by indexed relational
tables and unique constraints rather than JSON list scans.

## Canonical identity and pointers

A plan pins:

- assessment Assembly logical ID and immutable revision ID;
- Assembly manifest SHA-256;
- an ordered tuple of Item logical ID, immutable Item revision ID, and Item manifest SHA-256;
- a canonical plan SHA-256 derived from those pins and the secondary-review positions.

The plan Item rows are small pointer snapshots.  They are not copies of Item content.  Plan
creation re-resolves the Assembly through the Catalog application boundary and rejects missing,
non-released, stale, reordered, duplicate, or hash-mismatched pointers.  Later reads never resolve
an implicit latest revision.

## State and concurrency

Each plan has at most one session per role (`PRIMARY` or `SECONDARY`), and one human operator
cannot hold both roles for the same plan.  This database-backed rule preserves independent second
review rather than merely displaying it as a UI convention.  Draft
observations use `(session_id, position)` as their key and update under a session lock-version
precondition.  Finalization is allowed only when every position required by that role has one
complete observation.  A finalized session is immutable.  A resolution for a doubly reviewed
position must select one finalized observation and is unique per plan and position.

The scorecard is a non-persisted projection.  It becomes `READY` only after both independent
sessions are finalized and every differing sampled observation has an immutable resolution.  It
then chooses the primary observation outside the sample and the explicitly selected observation
inside each disagreement.  Counts, edit time, and integer milli-score means are derived in O(n)
time from that canonical map.  Draft or unresolved reviews never expose a partial metric set as a
final scorecard.

The Application API transaction owns each command.  Existing API idempotency protects HTTP
replay, while database constraints protect concurrent creation.  No binary, Item body, worker
result, prompt, or HWPX bytes are persisted in this aggregate.

Expected scale is tens of active plans and at most a few hundred observations per plan.  Key
lookups and ordered reads are O(1) or O(n) through B-tree indexes; storage is O(plans × items ×
reviewers).  A single JSON document was rejected because it makes optimistic concurrency,
uniqueness, indexed progress queries, and immutable finalization difficult to enforce.

## Dependency direction and failure behavior

The Web GUI calls the Application API.  The Application service validates contracts and owns the
transaction.  It resolves Catalog pointers through the existing Catalog application client.  The
domain-shaped SQLAlchemy records do not call HTTP, NAS, or filesystem adapters.

Pointer drift fails closed with a stable error.  Concurrent stale writes fail with a precondition
error.  Failed commands do not partially persist.  Retry uses the same API idempotency key.  No
repair substitutes a current Assembly or Item revision.

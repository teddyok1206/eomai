# Legacy Item Extraction Batch

Status: implementation design for reviewed full-corpus execution. A batch may reuse an already
accepted extraction only when every reviewed source member is also bound to an exact byte-identical
entry in the batch inventory. It does not turn filename grouping into human review.

## Boundary and canonical source

Catalog owns the batch use case and its idempotency boundary. Each batch manifest is a small,
immutable Artifact containing typed extraction requests and exact pointer identities. PostgreSQL
stores only those identities, hashes, lifecycle state, claim lease, and pointers to the existing
Workflow/Job/receipt records. Source PDFs, HWP/HWPX, XLSX, PNG, and worker JSON never enter a DB
row. The inventory and reviewed bundle/occurrence revisions remain canonical; the batch is an
execution projection, not a new source identity.

## Access patterns and structures

The dominant operations are ordered FIFO claim, exact work-unit lookup, membership validation,
idempotency, and coverage partitioning. The manifest is an ordered tuple. Corpus source bindings
use maps keyed by bundle member ID and corpus inventory entry ID, avoiding repeated list scans. The
DB uses a unique key on `(batch_id, ordinal)`, an identity constraint on
`(bundle_revision_id, ordinal, expected_item_numbers_sha256)`, an indexed partial queue on
`(state, next_action_at, batch_id, ordinal)`, and a unique workflow pointer. Claims use one
transaction with `FOR UPDATE SKIP LOCKED`, giving expected `O(log n)` indexed claim and `O(1)`
manifest lookup after one `O(n)` parse. The limit is 10,000 work units and eight expected items per
unit; payload bytes remain in Artifact/NAS, so DB space is `O(work units)`.

## Corpus source equivalence

Schema `legacy-item-extraction-batch/1.1` adds the exact inventory Artifact pointer and, per work
unit, an ordered tuple mapping each reviewed bundle member to one entry in the batch inventory. A
binding carries both immutable inventory-entry pointers and requires equal content hashes. Catalog
then verifies the reviewed-side pointer against the registered bundle member and the corpus-side
pointer against an `ORIGINAL_SOURCE_CANDIDATE` in the pinned inventory document. This supports a
common real case: a small reviewed
pilot inventory and a later full-corpus inventory contain the same source bytes at different
relative paths. The relation is byte equivalence only; occurrence metadata, roles, rights, layout,
and item numbers continue to come solely from the reviewed bundle/request.

This mapping is a sparse adjacency list from work unit to immutable inventory entries. It is not a
second copy of either inventory, and it cannot certify an unreviewed candidate. Missing, duplicate,
stale, or hash-mismatched bindings fail admission explicitly.

## Transaction, retry, and failure behavior

Creation validates every request and inventory binding, commits the canonical manifest through the
existing Artifact boundary, and inserts the complete aggregate transactionally. Replaying the same
idempotency key and manifest hash returns the existing aggregate; a conflicting body fails. A
claimed `EXECUTE` unit has one submission attempt. Submission delegates to the existing
single-extraction application service and records only workflow/Job/receipt pointers. Response loss
is recovered by the same deterministic workflow idempotency key; no automatic model retry exists.
`CONTINUE_AND_COLLECT` allows unrelated units to continue.

The existing Catalog application runner polls due submitted/review work first and otherwise claims
the oldest ready unit with `SKIP LOCKED`. Poll scheduling is persisted in `next_action_at`, so a
process restart loses no work and multiple runners cannot claim the same row. Batch transitions
lock the aggregate before assigning the next append-only event sequence. This keeps lookup and
claim indexed while serializing only the short event append for one batch.

A successful extraction is `AWAITING_REVIEW`, not accepted. It becomes `ACCEPTED` only after the
existing human acceptance record resolves to the exact result pointer. `REUSE_ACCEPTED` admission
requires that exact record up front and creates no worker workflow. Aggregate state is `SUCCEEDED`
only when every unit is accepted, `AWAITING_REVIEW` when all runnable work has stopped but at least
one result needs review, and `COMPLETED_WITH_GAPS` only when no work remains and at least one unit
failed or was cancelled. Claim leases are short and explicit; expired pre-submission claims return
to `PENDING`, while a submitted unit is reconciled from its immutable workflow evidence.

## Dependency direction and simpler alternative

The CLI constructs typed commands; the Catalog application service owns validation, manifest
staging, DB transactions, claim leases, and delegation; the Orchestrator remains the only
worker/Artifact execution boundary. Contracts import no infrastructure. A JSON blob column or a
loop that directly creates workflows was rejected because it would duplicate mutable request data,
lose FIFO claim and idempotency semantics, and make response-loss recovery ambiguous. Automatically
promoting the 136 conflict-free filename groups was also rejected: structural discovery is not
occurrence, rights, layout, or expected-item review.

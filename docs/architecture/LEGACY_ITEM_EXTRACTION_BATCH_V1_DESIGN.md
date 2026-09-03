# Legacy Item Extraction Batch V1

Status: additive design for full-corpus execution; it does not authorize a live submission until
reviewed bundle revisions, rights revisions, layouts, and expected item numbers are present.

## Boundary and canonical source

Catalog owns the batch use case and its idempotency boundary. Each batch manifest is a small,
immutable Artifact containing typed extraction requests and exact pointer identities. PostgreSQL
stores only those identities, hashes, lifecycle state, claim lease, and pointers to the existing
Workflow/Job/receipt records. Source PDFs, HWP/HWPX, XLSX, PNG, and worker JSON never enter a DB
row. The inventory and reviewed bundle/occurrence revisions remain canonical; the batch is an
execution projection, not a new source identity.

## Access patterns and structures

The dominant operations are ordered FIFO claim, exact work-unit lookup, idempotency, and coverage
partitioning. The manifest is an ordered tuple; the DB uses a unique key on
`(bundle_revision_id, ordinal, expected_item_numbers_sha256)`, an indexed partial queue on
`(batch_id, state, ordinal)`, and a unique result pointer per work unit. Claims use one transaction
with `FOR UPDATE SKIP LOCKED`, giving expected `O(log n)` indexed claim and `O(1)` in-memory
manifest lookup. The initial limit is 10,000 work units and four expected items per unit; payload
bytes remain in Artifact/NAS, so DB space is `O(work units)`.

## Transaction, retry, and failure behavior

Creation validates every request and commits the manifest through the existing Artifact boundary
before inserting the batch aggregate. Replaying the same idempotency key and manifest hash returns
the existing aggregate; a conflicting body fails. A claimed work unit has one submission attempt.
The runner calls the existing single-extraction application service using the manifest's exact
typed request, then records only workflow/Job/receipt pointers. Response loss is recovered by the
same deterministic workflow idempotency key; no automatic model retry exists. `CONTINUE_AND_COLLECT`
allows unrelated units to continue. Terminal aggregate state is `SUCCEEDED` only when every unit
has an accepted extraction receipt; otherwise it is `COMPLETED_WITH_GAPS` with explicit failed or
unresolved positions. Continuation batches may reuse only exact accepted pointers and execute gaps.

## Dependency direction and simpler alternative

The CLI constructs typed commands; the Catalog application service owns validation, manifest
staging, DB transactions, and delegation; the Orchestrator remains the only worker/Artifact
execution boundary. Contracts import no infrastructure. A JSON blob column or a loop that directly
creates workflows was rejected because it would duplicate mutable request data, lose FIFO claim
and idempotency semantics, and make response-loss recovery ambiguous.


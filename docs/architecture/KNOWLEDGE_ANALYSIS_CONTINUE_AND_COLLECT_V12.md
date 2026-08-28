# Knowledge Analysis V12 Continue-and-Collect Design

Status: reviewed implementation design, 2026-08-28 UTC.

## Responsibility and boundary

The Catalog Knowledge Analysis batch service owns ordered range scheduling, immutable source
pointer validation, one submission per range, and aggregate lifecycle. A worker continues to
produce one schema-constrained candidate through the orchestrator. Workers do not coordinate,
write NAS, or repair another range. The orchestrator remains the only component that validates and
commits accepted artifacts.

V12 changes aggregate failure handling, not acceptance correctness. A malformed worker result is
still rejected and its range remains `FAILED`; it is never silently edited, committed, or treated
as accepted. For an explicitly versioned `CONTINUE_AND_COLLECT` batch, that terminal range no
longer prevents the next FIFO range from running. The aggregate becomes `BLOCKED` only after every
range is terminal and at least one range failed. This preserves a complete first-pass coverage
attempt while retaining fail-closed artifact validation.

## Canonical source and revision model

- The immutable batch request `knowledge-analysis-batch-request/1.2` is the canonical policy
  source and pins `range_failure_policy=CONTINUE_AND_COLLECT`.
- Historical request 1.0/1.1 bytes and batches retain `STOP_ON_FIRST_FAILURE`.
- Each range still pins document logical ID, immutable document revision, source/analysis/rights
  Artifact Revisions, hashes, page bounds, and curriculum keys.
- Accepted runs and Artifact Revisions are referenced, never copied. Failed candidate bytes remain
  workspace evidence and never become canonical artifacts.
- The V12 execution preset is a new immutable preset revision. It reuses the v1.11 role/result
  protocol but strengthens the pre-return closed-reference audit; historical V11 bytes remain
  unchanged.

## Required pointers and resolution checks

Reuse requires an existing `ACCEPTED` run under the exact current preset revision and risk policy,
the exact source pointer family and page bounds, approved logical Artifact and Artifact Revision,
matching SHA-256, expected accepted-result manifest, and matching accepted-result typed contract.
Execution with a predecessor pins a specific failed run; it never resolves an implicit latest run.
Dangling node/edge/anchor pointers remain explicit `WORKER_RESULT_INVALID` failures.

## Access patterns and data structures

- Claim: indexed FIFO lookup by range state, next action, batch, and ordinal.
- Membership/uniqueness: DB unique constraints for `(batch, ordinal)`, `(batch, range)`, and
  `(batch, analysis_run)`; request-side sets for duplicate run pointers.
- Aggregate counts: indexed grouped/count queries over bounded batches (maximum 1,000 ranges).
- History: append-only monotonic batch events.
- Revision chain: immutable predecessor and reuse pointers.

The claim predicate treats `ACCEPTED` and `FAILED` as completed predecessors only for
`CONTINUE_AND_COLLECT`; legacy batches require every predecessor to be `ACCEPTED`. One partial
unique index continues to permit at most one active range per batch. Lookup remains index-backed
and linear only in the bounded manifest validation performed once at creation.

## Transaction and concurrency boundary

Range transition, batch transition, and append-only event insertion occur in one PostgreSQL
transaction under row locks. Claim uses `FOR UPDATE SKIP LOCKED`; the existing partial unique index
prevents two active ranges. A failed continuing range is terminalized before the next claim becomes
eligible. Aggregate terminalization counts accepted and failed ranges in the same transaction as
the final range transition.

## Failure, retry, and idempotency

Every range still has `submission_attempts <= 1`; there is no automatic retry. A response-loss
replay uses only the same batch idempotency key and identical request hash. A new retry is a new
authorized continuation batch. `REUSE_ACCEPTED` is allowed only when the accepted run pins the
exact same preset revision. When the preset changes, as it does from V11 to V12, the accepted
prefix remains an external immutable coverage manifest and the new batch contains only the failed
and unattempted suffix. The prefix and suffix are joined by exact document-revision/page topology
checks rather than copied rows or artifacts. A failed predecessor from another preset revision is
preserved as historical evidence but is not misrepresented as an in-protocol retry pointer. A batch
with collected failures ends `BLOCKED` and reports a stable collected-failures code after all
ranges are terminal. It cannot publish a complete Graph snapshot until a later manifest proves
exact full coverage across the pinned accepted runs.

## Dependency direction

JSON Schema and frozen catalog contracts define the policy first. API DTOs adapt the public command
to the catalog contract. The Catalog application service owns the state machine. PostgreSQL and
systemd remain infrastructure adapters. Worker instructions contain no scheduling or persistence
rules.

## Scale and complexity

The production manifest contains 495 logical ranges and 1,702 pages; the continuation contains at
most 463 ranges. Creation is O(r) with bounded pointer resolution caches. Each claim is an indexed
ordered query with an anti-existence check over preceding terminal states. Space is O(r) for range
and event history. No binary payload is stored in PostgreSQL.

## Alternatives

Silently dropping dangling edges would keep a run moving but would mutate untrusted worker output,
hide pointer defects, and violate fail-closed provenance. Automatically calling Codex again would
consume unbounded usage and weaken one-shot authorization. Splitting node and edge extraction into
two workers could make endpoint enums schema-bound but doubles model work and adds an assembly
protocol before two real consumers exist. Continue-and-collect is the smallest general mechanism:
it preserves strict per-range acceptance while preventing one bad candidate from wasting the rest
of an authorized full-corpus pass.

## Acceptance gates

- Historical request schemas, preset revisions, batches, runs, and artifacts are byte- and
  pointer-preserved.
- A legacy batch still blocks at its first failed range.
- A 1.2 batch records a failed range, continues with the next FIFO ordinal, never submits twice,
  and terminalizes only after all ranges are accepted or failed.
- Same-preset reused pointers remain exact; a cross-preset continuation starts at the first missing
  range and preserves the earlier accepted prefix as a separately hashed pointer manifest.
- Failed results register no Artifact Revision.
- Coverage audit proves no duplicate or overlapping current document/page range and reports all
  missing ranges explicitly before Graph publication.

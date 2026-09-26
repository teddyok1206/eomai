# ADR 0125: Review a science-visual campaign in bounded, hash-bound batches

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: semantic classification of the completed internal science-visual campaign

## Context

ADR 0124 deliberately keeps the final campaign inventory bounded, complete, and
immutable.  The current campaign still contains 768 crops.  Asking one reviewer to
return one unstructured response for all crops would make retries, provenance, and
review quality poor; it would also tempt a caller to construct a final inventory from
unverifiable ad-hoc notes.

## Decision

Add two small control contracts:

```text
campaign plan/result pointers + 12..48 sorted candidate IDs
  -> immutable review-batch command
  -> local staged crop images and structured reviewer result
  -> immutable review-batch result
  -> orchestrator validates every result and merges the complete campaign inventory
```

Each command carries the complete, exact two-to-four shard tuple already defined by
ADR 0124, plus one sorted candidate subset.  The result binds the command artifact
and command semantic hash, and must contain exactly one sorted review for every
command candidate.  A reviewer receives staged local crop bytes only; it has no NAS,
database, or worker-to-worker channel.  The orchestrator is the only component that
may publish command/result artifacts or later merge them.

The batch size is 12 through 48.  For the current 768 candidates this makes at most
64 independently retryable review units, and normally 32 units at 24 candidates each.
The candidate union is indexed by `candidate_id`; validation is `O(s + b)` for `s <=
4` shards and `12 <= b <= 48` reviews, apart from deterministic sort checks.

## Invariants and failure behavior

- Candidate IDs are sorted, unique, and must be members of the resolved shard union.
- A command covers only a subset; a final inventory is still required to cover the
  full campaign exactly once.
- A result covers exactly the command's candidate IDs, binds the published command
  pointer and semantic hash, and preserves the existing unsafe-LoRA rejection rules.
- Missing/stale/hash-mismatched shard pointers, duplicate candidates, a changed
  command, or incomplete/extra reviews fail before artifact publication or merge.
- Retrying a failed review creates a new command/result identity; historical batch
  artifacts are not overwritten.  A later merge selects one exact result per command
  through typed pointers rather than a filesystem path.

## Simpler alternative rejected

A JSON file of reviewer notes would be easier to create, but it would not bind crops
to the campaign's published result manifests and could not safely drive LoRA selection.
Increasing ADR 0124's final artifact size or allowing partial final inventories would
weaken its completeness invariant.  Bounded command/result pairs preserve the existing
design while allowing review progress and recovery to be measured honestly.

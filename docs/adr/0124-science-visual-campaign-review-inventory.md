# ADR 0124: Review a bounded visual-corpus campaign as one immutable inventory

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: classifying the exact outputs of a completed internal science-visual campaign

## Context and boundary

ADR 0122 permits multiple independent visual-pilot shards so that a larger approved
science-PDF corpus can be processed without source overlap.  Its pilot result contract
is intentionally shard-local: a pattern inventory V1/V2 therefore pins exactly one
result manifest and is not allowed to silently combine candidates from other shards.

The completed initial campaign has three disjoint shards (108 PDFs, 483 pages and 768
candidate crops).  Treating those candidates as automatic LoRA data would be unsafe:
many are tables, plots, labels, or authoritative diagrams that belong to the typed
Python/SVG route.  Conversely, retaining only a tiny hand-picked sample would throw
away useful non-authoritative natural-image material.

This decision adds a bounded campaign-level *review inventory*.  It does not train or
activate an adapter, alter V1/V2 inventories, relax the second-pass raster rule, or
give a worker NAS/DB access.

## Decision

`local-image-science-visual-campaign-pattern-inventory/1.0` pins a complete bounded
campaign review.  Its immutable source tuple has two through four entries; each entry
contains the shard coordinate, the V1.2 plan pointer and semantic hash, and the
published result pointer with distinct file and semantic hashes.  The inventory pins
the common campaign identity and contains one sorted `ScienceVisualPatternReview` for
every candidate across the pinned successful results.

The orchestrator-side validation receives the already resolved V1.2 plans/results and
requires all of the following before publication:

- the tuple covers each shard index exactly once and has the full declared shard count;
- every plan has the inventory campaign ID and every result has that plan's hash;
- plan/result pointers and their file/semantic hashes are exact;
- PDF bytes, document IDs, candidate IDs, and review IDs are globally unique; and
- each review covers the exact candidate union and keeps tables/plots/authoritative
  geometry out of `LORA_ELIGIBLE`.

The initial inventory is deliberately limited to four shards / 2,048 candidate
reviews.  This is enough for the current three-shard campaign while keeping one
review artifact bounded for schema validation, review, and recovery.  A future larger
campaign must use an additive batched-review successor rather than increasing this
limit or concatenating JSON without a contract.

```text
published shard plan/result file sets (2..4, complete campaign)
  -> staged, bounded human/Codex review inputs
  -> sorted complete campaign inventory
  -> orchestrator validates resolved plans/results and commits one artifact
  -> later raster-suitability, refinement, and crop-set successors
```

The broad inventory routes useful diagrams to deterministic rendering.  It is not a
LoRA approval: non-authoritative candidates still require the existing exact-caption
raster suitability review before any train crop is selected.

## Access patterns, concurrency, and failure

Resolved plans/results and reviews are indexed by shard index and candidate ID using
maps/sets.  For `n <= 2,048` candidates and `s <= 4` shards, validation is `O(n+s)`
time and space except deterministic sorted output.  The immutable inventory hash is
the idempotency key.  Two reviewers may prepare local drafts, but only an exact,
complete, hash-bound inventory can become canonical through the orchestrator.

Missing/stale pointers, non-success results, a partial campaign, duplicate candidates,
source overlap, a result-plan mismatch, incomplete review coverage, or an unsafe
LoRA decision fail before commit.  A retry keeps the same campaign result pointers and
uses a new local draft; no historical result or inventory is overwritten.

## Simpler alternative rejected

Using one existing V2 inventory per shard would make global candidate and source
deduplication a downstream convention and make the next training selection ambiguous.
Putting every shard in a single unbounded list would make an expensive review job and
large control artifact.  A bounded complete campaign inventory is the smallest
successor that preserves the current three-shard campaign's provenance without
pretending that diagrams are raster training samples.

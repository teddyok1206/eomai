# ADR 0122: Disjoint science-visual corpus campaigns

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: bounded, repeatable expansion of the internal science-PDF visual corpus

## Context and boundary

ADR 0119 deliberately bounded the first visual pilot to at most 96 PDFs. That is
appropriate for a first safety and quality check, but it must not become an implicit
ceiling when the approved internal corpus contains substantially more PDFs. Reusing a
single broad selector for several workers risks repeated PDFs, partition leakage, and
unreproducible retraining inputs.

This decision adds a campaign-plan successor only. It does not relax the raster
suitability rules in ADR 0120/0121, activate an adapter, alter a released V1/V2 plan,
or permit a worker to resolve corpus state itself.

## Decision

`local-image-science-corpus-visual-pilot-plan/1.2` and its matching command bind one
immutable shard of a campaign. The plan pins:

- the corpus, authorization, policy, guidance, and tool pointers already required by
  ADR 0119;
- a deterministic selection seed;
- a campaign identity derived from the corpus/policy/seed and shard count; and
- a zero-based `(shard_index, shard_count)` coordinate and the exact selected PDF
  sources.

Source ranking is deterministic within `(partition, subject family, issuer)` strata.
After stable SHA-256 ranking, source rank modulo `shard_count` assigns a document to
exactly one shard. Each shard then applies the existing partition quotas and page
budget. It is still a bounded worker input (12–96 PDFs and at most 384 pages); a large
corpus is covered by multiple independent, explicitly numbered attempts rather than by
one unbounded job.

```text
pinned corpus revision + authorization
  -> campaign coordinates + exact source list
  -> isolated staged workspace
  -> worker page/candidate result
  -> orchestrator validation and NAS commit
  -> raster suitability / refinement / crop-set successors
```

## Access patterns, concurrency, and failure

Selection groups documents in a map keyed by partition and stratum, ranks each group
once, and emits an ordered tuple. It is `O(n log n)` time for ranking `n` corpus
documents and `O(n)` space; source membership and duplicate PDF checks use sets. The
published plan is the concurrency boundary: two workers may execute different shards,
but cannot silently claim the same selected source list. Existing attempt identity,
workspace isolation, and orchestrator-only commit rules remain unchanged.

An invalid coordinate, insufficient partition population, repeated PDF bytes,
page-limit overrun, stale pointer, or hash/schema mismatch fails before a worker runs.
Retries reuse the same immutable shard plan and use a new attempt identity. A campaign
is not considered a training dataset merely because its page/candidate extraction
succeeds: suitability review, panel refinement, partition separation, and an explicit
evaluation/release decision remain required.

## Simpler alternative rejected

Increasing the V1/V2 source limit would turn an intentionally bounded worker into a
long-running, hard-to-retry batch and would not prove non-overlap across repeated
runs. Re-running the existing selector with new seeds would also allow the same PDF to
appear in multiple pilots. Explicit shard coordinates are the smallest additive
contract that expands coverage while retaining immutable provenance and bounded
failure domains.
